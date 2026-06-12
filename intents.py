"""AAYU intent detection — heuristic-first, AI fallback."""

import re
import logging

from utils import (
    normalize_user_text,
    parse_json_from_text,
    detect_severity,
    detect_age,
    is_emergency,
    sanitize_user_input,
)
from database import (
    GEMINI_API_KEY,
    find_best_symptom,
    parse_ingredients_from_text,
    generate_gemini_with_timeout,
)

logger = logging.getLogger("aayu.intents")

# Intents that don't need the expensive AI style rewrite
_SIMPLE_INTENTS = {
    "help", "greet", "cancel", "menu_image", "about_data_source",
    "database_classification", "reminder_set", "reminder_off",
    "timezone_set", "start_consultation", "prakriti_start",
}


def extract_intent_with_ai(text):
    """AI-based intent classification — used only when heuristics are uncertain."""
    if not GEMINI_API_KEY:
        return None

    safe_text = sanitize_user_input(text)
    prompt = f"""
You classify user messages for an Ayurveda WhatsApp assistant.
Return only valid compact JSON.

Allowed intents:
- help
- greet
- start_consultation
- cancel
- menu_image
- recommendation
- daily_routine_plan
- hospital_near_address
- ingredient_remedy
- mood_support
- tracker
- explain
- graph
- reminder_set
- reminder_off
- timezone_set
- prakriti_start
- about_data_source
- database_classification
- emergency
- unknown

Also extract fields when present:
age(number), symptom(string), severity(mild|moderate|severe), address(string),
ingredients(array of strings), mood(string), condition(string),
reminder_time(HH:MM), reminder_message(string), timezone(string),
water(number), sleep(number), diet(string)

User message: {safe_text}
"""

    try:
        response = generate_gemini_with_timeout(prompt, timeout_seconds=8)
        return parse_json_from_text(getattr(response, "text", ""))
    except Exception:
        return None


def heuristic_extract(text):
    """Rule-based intent extraction — fast, no API calls."""
    msg = (text or "").strip()
    low = normalize_user_text(msg)
    extracted = {"intent": "unknown"}

    menu_shortcuts = {
        "1": {"intent": "start_consultation"},
        "2": {"intent": "recommendation", "age": detect_age(msg), "symptom": find_best_symptom(low), "severity": detect_severity(low)},
        "3": {"intent": "ingredient_remedy", "ingredients": parse_ingredients_from_text(low)},
        "4": {"intent": "daily_routine_plan", "age": detect_age(msg), "symptom": find_best_symptom(low)},
        "5": {"intent": "mood_support", "mood": low},
        "6": {"intent": "hospital_near_address", "address": ""},
        "7": {"intent": "reminder_set", "reminder_time": "", "reminder_message": ""},
    }
    if low in menu_shortcuts:
        return menu_shortcuts[low]

    if low in {"help", "menu"}:
        return {"intent": "help"}
    if low in {"hi", "hii", "hello", "hey", "namaste", "aayu"}:
        return {"intent": "greet"}
    if low == "start":
        return {"intent": "start_consultation"}
    if low == "cancel":
        return {"intent": "cancel"}
    if low in {"menu image", "image menu", "menu photo", "menu pic", "send menu image"}:
        return {"intent": "menu_image"}
    if low == "prakriti":
        return {"intent": "prakriti_start"}

    if any(k in low for k in ["database", "data source", "source of answer", "which db", "kis database"]):
        return {"intent": "about_data_source"}

    if any(k in low for k in ["classify database", "database classification", "classify db", "menu database"]):
        return {"intent": "database_classification"}

    if any(p in low for p in ["daily routine", "routine plan", "my routine", "diet plan timewise"]):
        return {
            "intent": "daily_routine_plan",
            "age": detect_age(low),
            "symptom": find_best_symptom(low),
        }

    if is_emergency(low):
        extracted["intent"] = "emergency"
        return extracted

    if low.startswith("timezone "):
        return {"intent": "timezone_set", "timezone": msg.split(" ", 1)[1].strip()}

    if "reminder off" in low:
        return {"intent": "reminder_off"}

    reminder_match = re.search(r"reminder\s+at\s+([0-2][0-9]:[0-5][0-9])\s+(.+)", low)
    if reminder_match:
        return {
            "intent": "reminder_set",
            "reminder_time": reminder_match.group(1),
            "reminder_message": reminder_match.group(2).strip(),
        }

    if low.startswith("hospital near"):
        address = msg[len("hospital near"):].strip()
        return {"intent": "hospital_near_address", "address": address}

    if low.startswith("graph "):
        return {"intent": "graph", "condition": msg.split(" ", 1)[1].strip()}

    if low.startswith("explain "):
        return {"intent": "explain", "condition": msg.split(" ", 1)[1].strip()}

    if "track" in low and "water" in low and "sleep" in low and "diet" in low:
        water_match = re.search(r"water\s+(\d+)", low)
        sleep_match = re.search(r"sleep\s+(\d+)", low)
        diet_match = re.search(r"diet\s+([a-z]+)", low)
        return {
            "intent": "tracker",
            "water": int(water_match.group(1)) if water_match else None,
            "sleep": int(sleep_match.group(1)) if sleep_match else None,
            "diet": diet_match.group(1) if diet_match else None,
        }

    ingredients = parse_ingredients_from_text(low)
    if ingredients and any(w in low for w in ["i have", "ingredients", "with", "available"]):
        return {"intent": "ingredient_remedy", "ingredients": ingredients}

    if any(m in low for m in ["anxious", "anxiety", "stressed", "stress", "sad", "low"]):
        return {"intent": "mood_support", "mood": low}

    if "," in msg:
        parts = [p.strip() for p in msg.split(",")]
        if len(parts) >= 3 and parts[0].isdigit():
            return {
                "intent": "recommendation",
                "age": int(parts[0]),
                "symptom": parts[1].lower(),
                "severity": parts[2].lower(),
            }

    guessed_symptom = find_best_symptom(low)
    if guessed_symptom:
        return {
            "intent": "recommendation",
            "age": detect_age(low),
            "symptom": guessed_symptom,
            "severity": detect_severity(low),
        }

    return extracted


def extract_intent(text):
    """Heuristic-first intent detection — AI is called only when heuristic is uncertain.

    This is the key efficiency improvement: heuristic detection handles ~70% of
    messages without any Gemini API call, saving both latency and cost.
    """
    normalized = normalize_user_text(text)

    # Hard-priority medical detection so disease paragraphs are never misrouted.
    def _looks_like_medical_query(msg):
        symptom = find_best_symptom(msg)
        has_age = detect_age(msg) is not None
        has_severity_word = detect_severity(msg) in {"mild", "severe"}
        has_duration = bool(re.search(r"\b\d+\s*(day|days|week|weeks|month|months)\b", msg))
        has_health_phrase = any(
            p in msg
            for p in [
                "i have", "i am feeling", "pain", "fever", "headache",
                "cough", "cold", "acidity", "bukhar", "sir dard",
            ]
        )

        if is_emergency(msg):
            return True
        return bool(symptom) or (has_age and (has_health_phrase or has_duration)) or (has_severity_word and has_health_phrase)

    medical_query = _looks_like_medical_query(normalized)

    # --- Heuristic first (no API cost) ---
    heur = heuristic_extract(text)
    heur_intent = heur.get("intent", "unknown")

    # If heuristic found a confident non-unknown intent, use it directly
    if heur_intent != "unknown":
        # Override weak conversational intents if message is clearly medical
        if medical_query and heur_intent in {"start_consultation", "greet", "help"}:
            return {
                "intent": "recommendation",
                "age": heur.get("age") or detect_age(normalized),
                "symptom": heur.get("symptom") or find_best_symptom(normalized),
                "severity": heur.get("severity") or detect_severity(normalized),
            }
        return heur

    # If heuristic returned unknown but message looks medical, route as recommendation
    if medical_query:
        return {
            "intent": "recommendation",
            "age": detect_age(normalized),
            "symptom": find_best_symptom(normalized),
            "severity": detect_severity(normalized),
        }

    # --- AI fallback for truly ambiguous messages ---
    ai = extract_intent_with_ai(text)
    if ai and isinstance(ai, dict) and ai.get("intent"):
        ai_intent = (ai.get("intent") or "").lower()
        if medical_query and ai_intent in {"start_consultation", "greet", "help", "unknown"}:
            ai["intent"] = "recommendation"
            ai["age"] = ai.get("age") or detect_age(normalized)
            ai["symptom"] = ai.get("symptom") or find_best_symptom(normalized)
            ai["severity"] = ai.get("severity") or detect_severity(normalized)
        return ai

    return heur

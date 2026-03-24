import json
import os
import re
from io import BytesIO
from difflib import get_close_matches
from flask import Flask, Response, request, send_file, send_from_directory
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

try:
    from database import (
        GEMINI_API_KEY,
        analyze_prakriti,
        disable_daily_reminder,
        explain_condition_styles,
        find_best_symptom,
        find_nearest_hospitals,
        generate_gemini_with_timeout,
        geocode_address,
        get_all_symptoms,
        get_ayurvedic_knowledge,
        get_ai_detailed_recommendation,
        get_ai_recommendation,
        get_home_remedies_by_ingredients,
        get_mood_mind_support,
        get_daily_routine_plan,
        load_structured_db,
        get_structured_conditions,
        get_user_daily_reminder,
        knowledge_graph_links,
        parse_ingredients_from_text,
        set_user_timezone,
        upsert_daily_reminder,
        update_health_tracker,
    )
except ImportError:
    print("database.py not found. Running in limited mode.")
    GEMINI_API_KEY = ""

    def _missing(*_args, **_kwargs):
        return None

    analyze_prakriti = _missing
    disable_daily_reminder = _missing
    explain_condition_styles = _missing
    find_best_symptom = _missing
    find_nearest_hospitals = _missing
    generate_gemini_with_timeout = _missing
    geocode_address = _missing
    get_all_symptoms = lambda: ()
    get_ayurvedic_knowledge = _missing
    get_ai_detailed_recommendation = _missing
    get_ai_recommendation = lambda _s, _a, _v: "AI logic is currently offline."
    get_home_remedies_by_ingredients = lambda _i: []
    get_mood_mind_support = _missing
    get_daily_routine_plan = lambda _t, _a=None: "Daily routine planner is currently offline."
    load_structured_db = lambda: {}
    get_structured_conditions = lambda: {}
    get_user_daily_reminder = _missing
    knowledge_graph_links = lambda _t: []
    parse_ingredients_from_text = lambda _t: []
    set_user_timezone = lambda _u, _t: False
    upsert_daily_reminder = _missing
    update_health_tracker = lambda *_args, **_kwargs: {"streak": 0, "badges": [], "good_day": False}

load_dotenv()

app = Flask(__name__)
USER_STATE = {}
AI_BRAIN_ENABLED = os.environ.get("AAYU_AI_BRAIN_ENABLED", "true").lower() == "true"
RAG_PRIMARY_ENABLED = os.environ.get("AAYU_RAG_PRIMARY_ENABLED", "true").lower() == "true"

EMERGENCY_KEYWORDS = [
    "chest pain",
    "difficulty breathing",
    "breathing problem",
    "cannot breathe",
    "stroke",
    "unconscious",
    "fainting",
    "severe bleeding",
    "suicidal",
]

SEVERITY_WORDS = {
    "mild": ["mild", "light", "thoda", "minor"],
    "moderate": ["moderate", "medium", "normal"],
    "severe": ["severe", "high", "bahut", "extreme", "intense", "worst"],
}

PRAKRITI_DEFAULT_QUESTIONS = [
    "How is your body frame: thin, medium, or broad?",
    "How is your digestion: irregular, strong, or slow?",
    "How is your sleep: light, medium, or deep?",
    "How is your mental tendency: anxious, focused, or calm?",
]

LOCAL_TEXT_NORMALIZATION = {
    "sir dard": "headache",
    "sar dard": "headache",
    "head pain": "headache",
    "pet dard": "stomach pain",
    "bukhar": "fever",
    "khansi": "cough",
    "sardi": "cold",
    "acidity ho rahi": "acidity",
    "gas ho rahi": "acidity",
    "ulti": "nausea",
    "saanse": "breathing",
    "सिर दर्द": "headache",
    "बुखार": "fever",
    "खांसी": "cough",
    "सर्दी": "cold",
    "घबराहट": "anxious",
}


def xml_twiml_response(resp):
    return Response(str(resp), mimetype="application/xml")


def get_user_id_and_phone(req):
    user_id = req.values.get("From", "unknown")
    phone = user_id.replace("whatsapp:", "") if user_id else ""
    return user_id, phone


def get_help_menu(profile_name="there"):
    name = profile_name or "there"
    return (
        f"Welcome {name}! 🌿\n\n"
        "📘 How to use AAYU\n"
        "1) Step-by-step consultation: type start\n"
        "2) Quick structured query: Age, Symptom, Severity\n"
        "   Example: 23, fever, mild\n"
        "3) Natural paragraph query:\n"
        "   Example: I am 23 and I have severe headache for 2 days\n"
        "4) Direct symptom query:\n"
        "   Example: migraine\n"
        "5) Nearest hospitals by address:\n"
        "   Example: hospital near Noida Sector 62\n"
        "6) Nearest hospitals by live location: share WhatsApp location\n"
        "7) Emergency support:\n"
        "   Example: severe chest pain and difficulty breathing\n"
        "8) Prakriti analyzer: type prakriti\n"
        "9) Ingredient remedies:\n"
        "   Example: I have turmeric, ginger, honey\n"
        "10) Mood + mind support:\n"
        "   Example: I am feeling anxious\n"
        "11) Health tracker:\n"
        "   Example: track water 8 sleep 7 diet good\n"
        "12) Explain like grandma mode:\n"
        "   Example: explain acidity\n"
        "13) Knowledge graph links:\n"
        "   Example: graph acidity\n"
        "14) Daily reminder setup:\n"
        "   Example: reminder at 08:00 drink warm water\n"
        "15) Set reminder timezone:\n"
        "   Example: timezone Asia/Kolkata\n"
        "16) Stop reminder: reminder off\n"
        "17) Stop consultation: type cancel\n"
        "18) Show this menu again: type help\n\n"
        "19) View menu image: type menu image\n"
        "20) Daily routine planner:\n"
        "   Example: daily routine for age 28 with acidity\n\n"
        "Tip: type start to begin guided consultation now."
    )


def parse_json_from_text(text):
    if not text:
        return None
    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    block = re.search(r"\{[\s\S]*\}", text)
    if not block:
        return None

    try:
        return json.loads(block.group(0))
    except Exception:
        return None


def detect_severity(text):
    msg = normalize_user_text(text).lower()
    for level, words in SEVERITY_WORDS.items():
        if any(w in msg for w in words):
            return level
    return "moderate"


def detect_age(text):
    match = re.search(r"\b(1[0-1][0-9]|120|[1-9]?[0-9])\b", text or "")
    if not match:
        return None
    age = int(match.group(1))
    return age if 1 <= age <= 120 else None


def is_emergency(text):
    msg = normalize_user_text(text).lower()
    return any(k in msg for k in EMERGENCY_KEYWORDS)


def normalize_user_text(text):
    normalized = (text or "").lower()
    for src, dest in LOCAL_TEXT_NORMALIZATION.items():
        normalized = normalized.replace(src, dest)
    return normalized


def extract_intent_with_ai(text):
    if not GEMINI_API_KEY:
        return None

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
- emergency
- unknown

Also extract fields when present:
age(number), symptom(string), severity(mild|moderate|severe), address(string),
ingredients(array of strings), mood(string), condition(string),
reminder_time(HH:MM), reminder_message(string), timezone(string),
water(number), sleep(number), diet(string)

User message: {text}
"""

    try:
        response = generate_gemini_with_timeout(prompt, timeout_seconds=8)
        return parse_json_from_text(getattr(response, "text", ""))
    except Exception:
        return None


def heuristic_extract(text):
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
        address = msg[len("hospital near") :].strip()
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
    normalized = normalize_user_text(text)

    # Hard-priority medical detection so disease paragraphs are never misrouted to "start".
    def _looks_like_medical_query(msg):
        symptom = find_best_symptom(msg)
        has_age = detect_age(msg) is not None
        has_severity_word = detect_severity(msg) in {"mild", "severe"}
        has_duration = bool(re.search(r"\b\d+\s*(day|days|week|weeks|month|months)\b", msg))
        has_health_phrase = any(
            p in msg
            for p in [
                "i have",
                "i am feeling",
                "pain",
                "fever",
                "headache",
                "cough",
                "cold",
                "acidity",
                "bukhar",
                "sir dard",
            ]
        )

        if is_emergency(msg):
            return True
        return bool(symptom) or (has_age and (has_health_phrase or has_duration)) or (has_severity_word and has_health_phrase)

    medical_query = _looks_like_medical_query(normalized)

    ai = extract_intent_with_ai(text)
    if ai and isinstance(ai, dict) and ai.get("intent"):
        ai_intent = (ai.get("intent") or "").lower()

        # Override weak conversational intents if message is clearly a health query.
        if medical_query and ai_intent in {"start_consultation", "greet", "help", "unknown"}:
            ai["intent"] = "recommendation"
            ai["age"] = ai.get("age") or detect_age(normalized)
            ai["symptom"] = ai.get("symptom") or find_best_symptom(normalized)
            ai["severity"] = ai.get("severity") or detect_severity(normalized)

        return ai

    heur = heuristic_extract(text)
    if medical_query and (heur.get("intent") in {"start_consultation", "greet", "help", "unknown"}):
        return {
            "intent": "recommendation",
            "age": detect_age(normalized),
            "symptom": find_best_symptom(normalized),
            "severity": detect_severity(normalized),
        }

    return heur


def ai_understand_user_message(user_text):
    """RAG Step 1: AI understands free-form user message and extracts medical profile."""
    if not GEMINI_API_KEY:
        return None

    prompt = f"""
You are medical-intent extractor for Ayurveda assistant.
Return compact JSON only.

Required JSON keys:
- age (number or null)
- symptom_text (string)
- normalized_symptom (string or null)
- severity (mild|moderate|severe)
- duration (string or null)
- emergency (true/false)
- language_style (string)
- intent (recommendation|emergency|other)

User message:
{user_text}
"""

    try:
        response = generate_gemini_with_timeout(prompt, timeout_seconds=8)
        parsed = parse_json_from_text(getattr(response, "text", ""))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def ai_create_retrieval_plan(user_text, understanding):
    """RAG Step 2: AI creates retrieval keywords and canonical symptom candidates."""
    if not GEMINI_API_KEY:
        return None

    prompt = f"""
You are retrieval planner for Ayurveda RAG.
Return compact JSON only.

Schema:
- primary_symptom (string or null)
- symptom_candidates (array of strings)
- keywords (array of strings)
- severity (mild|moderate|severe)
- age (number or null)

User message:
{user_text}

Understanding JSON:
{json.dumps(understanding or {}, ensure_ascii=False)}
"""

    try:
        response = generate_gemini_with_timeout(prompt, timeout_seconds=8)
        parsed = parse_json_from_text(getattr(response, "text", ""))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _pick_best_local_symptom(plan, user_text):
    candidates = []
    if isinstance(plan, dict):
        primary = (plan.get("primary_symptom") or "").strip().lower()
        if primary:
            candidates.append(primary)
        for c in plan.get("symptom_candidates", []) or []:
            c = str(c).strip().lower()
            if c:
                candidates.append(c)

    normalized_text = normalize_user_text(user_text)
    guessed = find_best_symptom(normalized_text)
    if guessed:
        candidates.append(guessed)

    known = set(get_all_symptoms() or ())
    for c in candidates:
        if c in known:
            return c

    if candidates and known:
        close = get_close_matches(candidates[0], list(known), n=1, cutoff=0.72)
        if close:
            return close[0]

    return guessed


def retrieve_rag_evidence(user_text, understanding, retrieval_plan):
    """RAG Step 3: DB retrieval (knowledge.json + structured_db.json) using AI retrieval plan."""
    symptom = _pick_best_local_symptom(retrieval_plan, user_text)
    structured_db = load_structured_db() or {}
    conditions = structured_db.get("conditions", {})

    local_record = get_ayurvedic_knowledge(symptom) if symptom else None
    structured_record = conditions.get(symptom) if symptom else None

    keywords = []
    if isinstance(retrieval_plan, dict):
        keywords = [str(k).strip().lower() for k in retrieval_plan.get("keywords", []) or [] if str(k).strip()]

    graph_hits = []
    for key in [symptom] + keywords:
        if key:
            graph_hits.extend(knowledge_graph_links(key) or [])

    # Keep evidence concise for final synthesis.
    graph_hits = graph_hits[:6]

    return {
        "symptom": symptom,
        "local_record": local_record,
        "structured_record": structured_record,
        "graph_links": graph_hits,
        "understanding": understanding or {},
        "retrieval_plan": retrieval_plan or {},
    }


def ai_generate_rag_answer(user_text, evidence):
    """RAG Step 4: Final AI answer grounded on retrieved DB evidence."""
    if not GEMINI_API_KEY:
        return None

    prompt = f"""
You are AAYU medical assistant.
Generate final answer using DB evidence only where available.
If evidence is missing, clearly say 'limited database match' and give safe generic advice.
Keep output concise and WhatsApp-friendly.
Maintain user's language/slang style based on message.
Always include red-flag warning if severe/emergency signs are present.

User message:
{user_text}

Retrieved evidence JSON:
{json.dumps(evidence, ensure_ascii=False)}
"""

    try:
        response = generate_gemini_with_timeout(prompt, timeout_seconds=12)
        text = (getattr(response, "text", "") or "").strip()
        return text or None
    except Exception:
        return None


def generate_rag_response(user_text):
    """Full RAG pipeline required by user: AI -> AI -> DB -> AI -> answer."""
    if not RAG_PRIMARY_ENABLED:
        return None

    understanding = ai_understand_user_message(user_text)
    if not understanding:
        return None

    retrieval_plan = ai_create_retrieval_plan(user_text, understanding)
    if not retrieval_plan:
        return None

    evidence = retrieve_rag_evidence(user_text, understanding, retrieval_plan)
    final_answer = ai_generate_rag_answer(user_text, evidence)
    return final_answer


def get_user_language_hint(user_text):
    text = user_text or ""
    if re.search(r"[\u0900-\u097F]", text):
        return "Hindi"
    if any(token in text.lower() for token in ["hai", "mera", "mujhe", "kr", "kya", "nhi"]):
        return "Hinglish"
    return "English"


def ai_rewrite_in_user_style(user_id, user_text, base_response, intent_name):
    if not AI_BRAIN_ENABLED or not GEMINI_API_KEY:
        return base_response

    if not base_response:
        return base_response

    state = USER_STATE.setdefault(user_id, {})
    state["language_hint"] = state.get("language_hint") or get_user_language_hint(user_text)
    history = state.get("history", [])[-4:]
    history_blob = "\n".join(
        [
            f"U: {item.get('user', '')}\nA: {item.get('assistant', '')}"
            for item in history
            if isinstance(item, dict)
        ]
    )

    prompt = f"""
You are AAYU conversation stylist.
Rewrite the assistant response so it matches the user's language/slang and tone naturally.

Rules:
1) Keep all facts, medical cautions, numbers, times, and action steps unchanged.
2) Do not remove emergency warnings.
3) Keep the same intent and outcome.
4) Keep response concise and WhatsApp-friendly.
5) Use the same language style as user (Hindi/Hinglish/English/vernacular mix).
6) Return plain text only.

Intent: {intent_name}
Detected language hint: {state.get('language_hint', 'English')}

Recent conversation:
{history_blob}

Latest user message:
{user_text}

Base assistant response:
{base_response}
"""

    try:
        rewritten = generate_gemini_with_timeout(prompt, timeout_seconds=8)
        text = (getattr(rewritten, "text", "") or "").strip()
        return text if text else base_response
    except Exception:
        return base_response


def store_chat_turn(user_id, user_text, assistant_text):
    state = USER_STATE.setdefault(user_id, {})
    history = state.setdefault("history", [])
    history.append({"user": user_text, "assistant": assistant_text})
    if len(history) > 12:
        state["history"] = history[-12:]


def handle_guided_consultation(user_id, incoming_msg):
    state = USER_STATE.setdefault(user_id, {})
    flow = state.get("consultation")
    if not flow:
        return None

    step = flow.get("step", "age")
    text = incoming_msg.strip()

    if step == "age":
        age = detect_age(text)
        if not age:
            return "Please tell your age in number. Example: 23"
        flow["age"] = age
        flow["step"] = "symptom"
        return "What is your main symptom? You can reply naturally."

    if step == "symptom":
        symptom = find_best_symptom(text) or text.lower()
        flow["symptom"] = symptom
        flow["step"] = "severity"
        return "How severe is it: mild, moderate, or severe?"

    if step == "severity":
        flow["severity"] = detect_severity(text)
        flow["step"] = "duration"
        return "How long have you had this issue? Example: 2 days"

    if step == "duration":
        flow["duration"] = text
        flow["step"] = "reason"
        return "Any possible trigger or reason you noticed?"

    if step == "reason":
        flow["pain_reason"] = text
        flow["step"] = "activities"
        return "Any recent activity that may be linked?"

    if step == "activities":
        flow["activities"] = text
        result = get_ai_detailed_recommendation(
            flow.get("symptom", "unknown"),
            flow.get("age", "unknown"),
            flow.get("severity", "moderate"),
            flow.get("duration", "not provided"),
            flow.get("pain_reason", "not provided"),
            flow.get("activities", "not provided"),
        )
        state.pop("consultation", None)
        return result

    return None


def handle_prakriti_flow(user_id, incoming_msg):
    state = USER_STATE.setdefault(user_id, {})
    flow = state.get("prakriti")
    if not flow:
        return None

    flow["answers"].append(incoming_msg.strip())
    flow["index"] += 1
    questions = flow["questions"]

    if flow["index"] < len(questions):
        return questions[flow["index"]]

    result = analyze_prakriti(flow["answers"])
    state.pop("prakriti", None)
    return f"Prakriti analysis:\n\n{result}"


def format_hospitals(hospitals):
    if not hospitals:
        return "I could not find nearby hospitals for this location right now."

    lines = ["Nearest hospitals:"]
    for i, hospital in enumerate(hospitals, start=1):
        lines.append(
            f"{i}. {hospital.get('name', 'Hospital')} - {hospital.get('distance_km', '?')} km\n"
            f"   {hospital.get('address', 'Address not available')}"
        )
    return "\n".join(lines)


def build_menu_image_url(req):
    public_base = (os.environ.get("PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    if not public_base:
        forwarded_host = (req.headers.get("X-Forwarded-Host", "") or "").strip()
        host = forwarded_host or req.host

        forwarded_proto = (req.headers.get("X-Forwarded-Proto", "") or "").strip().lower()
        if forwarded_proto in {"http", "https"}:
            scheme = forwarded_proto
        else:
            # Render/Twilio webhook calls should use HTTPS publicly.
            scheme = "https" if host and "localhost" not in host and not host.startswith("127.0.0.1") else req.scheme

        public_base = f"{scheme}://{host}".rstrip("/")
    return f"{public_base}/menu-image.png"


def generate_ai_menu_solution(user_text, intent_name, context_text=""):
    """Gemini-first response generator for menu and free-form queries."""
    if not GEMINI_API_KEY:
        return "Gemini API is not configured right now. Please set GEMINI_API_KEY."

    prompt = f"""
You are AAYU Ayurveda assistant.
Intent: {intent_name}
User message: {user_text}
Context: {context_text}

Rules:
- User can write in any style. Do not ask fixed input pattern unless necessary.
- Give practical, safe, concise WhatsApp-friendly response.
- If emergency signs are present, place emergency warning first.
- End with: Source: Gemini API
"""

    try:
        response = generate_gemini_with_timeout(prompt, timeout_seconds=14)
        text = (getattr(response, "text", "") or "").strip()
        return text if text else "I could not generate a response right now."
    except Exception:
        return "I could not generate a response right now."


def detect_custom_menu_image():
    static_dir = os.path.join(app.root_path, "static")
    if not os.path.isdir(static_dir):
        return None

    preferred = [
        "menu_custom.png",
        "menu_custom.jpg",
        "menu_custom.jpeg",
        "menu_custom.webp",
    ]
    for name in preferred:
        full_path = os.path.join(static_dir, name)
        if os.path.exists(full_path):
            return name

    allowed_ext = {".png", ".jpg", ".jpeg", ".webp"}
    candidates = []
    for name in os.listdir(static_dir):
        ext = os.path.splitext(name)[1].lower()
        if ext in allowed_ext:
            full = os.path.join(static_dir, name)
            try:
                mtime = os.path.getmtime(full)
            except Exception:
                mtime = 0
            candidates.append((mtime, name))

    if not candidates:
        return None

    # Use most recently added image if user did not use a preferred filename.
    candidates.sort(reverse=True)
    return candidates[0][1]


def handle_main_intent(user_id, phone, profile_name, incoming_msg, intent_data, req):
    intent = (intent_data.get("intent") or "unknown").lower()
    low = normalize_user_text(incoming_msg)

    if intent in {"help", "greet"}:
        return get_help_menu(profile_name)

    if intent == "cancel":
        USER_STATE.setdefault(user_id, {}).pop("consultation", None)
        USER_STATE.setdefault(user_id, {}).pop("prakriti", None)
        return "Conversation flow cancelled. You can type start or help anytime."

    if intent == "menu_image":
        return {
            "kind": "menu_image",
            "caption": (
                "Here is the visual menu guide.\n"
                "Reply with a number like 1 or 4, or type your issue directly.\n"
                f"Open directly: {build_menu_image_url(req)}"
            ),
        }

    if intent == "about_data_source":
        return (
            "AAYU data sources:\n"
            "1) Gemini API for final health guidance and menu solutions.\n"
            "2) Local knowledge files (knowledge.json, structured_db.json) as optional context.\n"
            "3) SQLite (reminders.db) for reminders/tracker user state only.\n"
            "Source: Gemini API"
        )

    if intent == "start_consultation":
        USER_STATE.setdefault(user_id, {})["consultation"] = {"step": "age"}
        return "Guided consultation started. Please tell your age."

    if intent == "prakriti_start":
        questions = PRAKRITI_DEFAULT_QUESTIONS
        try:
            q = [x.get("q") for x in load_structured_db().get("prakriti_questions", []) if isinstance(x, dict)]
            if q:
                questions = q
        except Exception:
            pass

        USER_STATE.setdefault(user_id, {})["prakriti"] = {"index": 0, "answers": [], "questions": questions}
        return f"Prakriti analyzer started.\n\n{questions[0]}"

    if intent == "emergency" or is_emergency(low):
        return (
            "Emergency warning detected. Please contact emergency services or go to nearest hospital immediately. "
            "If possible, share your live location now and I will list nearest hospitals."
        )

    if req.values.get("Latitude") and req.values.get("Longitude"):
        try:
            lat = float(req.values.get("Latitude"))
            lon = float(req.values.get("Longitude"))
            hospitals = find_nearest_hospitals(lat, lon, limit=5)
            return format_hospitals(hospitals)
        except Exception:
            return "I received location but could not parse it. Please try sharing location again."

    if intent == "hospital_near_address":
        address = (intent_data.get("address") or "").strip()
        if not address:
            return "Please share the address. Example: hospital near Noida Sector 62"
        point = geocode_address(address)
        if not point:
            return "I could not understand that address. Please send a clearer address."
        hospitals = find_nearest_hospitals(point["lat"], point["lon"], limit=5)
        return format_hospitals(hospitals)

    if intent == "ingredient_remedy":
        ingredients = intent_data.get("ingredients") or parse_ingredients_from_text(incoming_msg)
        context = f"Detected ingredients: {', '.join(ingredients) if ingredients else 'not clearly detected'}"
        return generate_ai_menu_solution(incoming_msg, "ingredient_remedy", context)

    if intent == "mood_support":
        support = get_mood_mind_support(intent_data.get("mood") or incoming_msg)
        context = f"Mood DB context: {support if support else 'none'}"
        return generate_ai_menu_solution(incoming_msg, "mood_support", context)

    if intent == "tracker":
        water = intent_data.get("water")
        sleep = intent_data.get("sleep")
        diet = intent_data.get("diet")
        if water is None or sleep is None or not diet:
            return "Please use: track water 8 sleep 7 diet good"
        result = update_health_tracker(user_id, int(water), int(sleep), str(diet).lower())
        badges = ", ".join(result.get("badges", [])) or "None yet"
        context = (
            f"Tracker updated: good_day={result.get('good_day')}, "
            f"streak={result.get('streak', 0)}, badges={badges}"
        )
        return generate_ai_menu_solution(incoming_msg, "tracker", context)

    if intent == "explain":
        condition = (intent_data.get("condition") or find_best_symptom(incoming_msg) or "").strip().lower()
        if not condition:
            return generate_ai_menu_solution(incoming_msg, "explain", "Condition not explicitly detected")
        info = explain_condition_styles(condition)
        return generate_ai_menu_solution(incoming_msg, "explain", f"Condition: {condition}, DB context: {info}")

    if intent == "graph":
        condition = (intent_data.get("condition") or find_best_symptom(incoming_msg) or "").strip().lower()
        if not condition:
            return generate_ai_menu_solution(incoming_msg, "graph", "Condition not explicitly detected")
        links = knowledge_graph_links(condition)
        return generate_ai_menu_solution(incoming_msg, "graph", f"Condition: {condition}, graph links: {links}")

    if intent == "reminder_set":
        reminder_time = (intent_data.get("reminder_time") or "").strip()
        reminder_message = (intent_data.get("reminder_message") or "").strip()
        if not re.match(r"^[0-2][0-9]:[0-5][0-9]$", reminder_time):
            return "Invalid reminder time. Use HH:MM like 08:00"
        if not reminder_message:
            return "Please add reminder text. Example: reminder at 08:00 drink warm water"
        upsert_daily_reminder(user_id, phone, reminder_time, reminder_message)
        return f"Reminder set at {reminder_time} with message: {reminder_message}"

    if intent == "timezone_set":
        timezone = (intent_data.get("timezone") or "").strip()
        if not timezone:
            return "Please provide timezone. Example: timezone Asia/Kolkata"
        ok = set_user_timezone(user_id, timezone)
        if not ok:
            return "Timezone update failed. Ensure reminder exists and timezone is valid like Asia/Kolkata"
        return f"Timezone updated to {timezone}"

    if intent == "reminder_off":
        ok = disable_daily_reminder(user_id)
        if not ok:
            return "No active reminder found."
        return "Reminder turned off."

    if intent == "daily_routine_plan":
        age = intent_data.get("age") or detect_age(incoming_msg)
        return get_daily_routine_plan(incoming_msg, age)

    if low in {"reminder", "my reminder"}:
        data = get_user_daily_reminder(user_id)
        if not data:
            return "No active reminder found. Use: reminder at 08:00 drink warm water"
        return (
            f"Your reminder: {data.get('reminder_time')} {data.get('timezone')}\n"
            f"Message: {data.get('reminder_message')}\n"
            f"Active: {'Yes' if data.get('enabled') else 'No'}"
        )

    if intent == "recommendation":
        rag_answer = generate_rag_response(incoming_msg)
        if rag_answer:
            return rag_answer

        age = intent_data.get("age") or detect_age(incoming_msg) or "unknown"
        symptom = (intent_data.get("symptom") or find_best_symptom(low) or low).lower().strip()
        severity = (intent_data.get("severity") or detect_severity(incoming_msg)).lower().strip()
        return get_ai_recommendation(symptom, age, severity)

    # Free-form fallback: try symptom extraction from any slang paragraph.
    symptom = find_best_symptom(low)
    if symptom:
        rag_answer = generate_rag_response(incoming_msg)
        if rag_answer:
            return rag_answer

        age = detect_age(incoming_msg) or "unknown"
        severity = detect_severity(incoming_msg)
        return get_ai_recommendation(symptom, age, severity)

    return generate_ai_menu_solution(incoming_msg, "free_form_query")


@app.route("/", methods=["GET"])
def home():
    return (
        "<div style='font-family:sans-serif;text-align:center;margin-top:50px;'>"
        "<h1 style='color:#2e7d32;'>AAYU Ayurvedic AI is LIVE</h1>"
        "<p>Webhook: <b>/whatsapp</b></p>"
        "<p style='color:#666;'>Natural language mode enabled.</p>"
        "<hr style='width:50%;margin:20px auto;'>"
        "<p><i>Executed By Aniket Yadav</i></p>"
        "</div>"
    )


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


@app.route("/menu-image", methods=["GET"])
def menu_image():
    custom_name = detect_custom_menu_image()
    if custom_name:
        return send_from_directory(os.path.join(app.root_path, "static"), custom_name)

    svg_path = os.path.join(app.root_path, "static", "menu_guide.svg")
    if not os.path.exists(svg_path):
        return Response("Menu image not found", status=404)

    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "menu_guide.svg",
        mimetype="image/svg+xml",
    )


@app.route("/menu-image.png", methods=["GET"])
def menu_image_png():
    custom_name = detect_custom_menu_image()
    if custom_name:
        return send_from_directory(os.path.join(app.root_path, "static"), custom_name)

    if not PIL_AVAILABLE:
        return menu_image()

    img = Image.new("RGB", (1080, 1920), color=(236, 247, 223))
    draw = ImageDraw.Draw(img)

    draw.rectangle([(40, 40), (1040, 220)], fill=(214, 236, 196), outline=(147, 186, 137), width=4)
    draw.text((80, 85), "AAYU Visual Menu", fill=(23, 74, 45))
    draw.text((80, 145), "Reply with number or type your problem", fill=(37, 95, 60))

    rows = [
        "1. Start Consultation    (type: start)",
        "2. Symptom Advice        (example: 23, fever, mild)",
        "3. Ingredient Remedy     (I have turmeric, ginger, honey)",
        "4. Daily Routine Planner (daily routine for age 28 with acidity)",
        "5. Mood and Mind Support (I am feeling anxious)",
        "6. Hospital Nearby       (hospital near Noida Sector 62)",
        "7. Daily Reminder        (reminder at 08:00 drink warm water)",
    ]

    y = 300
    for line in rows:
        draw.rectangle([(70, y - 20), (1010, y + 120)], fill=(255, 255, 255), outline=(190, 224, 178), width=3)
        draw.text((95, y + 20), line, fill=(24, 80, 48))
        y += 200

    draw.text((85, 1780), "Type help for full menu. Emergency: contact nearest hospital immediately.", fill=(30, 82, 53))

    output = BytesIO()
    img.save(output, format="PNG")
    output.seek(0)
    return send_file(output, mimetype="image/png")


@app.route("/whatsapp", methods=["POST"])
@app.route("/whatsapp/", methods=["POST"])
def whatsapp_bot():
    print("\n--- NEW MESSAGE RECEIVED ---")
    incoming_msg = request.values.get("Body", "").strip()
    print(f"Content: '{incoming_msg}'")

    resp = MessagingResponse()
    msg = resp.message()
    user_id, phone = get_user_id_and_phone(request)
    profile_name = request.values.get("ProfileName", "there")

    try:
        if not incoming_msg and not request.values.get("Latitude"):
            msg.body("Please send a message. Type help to see what I can do.")
            return xml_twiml_response(resp)

        low = incoming_msg.lower().strip()
        if low in {"help", "menu"}:
            USER_STATE.setdefault(user_id, {}).pop("consultation", None)
            USER_STATE.setdefault(user_id, {}).pop("prakriti", None)
            base = get_help_menu(profile_name)
            final_reply = ai_rewrite_in_user_style(user_id, incoming_msg, base, "help")
            store_chat_turn(user_id, incoming_msg, final_reply)
            msg.body(final_reply)
            msg.media(build_menu_image_url(request))
            return xml_twiml_response(resp)

        if low == "cancel":
            USER_STATE.setdefault(user_id, {}).pop("consultation", None)
            USER_STATE.setdefault(user_id, {}).pop("prakriti", None)
            base = "Conversation flow cancelled. You can type start or help anytime."
            final_reply = ai_rewrite_in_user_style(user_id, incoming_msg, base, "cancel")
            store_chat_turn(user_id, incoming_msg, final_reply)
            msg.body(final_reply)
            return xml_twiml_response(resp)

        guided_reply = handle_guided_consultation(user_id, incoming_msg)
        if guided_reply:
            final_reply = ai_rewrite_in_user_style(user_id, incoming_msg, guided_reply, "guided_consultation")
            store_chat_turn(user_id, incoming_msg, final_reply)
            msg.body(final_reply)
            return xml_twiml_response(resp)

        prakriti_reply = handle_prakriti_flow(user_id, incoming_msg)
        if prakriti_reply:
            final_reply = ai_rewrite_in_user_style(user_id, incoming_msg, prakriti_reply, "prakriti")
            store_chat_turn(user_id, incoming_msg, final_reply)
            msg.body(final_reply)
            return xml_twiml_response(resp)

        intent_data = extract_intent(incoming_msg)
        response_text = handle_main_intent(user_id, phone, profile_name, incoming_msg, intent_data, request)
        intent_name = (intent_data.get("intent") or "unknown") if isinstance(intent_data, dict) else "unknown"

        if isinstance(response_text, dict) and response_text.get("kind") == "menu_image":
            caption = response_text.get("caption") or "Menu image"
            media_url = build_menu_image_url(request)
            msg.body(caption)
            msg.media(media_url)
            store_chat_turn(user_id, incoming_msg, f"{caption}\n[Image: {media_url}]")
            return xml_twiml_response(resp)

        final_reply = ai_rewrite_in_user_style(user_id, incoming_msg, response_text, intent_name)
        store_chat_turn(user_id, incoming_msg, final_reply)
        msg.body(final_reply)
        return xml_twiml_response(resp)

    except Exception as e:
        print(f"ERROR: {e}")
        msg.body("I am currently balancing my energies. Please try again in a moment.")
        return xml_twiml_response(resp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"AAYU Server Starting on Port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
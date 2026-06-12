import json
import logging
import os
import re
import time
from io import BytesIO
from datetime import datetime

from flask import Flask, Response, abort, request, send_file, send_from_directory
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
from dotenv import load_dotenv

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

from database import (
    GEMINI_API_KEY,
    get_user_state,
    save_user_state,
    find_best_symptom,
    load_structured_db,
    find_nearest_hospitals,
    geocode_address,
    get_mood_mind_support,
    update_health_tracker,
    explain_condition_styles,
    knowledge_graph_links,
    upsert_daily_reminder,
    set_user_timezone,
    disable_daily_reminder,
    get_daily_routine_plan,
    get_user_daily_reminder,
    get_ai_recommendation,
    generate_gemini_with_timeout,
    get_menu_database_classification,
    parse_ingredients_from_text,
)

from utils import (
    sanitize_user_input,
    normalize_user_text,
    get_user_language_hint,
    detect_age,
    detect_severity,
    is_emergency,
    PRAKRITI_DEFAULT_QUESTIONS,
)

from intents import extract_intent, _SIMPLE_INTENTS
from rag import generate_rag_response
from flows import handle_guided_consultation, handle_prakriti_flow

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("aayu")

app = Flask(__name__)
AI_BRAIN_ENABLED = os.environ.get("AAYU_AI_BRAIN_ENABLED", "true").lower() == "true"
ENFORCE_TWILIO_SIGNATURE = os.environ.get("ENFORCE_TWILIO_SIGNATURE", "false").lower() == "true"
REMINDER_CRON_TOKEN = os.environ.get("REMINDER_CRON_TOKEN", "")

# Twilio request validator for webhook signature checking
_twilio_auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
_twilio_validator = RequestValidator(_twilio_auth_token) if _twilio_auth_token else None

# ---------------------------------------------------------------------------
# Rate Limiter (simple in-memory, per-user)
# ---------------------------------------------------------------------------
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 20     # max messages per window
_rate_limit_store = {}  # user_id -> list of timestamps


def _is_rate_limited(user_id):
    """Return True if user has exceeded rate limit."""
    now = time.time()
    timestamps = _rate_limit_store.get(user_id, [])
    # Prune old entries
    timestamps = [t for t in timestamps if now - t < _RATE_LIMIT_WINDOW]
    if len(timestamps) >= _RATE_LIMIT_MAX:
        _rate_limit_store[user_id] = timestamps
        return True
    timestamps.append(now)
    _rate_limit_store[user_id] = timestamps
    return False


def _validate_twilio_signature(req):
    """Validate Twilio webhook signature. Returns True if valid or validation is disabled."""
    if not ENFORCE_TWILIO_SIGNATURE:
        return True
    if not _twilio_validator:
        logger.warning("Twilio signature enforcement enabled but TWILIO_AUTH_TOKEN not set")
        return False
    signature = req.headers.get("X-Twilio-Signature", "")
    url = req.url
    params = req.form.to_dict()
    return _twilio_validator.validate(url, params, signature)


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
        "21) Menu-wise database classification:\n"
        "   Example: classify database\n\n"
        "Tip: type start to begin guided consultation now."
    )


def ai_rewrite_in_user_style(state, user_text, base_response, intent_name):
    if not AI_BRAIN_ENABLED or not GEMINI_API_KEY:
        return base_response

    # Skip expensive style rewrite for simple/structural intents
    if intent_name in _SIMPLE_INTENTS:
        return base_response

    if not base_response:
        return base_response

    lang_hint = get_user_language_hint(user_text)
    history = state.get("history", [])
    history_str = ""
    if history:
        history_str = "Recent Chat History:\n" + "\n".join(
            f"User: {h.get('user')}\nAssistant: {h.get('assistant')}"
            for h in history
        )

    prompt = f"""
You rewrite general Ayurvedic advice to match the patient's language and tone.
Instructions:
- Keep the exact original health advice details, recommendations, warnings, and structure intact.
- Translate or adapt the tone to: {lang_hint} (Hindi, Hinglish, or English).
- Keep formatting concise and WhatsApp-friendly (using simple bullet points and clear emojis).
{history_str}

Original text:
{base_response}

Rewritten plain text:
"""
    try:
        response = generate_gemini_with_timeout(prompt, timeout_seconds=12)
        text = (getattr(response, "text", "") or "").strip()
        return text if text else base_response
    except Exception:
        return base_response


def store_chat_turn(state, user_text, assistant_text):
    history = state.setdefault("history", [])
    history.append({"user": user_text, "assistant": assistant_text})
    if len(history) > 12:
        state["history"] = history[-12:]


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
            scheme = "https" if host and "localhost" not in host and not host.startswith("127.0.0.1") else "http"

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

    candidates.sort(reverse=True)
    return candidates[0][1]


def handle_main_intent(user_id, phone, profile_name, incoming_msg, intent_data, req, state):
    intent = (intent_data.get("intent") or "unknown").lower()
    low = normalize_user_text(incoming_msg)

    if intent in {"help", "greet"}:
        return get_help_menu(profile_name)

    if intent == "cancel":
        state.pop("consultation", None)
        state.pop("prakriti", None)
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

    if intent == "database_classification":
        return get_menu_database_classification()

    if intent == "start_consultation":
        state["consultation"] = {"step": "age"}
        return "Guided consultation started. Please tell your age."

    if intent == "prakriti_start":
        questions = PRAKRITI_DEFAULT_QUESTIONS
        try:
            raw_q = load_structured_db().get("prakriti_questions", [])
            q = []
            for x in raw_q:
                if isinstance(x, dict) and "q" in x:
                    q.append(x["q"])
                elif isinstance(x, str):
                    q.append(x)
            if q:
                questions = q
        except Exception:
            pass

        state["prakriti"] = {"index": 0, "answers": [], "questions": questions}
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

    # Free-form fallback
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
    # --- Twilio signature validation ---
    if not _validate_twilio_signature(request):
        logger.warning("Invalid Twilio signature — rejecting request")
        abort(403)

    logger.info("--- NEW MESSAGE RECEIVED ---")
    incoming_msg = request.values.get("Body", "").strip()
    logger.info("Content: '%s'", incoming_msg)

    resp = MessagingResponse()
    msg = resp.message()
    user_id, phone = get_user_id_and_phone(request)
    profile_name = request.values.get("ProfileName", "there")

    try:
        # --- Rate limiting ---
        if _is_rate_limited(user_id):
            msg.body("You are sending messages too fast. Please wait a moment and try again.")
            return xml_twiml_response(resp)

        if not incoming_msg and not request.values.get("Latitude"):
            msg.body("Please send a message. Type help to see what I can do.")
            return xml_twiml_response(resp)

        # Load persistent state
        state = get_user_state(user_id)

        low = incoming_msg.lower().strip()
        if low in {"help", "menu"}:
            state.pop("consultation", None)
            state.pop("prakriti", None)
            save_user_state(user_id, state)
            base = get_help_menu(profile_name)
            final_reply = ai_rewrite_in_user_style(state, incoming_msg, base, "help")
            store_chat_turn(state, incoming_msg, final_reply)
            save_user_state(user_id, state)
            msg.body(final_reply)
            msg.media(build_menu_image_url(request))
            return xml_twiml_response(resp)

        if low == "cancel":
            state.pop("consultation", None)
            state.pop("prakriti", None)
            save_user_state(user_id, state)
            base = "Conversation flow cancelled. You can type start or help anytime."
            final_reply = ai_rewrite_in_user_style(state, incoming_msg, base, "cancel")
            store_chat_turn(state, incoming_msg, final_reply)
            save_user_state(user_id, state)
            msg.body(final_reply)
            return xml_twiml_response(resp)

        guided_reply = handle_guided_consultation(state, incoming_msg)
        if guided_reply:
            save_user_state(user_id, state)
            final_reply = ai_rewrite_in_user_style(state, incoming_msg, guided_reply, "guided_consultation")
            store_chat_turn(state, incoming_msg, final_reply)
            save_user_state(user_id, state)
            msg.body(final_reply)
            return xml_twiml_response(resp)

        prakriti_reply = handle_prakriti_flow(state, incoming_msg)
        if prakriti_reply:
            save_user_state(user_id, state)
            final_reply = ai_rewrite_in_user_style(state, incoming_msg, prakriti_reply, "prakriti")
            store_chat_turn(state, incoming_msg, final_reply)
            save_user_state(user_id, state)
            msg.body(final_reply)
            return xml_twiml_response(resp)

        intent_data = extract_intent(incoming_msg)
        response_text = handle_main_intent(user_id, phone, profile_name, incoming_msg, intent_data, request, state)
        intent_name = (intent_data.get("intent") or "unknown") if isinstance(intent_data, dict) else "unknown"

        if isinstance(response_text, dict) and response_text.get("kind") == "menu_image":
            caption = response_text.get("caption") or "Menu image"
            media_url = build_menu_image_url(request)
            msg.body(caption)
            msg.media(media_url)
            store_chat_turn(state, incoming_msg, f"{caption}\n[Image: {media_url}]")
            save_user_state(user_id, state)
            return xml_twiml_response(resp)

        final_reply = ai_rewrite_in_user_style(state, incoming_msg, response_text, intent_name)
        store_chat_turn(state, incoming_msg, final_reply)
        save_user_state(user_id, state)
        msg.body(final_reply)
        return xml_twiml_response(resp)

    except Exception as e:
        logger.exception("Unhandled error processing message: %s", e)
        msg.body("I am currently balancing my energies. Please try again in a moment.")
        return xml_twiml_response(resp)


@app.route("/send-reminders", methods=["POST"])
def send_reminders():
    token = request.headers.get("X-Reminder-Token", "")
    if REMINDER_CRON_TOKEN and token != REMINDER_CRON_TOKEN:
        logger.warning("Unauthorized /send-reminders call")
        abort(403)

    try:
        from database import get_all_enabled_daily_reminders, mark_daily_reminder_sent
        from twilio.rest import Client as TwilioClient
    except ImportError as exc:
        logger.error("Cannot import reminder dependencies: %s", exc)
        return {"error": "dependencies unavailable"}, 500

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_number = os.environ.get("TWILIO_NUMBER", "")

    if not account_sid or not auth_token or not from_number:
        logger.error("Twilio credentials not configured for reminders")
        return {"error": "twilio not configured"}, 500

    client = TwilioClient(account_sid, auth_token)
    reminders = get_all_enabled_daily_reminders()
    sent_count = 0

    for rem in reminders:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(rem.get("timezone", "Asia/Kolkata"))
            now_in_tz = datetime.now(tz)
            current_time_hhmm = now_in_tz.strftime("%H:%M")
            current_date = now_in_tz.strftime("%Y-%m-%d")

            if rem.get("reminder_time") != current_time_hhmm:
                continue
            if rem.get("last_sent_date") == current_date:
                continue

            to_number = rem.get("phone", "")
            if not to_number:
                continue

            body = f"🌿 AAYU Reminder: {rem.get('reminder_message', 'Stay healthy!')}"
            client.messages.create(
                body=body,
                from_=from_number,
                to=f"whatsapp:{to_number}" if not to_number.startswith("whatsapp:") else to_number,
            )
            mark_daily_reminder_sent(rem["user_id"], current_date)
            sent_count += 1
            logger.info("Reminder sent to %s", rem["user_id"])
        except Exception as exc:
            logger.error("Failed to send reminder to %s: %s", rem.get("user_id"), exc)

    return {"sent": sent_count, "total_checked": len(reminders)}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info("AAYU Server Starting on Port %d...", port)
    app.run(host="0.0.0.0", port=port, debug=False)
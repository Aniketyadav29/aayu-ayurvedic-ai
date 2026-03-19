import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv

# Try to import your logic from database.py
try:
    from database import (
        get_ayurvedic_knowledge,
        get_ai_recommendation,
        get_ai_detailed_recommendation,
        get_all_symptoms,
        find_best_symptom,
        parse_ingredients_from_text,
        get_home_remedies_by_ingredients,
        get_mood_mind_support,
        analyze_prakriti,
        explain_condition_styles,
        knowledge_graph_links,
        update_health_tracker,
        upsert_daily_reminder,
        disable_daily_reminder,
        get_user_daily_reminder,
        get_due_daily_reminders,
        get_all_enabled_daily_reminders,
        set_user_timezone,
        mark_daily_reminder_sent,
        geocode_address,
        find_nearest_hospitals,
    )
except ImportError:
    print("⚠️ database.py not found! Using demo mode.")
    def get_ayurvedic_knowledge(x): return None
    def get_ai_recommendation(s, a, v): return "AI logic is currently offline."
    def get_ai_detailed_recommendation(s, a, sev, d, r, act): return "Detailed AI logic is currently offline."
    def get_all_symptoms(): return ()
    def find_best_symptom(text): return None
    def parse_ingredients_from_text(text): return []
    def get_home_remedies_by_ingredients(ingredients): return []
    def get_mood_mind_support(text): return None
    def analyze_prakriti(answers): return "Prakriti analyzer offline."
    def explain_condition_styles(condition): return None
    def knowledge_graph_links(topic): return []
    def update_health_tracker(user_id, water_glasses, sleep_hours, diet_quality, today=None): return {"streak": 0, "badges": [], "good_day": False}
    def upsert_daily_reminder(user_id, phone, reminder_time, reminder_message): return None
    def disable_daily_reminder(user_id): return False
    def get_user_daily_reminder(user_id): return None
    def get_due_daily_reminders(current_time, current_date): return []
    def get_all_enabled_daily_reminders(): return []
    def set_user_timezone(user_id, timezone_name): return False
    def mark_daily_reminder_sent(user_id, current_date): return None
    def geocode_address(address): return None
    def find_nearest_hospitals(lat, lon, limit=5): return []

# Load your .env file (API Keys)
load_dotenv()

app = Flask(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")
REMINDER_CRON_TOKEN = os.getenv("REMINDER_CRON_TOKEN", "")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN else None

KNOWN_SYMPTOMS = get_all_symptoms() or (
    "fever",
    "cough",
    "headache",
    "cold",
    "acidity",
    "indigestion",
)

SYMPTOM_ALIASES = {
    "high temperature": "fever",
    "body temperature": "fever",
    "sore throat": "cough",
    "migraine": "headache",
    "head pain": "headache",
    "running nose": "cold",
    "runny nose": "cold",
    "gas": "acidity",
    "heartburn": "acidity",
    "stomach burn": "acidity",
    "bloating": "indigestion",
    "stomach upset": "indigestion",
}

SEVERITY_KEYWORDS = {
    "mild": ["mild", "light", "slight", "low"],
    "moderate": ["moderate", "medium", "normal"],
    "severe": ["severe", "high", "intense", "critical", "serious", "worst"],
}

USER_SESSIONS = {}
USER_LANGUAGE_PREF = {}
GUIDED_STEPS = ["age", "symptom", "duration", "severity", "pain_reason", "activities"]
STEP_PROMPTS_EN = {
    "age": "Step 1/6: Please enter your age (example: 28)",
    "symptom": "Step 2/6: What is your main symptom or disease?",
    "duration": "Step 3/6: Since when are you facing this problem? (example: 2 days / 1 week)",
    "severity": "Step 4/6: How severe is it? (mild / moderate / severe)",
    "pain_reason": "Step 5/6: What do you think triggered it? (example: cold food, stress, long screen time)",
    "activities": "Step 6/6: Tell me your recent activities/routine (sleep, food, work, exercise).",
}

STEP_PROMPTS_HI = {
    "age": "चरण 1/6: कृपया अपनी उम्र लिखें (उदाहरण: 28)",
    "symptom": "चरण 2/6: आपकी मुख्य समस्या/लक्षण क्या है?",
    "duration": "चरण 3/6: यह समस्या कब से है? (उदाहरण: 2 दिन / 1 हफ्ता)",
    "severity": "चरण 4/6: समस्या कितनी गंभीर है? (mild / moderate / severe)",
    "pain_reason": "चरण 5/6: आपके हिसाब से दर्द/समस्या की वजह क्या हो सकती है?",
    "activities": "चरण 6/6: अपनी हाल की दिनचर्या बताएं (नींद, खाना, काम, एक्सरसाइज)।",
}

HELP_TEXT_EN = (
    "📘 *How to use AAYU*\n"
    "1) Step-by-step consultation: type `start`\n"
    "2) Quick structured query: `Age, Symptom, Severity`\n"
    "   Example: `23, fever, mild`\n"
    "3) Natural paragraph query:\n"
    "   Example: `I am 23 and I have severe headache for 2 days`\n"
    "4) Direct symptom query:\n"
    "   Example: `migraine`\n"
    "5) Nearest hospitals by address:\n"
    "   Example: `hospital near Noida Sector 62`\n"
    "6) Nearest hospitals by live location: share WhatsApp location\n"
    "7) Emergency support:\n"
    "   Example: `severe chest pain and difficulty breathing`\n"
    "8) Prakriti analyzer: type `prakriti`\n"
    "9) Ingredient remedies:\n"
    "   Example: `I have turmeric, ginger, honey`\n"
    "10) Mood + mind support:\n"
    "   Example: `I am feeling anxious`\n"
    "11) Health tracker:\n"
    "   Example: `track water 8 sleep 7 diet good`\n"
    "12) Explain like grandma mode:\n"
    "   Example: `explain acidity`\n"
    "13) Knowledge graph links:\n"
    "   Example: `graph acidity`\n"
    "14) Daily reminder setup:\n"
    "   Example: `reminder at 08:00 drink warm water`\n"
    "15) Set reminder timezone:\n"
    "   Example: `timezone Asia/Kolkata`\n"
    "16) Stop reminder: `reminder off`\n"
    "17) Stop consultation: type `cancel`\n"
    "18) Show this menu again: type `help`"
)

HELP_TEXT_HI = (
    "📘 *AAYU इस्तेमाल करने का तरीका*\n"
    "1) चरण-दर-चरण कंसल्टेशन: `start` लिखें\n"
    "2) जल्दी क्वेरी: `Age, Symptom, Severity`\n"
    "   उदाहरण: `23, fever, mild`\n"
    "3) पैराग्राफ में बताएं:\n"
    "   उदाहरण: `मुझे 2 दिन से तेज सिरदर्द है`\n"
    "4) सीधे लक्षण लिखें:\n"
    "   उदाहरण: `migraine`\n"
    "5) पते से नजदीकी अस्पताल:\n"
    "   उदाहरण: `hospital near Noida Sector 62`\n"
    "6) लाइव लोकेशन शेयर करके नजदीकी अस्पताल पाएं\n"
    "7) इमरजेंसी सपोर्ट:\n"
    "   उदाहरण: `severe chest pain and difficulty breathing`\n"
    "8) प्रकृति विश्लेषण: `prakriti` लिखें\n"
    "9) उपलब्ध सामग्री से उपाय:\n"
    "   उदाहरण: `I have turmeric, ginger, honey`\n"
    "10) मूड + माइंड सपोर्ट:\n"
    "   उदाहरण: `I am feeling anxious`\n"
    "11) हेल्थ ट्रैकर:\n"
    "   उदाहरण: `track water 8 sleep 7 diet good`\n"
    "12) Explain like grandma:\n"
    "   उदाहरण: `explain acidity`\n"
    "13) Knowledge graph:\n"
    "   उदाहरण: `graph acidity`\n"
    "14) डेली रिमाइंडर सेट करें:\n"
    "   उदाहरण: `reminder at 08:00 drink warm water`\n"
    "15) टाइमज़ोन सेट करें:\n"
    "   उदाहरण: `timezone Asia/Kolkata`\n"
    "16) रिमाइंडर बंद करें: `reminder off`\n"
    "17) कंसल्टेशन रोकने के लिए: `cancel`\n"
    "18) यह मेनू फिर से देखने के लिए: `help`"
)

REASON_HINTS = {
    "headache": "Possible reasons include stress, dehydration, poor sleep, or long screen time.",
    "migraine": "Possible triggers include bright light, fasting, stress, and sleep disturbance.",
    "acidity": "Likely linked with spicy/oily food, irregular meals, stress, or late-night eating.",
    "gastritis": "Likely linked with acidic food, stress, or prolonged empty stomach.",
    "cough": "Possible reasons include throat irritation, allergy, viral infection, or dust exposure.",
    "cold": "Possible reasons include viral infection, weather change, or low immunity.",
    "back pain": "Possible reasons include poor posture, prolonged sitting, or muscle strain.",
    "joint pain": "Possible reasons include inflammation, overuse, stiffness, or vitamin deficiency.",
    "insomnia": "Possible reasons include stress, excess screen time, and irregular sleep cycle.",
}

EMERGENCY_KEYWORDS = [
    "chest pain",
    "severe chest pain",
    "breathlessness",
    "shortness of breath",
    "difficulty breathing",
    "fainting",
    "unconscious",
    "stroke",
    "one side weakness",
    "slurred speech",
    "seizure",
    "fits",
    "blood vomiting",
    "vomiting blood",
    "black stool",
    "severe bleeding",
    "suicidal",
    "self harm",
]

SEVERE_RISK_SYMPTOMS = {
    "chest pain",
    "breathlessness",
    "shortness of breath",
    "difficulty breathing",
    "stroke",
    "pneumonia",
    "dengue",
    "malaria",
    "typhoid",
    "covid",
}


def parse_age(text):
    """Extract age from free text if present."""
    match = re.search(r"\b(\d{1,3})\s*(?:years?|yrs?)?\b", text)
    if not match:
        return None

    value = int(match.group(1))
    if 0 < value <= 120:
        return str(value)
    return None


def detect_language(text):
    text = text or ""
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"

    hindi_keywords = ["hindi", "हिंदी", "namaste", "नमस्ते", "mujhe", "dard", "bukhar"]
    lower = text.lower()
    if any(keyword in lower for keyword in hindi_keywords):
        return "hi"
    return "en"


def get_help_text(lang):
    return HELP_TEXT_HI if lang == "hi" else HELP_TEXT_EN


def get_step_prompt(step, lang):
    prompts = STEP_PROMPTS_HI if lang == "hi" else STEP_PROMPTS_EN
    return prompts.get(step, STEP_PROMPTS_EN.get(step, "Please continue."))


PRAKRITI_QUESTIONS_EN = [
    "Prakriti Q1/5: Body frame (thin / medium / broad)?",
    "Prakriti Q2/5: Digestion (irregular / strong / slow)?",
    "Prakriti Q3/5: Climate preference (warm / cool / dry)?",
    "Prakriti Q4/5: Sleep pattern (light / moderate / deep)?",
    "Prakriti Q5/5: Mind tendency (quick/anxious, intense/focused, calm/steady)?",
]

PRAKRITI_QUESTIONS_HI = [
    "प्रकृति Q1/5: आपका शरीर ढांचा कैसा है? (thin / medium / broad)",
    "प्रकृति Q2/5: पाचन कैसा रहता है? (irregular / strong / slow)",
    "प्रकृति Q3/5: मौसम पसंद? (warm / cool / dry)",
    "प्रकृति Q4/5: नींद कैसी है? (light / moderate / deep)",
    "प्रकृति Q5/5: मानसिक प्रवृत्ति? (quick/anxious, intense/focused, calm/steady)",
]


def get_prakriti_question(index, lang):
    items = PRAKRITI_QUESTIONS_HI if lang == "hi" else PRAKRITI_QUESTIONS_EN
    return items[index]


def start_prakriti_session(user_id, lang):
    USER_SESSIONS[user_id] = {
        "mode": "prakriti",
        "step_index": 0,
        "answers": [],
        "lang": lang,
    }
    intro = "🧬 प्रकृति विश्लेषण शुरू हो रहा है।" if lang == "hi" else "🧬 Starting Prakriti analyzer."
    return f"{intro}\n{get_prakriti_question(0, lang)}"


def format_remedy_response(remedies, lang):
    if not remedies:
        return (
            "कोई strong exact remedy match नहीं मिला, लेकिन मैं help कर सकता हूं।\n"
            "कृपया ingredients comma से भेजें, जैसे: haldi, adrak, shahad या tulsi, kali mirch, ginger"
            if lang == "hi"
            else "I could not find an exact strong remedy match, but I can still suggest options.\n"
            "Please share ingredients in comma format, for example: turmeric, ginger, honey or tulsi, black pepper, ginger"
        )

    lines = ["🏡 *Ingredient-based Home Remedies*" if lang == "en" else "🏡 *उपलब्ध सामग्री से घरेलू उपाय*"]
    for idx, item in enumerate(remedies[:3], start=1):
        missing = item.get("missing_ingredients", [])
        partial = item.get("partial", False)
        missing_line = (
            f"• Add if possible: {', '.join(missing)}\n" if partial and missing else ""
        )
        lines.append(
            f"\n{idx}. *{item['name']}*\n"
            f"• For: {', '.join(item.get('for', []))}\n"
            f"• Matched: {', '.join(item.get('matched_ingredients', []))}\n"
            f"{missing_line}"
            f"• Method: {item.get('instructions', '')}"
        )

    if any(item.get("partial") for item in remedies[:3]):
        lines.append(
            "\nNote: These are best possible options from your available ingredients."
            if lang == "en"
            else "\nनोट: ये आपके उपलब्ध ingredients के आधार पर best possible विकल्प हैं।"
        )

    return "\n".join(lines)


def format_mood_response(mood_data, lang):
    if not mood_data:
        return None
    header = "🧠 *Mood + Mind Ayurveda*" if lang == "en" else "🧠 *मूड + माइंड आयुर्वेद*"
    lines = [header, f"Dosha: {mood_data.get('dosha', 'Unknown')}"]
    for tip in mood_data.get("suggestions", []):
        lines.append(f"• {tip}")
    return "\n".join(lines)


def parse_tracker_command(text):
    """Parse tracker command like: track water 8 sleep 7 diet good"""
    text = (text or "").lower()
    if not text.startswith("track"):
        return None

    water_match = re.search(r"water\s*(\d+)", text)
    sleep_match = re.search(r"sleep\s*(\d+)", text)
    diet_match = re.search(r"diet\s*(good|healthy|clean|average|poor)", text)

    if not (water_match and sleep_match and diet_match):
        return None

    return {
        "water": int(water_match.group(1)),
        "sleep": int(sleep_match.group(1)),
        "diet": diet_match.group(1),
    }


def format_tracker_response(result, lang):
    streak = result.get("streak", 0)
    badges = result.get("badges", [])
    if lang == "hi":
        text = f"🎯 आज की एंट्री सेव हो गई।\nCurrent streak: {streak} day(s)."
        if badges:
            text += "\n🏅 Badges: " + ", ".join(badges)
        return text

    text = f"🎯 Daily health log saved.\nCurrent streak: {streak} day(s)."
    if badges:
        text += "\n🏅 Badges: " + ", ".join(badges)
    return text


def format_explain_styles(condition, styles, lang):
    if not styles:
        return (
            "इस condition के लिए explain-style data उपलब्ध नहीं है।"
            if lang == "hi"
            else "Explain-style data is not available for this condition."
        )

    return (
        f"🧾 *Explain Like Grandma Mode: {condition}*\n"
        f"Dosha: {styles.get('dosha')}\n\n"
        f"1) Scientific: {styles.get('scientific')}\n\n"
        f"2) Simple: {styles.get('simple')}\n\n"
        f"3) Traditional (Grandma): {styles.get('grandma')}"
    )


def format_graph_links(topic, links, lang):
    if not links:
        return (
            f"No graph links found for `{topic}`."
            if lang == "en"
            else f"`{topic}` के लिए graph links नहीं मिले।"
        )
    lines = [f"🕸️ *Knowledge Graph Links: {topic}*"]
    for item in links:
        lines.append(f"• {item.get('from')} --{item.get('type')}--> {item.get('to')}")
    return "\n".join(lines)


def parse_daily_reminder_command(text):
    """Parse reminder commands.

    Supported:
    - reminder on
    - reminder off
    - reminder at 08:30 drink warm water
    - remind me daily at 09:00 take tulsi tea
    """
    text = (text or "").strip().lower()

    if text in {"reminder on", "daily reminder on"}:
        return {"action": "on", "time": "08:00", "message": "Time for your daily Ayurveda self-care check: hydrate, breathe, and eat warm food."}

    if text in {"reminder off", "daily reminder off", "stop reminder"}:
        return {"action": "off"}

    m = re.search(r"(?:reminder at|daily reminder at|remind me daily at)\s*(\d{1,2}:\d{2})(?:\s+(.+))?", text)
    if m:
        t = m.group(1)
        hh, mm = t.split(":")
        hh_i, mm_i = int(hh), int(mm)
        if not (0 <= hh_i <= 23 and 0 <= mm_i <= 59):
            return {"action": "invalid"}
        message = m.group(2).strip() if m.group(2) else "Time for your Ayurveda daily routine check."
        return {"action": "on", "time": f"{hh_i:02d}:{mm_i:02d}", "message": message}

    if text in {"my reminder", "my reminders", "show reminder"}:
        return {"action": "show"}

    return None


def parse_timezone_command(text):
    text = (text or "").strip()
    m = re.match(r"^(?:timezone|tz)\s+([A-Za-z_]+\/[A-Za-z_]+)$", text, flags=re.IGNORECASE)
    if not m:
        return None
    return m.group(1)


def send_whatsapp_message(to_number, body):
    if not twilio_client or not TWILIO_NUMBER:
        return False, "Twilio client not configured"
    try:
        twilio_client.messages.create(from_=TWILIO_NUMBER, to=to_number, body=body)
        return True, "sent"
    except Exception as e:
        return False, str(e)


def parse_severity(text):
    """Infer severity level from common words in natural language input."""
    for severity, words in SEVERITY_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(word)}\b", text) for word in words):
            return severity
    return "moderate"


def parse_symptom(text):
    """Infer known symptom from free-form text."""
    text = (text or "").lower().strip()
    db_match = find_best_symptom(text)
    if db_match:
        return db_match

    for symptom in KNOWN_SYMPTOMS:
        if re.search(rf"\b{re.escape(symptom)}\b", text):
            return symptom

    for alias, symptom in SYMPTOM_ALIASES.items():
        if alias in text:
            return symptom

    cleaned = re.sub(r"[^a-z\s]", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned in KNOWN_SYMPTOMS:
        return cleaned
    return None


def build_local_record(symptom, local_data, include_footer=True):
    """Format response from local Ayurvedic knowledge base."""
    result = f"📖 *Virasat Record for {symptom.capitalize()}*:\n\n"
    result += f"• Medicine: {local_data.get('medicine')}\n"
    result += f"• Remedy: {local_data.get('home_remedy')}\n"
    result += f"• Precaution: {local_data.get('avoid')}\n"

    if include_footer:
        result += "\n_Executed By Aniket Yadav_"
    return result


def parse_natural_input(incoming_msg):
    """Parse paragraph-style text into age/symptom/severity fields."""
    age = parse_age(incoming_msg) or "not provided"
    severity = parse_severity(incoming_msg)
    symptom = parse_symptom(incoming_msg)
    return age, symptom, severity


def user_wants_hospital_help(text):
    clean = (text or "").lower().strip()
    if not clean:
        return False

    # Only trigger hospital lookup for explicit location-seeking intent.
    if extract_address_from_text(clean):
        return True

    location_terms = [" near ", " nearby", " nearest", " in ", " around ", "location", "address"]
    service_terms = ["hospital", "clinic", "doctor"]

    has_service = any(term in clean for term in service_terms)
    has_location = any(term in clean for term in location_terms)
    return has_service and has_location


def is_greeting(text):
    text = (text or "").strip().lower()
    english_tokens = {"hi", "hello", "hey", "namaste", "aayu"}
    hindi_tokens = {"नमस्ते", "हैलो"}

    words = set(re.findall(r"[\w\u0900-\u097F]+", text))
    if any(token in words for token in english_tokens | hindi_tokens):
        return True

    # Fallback only for Hindi full tokens in case of punctuation-adjacent input.
    return any(token in text for token in hindi_tokens)


def extract_address_from_text(text):
    patterns = [
        r"hospital near (.+)",
        r"nearest hospital near (.+)",
        r"find hospital in (.+)",
        r"hospital in (.+)",
        r"doctor near (.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip(" .,")
    return None


def format_hospital_response(hospitals, location_label="your location"):
    if not hospitals:
        return (
            "I could not find nearby hospitals right now.\n"
            "Please try again with a clearer address or share your WhatsApp location."
        )

    lines = [f"🏥 *Nearest Hospitals near {location_label}*:\n"]
    for index, hospital in enumerate(hospitals, start=1):
        lines.append(
            f"{index}. *{hospital['name']}*\n"
            f"   • Distance: {hospital['distance_km']} km\n"
            f"   • Address: {hospital['address']}"
        )
    return "\n".join(lines)


def detect_emergency(text):
    clean = (text or "").lower()
    return [keyword for keyword in EMERGENCY_KEYWORDS if keyword in clean]


def build_emergency_response(matched_signs, hospitals=None, location_label="your location"):
    signs_text = ", ".join(matched_signs[:3]) if matched_signs else "critical symptoms"
    lines = [
        "🚨 *Emergency Alert*",
        f"Detected red-flag signs: {signs_text}.",
        "Please seek immediate medical care now.",
        "Call local emergency services and do not delay treatment.",
    ]

    if hospitals:
        lines.append("\n" + format_hospital_response(hospitals, location_label=location_label))
    else:
        lines.append("\nShare your WhatsApp location and I will send nearest hospitals immediately.")

    lines.append("\n_Executed By Aniket Yadav_")
    return "\n".join(lines)


def should_escalate_guided(session_data):
    """Escalate guided session when risk signals are detected."""
    symptom = (session_data.get("symptom") or "").lower()
    severity = (session_data.get("severity") or "").lower()
    duration = (session_data.get("duration") or "").lower()
    pain_reason = (session_data.get("pain_reason") or "").lower()
    activities = (session_data.get("activities") or "").lower()

    combined_text = " ".join([symptom, duration, pain_reason, activities]).strip()
    matched = detect_emergency(combined_text)

    if severity == "severe" and symptom in SEVERE_RISK_SYMPTOMS:
        matched.append(f"severe {symptom}")

    long_duration_tokens = ["week", "weeks", "month", "months", "15", "20", "30"]
    if severity == "severe" and any(token in duration for token in long_duration_tokens):
        matched.append("severe persistent symptoms")

    # Unique while preserving order.
    seen = set()
    unique = []
    for item in matched:
        if item not in seen:
            seen.add(item)
            unique.append(item)

    return unique


def start_guided_session(user_id, lang="en"):
    USER_SESSIONS[user_id] = {
        "mode": "guided",
        "step_index": 0,
        "data": {},
        "lang": lang,
    }
    return (
        (
            "🩺 चरण-दर-चरण कंसल्टेशन शुरू हो रहा है।\nआप कभी भी `cancel` लिखकर रोक सकते हैं।\n\n"
            if lang == "hi"
            else "🩺 Starting step-by-step consultation.\nYou can type `cancel` anytime to stop.\n\n"
        )
        + get_step_prompt("age", lang)
    )


def get_user_display_name(request_values):
    """Get best available display name from Twilio request payload."""
    profile_name = (request_values.get("ProfileName") or "").strip()
    if profile_name:
        return profile_name

    from_user = (request_values.get("From") or "").strip()
    if from_user:
        # Fallback: use masked sender identifier.
        short = from_user[-4:] if len(from_user) >= 4 else from_user
        return f"User {short}"

    return "Friend"


def get_current_step(user_id):
    session = USER_SESSIONS.get(user_id)
    if not session:
        return None
    return GUIDED_STEPS[session["step_index"]]


def get_next_prompt(user_id):
    session = USER_SESSIONS.get(user_id)
    if not session:
        return None

    session["step_index"] += 1
    if session["step_index"] >= len(GUIDED_STEPS):
        return None

    return get_step_prompt(GUIDED_STEPS[session["step_index"]], session.get("lang", "en"))


def save_step_answer(user_id, step, answer):
    session = USER_SESSIONS.get(user_id)
    if not session:
        return False, "Session expired. Please type `start` to begin again."

    answer = answer.strip()
    if step == "age":
        if not re.fullmatch(r"\d{1,3}", answer):
            return False, "Please enter a valid age in numbers only (example: 28)."
        age_num = int(answer)
        if age_num < 1 or age_num > 120:
            return False, "Please enter a realistic age between 1 and 120."
        session["data"][step] = str(age_num)
        return True, None

    if step == "severity":
        sev = parse_severity(answer.lower())
        session["data"][step] = sev
        return True, None

    if step == "symptom":
        normalized = parse_symptom(answer.lower()) or answer.lower()
        session["data"][step] = normalized
        return True, None

    session["data"][step] = answer
    return True, None


def infer_reason_text(symptom, severity, duration, pain_reason, activities):
    symptom_key = (symptom or "").lower()
    base = REASON_HINTS.get(symptom_key, "Likely causes can include lifestyle, diet, stress, immunity, or posture factors.")

    activity_notes = []
    activities_l = (activities or "").lower()
    if "screen" in activities_l or "laptop" in activities_l or "mobile" in activities_l:
        activity_notes.append("high screen time")
    if "stress" in activities_l or "tension" in activities_l:
        activity_notes.append("stress load")
    if "sleep" in activities_l and ("less" in activities_l or "poor" in activities_l):
        activity_notes.append("insufficient sleep")
    if "exercise" in activities_l and ("no" in activities_l or "not" in activities_l):
        activity_notes.append("low physical activity")

    lines = [f"• {base}"]
    if pain_reason:
        lines.append(f"• User-reported trigger: {pain_reason}.")
    if duration:
        lines.append(f"• Duration noted: {duration} (longer duration may require medical review).")
    if severity == "severe":
        lines.append("• Severity is high, so immediate medical consultation is advised.")
    if activity_notes:
        lines.append(f"• Activity factors observed: {', '.join(activity_notes)}.")

    return "\n".join(lines)


def build_guided_assessment(session_data):
    age = session_data.get("age", "not provided")
    symptom = session_data.get("symptom", "unknown")
    duration = session_data.get("duration", "not provided")
    severity = session_data.get("severity", "moderate")
    pain_reason = session_data.get("pain_reason", "not provided")
    activities = session_data.get("activities", "not provided")

    local_data = get_ayurvedic_knowledge(symptom)
    reason_text = infer_reason_text(symptom, severity, duration, pain_reason, activities)

    if local_data:
        result = build_local_record(symptom, local_data, include_footer=False)
        result += "\n🧠 *Possible Reason of Pain*:\n"
        result += reason_text
        result += "\n\n🏃 *Activity-Based Advice*:\n"
        result += f"• Based on your routine: {activities}\n"
        result += "• Keep hydration, sleep, and daily movement consistent.\n"
        result += "• If symptoms worsen or continue, visit a doctor/hospital.\n"
        result += "\n_Executed By Aniket Yadav_"
        return result

    result = get_ai_detailed_recommendation(symptom, age, severity, duration, pain_reason, activities)
    result += "\n\n_Executed By Aniket Yadav_"
    return result

@app.route("/", methods=['GET'])
def home():
    """Verify if the server is live in your browser."""
    return """
    <div style="font-family: sans-serif; text-align: center; margin-top: 50px;">
        <h1 style="color: #2e7d32;">🌿 AAYU Ayurvedic AI is LIVE</h1>
        <p>Webhook: <b>/whatsapp</b></p>
        <p style="color: #666;">Ready to receive messages via Twilio.</p>
        <hr style="width: 50%; margin: 20px auto;">
        <p><i>Executed By Aniket Yadav</i></p>
    </div>
    """


@app.route("/health", methods=['GET'])
def health():
    return {"status": "ok"}, 200


@app.route("/send-reminders", methods=['POST'])
def send_due_reminders():
    """Cron endpoint: sends reminders due for current HH:MM.

    Protect with REMINDER_CRON_TOKEN passed as header: X-Reminder-Token.
    """
    token = request.headers.get("X-Reminder-Token", "")
    if REMINDER_CRON_TOKEN and token != REMINDER_CRON_TOKEN:
        return {"status": "forbidden"}, 403

    now = datetime.now()
    today = now.date().isoformat()

    # Timezone-aware reminder selection: compare each user's local HH:MM and local date.
    due = []
    for item in get_all_enabled_daily_reminders():
        timezone_name = item.get("timezone") or "Asia/Kolkata"
        try:
            local_now = now.astimezone(ZoneInfo(timezone_name))
        except Exception:
            local_now = now.astimezone(ZoneInfo("Asia/Kolkata"))
            timezone_name = "Asia/Kolkata"

        candidate_times = {(local_now - timedelta(minutes=i)).strftime("%H:%M") for i in range(0, 5)}
        local_date = local_now.date().isoformat()

        if item.get("reminder_time") not in candidate_times:
            continue
        if item.get("last_sent_date") == local_date:
            continue

        item["_local_date"] = local_date
        due.append(item)
    sent_count = 0
    failed = []

    for item in due:
        ok, reason = send_whatsapp_message(
            item["phone"],
            f"🌿 Daily Reminder\n{item['reminder_message']}\n\n_Executed By Aniket Yadav_",
        )
        if ok:
            mark_daily_reminder_sent(item["user_id"], item.get("_local_date", today))
            sent_count += 1
        else:
            failed.append({"user_id": item["user_id"], "reason": reason})

    return {"status": "ok", "checked": len(due), "sent": sent_count, "failed": failed}, 200

@app.route("/whatsapp", methods=['POST', 'GET'])
def whatsapp_bot():
    # 1. Capture incoming message
    print("\n--- 🚀 NEW MESSAGE RECEIVED ---")
    incoming_msg = request.values.get('Body', '').strip().lower()
    print(f"📩 Content: '{incoming_msg}'")
    from_user = request.values.get("From", "unknown")
    user_name = get_user_display_name(request.values)
    latitude = request.values.get("Latitude")
    longitude = request.values.get("Longitude")
    shared_address = request.values.get("Address") or request.values.get("Label")

    resp = MessagingResponse()
    msg = resp.message()

    # 2. Flexible Greeting Logic (Handles Hi, Hello, etc.)
    if is_greeting(incoming_msg):
        lang = USER_LANGUAGE_PREF.get(from_user) or detect_language(request.values.get('Body', ''))
        USER_LANGUAGE_PREF[from_user] = lang
        intro = f"Welcome {user_name}! 🌿\n\n" if lang == "en" else f"नमस्ते {user_name}! 🌿\n\n"
        msg.body(
            intro
            + get_help_text(lang)
            + ("\n\nTip: type `start` to begin guided consultation now." if lang == "en" else "\n\nसुझाव: guided consultation शुरू करने के लिए `start` लिखें।")
            + "\n\n_Executed By Aniket Yadav_"
        )
        return str(resp)

    if incoming_msg in {"help", "menu", "instructions", "guide", "मदद", "हेल्प"}:
        lang = USER_LANGUAGE_PREF.get(from_user) or detect_language(request.values.get('Body', ''))
        USER_LANGUAGE_PREF[from_user] = lang
        msg.body(
            (f"Hi {user_name}!\n\n" if lang == "en" else f"नमस्ते {user_name}!\n\n")
            + get_help_text(lang)
            + "\n\n_Executed By Aniket Yadav_"
        )
        return str(resp)

    if incoming_msg in {"start", "consult", "diagnose", "शुरू", "प्रारंभ"}:
        lang = USER_LANGUAGE_PREF.get(from_user) or detect_language(request.values.get('Body', ''))
        USER_LANGUAGE_PREF[from_user] = lang
        msg.body(start_guided_session(from_user, lang=lang) + "\n\n_Executed By Aniket Yadav_")
        return str(resp)

    if incoming_msg in {"prakriti", "प्रकृति"}:
        lang = USER_LANGUAGE_PREF.get(from_user) or detect_language(request.values.get('Body', ''))
        USER_LANGUAGE_PREF[from_user] = lang
        msg.body(start_prakriti_session(from_user, lang=lang) + "\n\n_Executed By Aniket Yadav_")
        return str(resp)

    try:
        if incoming_msg in {"cancel", "stop", "exit"} and from_user in USER_SESSIONS:
            USER_SESSIONS.pop(from_user, None)
            msg.body("Consultation cancelled. Type `start` to begin again.\n\n_Executed By Aniket Yadav_")
            return str(resp)

        lang = USER_LANGUAGE_PREF.get(from_user) or detect_language(request.values.get('Body', ''))
        USER_LANGUAGE_PREF[from_user] = lang

        # 3. Prakriti Q&A mode.
        if from_user in USER_SESSIONS and USER_SESSIONS[from_user].get("mode") == "prakriti":
            session = USER_SESSIONS[from_user]
            answer = request.values.get('Body', '').strip()
            session["answers"].append(answer)
            session["step_index"] += 1

            if session["step_index"] < len(PRAKRITI_QUESTIONS_EN):
                msg.body(get_prakriti_question(session["step_index"], session.get("lang", "en")) + "\n\n_Executed By Aniket Yadav_")
                return str(resp)

            final_text = analyze_prakriti(session.get("answers", []))
            USER_SESSIONS.pop(from_user, None)
            msg.body("🧬 *Prakriti Analyzer Result*\n\n" + final_text + "\n\n_Executed By Aniket Yadav_")
            return str(resp)

        # Daily reminder commands.
        reminder_cmd = parse_daily_reminder_command(incoming_msg)
        if reminder_cmd:
            if reminder_cmd["action"] == "on":
                upsert_daily_reminder(
                    user_id=from_user,
                    phone=from_user,
                    reminder_time=reminder_cmd["time"],
                    reminder_message=reminder_cmd["message"],
                )
                msg.body(
                    f"✅ Daily reminder set at {reminder_cmd['time']}\n"
                    f"Message: {reminder_cmd['message']}\n"
                    "You can stop it anytime using `reminder off`.\n\n"
                    "_Executed By Aniket Yadav_"
                )
                return str(resp)

            if reminder_cmd["action"] == "off":
                disabled = disable_daily_reminder(from_user)
                msg.body(
                    ("✅ Daily reminder turned off." if disabled else "No active reminder found.")
                    + "\n\n_Executed By Aniket Yadav_"
                )
                return str(resp)

            if reminder_cmd["action"] == "show":
                current = get_user_daily_reminder(from_user)
                if not current or not current.get("enabled"):
                    msg.body("No active daily reminder set.\nUse: `reminder at 08:00 drink warm water`\n\n_Executed By Aniket Yadav_")
                else:
                    msg.body(
                        f"🔔 Your daily reminder\nTime: {current['reminder_time']}\n"
                        f"Timezone: {current.get('timezone', 'Asia/Kolkata')}\n"
                        f"Message: {current['reminder_message']}\n\n"
                        "_Executed By Aniket Yadav_"
                    )
                return str(resp)

            if reminder_cmd["action"] == "invalid":
                msg.body("Invalid reminder time format. Use HH:MM (24-hour).\nExample: `reminder at 20:30 drink water`\n\n_Executed By Aniket Yadav_")
                return str(resp)

        timezone_name = parse_timezone_command(request.values.get('Body', '').strip())
        if timezone_name:
            updated = set_user_timezone(from_user, timezone_name)
            if updated:
                msg.body(f"✅ Reminder timezone updated to {timezone_name}.\n\n_Executed By Aniket Yadav_")
            else:
                msg.body(
                    "Could not set timezone. Please ensure a reminder exists first and use a valid format, e.g. `timezone Asia/Kolkata`.\n\n"
                    "_Executed By Aniket Yadav_"
                )
            return str(resp)

        # 4. Ingredient-based home remedies NLP intent.
        ingredient_markers = [
            "ingredients",
            "ingredient",
            "available",
            "with these",
            "using",
            "use these",
            "kitchen",
            "home remedy",
            "घरेलू",
            "सामग्री",
        ]
        ingredients = parse_ingredients_from_text(incoming_msg)
        has_ingredient_keyword = any(marker in incoming_msg for marker in ingredient_markers)
        has_list_style_text = any(sep in incoming_msg for sep in [",", " and ", " with ", "/"]) 
        has_possession_phrase = ("i have" in incoming_msg) or ("मेरे पास" in incoming_msg)

        should_run_ingredient_flow = (
            len(ingredients) >= 2
            or has_ingredient_keyword
            or (has_possession_phrase and has_list_style_text and len(ingredients) >= 1)
        )

        if should_run_ingredient_flow:
            remedies = get_home_remedies_by_ingredients(ingredients)
            result = format_remedy_response(remedies, lang)
            msg.body(result + "\n\n_Executed By Aniket Yadav_")
            return str(resp)

        # 5. Mood + mind Ayurveda intent.
        mood_support = get_mood_mind_support(incoming_msg)
        if mood_support:
            result = format_mood_response(mood_support, lang)
            msg.body(result + "\n\n_Executed By Aniket Yadav_")
            return str(resp)

        # 6. Health tracker intent.
        tracker_payload = parse_tracker_command(incoming_msg)
        if tracker_payload:
            tracker_result = update_health_tracker(
                from_user,
                water_glasses=tracker_payload["water"],
                sleep_hours=tracker_payload["sleep"],
                diet_quality=tracker_payload["diet"],
            )
            msg.body(format_tracker_response(tracker_result, lang) + "\n\n_Executed By Aniket Yadav_")
            return str(resp)

        # 7. Explain-like-grandma mode intent.
        if incoming_msg.startswith("explain ") or incoming_msg.startswith("grandma "):
            condition = incoming_msg.split(" ", 1)[1].strip()
            styles = explain_condition_styles(parse_symptom(condition) or condition)
            msg.body(format_explain_styles(condition, styles, lang) + "\n\n_Executed By Aniket Yadav_")
            return str(resp)

        # 8. Knowledge graph links intent.
        if incoming_msg.startswith("graph "):
            topic = incoming_msg.split(" ", 1)[1].strip()
            links = knowledge_graph_links(parse_symptom(topic) or topic)
            msg.body(format_graph_links(topic, links, lang) + "\n\n_Executed By Aniket Yadav_")
            return str(resp)

        # 9. Emergency triage mode always gets top priority.
        emergency_signs = detect_emergency(incoming_msg)
        if emergency_signs:
            hospitals = []
            location_label = "your location"

            if latitude and longitude:
                hospitals = find_nearest_hospitals(float(latitude), float(longitude), limit=5)
            else:
                addr = extract_address_from_text(incoming_msg) or shared_address
                if addr:
                    geo = geocode_address(addr)
                    if geo:
                        hospitals = find_nearest_hospitals(geo["lat"], geo["lon"], limit=5)
                        location_label = addr

            result = build_emergency_response(emergency_signs, hospitals=hospitals, location_label=location_label)
            msg.body(result)
            print("✅ Emergency triage response sent!")
            return str(resp)

        # 10. Hospital help via shared location or typed address.
        if latitude and longitude:
            hospitals = find_nearest_hospitals(float(latitude), float(longitude), limit=5)
            result = format_hospital_response(hospitals)
            result += "\n\n_Executed By Aniket Yadav_"
            msg.body(result)
            print("✅ Hospital response sent successfully!")
            return str(resp)

        if user_wants_hospital_help(incoming_msg):
            address = extract_address_from_text(incoming_msg) or shared_address

            if not address:
                msg.body(
                    "To find nearest hospitals, please either:\n"
                    "1) Share your WhatsApp location, or\n"
                    "2) Type: `hospital near <your address>`\n"
                    "Example: `hospital near Noida Sector 62`\n\n"
                    "_Executed By Aniket Yadav_"
                )
                return str(resp)

            geo = geocode_address(address)
            if not geo:
                msg.body(
                    "I could not understand that address.\n"
                    "Try with a fuller location, e.g. `hospital near Andheri West Mumbai`\n\n"
                    "_Executed By Aniket Yadav_"
                )
                return str(resp)

            hospitals = find_nearest_hospitals(geo["lat"], geo["lon"], limit=5)
            result = format_hospital_response(hospitals, location_label=address)
            result += "\n\n_Executed By Aniket Yadav_"
            msg.body(result)
            print("✅ Hospital response sent successfully!")
            return str(resp)

        # 11. Guided consultation mode (step-by-step).
        if from_user in USER_SESSIONS and USER_SESSIONS[from_user].get("mode") == "guided":
            current_step = get_current_step(from_user)
            ok, error_text = save_step_answer(from_user, current_step, request.values.get('Body', '').strip())
            if not ok:
                session_lang = USER_SESSIONS.get(from_user, {}).get("lang", "en")
                msg.body(error_text + "\n\n" + get_step_prompt(current_step, session_lang) + "\n\n_Executed By Aniket Yadav_")
                return str(resp)

            session_data_now = USER_SESSIONS.get(from_user, {}).get("data", {})
            risk_signs = should_escalate_guided(session_data_now)
            if risk_signs:
                USER_SESSIONS.pop(from_user, None)
                hospitals = []
                location_label = "your location"

                if latitude and longitude:
                    hospitals = find_nearest_hospitals(float(latitude), float(longitude), limit=5)
                else:
                    addr = shared_address or extract_address_from_text(incoming_msg)
                    if addr:
                        geo = geocode_address(addr)
                        if geo:
                            hospitals = find_nearest_hospitals(geo["lat"], geo["lon"], limit=5)
                            location_label = addr

                result = build_emergency_response(risk_signs, hospitals=hospitals, location_label=location_label)
                msg.body(result)
                print("✅ Guided flow escalated to emergency response!")
                return str(resp)

            next_prompt = get_next_prompt(from_user)
            if next_prompt:
                msg.body(next_prompt + "\n\n_Executed By Aniket Yadav_")
                return str(resp)

            session_data = USER_SESSIONS.pop(from_user, {}).get("data", {})
            result = build_guided_assessment(session_data)
            msg.body(result)
            print("✅ Guided assessment sent successfully!")
            return str(resp)

        # 6. Structured format: Age, Symptom, Severity
        if ',' in incoming_msg:
            parts = [p.strip() for p in incoming_msg.split(',')]
            
            if len(parts) >= 3:
                age = parts[0]
                symptom = parse_symptom(parts[1]) or parts[1]
                severity = parts[2]
                print(f"🧩 Processing: {symptom} for age {age}...")

                # Check Local Database
                local_data = get_ayurvedic_knowledge(symptom)
                
                if local_data:
                    result = build_local_record(symptom, local_data)
                else:
                    # Call Gemini AI
                    result = get_ai_recommendation(symptom, age, severity)
                    result += "\n\n_Executed By Aniket Yadav_"
                
                msg.body(result)
            else:
                msg.body("Format Error. Please use: *Age, Symptom, Severity*")
        else:
            # 7. Natural language mode for paragraph-style inputs.
            age, symptom, severity = parse_natural_input(incoming_msg)
            local_data = get_ayurvedic_knowledge(symptom) if symptom else None

            if local_data:
                result = build_local_record(symptom, local_data, include_footer=False)
                result += "\n"
                result += "For personalized dosage, send: *Age, Symptom, Severity*"
                result += "\nExample: `23, fever, mild`\n\n"
                result += "_Executed By Aniket Yadav_"
                msg.body(result)
            elif len(incoming_msg.split()) >= 4:
                # If the user wrote a paragraph, generate AI guidance even when symptom isn't in local DB.
                ai_symptom = symptom if symptom else incoming_msg[:120]
                result = get_ai_recommendation(ai_symptom, age, severity)
                result += "\n\n_Executed By Aniket Yadav_"
                msg.body(result)
            else:
                msg.body(
                    f"Hi {user_name}, I can help with multiple query styles.\n\n"
                    + get_help_text(USER_LANGUAGE_PREF.get(from_user, "en"))
                    + "\n\n"
                    "_Executed By Aniket Yadav_"
                )

        print("✅ Response sent successfully!")
        return str(resp)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        msg.body("I'm currently balancing my energies. Please try again soon. 🧘‍♂️")
        return str(resp)

if __name__ == "__main__":
    # Render provides a 'PORT' environment variable automatically
    port = int(os.environ.get("PORT", 8080))
    print(f"📡 AAYU Server Starting on Render Port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)
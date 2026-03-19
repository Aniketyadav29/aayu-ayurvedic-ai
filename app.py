import os
import re
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv

# Try to import your logic from database.py
try:
    from database import (
        get_ayurvedic_knowledge,
        get_ai_recommendation,
        get_ai_detailed_recommendation,
        get_all_symptoms,
        find_best_symptom,
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
    def geocode_address(address): return None
    def find_nearest_hospitals(lat, lon, limit=5): return []

# Load your .env file (API Keys)
load_dotenv()

app = Flask(__name__)

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
GUIDED_STEPS = ["age", "symptom", "duration", "severity", "pain_reason", "activities"]
STEP_PROMPTS = {
    "age": "Step 1/6: Please enter your age (example: 28)",
    "symptom": "Step 2/6: What is your main symptom or disease?",
    "duration": "Step 3/6: Since when are you facing this problem? (example: 2 days / 1 week)",
    "severity": "Step 4/6: How severe is it? (mild / moderate / severe)",
    "pain_reason": "Step 5/6: What do you think triggered it? (example: cold food, stress, long screen time)",
    "activities": "Step 6/6: Tell me your recent activities/routine (sleep, food, work, exercise).",
}

HELP_TEXT = (
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
    "8) Stop consultation: type `cancel`\n"
    "9) Show this menu again: type `help`"
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
    keywords = ["hospital", "doctor", "clinic", "nearest hospital", "nearby hospital", "emergency"]
    return any(keyword in text for keyword in keywords)


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


def start_guided_session(user_id):
    USER_SESSIONS[user_id] = {
        "step_index": 0,
        "data": {},
    }
    return (
        "🩺 Starting step-by-step consultation.\n"
        "You can type `cancel` anytime to stop.\n\n"
        f"{STEP_PROMPTS['age']}"
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

    return STEP_PROMPTS[GUIDED_STEPS[session["step_index"]]]


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

@app.route("/whatsapp", methods=['POST'])
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
    greetings = ['hi', 'hello', 'hey', 'namaste', 'aayu']
    if any(re.search(rf"\b{re.escape(greet)}\b", incoming_msg) for greet in greetings):
        msg.body(
            f"Welcome {user_name}! 🌿\n\n"
            + HELP_TEXT
            + "\n\nTip: type `start` to begin guided consultation now."
            + "\n\n_Executed By Aniket Yadav_"
        )
        return str(resp)

    if incoming_msg in {"help", "menu", "instructions", "guide"}:
        msg.body(
            f"Hi {user_name}!\n\n"
            + HELP_TEXT
            + "\n\n_Executed By Aniket Yadav_"
        )
        return str(resp)

    if incoming_msg in {"start", "consult", "diagnose"}:
        msg.body(start_guided_session(from_user) + "\n\n_Executed By Aniket Yadav_")
        return str(resp)

    try:
        if incoming_msg in {"cancel", "stop", "exit"} and from_user in USER_SESSIONS:
            USER_SESSIONS.pop(from_user, None)
            msg.body("Consultation cancelled. Type `start` to begin again.\n\n_Executed By Aniket Yadav_")
            return str(resp)

        # 3. Emergency triage mode always gets top priority.
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

        # 4. Hospital help via shared location or typed address.
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

        # 5. Guided consultation mode (step-by-step).
        if from_user in USER_SESSIONS:
            current_step = get_current_step(from_user)
            ok, error_text = save_step_answer(from_user, current_step, request.values.get('Body', '').strip())
            if not ok:
                msg.body(error_text + "\n\n" + STEP_PROMPTS.get(current_step, "Please continue.") + "\n\n_Executed By Aniket Yadav_")
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
                    + HELP_TEXT
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
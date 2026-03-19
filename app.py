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
        get_all_symptoms,
        find_best_symptom,
        geocode_address,
        find_nearest_hospitals,
    )
except ImportError:
    print("⚠️ database.py not found! Using demo mode.")
    def get_ayurvedic_knowledge(x): return None
    def get_ai_recommendation(s, a, v): return "AI logic is currently offline."
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
    latitude = request.values.get("Latitude")
    longitude = request.values.get("Longitude")
    shared_address = request.values.get("Address") or request.values.get("Label")

    resp = MessagingResponse()
    msg = resp.message()

    # 2. Flexible Greeting Logic (Handles Hi, Hello, etc.)
    greetings = ['hi', 'hello', 'hey', 'namaste', 'aayu']
    if any(re.search(rf"\b{re.escape(greet)}\b", incoming_msg) for greet in greetings):
        msg.body(
            "Welcome to AAYU Ayurvedic AI! 🌿\n\n"
            "You can message in any style:\n"
            "• Structured: *23, fever, mild*\n"
            "• Natural text: *I am 23 and I have severe fever since morning*\n"
            "• Hospital help: *hospital near Andheri West Mumbai*\n"
            "• Or share your WhatsApp location for nearest hospitals\n\n"
            "_Executed By Aniket Yadav_"
        )
        return str(resp)

    try:
        # 3. Hospital help via shared location or typed address.
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

        # 4. Structured format: Age, Symptom, Severity
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
            # 5. Natural language mode for paragraph-style inputs.
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
                    "Please explain your condition in one of these styles:\n"
                    "• `23, fever, mild`\n"
                    "• `I am 23 and I have severe headache for 2 days`\n"
                    "• `fever`\n"
                    "• `hospital near Noida Sector 62`\n\n"
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
import os
import re
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv

# Try to import your logic from database.py
try:
    from database import get_ayurvedic_knowledge, get_ai_recommendation
except ImportError:
    print("⚠️ database.py not found! Using demo mode.")
    def get_ayurvedic_knowledge(x): return None
    def get_ai_recommendation(s, a, v): return "AI logic is currently offline."

# Load your .env file (API Keys)
load_dotenv()

app = Flask(__name__)

KNOWN_SYMPTOMS = (
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

    resp = MessagingResponse()
    msg = resp.message()

    # 2. Flexible Greeting Logic (Handles Hi, Hello, etc.)
    greetings = ['hi', 'hello', 'hey', 'namaste', 'aayu']
    if any(re.search(rf"\b{re.escape(greet)}\b", incoming_msg) for greet in greetings):
        msg.body(
            "Welcome to AAYU Ayurvedic AI! 🌿\n\n"
            "You can message in any style:\n"
            "• Structured: *23, fever, mild*\n"
            "• Natural text: *I am 23 and I have severe fever since morning*\n\n"
            "_Executed By Aniket Yadav_"
        )
        return str(resp)

    try:
        # 3. Structured format: Age, Symptom, Severity
        if ',' in incoming_msg:
            parts = [p.strip() for p in incoming_msg.split(',')]
            
            if len(parts) >= 3:
                age, symptom, severity = parts[0], parts[1], parts[2]
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
            # 4. Natural language mode for paragraph-style inputs.
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
                    "• `fever`\n\n"
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
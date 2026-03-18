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

@app.route("/whatsapp", methods=['POST'])
def whatsapp_bot():
    # 1. Capture incoming message
    print("\n--- 🚀 NEW MESSAGE RECEIVED ---")
    incoming_msg = request.values.get('Body', '').strip().lower()
    print(f"📩 Content: '{incoming_msg}'")

    resp = MessagingResponse()
    msg = resp.message()

    # 2. Flexible Greeting Logic (Handles Hi, Hii, Hello, etc.)
    greetings = ['hi', 'hello', 'hey', 'namaste', 'aayu']
    if any(greet in incoming_msg for greet in greetings):
        msg.body("Welcome to AAYU Ayurvedic AI! 🌿\n\nPlease provide: *Age, Symptom, Severity*\nExample: `23, fever, mild` \n\n_Executed By Aniket Yadav_")
        return str(resp)

    try:
        # 3. Parse Data (Age, Symptom, Severity)
        if ',' in incoming_msg:
            parts = [p.strip() for p in incoming_msg.split(',')]
            
            if len(parts) >= 3:
                age, symptom, severity = parts[0], parts[1], parts[2]
                print(f"🧩 Processing: {symptom} for age {age}...")

                # Check Local Database
                local_data = get_ayurvedic_knowledge(symptom)
                
                if local_data:
                    result = f"📖 *Virasat Record for {symptom.capitalize()}*:\n\n"
                    result += f"• Medicine: {local_data.get('medicine')}\n"
                    result += f"• Remedy: {local_data.get('home_remedy')}\n"
                    result += f"• Precaution: {local_data.get('avoid')}\n\n"
                    result += "_Executed By Aniket Yadav_"
                else:
                    # Call Gemini AI
                    result = get_ai_recommendation(symptom, age, severity)
                    result += "\n\n_Executed By Aniket Yadav_"
                
                msg.body(result)
            else:
                msg.body("Format Error. Please use: *Age, Symptom, Severity*")
        else:
            # Fallback: allow direct symptom queries like "fever".
            symptom = re.sub(r'[^a-z\s]', '', incoming_msg).strip()
            local_data = get_ayurvedic_knowledge(symptom) if symptom else None

            if local_data:
                result = f"📖 *Virasat Record for {symptom.capitalize()}*:\n\n"
                result += f"• Medicine: {local_data.get('medicine')}\n"
                result += f"• Remedy: {local_data.get('home_remedy')}\n"
                result += f"• Precaution: {local_data.get('avoid')}\n\n"
                result += "For personalized dosage, send: *Age, Symptom, Severity*"
                result += "\nExample: `23, fever, mild`\n\n"
                result += "_Executed By Aniket Yadav_"
                msg.body(result)
            else:
                msg.body("Please use the format: *Age, Symptom, Severity*\nExample: `23, fever, mild`\nOr send a known symptom like: fever\n\n_Executed By Aniket Yadav_")

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
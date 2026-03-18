import os
import json
from google import genai
from dotenv import load_dotenv

# Load API Keys
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize the new Google GenAI Client
client = genai.Client(api_key=GEMINI_API_KEY)

def get_ayurvedic_knowledge(symptom):
    """Search local knowledge.json file."""
    try:
        if os.path.exists('knowledge.json'):
            with open('knowledge.json', 'r') as f:
                data = json.load(f)
                return data.get(symptom.lower(), None)
        return None
    except Exception as e:
        print(f"Error reading local database: {e}")
        return None

def get_ai_recommendation(symptom, age, severity):
    """Call Gemini 2.5 Flash using the new SDK."""
    prompt = f"""
    You are an Ayurvedic Consultant for 'AAYU'.
    Details: Age {age}, Symptom {symptom}, Severity {severity}.
    
    Provide:
    🌿 AAYU AI Recommendation
    1. Medicine:
    2. Home Remedy:
    3. Diet:
    4. Caution:
    """

    try:
        # New syntax for Gemini 2.5 Flash
        response = client.models.generate_content(
            model="gemini-2.0-flash", 
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"❌ AI Error: {e}")
        return "⚠️ Connection to Ayurvedic AI lost. Try ginger tea while I reconnect!"


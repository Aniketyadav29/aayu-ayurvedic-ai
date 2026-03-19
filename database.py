import os
import json
import math
import urllib.parse
import urllib.request
from google import genai
from dotenv import load_dotenv

# Load API Keys
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize the new Google GenAI Client
client = genai.Client(api_key=GEMINI_API_KEY)

DEFAULT_SYMPTOM_ALIASES = {
    "high temperature": "fever",
    "viral fever": "fever",
    "dry cough": "cough",
    "wet cough": "cough",
    "migraine": "headache",
    "head pain": "headache",
    "common cold": "cold",
    "runny nose": "cold",
    "running nose": "cold",
    "heart burn": "acidity",
    "gas": "acidity",
    "bloated": "indigestion",
    "stomach upset": "indigestion",
    "loose motion": "diarrhea",
    "food poisoning": "diarrhea",
    "vomiting": "nausea",
    "throwing up": "nausea",
    "sugar": "diabetes",
    "bp": "hypertension",
    "high bp": "hypertension",
    "low blood": "anemia",
    "joint pain": "arthritis",
    "knee pain": "arthritis",
    "chest burning": "acidity",
    "breathing issue": "asthma",
    "skin allergy": "allergy",
    "period pain": "menstrual cramps",
    "pcod": "pcos",
}


def load_knowledge_data():
    """Load local Ayurvedic knowledge database."""
    try:
        if os.path.exists('knowledge.json'):
            with open('knowledge.json', 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error reading local database: {e}")
    return {}

def get_ayurvedic_knowledge(symptom):
    """Search local knowledge.json file."""
    data = load_knowledge_data()
    if not symptom:
        return None
    return data.get(symptom.lower(), None)


def get_all_symptoms():
    """Return all known symptom keys from local database."""
    return tuple(load_knowledge_data().keys())


def find_best_symptom(text):
    """Find the most likely known symptom in free-form user text."""
    if not text:
        return None

    text = text.lower().strip()
    data = load_knowledge_data()
    if not data:
        return None

    if text in data:
        return text

    for alias, canonical in DEFAULT_SYMPTOM_ALIASES.items():
        if alias in text and canonical in data:
            return canonical

    for symptom in data.keys():
        if symptom in text:
            return symptom

    tokens = [t for t in text.replace(',', ' ').split() if len(t) > 2]
    best_match = None
    best_score = 0
    for symptom in data.keys():
        score = sum(1 for token in tokens if token in symptom)
        if score > best_score:
            best_score = score
            best_match = symptom

    return best_match if best_score > 0 else None


def geocode_address(address):
    """Convert user-provided address into latitude/longitude via Nominatim."""
    if not address:
        return None

    query = urllib.parse.quote(address)
    url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "aayu-ayurvedic-bot/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if not payload:
            return None

        first = payload[0]
        return {
            "lat": float(first["lat"]),
            "lon": float(first["lon"]),
            "display_name": first.get("display_name", address),
        }
    except Exception as e:
        print(f"Geocoding error: {e}")
        return None


def haversine_distance_km(lat1, lon1, lat2, lon2):
    """Calculate distance in KM between two lat/lon coordinates."""
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def find_nearest_hospitals(lat, lon, limit=5):
    """Find nearby hospitals using OpenStreetMap Overpass API."""
    overpass_query = f"""
    [out:json][timeout:25];
    (
      node[\"amenity\"=\"hospital\"](around:10000,{lat},{lon});
      way[\"amenity\"=\"hospital\"](around:10000,{lat},{lon});
      relation[\"amenity\"=\"hospital\"](around:10000,{lat},{lon});
    );
    out center tags;
    """

    encoded = urllib.parse.urlencode({"data": overpass_query}).encode("utf-8")
    request = urllib.request.Request(
        "https://overpass-api.de/api/interpreter",
        data=encoded,
        headers={"User-Agent": "aayu-ayurvedic-bot/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"Hospital lookup error: {e}")
        return []

    hospitals = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        name = tags.get("name", "Unnamed Hospital")
        address_parts = [
            tags.get("addr:street", ""),
            tags.get("addr:city", ""),
            tags.get("addr:state", ""),
        ]
        address = ", ".join([part for part in address_parts if part]) or "Address not available"

        if "lat" in element and "lon" in element:
            h_lat, h_lon = element["lat"], element["lon"]
        elif "center" in element:
            h_lat, h_lon = element["center"]["lat"], element["center"]["lon"]
        else:
            continue

        distance = haversine_distance_km(lat, lon, h_lat, h_lon)
        hospitals.append(
            {
                "name": name,
                "address": address,
                "distance_km": round(distance, 2),
            }
        )

    hospitals.sort(key=lambda item: item["distance_km"])
    return hospitals[:limit]

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


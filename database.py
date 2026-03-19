import os
import json
import math
import sqlite3
import urllib.parse
import urllib.request
from datetime import date, timedelta
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

TRACKER_STATE = {}
REMINDER_DB_PATH = "reminders.db"


def init_reminder_db():
    """Create reminders table if it does not exist."""
    conn = sqlite3.connect(REMINDER_DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_reminders (
                user_id TEXT PRIMARY KEY,
                phone TEXT NOT NULL,
                reminder_time TEXT NOT NULL,
                reminder_message TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_sent_date TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def upsert_daily_reminder(user_id, phone, reminder_time, reminder_message):
    """Create or update a user's daily reminder."""
    init_reminder_db()
    conn = sqlite3.connect(REMINDER_DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO daily_reminders (user_id, phone, reminder_time, reminder_message, enabled, last_sent_date)
            VALUES (?, ?, ?, ?, 1, NULL)
            ON CONFLICT(user_id) DO UPDATE SET
                phone=excluded.phone,
                reminder_time=excluded.reminder_time,
                reminder_message=excluded.reminder_message,
                enabled=1
            """,
            (user_id, phone, reminder_time, reminder_message),
        )
        conn.commit()
    finally:
        conn.close()


def disable_daily_reminder(user_id):
    """Disable daily reminder for a user."""
    init_reminder_db()
    conn = sqlite3.connect(REMINDER_DB_PATH)
    try:
        cur = conn.execute("UPDATE daily_reminders SET enabled=0 WHERE user_id=?", (user_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_user_daily_reminder(user_id):
    """Fetch configured daily reminder for a user."""
    init_reminder_db()
    conn = sqlite3.connect(REMINDER_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT user_id, phone, reminder_time, reminder_message, enabled, last_sent_date FROM daily_reminders WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_due_daily_reminders(current_time, current_date):
    """Return reminders due at the provided HH:MM and not sent today."""
    init_reminder_db()
    conn = sqlite3.connect(REMINDER_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT user_id, phone, reminder_time, reminder_message, enabled, last_sent_date
            FROM daily_reminders
            WHERE enabled=1
              AND reminder_time=?
              AND (last_sent_date IS NULL OR last_sent_date <> ?)
            """,
            (current_time, current_date),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_daily_reminder_sent(user_id, current_date):
    """Mark reminder as sent for the day."""
    init_reminder_db()
    conn = sqlite3.connect(REMINDER_DB_PATH)
    try:
        conn.execute(
            "UPDATE daily_reminders SET last_sent_date=? WHERE user_id=?",
            (current_date, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def load_structured_db():
    """Load structured Ayurveda DB used for NLP and knowledge graph retrieval."""
    try:
        if os.path.exists("structured_db.json"):
            with open("structured_db.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"Error reading structured DB: {e}")
    return {
        "conditions": {},
        "ingredient_remedies": [],
        "mood_mind": {},
        "prakriti_questions": [],
        "knowledge_graph": {"nodes": [], "edges": []},
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


def get_structured_conditions():
    return load_structured_db().get("conditions", {})


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

    condition_names = set(data.keys()) | set(get_structured_conditions().keys())

    for symptom in condition_names:
        if symptom in text:
            return symptom

    tokens = [t for t in text.replace(',', ' ').split() if len(t) > 2]
    best_match = None
    best_score = 0
    for symptom in condition_names:
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


def parse_ingredients_from_text(text):
    """Simple NLP extraction of ingredients from user text."""
    if not text:
        return []

    text = text.lower()
    db = load_structured_db()
    ingredient_vocab = set()
    for item in db.get("ingredient_remedies", []):
        ingredient_vocab.update(i.lower() for i in item.get("ingredients", []))

    # Support common kitchen synonyms.
    synonyms = {
        "haldi": "turmeric",
        "adrak": "ginger",
        "shahad": "honey",
        "cumin": "jeera",
        "carom": "ajwain",
        "fennel": "saunf",
    }

    normalized = text
    for src, dest in synonyms.items():
        normalized = normalized.replace(src, dest)

    found = []
    for ingredient in ingredient_vocab:
        if ingredient in normalized:
            found.append(ingredient)

    # Generic comma-separated fallback.
    if not found and "," in text:
        for token in [t.strip().lower() for t in text.split(",") if t.strip()]:
            if len(token) > 2:
                found.append(token)

    return sorted(set(found))


def get_home_remedies_by_ingredients(ingredients):
    """Return remedies user can prepare using available ingredients."""
    db = load_structured_db()
    remedies = []
    ing_set = set(i.lower() for i in ingredients)

    for item in db.get("ingredient_remedies", []):
        required = set(i.lower() for i in item.get("ingredients", []))
        matched = sorted(required & ing_set)

        if len(required) == 0:
            continue

        # Practical match threshold: at least 2 ingredients or full match for small recipes.
        min_required = 2 if len(required) >= 3 else len(required)
        if len(matched) >= min_required:
            remedies.append(
                {
                    "name": item.get("name"),
                    "for": item.get("for", []),
                    "instructions": item.get("instructions", ""),
                    "matched_ingredients": matched,
                    "missing_ingredients": sorted(required - ing_set),
                }
            )

    return remedies


def get_mood_mind_support(text):
    """Return dosha-linked mental wellness suggestions."""
    text = (text or "").lower()
    mood_db = load_structured_db().get("mood_mind", {})
    mood_aliases = {
        "anxious": ["anxious", "anxiety", "घबराहट"],
        "stressed": ["stress", "stressed", "tension", "तनाव"],
        "sad": ["sad", "low", "depressed", "उदास"],
    }

    for mood_key, keywords in mood_aliases.items():
        if any(k in text for k in keywords):
            return mood_db.get(mood_key)
    return None


def analyze_prakriti(answers):
    """AI-assisted plus rule-based Prakriti analyzer (Vata/Pitta/Kapha)."""
    joined = " | ".join(a.lower() for a in answers if a)
    score = {"Vata": 0, "Pitta": 0, "Kapha": 0}

    vata_words = ["thin", "irregular", "dry", "light sleep", "anxious", "quick"]
    pitta_words = ["medium", "strong", "warm", "intense", "focused", "hot"]
    kapha_words = ["broad", "slow", "cool", "deep sleep", "calm", "steady"]

    for word in vata_words:
        if word in joined:
            score["Vata"] += 1
    for word in pitta_words:
        if word in joined:
            score["Pitta"] += 1
    for word in kapha_words:
        if word in joined:
            score["Kapha"] += 1

    dominant = max(score, key=score.get)
    confidence = round((score[dominant] / max(1, sum(score.values()))) * 100)

    # AI refinement where possible.
    ai_text = None
    try:
        prompt = (
            "You are an Ayurveda specialist. Based on these answers, detect dominant dosha (Vata/Pitta/Kapha), "
            "secondary dosha, and give 3 concise lifestyle tips.\n"
            f"Answers: {answers}"
        )
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        ai_text = response.text
    except Exception as e:
        print(f"Prakriti AI fallback used: {e}")

    fallback = (
        f"Dominant dosha: {dominant} (confidence: {confidence}%).\n"
        "General tips: Keep routine stable, eat fresh warm food, and manage stress with breathing practice."
    )
    return ai_text or fallback


def explain_condition_styles(condition):
    """Return scientific/simple/grandma style explanation for condition."""
    condition = (condition or "").lower().strip()
    data = get_structured_conditions().get(condition)
    if not data:
        return None

    return {
        "dosha": data.get("dosha", "Unknown"),
        "scientific": data.get("scientific", "N/A"),
        "simple": data.get("simple", "N/A"),
        "grandma": data.get("grandma", "N/A"),
    }


def knowledge_graph_links(topic):
    """Return related knowledge-graph edges for a topic."""
    topic = (topic or "").lower().strip()
    graph = load_structured_db().get("knowledge_graph", {})
    edges = graph.get("edges", [])
    related = [e for e in edges if e.get("from", "").lower() == topic or e.get("to", "").lower() == topic]
    return related[:8]


def update_health_tracker(user_id, water_glasses, sleep_hours, diet_quality, today=None):
    """Update per-user daily habit tracker with simple gamification streaks."""
    if today is None:
        today = date.today().isoformat()

    tracker = TRACKER_STATE.setdefault(
        user_id,
        {"last_date": None, "streak": 0, "history": [], "badges": []},
    )

    score = 0
    if water_glasses >= 8:
        score += 1
    if sleep_hours >= 7:
        score += 1
    if diet_quality in {"good", "healthy", "clean"}:
        score += 1

    good_day = score >= 2

    if tracker["last_date"] is None:
        tracker["streak"] = 1 if good_day else 0
    else:
        prev = date.fromisoformat(tracker["last_date"])
        curr = date.fromisoformat(today)
        if curr == prev:
            # Same day update only replaces data.
            pass
        elif curr == prev + timedelta(days=1):
            tracker["streak"] = tracker["streak"] + 1 if good_day else 0
        else:
            tracker["streak"] = 1 if good_day else 0

    tracker["last_date"] = today
    tracker["history"].append(
        {
            "date": today,
            "water": water_glasses,
            "sleep": sleep_hours,
            "diet": diet_quality,
            "good_day": good_day,
        }
    )

    if tracker["streak"] >= 7 and "Healthy 7-Day Badge" not in tracker["badges"]:
        tracker["badges"].append("Healthy 7-Day Badge")
    if tracker["streak"] >= 21 and "Discipline 21-Day Badge" not in tracker["badges"]:
        tracker["badges"].append("Discipline 21-Day Badge")

    return {
        "streak": tracker["streak"],
        "badges": list(tracker["badges"]),
        "good_day": good_day,
    }

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


def get_ai_detailed_recommendation(symptom, age, severity, duration, pain_reason, activities):
    """Generate detailed recommendation for guided step-by-step consultation."""
    prompt = f"""
    You are an Ayurvedic Consultant for 'AAYU'.
    Patient profile:
    - Age: {age}
    - Main symptom/condition: {symptom}
    - Severity: {severity}
    - Duration: {duration}
    - Suspected reason of pain: {pain_reason}
    - Recent activities: {activities}

    Give a concise, practical response in this exact structure:
    🌿 AAYU Guided Assessment
    1. Probable Reason:
    2. Medicine Support (general):
    3. Home Remedy:
    4. Activity/Lifestyle Changes:
    5. Diet Advice:
    6. Red-Flag Warning (when to visit hospital immediately):

    Keep the response user-friendly and safe.
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"❌ AI Detailed Error: {e}")
        return (
            "⚠️ I could not generate a full guided assessment right now.\n"
            "Please rest, stay hydrated, and if symptoms are severe or persistent, visit the nearest hospital."
        )


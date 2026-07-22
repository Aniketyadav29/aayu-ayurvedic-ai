import json
import logging
import math
import os
import re
import sqlite3
import threading
import urllib.parse
import urllib.request
from difflib import get_close_matches
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from google import genai
from dotenv import load_dotenv

logger = logging.getLogger("aayu.database")

# Load API Keys
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_MODEL_CANDIDATES = [
    GEMINI_MODEL_NAME,
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-pro-latest",
]

# New unified google-genai SDK client (handles both AIza and AQ. Auth keys internally).
if GEMINI_API_KEY:
    GEMINI_CLIENT = genai.Client(api_key=GEMINI_API_KEY)
else:
    GEMINI_CLIENT = None

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
REMINDER_DB_PATH = os.path.join("/tmp", "reminders.db") if os.getenv("VERCEL") else "reminders.db"

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
USING_POSTGRES = bool(DATABASE_URL)


class DBRow(dict):
    def __init__(self, col_names, row_tuple):
        super().__init__(zip(col_names, row_tuple))
        self._tuple = row_tuple

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._tuple[key]
        return super().__getitem__(key)


def get_db():
    if USING_POSTGRES:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
    else:
        conn = sqlite3.connect(REMINDER_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
    return conn, cur


def query_db(cur, query, params=()):
    if USING_POSTGRES:
        query = query.replace('?', '%s')
    cur.execute(query, params)
    return cur


def fetch_one(cur):
    row = cur.fetchone()
    if row is None:
        return None
    if USING_POSTGRES:
        col_names = [desc[0] for desc in cur.description]
        return DBRow(col_names, row)
    return row


def fetch_all(cur):
    rows = cur.fetchall()
    if USING_POSTGRES:
        col_names = [desc[0] for desc in cur.description]
        return [DBRow(col_names, r) for r in rows]
    return rows

# ---------------------------------------------------------------------------
# Module-level caches for knowledge.json and structured_db.json
# Loaded once at import time instead of re-reading from disk on every request.
# ---------------------------------------------------------------------------
_knowledge_cache: dict | None = None
_structured_db_cache: dict | None = None


def _load_knowledge_data_from_disk() -> dict:
    """Read knowledge.json from disk (internal helper)."""
    try:
        if os.path.exists("knowledge.json"):
            with open("knowledge.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error("Error reading knowledge.json: %s", e)
    return {}


def _load_structured_db_from_disk() -> dict:
    """Read structured_db.json from disk (internal helper)."""
    try:
        if os.path.exists("structured_db.json"):
            with open("structured_db.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error("Error reading structured_db.json: %s", e)
    return {
        "conditions": {},
        "ingredient_remedies": [],
        "mood_mind": {},
        "prakriti_questions": [],
        "knowledge_graph": {"nodes": [], "edges": []},
    }


def _init_caches():
    """Initialize module-level caches."""
    global _knowledge_cache, _structured_db_cache
    _knowledge_cache = _load_knowledge_data_from_disk()
    _structured_db_cache = _load_structured_db_from_disk()
    logger.info(
        "Caches loaded: %d symptoms, %d conditions",
        len(_knowledge_cache),
        len(_structured_db_cache.get("conditions", {})),
    )


def reload_caches():
    """Hot-reload caches from disk (e.g. after updating JSON files)."""
    _init_caches()


# Initialize caches at module load
_init_caches()


def init_reminder_db():
    """Create reminders table if it does not exist."""
    conn, cur = get_db()
    try:
        query_db(
            cur,
            """
            CREATE TABLE IF NOT EXISTS daily_reminders (
                user_id TEXT PRIMARY KEY,
                phone TEXT NOT NULL,
                reminder_time TEXT NOT NULL,
                reminder_message TEXT NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_sent_date TEXT
            )
            """,
        )

        # Health tracker table (persistent, replaces in-memory TRACKER_STATE)
        query_db(
            cur,
            """
            CREATE TABLE IF NOT EXISTS health_tracker (
                user_id TEXT NOT NULL,
                date TEXT NOT NULL,
                water INTEGER NOT NULL DEFAULT 0,
                sleep INTEGER NOT NULL DEFAULT 0,
                diet TEXT NOT NULL DEFAULT '',
                good_day INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, date)
            )
            """,
        )
        query_db(
            cur,
            """
            CREATE TABLE IF NOT EXISTS health_tracker_meta (
                user_id TEXT PRIMARY KEY,
                streak INTEGER NOT NULL DEFAULT 0,
                badges_json TEXT NOT NULL DEFAULT '[]',
                last_date TEXT
            )
            """,
        )
        query_db(
            cur,
            """
            CREATE TABLE IF NOT EXISTS user_state (
                user_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL
            )
            """,
        )

        # Lightweight migration for older DBs created before timezone column existed.
        if not USING_POSTGRES:
            query_db(cur, "PRAGMA table_info(daily_reminders)")
            columns = [row[1] for row in cur.fetchall()]
            if "timezone" not in columns:
                query_db(
                    cur,
                    "ALTER TABLE daily_reminders ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata'",
                )

        conn.commit()
    finally:
        conn.close()


def get_user_state(user_id):
    """Retrieve user conversation state from database."""
    init_reminder_db()
    conn, cur = get_db()
    try:
        query_db(cur, "SELECT state_json FROM user_state WHERE user_id = ?", (user_id,))
        row = fetch_one(cur)
        if row:
            return json.loads(row[0])
        return {}
    finally:
        conn.close()


def save_user_state(user_id, state):
    """Save user conversation state to database."""
    init_reminder_db()
    conn, cur = get_db()
    try:
        query_db(
            cur,
            """
            INSERT INTO user_state (user_id, state_json)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET state_json = excluded.state_json
            """,
            (user_id, json.dumps(state)),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_daily_reminder(user_id, phone, reminder_time, reminder_message):
    """Create or update a user's daily reminder."""
    init_reminder_db()
    conn, cur = get_db()
    try:
        query_db(
            cur,
            """
            INSERT INTO daily_reminders (user_id, phone, reminder_time, reminder_message, timezone, enabled, last_sent_date)
            VALUES (?, ?, ?, ?, 'Asia/Kolkata', 1, NULL)
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


def set_user_timezone(user_id, timezone_name):
    """Set timezone for a user's reminder schedule."""
    init_reminder_db()
    try:
        ZoneInfo(timezone_name)
    except Exception:
        return False

    conn, cur = get_db()
    try:
        query_db(
            cur,
            "UPDATE daily_reminders SET timezone=? WHERE user_id=?",
            (timezone_name, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def disable_daily_reminder(user_id):
    """Disable daily reminder for a user."""
    init_reminder_db()
    conn, cur = get_db()
    try:
        query_db(cur, "UPDATE daily_reminders SET enabled=0 WHERE user_id=?", (user_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_user_daily_reminder(user_id):
    """Fetch configured daily reminder for a user."""
    init_reminder_db()
    conn, cur = get_db()
    try:
        query_db(
            cur,
            "SELECT user_id, phone, reminder_time, reminder_message, timezone, enabled, last_sent_date FROM daily_reminders WHERE user_id=?",
            (user_id,),
        )
        row = fetch_one(cur)
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_enabled_daily_reminders():
    """Return all enabled reminders with timezone metadata."""
    init_reminder_db()
    conn, cur = get_db()
    try:
        query_db(
            cur,
            """
            SELECT user_id, phone, reminder_time, reminder_message, timezone, enabled, last_sent_date
            FROM daily_reminders
            WHERE enabled=1
            """,
        )
        rows = fetch_all(cur)
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_due_daily_reminders(current_time, current_date):
    """Return reminders due at the provided HH:MM and not sent today."""
    init_reminder_db()
    conn, cur = get_db()
    try:
        query_db(
            cur,
            """
            SELECT user_id, phone, reminder_time, reminder_message, enabled, last_sent_date
            FROM daily_reminders
            WHERE enabled=1
              AND reminder_time=?
              AND (last_sent_date IS NULL OR last_sent_date <> ?)
            """,
            (current_time, current_date),
        )
        rows = fetch_all(cur)
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_daily_reminder_sent(user_id, current_date):
    """Mark reminder as sent for the day."""
    init_reminder_db()
    conn, cur = get_db()
    try:
        query_db(
            cur,
            "UPDATE daily_reminders SET last_sent_date=? WHERE user_id=?",
            (current_date, user_id),
        )
        conn.commit()
    finally:
        conn.close()



def load_structured_db():
    """Return cached structured Ayurveda DB."""
    return _structured_db_cache if _structured_db_cache is not None else _load_structured_db_from_disk()


def load_knowledge_data():
    """Return cached Ayurvedic knowledge database."""
    return _knowledge_cache if _knowledge_cache is not None else _load_knowledge_data_from_disk()

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


def get_menu_database_classification():
    """Classify available data coverage according to AAYU menu sections."""
    knowledge = load_knowledge_data() or {}
    structured = load_structured_db() or {}

    conditions = structured.get("conditions", {}) or {}
    ingredient_remedies = structured.get("ingredient_remedies", []) or []
    mood_mind = structured.get("mood_mind", {}) or {}
    prakriti_questions = structured.get("prakriti_questions", []) or []
    graph = structured.get("knowledge_graph", {}) or {}
    graph_nodes = graph.get("nodes", []) or []
    graph_edges = graph.get("edges", []) or []

    menu_map = [
        ("Step-by-step Consultation", "Gemini API + knowledge.json + structured_db.json", f"symptoms={len(knowledge)}, conditions={len(conditions)}"),
        ("Quick Query / Paragraph / Symptom", "Gemini API + knowledge.json", f"symptoms={len(knowledge)}"),
        ("Hospital Near Me / Live Location", "OpenStreetMap APIs (geocoding + hospitals)", "external live data"),
        ("Emergency Support", "Gemini API + emergency keyword rules", "rules + AI triage text"),
        ("Ingredient Remedies", "Gemini API + structured_db.json: ingredient_remedies", f"remedies={len(ingredient_remedies)}"),
        ("Mood Support", "Gemini API + structured_db.json: mood_mind", f"mood_profiles={len(mood_mind)}"),
        ("Prakriti Analyzer", "Gemini API + structured_db.json: prakriti_questions", f"questions={len(prakriti_questions)}"),
        ("Explain Like Grandma", "Gemini API + structured_db.json: conditions", f"conditions={len(conditions)}"),
        ("Knowledge Graph", "Gemini API + structured_db.json: knowledge_graph", f"nodes={len(graph_nodes)}, edges={len(graph_edges)}"),
        ("Health Tracker", "SQLite reminders.db (tracker state) + Gemini interpretation", "stateful user data"),
        ("Daily Reminder / Timezone", "SQLite reminders.db", "stateful user schedule"),
        ("Menu Image", "static/menu_custom.png or fallback generated image", "static media asset"),
        ("Daily Routine Planner", "Gemini API (primary) + local fallback", "AI-first routine generation"),
    ]

    gaps = []
    if len(knowledge) < 30:
        gaps.append("knowledge.json symptom coverage is limited (<30).")
    if len(conditions) < 15:
        gaps.append("structured conditions coverage is limited (<15).")
    if len(ingredient_remedies) < 10:
        gaps.append("ingredient remedies are limited (<10).")
    if len(mood_mind) < 5:
        gaps.append("mood support profiles are limited (<5).")
    if len(graph_edges) < 20:
        gaps.append("knowledge graph links are limited (<20 edges).")

    lines = ["AAYU Menu-wise Database Classification"]
    for idx, (menu_name, source, coverage) in enumerate(menu_map, start=1):
        lines.append(f"{idx}. {menu_name}")
        lines.append(f"   Source: {source}")
        lines.append(f"   Coverage: {coverage}")

    if gaps:
        lines.append("Data gaps detected:")
        for g in gaps:
            lines.append(f"- {g}")
    else:
        lines.append("Data gaps detected: none major")

    return "\n".join(lines)


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
        logger.error("Geocoding error: %s", e)
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
        logger.error("Hospital lookup error: %s", e)
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
        "haldi powder": "turmeric",
        "adrak": "ginger",
        "sonth": "ginger",
        "shahad": "honey",
        "madhu": "honey",
        "cumin": "jeera",
        "jeera seeds": "jeera",
        "carom": "ajwain",
        "ajvain": "ajwain",
        "fennel": "saunf",
        "saumph": "saunf",
        "kali mirch": "black pepper",
        "blackpepper": "black pepper",
        "tulasi": "tulsi",
    }

    normalized = text
    for src, dest in synonyms.items():
        normalized = normalized.replace(src, dest)

    found = []
    for ingredient in ingredient_vocab:
        if ingredient in normalized:
            found.append(ingredient)

    # Token-level fallback with fuzzy matching for typos.
    if not found:
        tokens = [
            t.strip().lower()
            for t in re.split(r"[,;/]|\band\b|\bwith\b|\busing\b|\bor\b", normalized)
            if t.strip()
        ]
        cleaned_tokens = []
        for token in tokens:
            token = re.sub(r"[^a-z\s]", " ", token)
            token = " ".join(token.split())
            if len(token) >= 3:
                cleaned_tokens.append(token)

        for token in cleaned_tokens:
            if token in ingredient_vocab:
                found.append(token)
                continue

            # Match ingredient phrase included in user token (e.g., "fresh ginger root").
            contains_match = next((ing for ing in ingredient_vocab if ing in token or token in ing), None)
            if contains_match:
                found.append(contains_match)
                continue

            close = get_close_matches(token, list(ingredient_vocab), n=1, cutoff=0.76)
            if close:
                found.append(close[0])

    return sorted(set(found))


def get_home_remedies_by_ingredients(ingredients):
    """Return remedies user can prepare using available ingredients."""
    db = load_structured_db()
    remedies = []
    ing_set = set(i.lower() for i in ingredients)

    if not ing_set:
        defaults = []
        for item in db.get("ingredient_remedies", [])[:3]:
            required = set(i.lower() for i in item.get("ingredients", []))
            defaults.append(
                {
                    "name": item.get("name"),
                    "for": item.get("for", []),
                    "instructions": item.get("instructions", ""),
                    "matched_ingredients": [],
                    "missing_ingredients": sorted(required),
                    "match_score": 0,
                    "partial": True,
                }
            )
        return defaults

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
                    "match_score": len(matched),
                    "partial": False,
                }
            )

    if remedies:
        remedies.sort(key=lambda r: (-r.get("match_score", 0), len(r.get("missing_ingredients", []))))
        return remedies

    # If no strong match, still provide best partial suggestions.
    partial_candidates = []
    for item in db.get("ingredient_remedies", []):
        required = set(i.lower() for i in item.get("ingredients", []))
        matched = sorted(required & ing_set)
        if not matched:
            continue
        partial_candidates.append(
            {
                "name": item.get("name"),
                "for": item.get("for", []),
                "instructions": item.get("instructions", ""),
                "matched_ingredients": matched,
                "missing_ingredients": sorted(required - ing_set),
                "match_score": len(matched),
                "partial": True,
            }
        )

    partial_candidates.sort(key=lambda r: (-r.get("match_score", 0), len(r.get("missing_ingredients", []))))
    return partial_candidates[:3]


def build_non_ai_recommendation(symptom, age, severity, detailed=False, duration=None, pain_reason=None, activities=None):
    """Reliable local fallback response when Gemini is unavailable."""
    symptom_key = (symptom or "unknown").lower().strip()
    local = get_ayurvedic_knowledge(symptom_key)
    structured = get_structured_conditions().get(symptom_key)

    lines = ["🌿 AAYU Fallback Recommendation"]
    lines.append(f"Symptom: {symptom_key if symptom_key else 'not provided'}")
    lines.append(f"Severity: {severity}")

    if local:
        lines.append(f"Medicine: {local.get('medicine', 'General supportive care')}")
        lines.append(f"Home Remedy: {local.get('home_remedy', 'Warm fluids and rest')}")
        lines.append(f"Diet/Lifestyle: {local.get('lifestyle_tips', 'Eat light, warm meals and hydrate')}")
        lines.append(f"Precaution: {local.get('avoid', 'Avoid self-medication if symptoms worsen')}")
    elif structured:
        lines.append(f"Dosha tendency: {structured.get('dosha', 'Unknown')}")
        lines.append(f"Simple view: {structured.get('simple', 'Support digestion, hydration, and rest')}")
        lines.append(f"Traditional tip: {structured.get('grandma', 'Use warm food and regular routine')}")
    else:
        lines.append("Medicine: Please use doctor-advised medicine for this condition.")
        lines.append("Home Remedy: Warm fluids, rest, and light meals can support recovery.")
        lines.append("Diet/Lifestyle: Avoid heavy, oily, and very cold foods.")

    if detailed:
        if duration:
            lines.append(f"Duration noted: {duration}")
        if pain_reason:
            lines.append(f"Possible trigger: {pain_reason}")
        if activities:
            lines.append(f"Activity context: {activities}")

    lines.append("⚠️ If symptoms are severe, persistent, or include emergency signs, visit nearest hospital immediately.")
    return "\n".join(lines)


def get_daily_routine_plan(user_text, age=None):
    """Generate a time-wise Ayurveda daily routine with food and exercise guidance."""
    symptom = find_best_symptom(user_text or "") or "general wellness"
    age_hint = age if isinstance(age, int) and 1 <= age <= 120 else None

    fallback = [
        "🌿 AAYU Daily Routine Planner",
        f"Profile: age {age_hint if age_hint else 'adult'} | focus: {symptom}",
        "",
        "05:30 - 06:00: Wake up, drink 1 glass warm water.",
        "06:00 - 06:20: Light stretching + 10 minutes deep breathing.",
        "06:30 - 07:00: Walk / yoga (20-30 minutes).",
        "07:30: Breakfast: warm, light meal (for example porridge, fruit, soaked nuts).",
        "10:30: Mid-morning: herbal water or seasonal fruit.",
        "13:00: Lunch: main meal, fresh cooked food, include vegetables + protein.",
        "16:30: Evening snack: light snack, avoid deep-fried items.",
        "18:00 - 18:30: Evening walk or gentle mobility exercises.",
        "19:30: Dinner: lighter than lunch, easy to digest warm food.",
        "21:00: Screen-off wind-down, 5 minutes calm breathing.",
        "22:00: Sleep.",
        "",
        "Exercise routine: 5 days/week moderate movement + 2 days gentle recovery/stretching.",
        "Hydration: sip warm water through the day.",
        "⚠️ If symptoms worsen or severe signs appear, consult a doctor promptly.",
    ]
    fallback_text = "\n".join(fallback)

    if not GEMINI_API_KEY:
        return fallback_text

    prompt = f"""
You are an Ayurveda lifestyle planner.
Create a practical, time-wise daily routine for WhatsApp format.

User message: {user_text}
Detected age: {age_hint if age_hint else 'not provided'}
Detected focus symptom: {symptom}

Return plain text only with this structure:
1) Title line
2) Time-wise routine from morning to night (at least 8 time slots)
3) What to eat through the day (time-wise)
4) Exercise routine (morning + evening)
5) 1 safety warning line

Rules:
- Keep it concise and realistic.
- Use simple language.
- Avoid prescribing exact medicines/doses.
"""

    try:
        response = generate_gemini_with_timeout(prompt, timeout_seconds=9)
        text = (getattr(response, "text", "") or "").strip()
        return text if text else fallback_text
    except Exception:
        return fallback_text


def generate_gemini_with_timeout(prompt, timeout_seconds=9):
    """Call Gemini with a hard timeout without blocking webhook response."""
    result_holder = {"response": None, "error": None}

    def _worker():
        try:
            if not GEMINI_CLIENT:
                raise ValueError("Gemini API key is not configured")

            last_err = None
            for model_name in GEMINI_MODEL_CANDIDATES:
                try:
                    result_holder["response"] = GEMINI_CLIENT.models.generate_content(
                        model=model_name, contents=prompt
                    )
                    return
                except Exception as model_err:
                    last_err = model_err

            raise last_err if last_err else RuntimeError("Gemini call failed for all candidate models")
        except Exception as err:
            result_holder["error"] = err

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive():
        raise TimeoutError("Gemini request timed out")
    if result_holder["error"] is not None:
        raise result_holder["error"]
    return result_holder["response"]


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
        if not GEMINI_CLIENT:
            raise ValueError("Gemini API key is not configured")
        response = GEMINI_CLIENT.models.generate_content(model=GEMINI_MODEL_NAME, contents=prompt)
        ai_text = response.text
    except Exception as e:
        logger.info("Prakriti AI fallback used: %s", e)

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
    """Update per-user daily habit tracker with gamification (persisted to SQLite)."""
    init_reminder_db()
    if today is None:
        today = date.today().isoformat()

    score = 0
    if water_glasses >= 8:
        score += 1
    if sleep_hours >= 7:
        score += 1
    if diet_quality in {"good", "healthy", "clean"}:
        score += 1

    good_day = score >= 2

    conn, cur = get_db()
    try:
        # Upsert daily entry
        query_db(
            cur,
            """
            INSERT INTO health_tracker (user_id, date, water, sleep, diet, good_day)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, date) DO UPDATE SET
                water=excluded.water,
                sleep=excluded.sleep,
                diet=excluded.diet,
                good_day=excluded.good_day
            """,
            (user_id, today, water_glasses, sleep_hours, diet_quality, int(good_day)),
        )

        # Calculate streak from DB history directly
        query_db(
            cur,
            "SELECT date, good_day FROM health_tracker WHERE user_id = ? ORDER BY date DESC",
            (user_id,),
        )
        rows = fetch_all(cur)
        dates_map = {r["date"]: r["good_day"] for r in rows}

        curr = date.fromisoformat(today)
        if dates_map.get(today, 0) == 1:
            streak = 1
            check_date = curr - timedelta(days=1)
            while dates_map.get(check_date.isoformat(), 0) == 1:
                streak += 1
                check_date -= timedelta(days=1)
        else:
            streak = 0

        # Read or create tracker meta
        query_db(
            cur,
            "SELECT streak, badges_json, last_date FROM health_tracker_meta WHERE user_id=?",
            (user_id,),
        )
        meta = fetch_one(cur)

        if meta is None:
            badges = []
            query_db(
                cur,
                "INSERT INTO health_tracker_meta (user_id, streak, badges_json, last_date) VALUES (?, ?, ?, ?)",
                (user_id, streak, json.dumps(badges), today),
            )
        else:
            badges_json = meta["badges_json"]
            badges = json.loads(badges_json) if badges_json else []

            if streak >= 7 and "Healthy 7-Day Badge" not in badges:
                badges.append("Healthy 7-Day Badge")
            if streak >= 21 and "Discipline 21-Day Badge" not in badges:
                badges.append("Discipline 21-Day Badge")

            query_db(
                cur,
                "UPDATE health_tracker_meta SET streak=?, badges_json=?, last_date=? WHERE user_id=?",
                (streak, json.dumps(badges), today, user_id),
            )

        conn.commit()
    finally:
        conn.close()

    return {
        "streak": streak,
        "badges": badges,
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

    if not GEMINI_API_KEY:
        return build_non_ai_recommendation(symptom, age, severity, detailed=False)

    try:
        response = generate_gemini_with_timeout(prompt, timeout_seconds=9)
        return response.text
    except TimeoutError:
        logger.warning("AI Timeout: falling back to local recommendation")
        return build_non_ai_recommendation(symptom, age, severity, detailed=False)
    except Exception as e:
        logger.error("AI Error: %s", e)
        return build_non_ai_recommendation(symptom, age, severity, detailed=False)


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

    if not GEMINI_API_KEY:
        return build_non_ai_recommendation(
            symptom,
            age,
            severity,
            detailed=True,
            duration=duration,
            pain_reason=pain_reason,
            activities=activities,
        )

    try:
        response = generate_gemini_with_timeout(prompt, timeout_seconds=10)
        return response.text
    except TimeoutError:
        logger.warning("AI Detailed Timeout: falling back to local recommendation")
        return build_non_ai_recommendation(
            symptom,
            age,
            severity,
            detailed=True,
            duration=duration,
            pain_reason=pain_reason,
            activities=activities,
        )
    except Exception as e:
        logger.error("AI Detailed Error: %s", e)
        return build_non_ai_recommendation(
            symptom,
            age,
            severity,
            detailed=True,
            duration=duration,
            pain_reason=pain_reason,
            activities=activities,
        )


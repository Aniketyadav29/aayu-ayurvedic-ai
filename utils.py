"""AAYU utility functions and shared constants."""

import json
import re

MAX_MESSAGE_LENGTH = 1000

EMERGENCY_KEYWORDS = [
    "chest pain",
    "difficulty breathing",
    "breathing problem",
    "cannot breathe",
    "stroke",
    "unconscious",
    "fainting",
    "severe bleeding",
    "suicidal",
]

SEVERITY_WORDS = {
    "mild": ["mild", "light", "thoda", "minor"],
    "moderate": ["moderate", "medium", "normal"],
    "severe": ["severe", "high", "bahut", "extreme", "intense", "worst"],
}

PRAKRITI_DEFAULT_QUESTIONS = [
    "How is your body frame: thin, medium, or broad?",
    "How is your digestion: irregular, strong, or slow?",
    "How is your sleep: light, medium, or deep?",
    "How is your mental tendency: anxious, focused, or calm?",
]

LOCAL_TEXT_NORMALIZATION = {
    "sir dard": "headache",
    "sar dard": "headache",
    "head pain": "headache",
    "pet dard": "stomach pain",
    "bukhar": "fever",
    "khansi": "cough",
    "sardi": "cold",
    "acidity ho rahi": "acidity",
    "gas ho rahi": "acidity",
    "ulti": "nausea",
    "saanse": "breathing",
    "\u0938\u093f\u0930 \u0926\u0930\u094d\u0926": "headache",
    "\u092c\u0941\u0916\u093e\u0930": "fever",
    "\u0916\u093e\u0902\u0938\u0940": "cough",
    "\u0938\u0930\u094d\u0926\u0940": "cold",
    "\u0918\u092c\u0930\u093e\u0939\u091f": "anxious",
}


def sanitize_user_input(text):
    """Sanitize user input to prevent prompt injection and limit length."""
    if not text:
        return ""
    # Strip control characters except newlines and carriage returns
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Limit length
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH]
    return text.strip()


def normalize_user_text(text):
    normalized = (text or "").lower()
    for src, dest in LOCAL_TEXT_NORMALIZATION.items():
        normalized = normalized.replace(src, dest)
    return normalized


def parse_json_from_text(text):
    if not text:
        return None
    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    block = re.search(r"\{[\s\S]*\}", text)
    if not block:
        return None

    try:
        return json.loads(block.group(0))
    except Exception:
        return None


def detect_severity(text):
    msg = normalize_user_text(text).lower()
    for level, words in SEVERITY_WORDS.items():
        if any(w in msg for w in words):
            return level
    return "moderate"


def detect_age(text):
    match = re.search(r"\b(1[0-1][0-9]|120|[1-9]?[0-9])\b", text or "")
    if not match:
        return None
    age = int(match.group(1))
    return age if 1 <= age <= 120 else None


def is_emergency(text):
    msg = normalize_user_text(text).lower()
    return any(k in msg for k in EMERGENCY_KEYWORDS)


def get_user_language_hint(user_text):
    text = user_text or ""
    if re.search(r"[\u0900-\u097F]", text):
        return "Hindi"
    if any(token in text.lower() for token in ["hai", "mera", "mujhe", "kr", "kya", "nhi"]):
        return "Hinglish"
    return "English"

"""AAYU guided consultation and Prakriti analysis flows."""

import logging

from utils import detect_age, detect_severity, PRAKRITI_DEFAULT_QUESTIONS
from database import (
    find_best_symptom,
    get_ai_detailed_recommendation,
    analyze_prakriti,
    load_structured_db,
)

logger = logging.getLogger("aayu.flows")


def handle_guided_consultation(state, incoming_msg):
    """Process one step of the guided consultation flow.

    Args:
        state: The user's state dict (must contain 'consultation' key if active).
        incoming_msg: The user's message text.

    Returns:
        Response text, or None if no active consultation.
    """
    flow = state.get("consultation")
    if not flow:
        return None

    step = flow.get("step", "age")
    text = incoming_msg.strip()

    if step == "age":
        age = detect_age(text)
        if not age:
            return "Please tell your age in number. Example: 23"
        flow["age"] = age
        flow["step"] = "symptom"
        return "What is your main symptom? You can reply naturally."

    if step == "symptom":
        symptom = find_best_symptom(text) or text.lower()
        flow["symptom"] = symptom
        flow["step"] = "severity"
        return "How severe is it: mild, moderate, or severe?"

    if step == "severity":
        flow["severity"] = detect_severity(text)
        flow["step"] = "duration"
        return "How long have you had this issue? Example: 2 days"

    if step == "duration":
        flow["duration"] = text
        flow["step"] = "reason"
        return "Any possible trigger or reason you noticed?"

    if step == "reason":
        flow["pain_reason"] = text
        flow["step"] = "activities"
        return "Any recent activity that may be linked?"

    if step == "activities":
        flow["activities"] = text
        result = get_ai_detailed_recommendation(
            flow.get("symptom", "unknown"),
            flow.get("age", "unknown"),
            flow.get("severity", "moderate"),
            flow.get("duration", "not provided"),
            flow.get("pain_reason", "not provided"),
            flow.get("activities", "not provided"),
        )
        state.pop("consultation", None)
        return result

    return None


def handle_prakriti_flow(state, incoming_msg):
    """Process one step of the Prakriti analyzer flow.

    Args:
        state: The user's state dict (must contain 'prakriti' key if active).
        incoming_msg: The user's message text.

    Returns:
        Response text, or None if no active Prakriti flow.
    """
    flow = state.get("prakriti")
    if not flow:
        return None

    flow["answers"].append(incoming_msg.strip())
    flow["index"] += 1
    questions = flow["questions"]

    if flow["index"] < len(questions):
        return questions[flow["index"]]

    result = analyze_prakriti(flow["answers"])
    state.pop("prakriti", None)
    return f"Prakriti analysis:\n\n{result}"


def start_consultation(state):
    """Initialize a new guided consultation in user state."""
    state["consultation"] = {"step": "age"}
    return "Guided consultation started. Please tell your age."


def start_prakriti(state):
    """Initialize a new Prakriti analysis flow in user state."""
    questions = list(PRAKRITI_DEFAULT_QUESTIONS)
    try:
        raw_q = load_structured_db().get("prakriti_questions", [])
        q = []
        for x in raw_q:
            if isinstance(x, dict) and "q" in x:
                q.append(x["q"])
            elif isinstance(x, str):
                q.append(x)
        if q:
            questions = q
    except Exception:
        pass

    state["prakriti"] = {"index": 0, "answers": [], "questions": questions}
    return f"Prakriti analyzer started.\n\n{questions[0]}"

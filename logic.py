# logic.py

def calculate_dosage(age, base_dosage):
    """Age-based logic for dosage adjustment."""
    if age < 12:
        return f"{base_dosage} (Half Dose - Child Safety)"
    elif 12 <= age <= 50:
        return f"{base_dosage} (Standard Adult Dose)"
    else:
        return f"{base_dosage} (Mild Dose - Senior Care)"

def display_recommendation(symptom, age, severity, data):
    """
    MODIFIED: Integrated severity-based branching and reasoning.
    """
    info = data[symptom]
    
    # Improved Formatting with Separators
    print("\n" + "◈" * 50)
    print(f" RECOMMENDATION FOR: {symptom.upper()}")
    print(f" SEVERITY LEVEL    : {severity.upper()}")
    print("◈" * 50)

    # NEW: Severity Logic implementation
    if severity == "severe":
        print("🛑 [CRITICAL WARNING]")
        print("Your symptoms indicate a severe condition.")
        print("ACTION: Do not self-medicate. Please visit a Doctor or Vaidya immediately.")
    
    elif severity == "mild":
        print("🏡 [HOME REMEDY RECOMMENDATION]")
        print(f"Since the symptoms are mild, try: {info['home_remedy']}")
        print(f"Advice: {info['lifestyle_tips']}")
    
    else: # Moderate case
        dosage = calculate_dosage(age, info['base_dosage'])
        print(f"🌿 Medicine : {info['medicine']}")
        print(f"💡 Reason   : {info['reason']}") # NEW: Reason included
        print(f"⚖️ Dosage   : {dosage}")
        print(f"📝 Tips     : {info['lifestyle_tips']}")
        print(f"🚫 Avoid    : {info['avoid']}")
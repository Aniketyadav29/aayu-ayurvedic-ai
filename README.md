# Ayurvedic Recommendation System

A Python CLI tool that gives Ayurvedic recommendations from a local knowledge base and falls back to Gemini for unknown symptoms.

## Setup

1. Create and activate a virtual environment (recommended):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Set the Gemini API key as an environment variable:

```powershell
$env:GEMINI_API_KEY="YOUR_API_KEY_HERE"
```

4. (Recommended for production) enforce Twilio signature validation:

```powershell
$env:ENFORCE_TWILIO_SIGNATURE="true"
```

This requires `TWILIO_AUTH_TOKEN` to be set correctly in your environment.

## Run

```powershell
python "main (1).py"
```

## WhatsApp Bot Run

```powershell
python app.py
```

Health check:

```text
GET /health
```

Example local URL:

```text
http://127.0.0.1:5000/health
```

## Notes

- If symptom exists in local database, recommendation is shown from local data.
- If symptom is not found, app asks Gemini for a formatted recommendation.
- If API key is not set or API is unavailable, the app shows a clear fallback message.

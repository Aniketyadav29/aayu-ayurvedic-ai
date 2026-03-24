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
python app.py
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

## New WhatsApp Features

- Visual menu image:
	- Send `menu image` to receive a visual menu card.
	- Users can reply with numbers like `1` (start consultation) or `4` (daily routine planner).
	- To use your own poster image, place it in `static/` with one of these names:
		- `menu_custom.png`
		- `menu_custom.jpg`
		- `menu_custom.jpeg`
		- `menu_custom.webp`
	- If file name is different, bot automatically uses the latest image found in `static/`.
- Daily routine planner:
	- Send `daily routine for age 28 with acidity` (or similar text).
	- Bot returns a time-wise routine with morning habits, meals, and exercise.
- Menu-wise database classification:
	- Send `classify database`.
	- Bot returns database mapping for each menu section with current data coverage and gaps.

## Optional Environment Variable

- `PUBLIC_BASE_URL`:
	- Set this in production so media URLs (menu image) resolve correctly.
	- Example: `https://your-app.onrender.com`

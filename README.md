# AAYU Ayurvedic WhatsApp Bot

A Flask + Twilio WhatsApp bot that gives Ayurvedic recommendations from a local knowledge base and falls back to Gemini for unknown symptoms.

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

3. Set environment variables:

```powershell
$env:GEMINI_API_KEY="YOUR_API_KEY_HERE"
$env:TWILIO_ACCOUNT_SID="YOUR_TWILIO_SID"
$env:TWILIO_AUTH_TOKEN="YOUR_TWILIO_AUTH_TOKEN"
```

4. (Recommended for production) enforce Twilio signature validation:

```powershell
$env:ENFORCE_TWILIO_SIGNATURE="true"
```

This requires `TWILIO_AUTH_TOKEN` to be set correctly in your environment.

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
http://127.0.0.1:8080/health
```

## Input Styles Supported

You can send messages in any of these styles:

1. Structured:
```text
23, fever, mild
```

2. Single symptom:
```text
fever
```

3. Natural paragraph:
```text
I am 23 years old and I have severe headache with slight cold since yesterday.
```

The bot extracts age, symptom, and severity from natural text and responds accordingly.

## Keepalive (24x7)

### GitHub Actions Keepalive (every 5 minutes)

File already added:
```text
.github/workflows/keep.yml
```

Set repository secret in GitHub:

1. Open repository `Settings` -> `Secrets and variables` -> `Actions`
2. Add secret name: `RENDER_HEALTH_URL`
3. Add value: `https://aayu-ayurvedic-ai-1.onrender.com/health`

Then push changes to `main`. The workflow will ping the app every 5 minutes.

### 2-minute ping requirement

GitHub Actions does not support every-2-minute cron. For exactly every 2 minutes, use an external cron service (for example cron-job.org) with:

```text
GET https://aayu-ayurvedic-ai-1.onrender.com/health
Interval: 2 minutes
```

## Notes

- If symptom exists in local database, recommendation is shown from local data.
- If symptom is not found, app asks Gemini for a formatted recommendation.
- If API key is not set or API is unavailable, the app shows a clear fallback message.

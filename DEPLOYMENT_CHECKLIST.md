# 🚀 AAYU Ayurvedic AI - Render + Twilio Deployment Checklist

## Phase 1: Pre-Deployment Setup ✅

### 1.1 Prepare Your Project Files

- [ ] **Knowledge Database**
  - [ ] Create `knowledge.json` with Ayurvedic remedies (format below)
  - [ ] Place it in the project root directory
  ```json
  {
    "fever": {
      "medicine": "Paracetamol",
      "home_remedy": "Tulsi leaves tea",
      "avoid": "Cold water",
      "lifestyle_tips": "Rest and hydrate"
    }
  }
  ```

- [ ] **Environment Setup**
  - [ ] Create `.env` file locally (do NOT commit to Git):
    ```
    GEMINI_API_KEY=your_gemini_api_key_here
    TWILIO_ACCOUNT_SID=your_twilio_account_sid
    TWILIO_AUTH_TOKEN=your_twilio_auth_token
    ```

### 1.2 Verify Project Structure

- [ ] Confirm all files exist:
  - [ ] `app.py` (main Flask app)
  - [ ] `database.py` (Gemini AI + knowledge.json logic)
  - [ ] `logic.py` (utility functions)
  - [ ] `requirements.txt` (dependencies)
  - [ ] `README.md` (documentation)
  - [ ] `.env` (NOT in version control)
  - [ ] `knowledge.json` (Ayurvedic data)

### 1.3 Create Missing Files

- [ ] **Create `Procfile`** (tells Render how to run the app)
  ```
  web: gunicorn app:app
  ```

- [ ] **Create `.gitignore`** (protect sensitive files)
  ```
  .env
  __pycache__/
  *.pyc
  .DS_Store
  venv/
  .vscode/
  knowledge.json
  ```

### 1.4 Update Requirements

- [ ] Verify `requirements.txt` has all dependencies:
  ```
  Flask==2.3.0
  google-genai==0.3.0
  python-dotenv==1.0.0
  twilio==8.10.0
  gunicorn==21.2.0
  ```

---

## Phase 2: Twilio Setup ✅

### 2.1 Create/Access Twilio Account

- [ ] Go to [twilio.com](https://www.twilio.com)
- [ ] Sign up (Free trial with $15 credit) or login
- [ ] Verify phone number
- [ ] Get **Account SID** (from dashboard)
- [ ] Get **Auth Token** (from dashboard - keep secret!)

### 2.2 Get WhatsApp Number

- [ ] Navigate to **Messaging > Try it out > Send a WhatsApp message**
- [ ] Accept Twilio's sandbox WhatsApp number (e.g., +1 415 523 8886)
- [ ] Save this number - you'll need it for testing
- [ ] Get your **Twilio WhatsApp Number** (if you have production sandbox)

### 2.3 Configure Webhook URL (AFTER Render deployment - come back to this)

- [ ] In Twilio Console → **Messaging > Settings > WhatsApp Sandbox**
- [ ] Find **When a message comes in** field
- [ ] Set it to: `https://your-render-app.onrender.com/whatsapp` (POST)
- [ ] Save changes

### 2.4 Test Twilio Number (Optional)

- [ ] Save Twilio WhatsApp number to your phone
- [ ] Send "join [code]" message to activate sandbox (code shown in Twilio console)
- [ ] Send test message: `hi`

---

## Phase 3: Google Gemini API Setup ✅

### 3.1 Get Gemini API Key

- [ ] Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
- [ ] Click **"Create API Key"**
- [ ] Copy API key
- [ ] Add to your `.env` file:
  ```
  GEMINI_API_KEY=your_key_here
  ```

### 3.2 Enable Billing (Optional but Recommended)

- [ ] Visit [Google Cloud Console](https://console.cloud.google.com)
- [ ] Verify free tier limits for Gemini API
- [ ] Consider enabling billing for higher rate limits (optional)

---

## Phase 4: Git Repository Setup ✅

### 4.1 Initialize Git Repository

- [ ] Open terminal in project folder
- [ ] Run: `git init`
- [ ] Run: `git add .`
  - [ ] Ensure `.env` is NOT added (check `.gitignore`)
- [ ] Run: `git commit -m "Initial AAYU Ayurvedic AI setup"`

### 4.2 Push to GitHub/GitLab (Required for Render)

- [ ] Create repo on [GitHub](https://github.com/new)
- [ ] Copy repo URL
- [ ] In terminal:
  ```bash
  git remote add origin https://github.com/YOUR_USERNAME/REPO_NAME.git
  git branch -M main
  git push -u origin main
  ```

---

## Phase 5: Render Deployment ✅

### 5.1 Create Render Account

- [ ] Go to [render.com](https://render.com)
- [ ] Sign up with GitHub account
- [ ] Authorize Render to access your repositories

### 5.2 Deploy New Web Service

- [ ] Click **"New +"** → **"Web Service"**
- [ ] Select your GitHub repository
- [ ] Configure:
  - [ ] **Name**: `aayu-ayurvedic-ai` (or your choice)
  - [ ] **Environment**: `Python 3`
  - [ ] **Build Command**: `pip install -r requirements.txt`
  - [ ] **Start Command**: `gunicorn app:app`
  - [ ] **Instance Type**: Free (or paid for higher reliability)

### 5.3 Add Environment Variables (Critical!)

- [ ] Click **"Environment"** tab
- [ ] Add each variable:
  ```
  GEMINI_API_KEY=your_actual_api_key
  TWILIO_ACCOUNT_SID=your_account_sid
  TWILIO_AUTH_TOKEN=your_auth_token
  PORT=8080
  ```
- [ ] **Do NOT use `.env` file on Render - use their UI**

### 5.4 Deploy

- [ ] Click **"Create Web Service"**
- [ ] Wait for deployment (2-3 minutes)
- [ ] Check logs for errors
- [ ] Copy the **Render URL** (e.g., `https://aayu-ayurvedic-ai.onrender.com`)

### 5.5 Verify Deployment

- [ ] Open `https://your-render-url.onrender.com` in browser
- [ ] Should see "🌿 AAYU Ayurvedic AI is LIVE" message
- [ ] **Copy this URL - you need it for Twilio webhook**

---

## Phase 6: Connect Twilio to Render ✅

### 6.1 Update Twilio Webhook

- [ ] Go to **Twilio Console > Messaging > Settings > WhatsApp Sandbox**
- [ ] Paste your Render URL in **"When a message comes in"** field:
  ```
  https://your-render-url.onrender.com/whatsapp
  ```
- [ ] Make sure it's **POST** method
- [ ] Click **"Save"**

### 6.2 Add Your Phone Number to Sandbox

- [ ] In same Twilio WhatsApp Sandbox settings
- [ ] Find **"Learn how to send"** section
- [ ] Follow the "join" code instructions
- [ ] Send message: `join [TWILIO-CODE]` to activate

---

## Phase 7: Testing & Verification ✅

### 7.1 Basic Connectivity Test

- [ ] Send **"hi"** to Twilio WhatsApp number
- [ ] Should receive welcome message
- [ ] Check Render logs for incoming request

### 7.2 Full Workflow Test

- [ ] Send: `23, fever, mild`
- [ ] Should receive:
  - [ ] Local database response (if `knowledge.json` has "fever"), OR
  - [ ] AI-generated response from Gemini

### 7.3 Error Handling Test

- [ ] Send malformed message: `23 fever mild` (no commas)
- [ ] Should get format error message
- [ ] Check Render logs for errors

### 7.4 Monitor Logs

- [ ] Open Render dashboard
- [ ] Click your service
- [ ] Monitor **"Logs"** tab in real-time
- [ ] Look for:
  - [ ] ✅ "NEW MESSAGE RECEIVED"
  - [ ] ✅ "Response sent successfully!"
  - [ ] ❌ Any ERROR messages

---

## Phase 8: Production Optimization ✅

### 8.1 Prevent Cold Starts

- [ ] Upgrade from Free to **Paid** plan ($7/month)
- [ ] Free tier spins down after 15 min inactivity (bot goes offline)
- [ ] Paid tier: Always on = 24/7 availability

### 8.2 Add Uptime Monitoring

- [ ] Use [Healthchecks.io](https://healthchecks.io) (free)
- [ ] Or [UptimeRobot](https://uptimerobot.com) (free)
- [ ] Ping your Render URL every 5 minutes to keep it alive

### 8.3 Add Logging & Debugging

- [ ] Consider integrating [Sentry.io](https://sentry.io) for error tracking
- [ ] Enable detailed logging in `app.py`

### 8.4 Secure Twilio Integration

- [ ] Never expose API keys in code
- [ ] Use Render's environment variables (already done)
- [ ] Rotate tokens periodically
- [ ] Set up IP whitelisting (if needed)

---

## Phase 9: Upgrade to Production (Optional) ✅

### 9.1 Move from Sandbox to Production

- [ ] In Twilio Console: **Messaging > Send a Message > WhatsApp**
- [ ] Click **"Get a production number"**
- [ ] Follow setup wizard (may require verification)
- [ ] Update webhook URL to same Render endpoint
- [ ] Update Twilio credentials in Render environment

### 9.2 Scale Infrastructure

- [ ] Monitor Render usage
- [ ] If heavily used, upgrade instance type
- [ ] Consider using PostgreSQL for data storage (free tier available)

---

## 🎯 Quick Command Reference

```bash
# Local testing
python app.py

# Git operations
git add .
git commit -m "message"
git push

# Check requirements
pip freeze > requirements.txt

# Generate Procfile
echo "web: gunicorn app:app" > Procfile
```

---

## 📞 Support Resources

- **Twilio**: https://www.twilio.com/docs
- **Render**: https://render.com/docs
- **Flask**: https://flask.palletsprojects.com
- **Google Gemini**: https://github.com/google-gemini/python-client-prep

---

## ✅ Final Checklist Summary

- [ ] Project files ready (app.py, database.py, logic.py, requirements.txt, Procfile)
- [ ] Twilio account set up (Account SID, Auth Token, WhatsApp Sandbox)
- [ ] Google Gemini API key obtained
- [ ] `.env` file created locally (NOT committed)
- [ ] Git repository created and pushed to GitHub
- [ ] Render account created and connected to GitHub
- [ ] Render service deployed successfully
- [ ] Render URL obtained and tested (loads successfully)
- [ ] Twilio webhook connected to Render URL
- [ ] Paid/Upgraded plan selected for 24/7 uptime (optional but recommended)
- [ ] Test message sent and received successfully
- [ ] Monitor logs and fix any errors

🎉 **Once all checkboxes are done, your bot will be LIVE 24/7!**

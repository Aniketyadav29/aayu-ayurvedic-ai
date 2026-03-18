# 🚀 AAYU Ayurvedic AI - Quick Start Deployment Guide

## ⚡ Step-by-Step Execution

### **Step 1: Prepare Your Local Environment (5 min)**

```bash
# Navigate to your project
cd c:\Users\Dell\Desktop\Ayurveda

# Create .env file with your credentials
# Windows PowerShell:
@'
GEMINI_API_KEY=paste_your_gemini_key_here
TWILIO_ACCOUNT_SID=paste_your_account_sid_here
TWILIO_AUTH_TOKEN=paste_your_auth_token_here
'@ | Out-File .env -Encoding UTF8

# Test locally
python app.py
# Visit: http://localhost:8080 in browser
```

---

### **Step 2: Create Twilio WhatsApp Sandbox (10 min)**

1. Go to https://www.twilio.com/console
2. Navigate: **Messaging → Try it out → Send a Message**
3. Click **WhatsApp tab**
4. Copy your **Account SID** (Dashboard top-right)
5. Copy your **Auth Token** (Dashboard top-right)
6. Note the **Twilio Sandbox WhatsApp Number** (e.g., +1 415 523 8886)
7. Save: Join code shown in "Learn how to send" section

---

### **Step 3: Get Google Gemini API Key (2 min)**

1. Go to https://aistudio.google.com/app/apikey
2. Click **"Create API Key"**
3. Copy the key
4. Paste in your `.env` file as `GEMINI_API_KEY`

---

### **Step 4: Push Code to GitHub (5 min)**

```bash
# Initialize git (if not already done)
git init
git add .
git commit -m "AAYU Ayurvedic AI - Initial Deployment"

# Create new repo at https://github.com/new
# Then:
git remote add origin https://github.com/YOUR_USERNAME/aayu-ayurvedic-ai.git
git branch -M main
git push -u origin main
```

---

### **Step 5: Deploy to Render (10 min)**

1. Go to https://render.com
2. Sign up with GitHub
3. Click **"+ New"** → **"Web Service"**
4. Select your repository
5. Configure:
   - **Name**: `aayu-ayurvedic-ai`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Instance Type**: Choose **"Paid - $7/month"** (Free tier spins down → bot goes offline)

6. Click **"Environment"** tab → Add variables:
   ```
   GEMINI_API_KEY = [your key]
   TWILIO_ACCOUNT_SID = [your SID]
   TWILIO_AUTH_TOKEN = [your token]
   ```

7. Click **"Create Web Service"** → Wait 2-3 minutes
8. **Copy your Render URL** when deployment completes (e.g., `https://aayu-ayurvedic-ai.onrender.com`)

---

### **Step 6: Connect Twilio to Render (5 min)**

1. Go to https://www.twilio.com/console
2. Navigate: **Messaging → Settings → WhatsApp Sandbox**
3. Find **"When a message comes in"** field
4. Paste: `https://aayu-ayurvedic-ai.onrender.com/whatsapp` (replace with your URL)
5. Method: **POST**
6. Click **"Save"**

---

### **Step 7: Test the Bot (2 min)**

1. Save Twilio WhatsApp sandbox number to your phone: **+1 415 523 8886**
2. Open WhatsApp → Send message: `join [CODE]` (code from Twilio console)
3. Send: `hi`
4. Should get welcome message ✅
5. Send: `23, fever, mild`
6. Should get AI recommendation ✅

---

### **Step 8: Monitor & Debug**

```bash
# Check Render logs (real-time)
# Open: https://dashboard.render.com → Your Service → Logs tab

# Common issues:
# ❌ "502 Bad Gateway" → Check Start Command in Render settings
# ❌ No response → Check Twilio webhook URL and method
# ❌ "ModuleNotFoundError" → Add package to requirements.txt
```

---

## 🎯 Key Points for 24/7 Availability

| Feature | Free Render | Paid Render |
|---------|-----------|-----------|
| Uptime | Spins down after 15 min inactivity | Always On ✅ |
| Cost | Free | $7/month |
| Performance | Slower cold starts | Instant response |
| Best for | Testing | Production |

**For 24/7 bot availability → Upgrade to Paid plan**

---

## 🆘 Troubleshooting

### Bot not receiving messages
- [ ] Verify Twilio webhook URL is correct (check HTTPS, not HTTP)
- [ ] Verify HTTP method is POST
- [ ] Check Render logs for incoming requests
- [ ] Make sure you've sent "join [code]" to Twilio WhatsApp number first

### Getting errors in logs
- [ ] Check if `GEMINI_API_KEY` is set correctly in Render environment
- [ ] Verify `knowledge.json` file exists in project root
- [ ] Check if all dependencies in `requirements.txt` are installed

### "502 Bad Gateway" error
- [ ] Verify Start Command is: `gunicorn app:app`
- [ ] Check if `app.py` has any syntax errors
- [ ] Restart the Render service

### Render service keeps restarting
- [ ] Check logs for Python errors
- [ ] Verify environment variables are set
- [ ] Ensure `Procfile` exists and is correct

---

## 📋 Final Verification Checklist

- [ ] Local `.env` file created with API keys
- [ ] `Procfile` created in project root
- [ ] Code pushed to GitHub
- [ ] Render service deployed successfully
- [ ] Render URL loads without errors
- [ ] Twilio webhook connected to Render URL
- [ ] Test message received successfully
- [ ] Paid plan activated (for 24/7)
- [ ] Environment variables set in Render
- [ ] Logs monitored and no errors

✅ **All done? Your bot is now LIVE 24/7!**

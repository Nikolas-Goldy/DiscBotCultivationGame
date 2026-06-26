# ⚡ Path of the Immortal 修仙之路

A full-stack Discord cultivation RPG with a website shop, Discord OAuth2 login, and BCA Virtual Account payments via Midtrans.

---

## 📁 Project Structure

```
path-of-the-immortal/
├── frontend/
│   └── index.html          # Website (hero, shop, Discord login)
├── backend/
│   ├── main.py             # FastAPI server (auth, payments, webhook)
│   ├── requirements.txt
│   ├── .env.example        # Copy to .env and fill in
│   └── .env                # ← your secrets (never commit this)
├── bot/
│   ├── bot.py              # Discord bot (all game commands)
│   └── requirements.txt
├── .gitignore
└── README.md
```

Open the root folder `path-of-the-immortal/` in VS Code to see everything.

---

## 🛠️ Setup Guide

### Step 1 — PostgreSQL Database (DBeaver)

1. Download DBeaver: https://dbeaver.io/download/
2. Get a free PostgreSQL database:
   - **Supabase** (recommended): https://supabase.com → New Project → copy the connection string
   - **Neon**: https://neon.tech → also free
3. Open DBeaver → New Connection → PostgreSQL → paste your connection string
4. The tables are created automatically when the backend starts

---

### Step 2 — Discord Application

1. Go to https://discord.com/developers/applications
2. Click **New Application** → name it "Path of the Immortal"
3. Go to **Bot** tab → click **Reset Token** → copy it (this is `DISCORD_BOT_TOKEN`)
4. Enable these under **Privileged Gateway Intents**:
   - ✅ Server Members Intent
   - ✅ Message Content Intent
5. Go to **OAuth2** tab → copy **Client ID** and **Client Secret**
6. Under **Redirects**, add:
   - `http://localhost:8000/auth/callback` (for development)
   - `https://yourdomain.com/auth/callback` (for production)
7. Invite the bot to your server:
   - OAuth2 → URL Generator → Scopes: `bot`, `applications.commands`
   - Permissions: `Send Messages`, `Embed Links`, `Read Message History`
   - Copy and open the generated URL

---

### Step 3 — Midtrans

1. Register at https://dashboard.midtrans.com
2. Go to **Settings → Access Keys**
3. Copy **Server Key** and **Client Key** (use Sandbox keys while testing)
4. Go to **Settings → Payment → Notification URL** and add:
   - `https://yourdomain.com/webhook/midtrans`
   - (For local testing use ngrok — see below)

---

### Step 4 — Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Open .env and fill in all values

# Run the backend
uvicorn main:app --reload --port 8000
```

Backend runs at: http://localhost:8000

---

### Step 5 — Frontend Setup

1. Open `frontend/index.html` in VS Code
2. Install the **Live Server** extension in VS Code
3. Right-click `index.html` → **Open with Live Server**
4. It opens at http://127.0.0.1:5500

> Make sure `FRONTEND_URL=http://127.0.0.1:5500` in your `.env`

Two things to update in `index.html`:
- Line with `YOUR_MIDTRANS_CLIENT_KEY` → replace with your actual Midtrans client key
- Line with `YOUR_DISCORD_INVITE_LINK` → replace with your Discord server invite
- Line with `const BACKEND = 'http://localhost:8000'` → replace with your deployed backend URL when going live

---

### Step 6 — Bot Setup

```bash
cd bot

# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

pip install -r requirements.txt

# Make sure .env is filled in (bot reads from backend/.env or its own copy)
python bot.py
```

---

### Step 7 — Local Webhook Testing (ngrok)

Midtrans needs a public URL to send payment notifications. During development, use ngrok:

```bash
# Install: https://ngrok.com/download
ngrok http 8000
```

Copy the `https://xxxx.ngrok.io` URL and set it in Midtrans dashboard as the notification URL:
`https://xxxx.ngrok.io/webhook/midtrans`

---

## 💰 Economy

| Currency | How to Get | Used For |
|----------|-----------|----------|
| 🌀 Qi | `/cultivate`, `/mission` | Realm breakthroughs |
| 🪙 Spirit Stones | `/mission`, `/duel` wins | Shop items |
| 💎 Jade Coins | Purchase on website (BCA transfer) | Convert to Stones (1:100) |

### Jade Coin Packages

| Package | Coins | Price |
|---------|-------|-------|
| Disciple Satchel | 100 | Rp 30.000 |
| Elder's Pouch | 550 | Rp 120.000 |
| Sect Master Vault | 1,400 | Rp 220.000 |
| Immortal Hoard | 3,800 | Rp 450.000 |

---

## 🎮 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Register as a cultivator |
| `/status` | View your full profile |
| `/cultivate` | Gather Qi (1 hour cooldown) |
| `/breakthrough` | Attempt realm advancement |
| `/duel @user` | PvP battle |
| `/shop` | Browse items |
| `/buy <item>` | Buy with Spirit Stones |
| `/inventory` | View your items |
| `/mission` | Daily quest |
| `/leaderboard` | Heaven's Rankings |
| `/sect create/join/info/leave` | Sect management |
| `/convert <amount>` | Jade Coins → Spirit Stones |
| `/buyjade` | Get website purchase link |
| `/admin_give` | (Owner) Give currency |

---

## 🚀 Deployment (Going Live)

| Service | What it hosts | Cost |
|---------|--------------|------|
| **Railway** | Backend (FastAPI) + Bot | Free tier |
| **Netlify / GitHub Pages** | Frontend (HTML) | Free |
| **Supabase / Neon** | PostgreSQL | Free tier |

1. Deploy backend to Railway → copy the URL → update `BACKEND_URL` and Discord redirect URI
2. Deploy frontend to Netlify → copy URL → update `FRONTEND_URL` in backend `.env`
3. Switch Midtrans to **Production** keys and set `MIDTRANS_IS_PROD=true`
4. Update Midtrans webhook URL to your live backend URL

---

## 🔒 Security Notes

- Never commit `.env` to GitHub (it's in `.gitignore`)
- Rotate your `JWT_SECRET` before going to production
- Always verify Midtrans webhook signatures (already handled in `main.py`)
- Use HTTPS for everything in production

"""
PATH OF THE IMMORTAL — Backend API (Finalized)
================================================
Stack : FastAPI + asyncpg (PostgreSQL) + Midtrans + Discord OAuth2
Run   : uvicorn main:app --reload --port 8000
"""

import os, time, hmac, hashlib, secrets
from datetime import datetime, timedelta
from dotenv import load_dotenv

import httpx
import asyncpg
import midtransclient
from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt, JWTError

load_dotenv()

# ── CONFIG ──────────────────────────────────────────────────
DATABASE_URL          = os.getenv("DATABASE_URL")
DISCORD_CLIENT_ID     = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI  = os.getenv("DISCORD_REDIRECT_URI")
MIDTRANS_SERVER_KEY   = os.getenv("MIDTRANS_SERVER_KEY")
MIDTRANS_CLIENT_KEY   = os.getenv("MIDTRANS_CLIENT_KEY")
MIDTRANS_IS_PROD      = os.getenv("MIDTRANS_IS_PROD", "false").lower() == "true"
JWT_SECRET            = os.getenv("JWT_SECRET", secrets.token_hex(32))
FRONTEND_URL          = os.getenv("FRONTEND_URL", "https://path-of-the-immortal.vercel.app/#shop")
DISCORD_API           = "https://discord.com/api/v10"

PACKAGES = {
    "disciple": {"name": "Disciple Satchel",  "jade": 100,  "price_idr": 30_000},
    "elder":    {"name": "Elder's Pouch",      "jade": 550,  "price_idr": 120_000},
    "sect":     {"name": "Sect Master Vault",  "jade": 1400, "price_idr": 220_000},
    "immortal": {"name": "Immortal Hoard",     "jade": 3800, "price_idr": 450_000},
}

# ── APP ─────────────────────────────────────────────────────
app = FastAPI(title="Path of the Immortal API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

snap = midtransclient.Snap(
    is_production=MIDTRANS_IS_PROD,
    server_key=MIDTRANS_SERVER_KEY,
)

# ── DATABASE ────────────────────────────────────────────────
pool: asyncpg.Pool = None

@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    await create_tables()
    print("✅ Database connected")

@app.on_event("shutdown")
async def shutdown():
    await pool.close()

async def create_tables():
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                discord_id      TEXT PRIMARY KEY,
                username        TEXT NOT NULL,
                avatar          TEXT,
                email           TEXT DEFAULT '',
                realm           INTEGER DEFAULT 1,
                qi              BIGINT DEFAULT 0,
                spirit_stones   BIGINT DEFAULT 0,
                jade_coins      BIGINT DEFAULT 0,
                last_cultivate  BIGINT DEFAULT 0,
                last_mission    BIGINT DEFAULT 0,
                sect_id         INTEGER DEFAULT NULL,
                wins            INTEGER DEFAULT 0,
                losses          INTEGER DEFAULT 0,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id          SERIAL PRIMARY KEY,
                discord_id  TEXT REFERENCES users(discord_id) ON DELETE CASCADE,
                item        TEXT NOT NULL,
                quantity    INTEGER DEFAULT 1,
                UNIQUE(discord_id, item)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sects (
                id          SERIAL PRIMARY KEY,
                name        TEXT UNIQUE NOT NULL,
                leader_id   TEXT REFERENCES users(discord_id),
                description TEXT DEFAULT '',
                funds       BIGINT DEFAULT 0,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id           TEXT PRIMARY KEY,
                discord_id   TEXT REFERENCES users(discord_id),
                package_id   TEXT NOT NULL,
                jade_coins   INTEGER NOT NULL,
                amount_idr   BIGINT NOT NULL,
                status       TEXT DEFAULT 'pending',
                va_number    TEXT,
                payment_type TEXT,
                paid_at      TIMESTAMPTZ,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)

# ── AUTH HELPERS ────────────────────────────────────────────
def make_token(discord_id: str, username: str) -> str:
    return jwt.encode(
        {"sub": discord_id, "username": username,
         "exp": datetime.utcnow() + timedelta(days=7)},
        JWT_SECRET, algorithm="HS256"
    )

async def current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(authorization.split(" ")[1], JWT_SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE discord_id=$1", payload["sub"])
    if not user:
        raise HTTPException(404, "User not found")
    return dict(user)

# ── AUTH ROUTES ─────────────────────────────────────────────
@app.get("/auth/login")
async def discord_login():
    url = (
        "https://discord.com/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify%20email"
    )
    return RedirectResponse(url)

@app.get("/auth/callback")
async def discord_callback(code: str):
    async with httpx.AsyncClient() as client:
        # Exchange code → access token
        tr = await client.post(f"{DISCORD_API}/oauth2/token", data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        td = tr.json()
        if "access_token" not in td:
            raise HTTPException(400, "Discord OAuth failed")

        # Fetch user
        ur = await client.get(f"{DISCORD_API}/users/@me",
                               headers={"Authorization": f"Bearer {td['access_token']}"})
        du = ur.json()

    did      = du["id"]
    username = du.get("username", "Unknown")
    discrim  = du.get("discriminator", "0")
    fullname = f"{username}#{discrim}" if discrim != "0" else username
    avatar   = du.get("avatar")
    av_url   = f"https://cdn.discordapp.com/avatars/{did}/{avatar}.png" if avatar else None
    email    = du.get("email", "")

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (discord_id, username, avatar, email)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (discord_id) DO UPDATE
              SET username=$2, avatar=$3, email=$4
        """, did, fullname, av_url, email)

    token = make_token(did, fullname)
    return RedirectResponse(f"{FRONTEND_URL}?token={token}#shop")

@app.get("/auth/me")
async def get_me(user=Depends(current_user)):
    REALMS = ["","Qi Condensation","Foundation Building","Core Formation",
              "Nascent Soul","Spirit Severing","Dao Seeking","True Immortal"]
    return {
        "discord_id":    user["discord_id"],
        "username":      user["username"],
        "avatar":        user["avatar"],
        "realm":         user["realm"],
        "realm_name":    REALMS[user["realm"]],
        "spirit_stones": user["spirit_stones"],
        "jade_coins":    user["jade_coins"],
        "wins":          user["wins"],
        "losses":        user["losses"],
    }

# ── SHOP ─────────────────────────────────────────────────────
@app.get("/shop/packages")
async def list_packages():
    return PACKAGES

@app.post("/shop/checkout/{package_id}")
async def create_checkout(package_id: str, user=Depends(current_user)):
    pkg = PACKAGES.get(package_id)
    if not pkg:
        raise HTTPException(404, "Package not found")

    order_id = f"POTI-{user['discord_id']}-{package_id}-{int(time.time())}"

    try:
        tx = snap.create_transaction({
            "transaction_details": {
                "order_id": order_id,
                "gross_amount": pkg["price_idr"],
            },
            "item_details": [{
                "id": package_id,
                "price": pkg["price_idr"],
                "quantity": 1,
                "name": f"{pkg['name']} — {pkg['jade']} Jade Coins",
            }],
            "customer_details": {
                "first_name": user["username"],
                "email": user.get("email") or "player@pathoftheimmortal.com",
            },
            "enabled_payments": ["bca_va"],
            "bank_transfer": {"bank": "bca"},
        })
    except Exception as e:
        raise HTTPException(500, f"Midtrans error: {e}")

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO transactions (id, discord_id, package_id, jade_coins, amount_idr)
            VALUES ($1, $2, $3, $4, $5)
        """, order_id, user["discord_id"], package_id, pkg["jade"], pkg["price_idr"])

    return {
        "order_id":     order_id,
        "snap_token":   tx["token"],
        "redirect_url": tx["redirect_url"],
        "package":      pkg,
    }

@app.get("/shop/history")
async def purchase_history(user=Depends(current_user)):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, package_id, jade_coins, amount_idr, status, paid_at, created_at
            FROM transactions
            WHERE discord_id=$1
            ORDER BY created_at DESC LIMIT 20
        """, user["discord_id"])
    return [dict(r) for r in rows]

# ── MIDTRANS WEBHOOK ─────────────────────────────────────────
@app.post("/webhook/midtrans")
async def midtrans_webhook(request: Request):
    body = await request.json()

    order_id   = body.get("order_id", "")
    status     = body.get("status_code", "")
    gross      = body.get("gross_amount", "")
    tx_status  = body.get("transaction_status", "")
    fraud      = body.get("fraud_status", "")
    sig        = body.get("signature_key", "")
    va_numbers = body.get("va_numbers", [])
    pay_type   = body.get("payment_type", "")

    # Verify signature
    expected = hashlib.sha512(
        f"{order_id}{status}{gross}{MIDTRANS_SERVER_KEY}".encode()
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(403, "Invalid signature")

    paid = (tx_status == "settlement") or (tx_status == "capture" and fraud == "accept")

    if paid:
        async with pool.acquire() as conn:
            tx = await conn.fetchrow(
                "SELECT * FROM transactions WHERE id=$1", order_id
            )
            if not tx or tx["status"] == "paid":
                return {"status": "already_processed"}

            va = va_numbers[0]["va_number"] if va_numbers else None
            await conn.execute("""
                UPDATE transactions
                SET status='paid', va_number=$2, payment_type=$3, paid_at=NOW()
                WHERE id=$1
            """, order_id, va, pay_type)

            await conn.execute("""
                UPDATE users SET jade_coins = jade_coins + $2
                WHERE discord_id = $1
            """, tx["discord_id"], tx["jade_coins"])

        return {"status": "success", "jade_credited": tx["jade_coins"]}

    if tx_status in ("cancel", "deny", "expire"):
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE transactions SET status=$2 WHERE id=$1", order_id, tx_status
            )

    return {"status": "received"}

# ── LEADERBOARD ──────────────────────────────────────────────
@app.get("/leaderboard")
async def leaderboard():
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT username, realm, qi, wins
            FROM users ORDER BY realm DESC, qi DESC LIMIT 10
        """)
    return [dict(r) for r in rows]

# ── HEALTH ───────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": int(time.time())}

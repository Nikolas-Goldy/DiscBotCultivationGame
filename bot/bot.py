"""
PATH OF THE IMMORTAL — Discord Bot (PostgreSQL version)
=========================================================
Now shares the PostgreSQL database with the FastAPI backend.
Players who buy Jade Coins on the website see them here instantly.

Requirements:
  pip install discord.py asyncpg python-dotenv

Run:
  python bot.py
"""

import os, time, random, asyncio
from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord import app_commands
import asyncpg

load_dotenv()

BOT_TOKEN  = os.getenv("DISCORD_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

CULTIVATE_COOLDOWN = 3600   # 1 hour
MISSION_COOLDOWN   = 86400  # 24 hours

# ─────────────────────────────────────────────
# REALM & GAME DATA
# ─────────────────────────────────────────────
REALMS = [
    {"id": 1, "name": "Qi Condensation",   "title": "Outer Disciple",  "qi_req": 0,      "item_req": None,               "qi_gain": (10, 30)},
    {"id": 2, "name": "Foundation Building","title": "Inner Disciple",  "qi_req": 500,    "item_req": "Qi Pill",          "qi_gain": (25, 60)},
    {"id": 3, "name": "Core Formation",    "title": "Elder Disciple",   "qi_req": 2000,   "item_req": "Core Stone",       "qi_gain": (50, 120)},
    {"id": 4, "name": "Nascent Soul",      "title": "Sect Guardian",    "qi_req": 8000,   "item_req": "Soul Jade",        "qi_gain": (100, 250)},
    {"id": 5, "name": "Spirit Severing",   "title": "Sect Elder",       "qi_req": 25000,  "item_req": "Heaven Shard",     "qi_gain": (200, 500)},
    {"id": 6, "name": "Dao Seeking",       "title": "Sect Master",      "qi_req": 80000,  "item_req": "Dao Scroll",       "qi_gain": (400, 1000)},
    {"id": 7, "name": "True Immortal",     "title": "Immortal",         "qi_req": 250000, "item_req": "Immortal Essence", "qi_gain": (800, 2000)},
]

SHOP_ITEMS = [
    {"name": "Qi Pill",          "desc": "Required for Foundation Building", "price": 200},
    {"name": "Core Stone",       "desc": "Required for Core Formation",      "price": 800},
    {"name": "Soul Jade",        "desc": "Required for Nascent Soul",        "price": 2500},
    {"name": "Heaven Shard",     "desc": "Required for Spirit Severing",     "price": 7000},
    {"name": "Dao Scroll",       "desc": "Required for Dao Seeking",         "price": 20000},
    {"name": "Immortal Essence", "desc": "Required for True Immortal",       "price": 60000},
    {"name": "Healing Pill",     "desc": "Restores HP after duel loss",      "price": 150},
    {"name": "Qi Surge Pill",    "desc": "Doubles next cultivation Qi gain", "price": 300},
    {"name": "Spirit Herb",      "desc": "Crafting ingredient",              "price": 50},
]

MISSIONS = [
    {"name": "Morning Meditation",     "reward_stones": 50,  "reward_qi": 20},
    {"name": "Patrol the Sect",        "reward_stones": 80,  "reward_qi": 0},
    {"name": "Gather Spirit Herbs",    "reward_stones": 60,  "reward_qi": 10},
    {"name": "Test the New Disciples", "reward_stones": 100, "reward_qi": 0},
    {"name": "Decipher Ancient Text",  "reward_stones": 120, "reward_qi": 30},
]

JADE_PACKAGES = {
    "disciple": {"name": "Disciple Satchel",  "jade": 100,  "price_idr": 30_000},
    "elder":    {"name": "Elder's Pouch",      "jade": 550,  "price_idr": 120_000},
    "sect":     {"name": "Sect Master Vault",  "jade": 1400, "price_idr": 220_000},
    "immortal": {"name": "Immortal Hoard",     "jade": 3800, "price_idr": 450_000},
}

# ─────────────────────────────────────────────
# BOT SETUP
# ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
pool: asyncpg.Pool = None

# ─────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────
async def get_user(discord_id: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE discord_id=$1", discord_id)

async def ensure_user(user: discord.User):
    """Create user row if they haven't logged in via website yet."""
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT discord_id FROM users WHERE discord_id=$1", str(user.id))
        if not existing:
            avatar_url = str(user.display_avatar.url) if user.display_avatar else None
            await conn.execute("""
                INSERT INTO users (discord_id, username, avatar)
                VALUES ($1, $2, $3)
                ON CONFLICT (discord_id) DO NOTHING
            """, str(user.id), str(user), avatar_url)
    return await get_user(str(user.id))

async def update_user(discord_id: str, **kwargs):
    sets = ", ".join(f"{k}=${i+2}" for i, k in enumerate(kwargs))
    vals = [discord_id] + list(kwargs.values())
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE users SET {sets} WHERE discord_id=$1", *vals)

async def get_inventory(discord_id: str) -> dict:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT item, quantity FROM inventory WHERE discord_id=$1", discord_id
        )
    return {r["item"]: r["quantity"] for r in rows}

async def add_item(discord_id: str, item: str, qty: int = 1):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO inventory (discord_id, item, quantity)
            VALUES ($1, $2, $3)
            ON CONFLICT (discord_id, item)
            DO UPDATE SET quantity = inventory.quantity + $3
        """, discord_id, item, qty)

async def remove_item(discord_id: str, item: str, qty: int = 1) -> bool:
    inv = await get_inventory(discord_id)
    if inv.get(item, 0) < qty:
        return False
    async with pool.acquire() as conn:
        new_qty = inv[item] - qty
        if new_qty <= 0:
            await conn.execute(
                "DELETE FROM inventory WHERE discord_id=$1 AND item=$2", discord_id, item
            )
        else:
            await conn.execute(
                "UPDATE inventory SET quantity=$3 WHERE discord_id=$1 AND item=$2",
                discord_id, item, new_qty
            )
    return True

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def realm_data(realm_id: int) -> dict:
    return REALMS[max(0, min(realm_id - 1, 6))]

def fmt_time(seconds: int) -> str:
    if seconds <= 0: return "now"
    h, rem = divmod(seconds, 3600)
    m, s   = divmod(rem, 60)
    parts  = []
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s and not h: parts.append(f"{s}s")
    return " ".join(parts)

def power_score(c) -> int:
    return c["realm"] * 1000 + c["qi"] // 10

def jade_embed(title: str, desc: str, color: int = 0x1a7a5c) -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=color)
    e.set_footer(text="Path of the Immortal 修仙之路")
    return e

WEBSITE_URL = os.getenv("FRONTEND_URL", "https://yourdomain.com")

# ─────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────

@tree.command(name="start", description="Begin your cultivation journey")
async def cmd_start(interaction: discord.Interaction):
    c = await ensure_user(interaction.user)
    r = realm_data(c["realm"])
    e = jade_embed(
        "⚡ Welcome, Cultivator!",
        f"Your path to immortality begins.\n\n"
        f"**Realm:** {r['name']} · {r['title']}\n"
        f"**Qi:** {c['qi']:,}\n"
        f"**Spirit Stones:** 🪙 {c['spirit_stones']:,}\n"
        f"**Jade Coins:** 💎 {c['jade_coins']:,}\n\n"
        f"Use `/cultivate` to begin gathering Qi.\n"
        f"Buy Jade Coins at: {WEBSITE_URL}"
    )
    await interaction.response.send_message(embed=e)


@tree.command(name="status", description="View your cultivator profile")
async def cmd_status(interaction: discord.Interaction):
    c = await ensure_user(interaction.user)
    r = realm_data(c["realm"])
    next_r = realm_data(c["realm"] + 1) if c["realm"] < 7 else None
    inv = await get_inventory(str(interaction.user.id))

    breakthrough_info = ""
    if next_r:
        qi_needed = max(0, next_r["qi_req"] - c["qi"])
        item_ok = (next_r["item_req"] is None) or (inv.get(next_r["item_req"], 0) > 0)
        breakthrough_info = (
            f"\n**Next Realm:** {next_r['name']}\n"
            f"Qi needed: {qi_needed:,} · Item: {'✅' if item_ok else f'❌ Need {next_r[\"item_req\"]}'}"
        )

    sect_name = "None"
    if c["sect_id"]:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT name FROM sects WHERE id=$1", c["sect_id"])
        sect_name = row["name"] if row else "Unknown"

    e = jade_embed(
        f"📜 {interaction.user.display_name}'s Profile",
        f"**Realm:** {r['name']} — *{r['title']}*\n"
        f"**Qi:** {c['qi']:,}\n"
        f"**Spirit Stones:** 🪙 {c['spirit_stones']:,}\n"
        f"**Jade Coins:** 💎 {c['jade_coins']:,}\n"
        f"**Sect:** {sect_name}\n"
        f"**Duels:** {c['wins']}W / {c['losses']}L"
        f"{breakthrough_info}"
    )
    await interaction.response.send_message(embed=e)


@tree.command(name="cultivate", description="Meditate and gather Qi (1 hour cooldown)")
async def cmd_cultivate(interaction: discord.Interaction):
    c = await ensure_user(interaction.user)
    now = int(time.time())
    elapsed = now - (c["last_cultivate"] or 0)

    if elapsed < CULTIVATE_COOLDOWN:
        remaining = CULTIVATE_COOLDOWN - elapsed
        await interaction.response.send_message(embed=jade_embed(
            "⏳ Still Meditating",
            f"Your Qi channels are recovering.\nReturn in **{fmt_time(remaining)}**.",
            color=0x6a7a88
        ), ephemeral=True)
        return

    inv = await get_inventory(str(interaction.user.id))
    r = realm_data(c["realm"])
    min_qi, max_qi = r["qi_gain"]
    bonus_text = ""

    if inv.get("Qi Surge Pill", 0) > 0:
        await remove_item(str(interaction.user.id), "Qi Surge Pill")
        min_qi *= 2; max_qi *= 2
        bonus_text = "\n✨ *Qi Surge Pill activated — doubled gain!*"

    gained  = random.randint(min_qi, max_qi)
    new_qi  = c["qi"] + gained
    await update_user(str(interaction.user.id), qi=new_qi, last_cultivate=now)

    await interaction.response.send_message(embed=jade_embed(
        "🌀 Cultivation Complete",
        f"You sink into deep meditation, drawing Qi from heaven and earth.\n\n"
        f"**Gained:** +{gained:,} Qi{bonus_text}\n"
        f"**Total Qi:** {new_qi:,}\n\n"
        f"*Next cultivation in 1 hour.*"
    ))


@tree.command(name="breakthrough", description="Attempt to break through to the next realm")
async def cmd_breakthrough(interaction: discord.Interaction):
    c = await ensure_user(interaction.user)
    if c["realm"] >= 7:
        await interaction.response.send_message(embed=jade_embed(
            "☀️ You are the True Immortal",
            "You have reached the pinnacle of existence.",
            color=0xc9922a
        ))
        return

    next_r = realm_data(c["realm"] + 1)
    inv    = await get_inventory(str(interaction.user.id))

    if c["qi"] < next_r["qi_req"]:
        needed = next_r["qi_req"] - c["qi"]
        await interaction.response.send_message(embed=jade_embed(
            "❌ Insufficient Qi",
            f"You need **{needed:,} more Qi**.\nRequired: {next_r['qi_req']:,} · Current: {c['qi']:,}",
            color=0x8b1a1a
        ), ephemeral=True)
        return

    if next_r["item_req"] and inv.get(next_r["item_req"], 0) < 1:
        await interaction.response.send_message(embed=jade_embed(
            "❌ Missing Item",
            f"You need a **{next_r['item_req']}**. Buy it with `/buy {next_r['item_req']}`.",
            color=0x8b1a1a
        ), ephemeral=True)
        return

    if next_r["item_req"]:
        await remove_item(str(interaction.user.id), next_r["item_req"])

    chance  = max(0.5, 0.95 - (c["realm"] * 0.05))
    success = random.random() < chance

    if success:
        await update_user(str(interaction.user.id), realm=c["realm"] + 1)
        e = jade_embed(
            f"⚡ BREAKTHROUGH! → {next_r['name']}",
            f"Heaven and earth tremble as you shatter your ceiling!\n\n"
            f"You have ascended to **{next_r['name']}**.\n"
            f"New title: *{next_r['title']}*",
            color=0xc9922a
        )
    else:
        qi_loss = c["qi"] // 5
        await update_user(str(interaction.user.id), qi=c["qi"] - qi_loss)
        e = jade_embed(
            "💀 Breakthrough Failed",
            f"The tribulation lightning strikes you down!\n\n"
            f"Lost **{qi_loss:,} Qi** and your breakthrough item.\n"
            f"Steel your will and try again.",
            color=0x8b1a1a
        )
    await interaction.response.send_message(embed=e)


@tree.command(name="duel", description="Challenge another cultivator")
@app_commands.describe(opponent="The cultivator you wish to challenge")
async def cmd_duel(interaction: discord.Interaction, opponent: discord.Member):
    if opponent.id == interaction.user.id or opponent.bot:
        await interaction.response.send_message("Invalid target.", ephemeral=True)
        return

    attacker = await ensure_user(interaction.user)
    defender = await ensure_user(opponent)
    a_pow    = power_score(attacker)
    d_pow    = power_score(defender)
    prize    = random.randint(50, 200)
    a_wins   = random.random() < (a_pow / (a_pow + d_pow))

    if a_wins:
        await update_user(str(interaction.user.id),
                          wins=attacker["wins"] + 1,
                          spirit_stones=attacker["spirit_stones"] + prize)
        await update_user(str(opponent.id),
                          losses=defender["losses"] + 1,
                          spirit_stones=max(0, defender["spirit_stones"] - prize // 2))
        result = (f"⚔️ **{interaction.user.display_name}** wins!\n"
                  f"Gained 🪙 +{prize} · {opponent.display_name} loses 🪙 {prize//2}")
        color = 0x1a7a5c
    else:
        await update_user(str(opponent.id),
                          wins=defender["wins"] + 1,
                          spirit_stones=defender["spirit_stones"] + prize)
        await update_user(str(interaction.user.id),
                          losses=attacker["losses"] + 1,
                          spirit_stones=max(0, attacker["spirit_stones"] - prize // 2))
        result = (f"⚔️ **{opponent.display_name}** wins!\n"
                  f"Gained 🪙 +{prize} · {interaction.user.display_name} loses 🪙 {prize//2}")
        color = 0x8b1a1a

    e = jade_embed(
        f"⚔️ {interaction.user.display_name} vs {opponent.display_name}",
        f"**{realm_data(attacker['realm'])['name']}** vs **{realm_data(defender['realm'])['name']}**\n\n{result}",
        color=color
    )
    await interaction.response.send_message(embed=e)


@tree.command(name="shop", description="Browse the Spirit Stone shop")
async def cmd_shop(interaction: discord.Interaction):
    lines = [f"**{i['name']}** — 🪙 {i['price']:,}\n{i['desc']}" for i in SHOP_ITEMS]
    e = jade_embed("🏪 Cultivation Shop",
                   "\n\n".join(lines) + f"\n\nUse `/buy <name>` to purchase.\nBuy Jade Coins: {WEBSITE_URL}")
    await interaction.response.send_message(embed=e)


@tree.command(name="buy", description="Buy an item from the shop")
@app_commands.describe(item_name="Exact name of the item")
async def cmd_buy(interaction: discord.Interaction, item_name: str):
    c    = await ensure_user(interaction.user)
    item = next((i for i in SHOP_ITEMS if i["name"].lower() == item_name.lower()), None)
    if not item:
        await interaction.response.send_message(f"`{item_name}` not found. Use `/shop`.", ephemeral=True)
        return
    if c["spirit_stones"] < item["price"]:
        await interaction.response.send_message(embed=jade_embed(
            "❌ Insufficient Spirit Stones",
            f"Need 🪙 {item['price']:,} · Have 🪙 {c['spirit_stones']:,}",
            color=0x8b1a1a
        ), ephemeral=True)
        return
    await update_user(str(interaction.user.id), spirit_stones=c["spirit_stones"] - item["price"])
    await add_item(str(interaction.user.id), item["name"])
    await interaction.response.send_message(embed=jade_embed(
        "✅ Purchased",
        f"Acquired **{item['name']}**.\nRemaining: 🪙 {c['spirit_stones'] - item['price']:,}"
    ))


@tree.command(name="inventory", description="View your storage ring")
async def cmd_inventory(interaction: discord.Interaction):
    inv = await get_inventory(str(interaction.user.id))
    desc = "\n".join(f"• **{k}** × {v}" for k, v in inv.items()) if inv else "*Empty*"
    await interaction.response.send_message(embed=jade_embed("🎒 Storage Ring", desc))


@tree.command(name="mission", description="Complete a daily sect mission")
async def cmd_mission(interaction: discord.Interaction):
    c   = await ensure_user(interaction.user)
    now = int(time.time())
    if now - (c["last_mission"] or 0) < MISSION_COOLDOWN:
        remaining = MISSION_COOLDOWN - (now - (c["last_mission"] or 0))
        await interaction.response.send_message(embed=jade_embed(
            "⏳ Mission Cooldown",
            f"Next mission available in **{fmt_time(remaining)}**.",
            color=0x6a7a88
        ), ephemeral=True)
        return

    m = random.choice(MISSIONS)
    await update_user(str(interaction.user.id),
                      spirit_stones=c["spirit_stones"] + m["reward_stones"],
                      qi=c["qi"] + m["reward_qi"],
                      last_mission=now)
    rewards = f"🪙 +{m['reward_stones']} Spirit Stones"
    if m["reward_qi"]: rewards += f"\n🌀 +{m['reward_qi']} Qi"
    await interaction.response.send_message(embed=jade_embed(
        f"📜 Mission Complete: {m['name']}", f"**Rewards:**\n{rewards}"
    ))


@tree.command(name="leaderboard", description="View the Heaven's Rankings")
async def cmd_leaderboard(interaction: discord.Interaction):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT username, realm, qi, wins FROM users ORDER BY realm DESC, qi DESC LIMIT 10"
        )
    medals = ["🥇","🥈","🥉"] + ["⚔️"] * 7
    lines  = [
        f"{medals[i]} **{r['username']}** — {realm_data(r['realm'])['name']} · {r['qi']:,} Qi · {r['wins']}W"
        for i, r in enumerate(rows)
    ]
    await interaction.response.send_message(embed=jade_embed(
        "🏆 Heaven's Rankings", "\n".join(lines) if lines else "No cultivators yet."
    ))


@tree.command(name="convert", description="Convert Jade Coins → Spirit Stones (1:100)")
@app_commands.describe(amount="Number of Jade Coins to convert")
async def cmd_convert(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("Amount must be positive.", ephemeral=True)
        return
    c = await ensure_user(interaction.user)
    if c["jade_coins"] < amount:
        await interaction.response.send_message(embed=jade_embed(
            "❌ Insufficient Jade Coins",
            f"You have 💎 {c['jade_coins']:,} but tried to convert 💎 {amount:,}.",
            color=0x8b1a1a
        ), ephemeral=True)
        return
    stones = amount * 100
    await update_user(str(interaction.user.id),
                      jade_coins=c["jade_coins"] - amount,
                      spirit_stones=c["spirit_stones"] + stones)
    await interaction.response.send_message(embed=jade_embed(
        "💱 Conversion Complete",
        f"💎 {amount:,} Jade Coins → 🪙 {stones:,} Spirit Stones\n\n"
        f"New balance: 💎 {c['jade_coins']-amount:,} · 🪙 {c['spirit_stones']+stones:,}"
    ))


@tree.command(name="buyjade", description="Get a link to purchase Jade Coins")
async def cmd_buyjade(interaction: discord.Interaction):
    lines = []
    for pkg_id, pkg in JADE_PACKAGES.items():
        price_k = pkg["price_idr"] // 1000
        lines.append(f"**{pkg['name']}** — 💎 {pkg['jade']:,} Jade Coins — Rp{price_k}k")
    await interaction.response.send_message(embed=jade_embed(
        "💎 Buy Jade Coins",
        "Purchase on the website — coins are credited to your account automatically.\n\n"
        + "\n".join(lines)
        + f"\n\n🔗 **{WEBSITE_URL}**\n\n"
        f"*Log in with your Discord account to link your purchase.*"
    ))


# ─────────────────────────────────────────────
# SECT COMMANDS
# ─────────────────────────────────────────────
sect_group = app_commands.Group(name="sect", description="Sect management")

@sect_group.command(name="create", description="Found a sect (costs 🪙 500)")
@app_commands.describe(name="Your sect name")
async def sect_create(interaction: discord.Interaction, name: str):
    c = await ensure_user(interaction.user)
    if c["sect_id"]:
        await interaction.response.send_message("Already in a sect. Use `/sect leave` first.", ephemeral=True)
        return
    if c["spirit_stones"] < 500:
        await interaction.response.send_message("Founding costs 🪙 500.", ephemeral=True)
        return
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO sects (name, leader_id) VALUES ($1, $2) RETURNING id",
                name, str(interaction.user.id)
            )
        await update_user(str(interaction.user.id),
                          sect_id=row["id"],
                          spirit_stones=c["spirit_stones"] - 500)
        await interaction.response.send_message(embed=jade_embed(
            f"🏯 Sect Founded: {name}",
            f"The **{name}** sect has been established.\nCost: 🪙 500 Spirit Stones"
        ))
    except asyncpg.UniqueViolationError:
        await interaction.response.send_message(f"Sect **{name}** already exists.", ephemeral=True)

@sect_group.command(name="join", description="Join a sect")
@app_commands.describe(name="Exact sect name")
async def sect_join(interaction: discord.Interaction, name: str):
    c = await ensure_user(interaction.user)
    if c["sect_id"]:
        await interaction.response.send_message("Already in a sect.", ephemeral=True)
        return
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM sects WHERE name=$1", name)
    if not row:
        await interaction.response.send_message(f"Sect **{name}** not found.", ephemeral=True)
        return
    await update_user(str(interaction.user.id), sect_id=row["id"])
    await interaction.response.send_message(embed=jade_embed(
        f"🏯 Joined: {name}", f"Welcome to the **{name}** sect."
    ))

@sect_group.command(name="leave", description="Leave your sect")
async def sect_leave(interaction: discord.Interaction):
    c = await ensure_user(interaction.user)
    if not c["sect_id"]:
        await interaction.response.send_message("Not in a sect.", ephemeral=True)
        return
    await update_user(str(interaction.user.id), sect_id=None)
    await interaction.response.send_message(embed=jade_embed("🚶 Left Sect", "You walk the path alone once more."))

@sect_group.command(name="info", description="View your sect")
async def sect_info(interaction: discord.Interaction):
    c = await ensure_user(interaction.user)
    if not c["sect_id"]:
        await interaction.response.send_message("Not in a sect.", ephemeral=True)
        return
    async with pool.acquire() as conn:
        s       = await conn.fetchrow("SELECT name, leader_id, funds FROM sects WHERE id=$1", c["sect_id"])
        members = await conn.fetch(
            "SELECT username, realm FROM users WHERE sect_id=$1 ORDER BY realm DESC LIMIT 10",
            c["sect_id"]
        )
    member_lines = "\n".join(f"• **{m['username']}** — {realm_data(m['realm'])['name']}" for m in members)
    await interaction.response.send_message(embed=jade_embed(
        f"🏯 {s['name']}",
        f"**Members ({len(members)}):**\n{member_lines}\n**Funds:** 🪙 {s['funds']:,}"
    ))

tree.add_command(sect_group)

# ─────────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────────
@tree.command(name="admin_give", description="[ADMIN] Give currency to a player")
@app_commands.describe(user="Target", spirit_stones="Stones to add", jade_coins="Jade to add")
async def admin_give(interaction: discord.Interaction,
                     user: discord.Member,
                     spirit_stones: int = 0,
                     jade_coins: int = 0):
    if not await bot.is_owner(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    c = await ensure_user(user)
    await update_user(str(user.id),
                      spirit_stones=c["spirit_stones"] + spirit_stones,
                      jade_coins=c["jade_coins"] + jade_coins)
    await interaction.response.send_message(
        f"✅ Given **{user.display_name}**: 🪙{spirit_stones} + 💎{jade_coins}", ephemeral=True
    )

# ─────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────
@bot.event
async def on_ready():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    await tree.sync()
    print(f"⚡ Bot online as {bot.user}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.playing, name="修仙之路 | /start"
    ))

bot.run(BOT_TOKEN)

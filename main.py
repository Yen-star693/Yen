import discord
from discord.ext import commands
import os
import json
import time
import asyncio
import requests
import unicodedata
import random
import logging

from flask import Flask
from threading import Thread

# ================= WEB SERVER =================
app = Flask('')

@app.route('/')
def home():
    return "Yen bot is alive!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host='0.0.0.0',
        port=port
    )

def keep_alive():
    t = Thread(
        target=run_web,
        daemon=True
    )
    t.start()

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO)

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN")
GROQ_KEY = os.getenv("GROQ_KEY")

if not TOKEN:
    raise ValueError("Missing TOKEN")

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("yen "),
    intents=intents
)

SAFE = discord.AllowedMentions(
    everyone=False,
    roles=False,
    users=True
)

CREATOR_ID = 1383111113016872980
LOCK_CHANNEL_ID = 1446191246828634223

IS_LEADER = False

FILES = {
    "memory": "memory.json",
    "logs": "logs.json",
    "ignore": "ignore_roles.json"
}

# ================= FILE UTILS =================
def load(f):
    try:
        with open(f, "r") as fp:
            return json.load(fp)
    except:
        return {}

def save(f, d):
    try:
        with open(f, "w") as fp:
            json.dump(d, fp, indent=2)
    except Exception as e:
        print(f"Save error ({f}): {e}")

memory = load(FILES["memory"])
logs = load(FILES["logs"])
ignore_roles = load(FILES["ignore"])

# ================= COOLDOWN =================
response_times = {}
processed_messages = set()

def on_cooldown(uid):
    last = response_times.get(uid, 0)
    return (time.time() - last) < 3

def mark_responded(uid):
    response_times[uid] = time.time()

# ================= UTIL =================
def norm(t):
    return unicodedata.normalize(
        "NFKD",
        t
    ).encode(
        "ascii",
        "ignore"
    ).decode()

def log(g, text):
    if not g:
        return

    gid = str(g.id)

    logs.setdefault(gid, [])

    logs[gid].append(
        f"{time.strftime('%H:%M:%S')} | {text}"
    )

    logs[gid] = logs[gid][-20:]

    save(FILES["logs"], logs)

# ================= ROLE LOGIC =================
def top_role_filtered(member):
    ignored = ignore_roles.get(str(member.guild.id))

    roles = sorted(
        member.roles,
        key=lambda r: r.position,
        reverse=True
    )

    for r in roles:
        if str(r.id) != ignored:
            return r

    return roles[0] if roles else None

def can_act(actor, target):
    if actor.id == CREATOR_ID:
        return True

    ar = top_role_filtered(actor)
    tr = top_role_filtered(target)

    if not ar or not tr:
        return False

    return ar.position > tr.position

def bot_can(target, guild):
    if not guild.me:
        return False

    return guild.me.top_role > target.top_role

# ================= AI =================
def ask_ai(uid, text, system_override=None):

    if not GROQ_KEY:
        return "AI off"

    history = memory.get(str(uid), [])[-3:]

    system_prompt = (
        system_override
        or
        "You are Yen. Sarcastic, blunt, casual internet humor. Dry reactions. Short replies. Uses modern slang naturally. Swears.Confident attitude. Talks like a chronically online friend. Never mention TikTok, followers, streaming, or being an influencer."
    )

    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    if history:
        messages.append({
            "role": "user",
            "content": " | ".join(history)
        })

    messages.append({
        "role": "user",
        "content": text
    })

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}"
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": messages,
                "max_tokens": 50
            },
            timeout=10
        )

        if r.status_code != 200:
            return f"AI {r.status_code}"

        data = r.json()

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        print(f"AI error: {e}")
        return "AI died 💀"

# ================= MESSAGE =================
@bot.event
async def on_message(m):

    global IS_LEADER

    if not m:
        return

    if not m.guild:
        return

    if m.author.bot:
        return

    # ================= DUPLICATE PROTECTION =================
    if m.id in processed_messages:
        return

    processed_messages.add(m.id)

    if len(processed_messages) > 1000:
        processed_messages.clear()

    # ================= COMMANDS =================
    await bot.process_commands(m)

    # Ignore command prefix
    if bot.user and (
        m.content.startswith("yen ")
        or
        m.content.startswith(f"<@{bot.user.id}>")
    ):
        return

    if not IS_LEADER:
        return

    msg = norm(m.content.lower())
    uid = str(m.author.id)

    # ================= REPLY TO BOT =================
    if (
        m.reference
        and m.reference.resolved
        and isinstance(m.reference.resolved, discord.Message)
        and bot.user
        and m.reference.resolved.author.id == bot.user.id
    ):

        if on_cooldown(m.author.id):
            return

        mark_responded(m.author.id)

        memory.setdefault(uid, [])
        memory[uid].append(m.content)
        memory[uid] = memory[uid][-6:]

        save(FILES["memory"], memory)

        reply = ask_ai(uid, m.content)

        log(m.guild, f"REPLY AI {m.author}")

        try:
            await m.reply(
                reply,
                allowed_mentions=SAFE
            )
        except Exception as e:
            print(f"Reply error: {e}")

        return

    # ================= DIRECT AI TRIGGER =================
    if msg.startswith("hey yen"):

        if on_cooldown(m.author.id):
            return

        mark_responded(m.author.id)

        memory.setdefault(uid, [])
        memory[uid].append(m.content)
        memory[uid] = memory[uid][-6:]

        save(FILES["memory"], memory)

        reply = ask_ai(uid, m.content)

        log(m.guild, f"AI {m.author}")

        try:
            await m.reply(
                reply,
                allowed_mentions=SAFE
            )
        except Exception as e:
            print(f"Reply error: {e}")

        return

    # ================= RANDOM REPLY =================
    words = m.content.strip().split()

    if len(words) >= 4 and random.random() < 0.03:

        if on_cooldown(m.author.id):
            return

        mark_responded(m.author.id)

        memory.setdefault(uid, [])
        memory[uid].append(m.content)
        memory[uid] = memory[uid][-6:]

        save(FILES["memory"], memory)

        reply = ask_ai(
            uid,
            m.content,
            system_override=(
                "You are Yen. "
                ""You are Yen. You randomly joined a conversation. React naturally with dry humor and blunt opinions. Swears.Keep replies short. Use casual modern slang naturally. Never act like an influencer or content creator. Never mention TikTok, followers, livestreams, edits, or social media fame."."
            )
        )

        log(m.guild, f"RANDOM AI {m.author}")

        try:
            await m.reply(
                reply,
                allowed_mentions=SAFE
            )
        except Exception as e:
            print(f"Random reply error: {e}")

# ================= READY =================
@bot.event
async def on_ready():

    global IS_LEADER

    print(f"Logged in as {bot.user}")

    ch = bot.get_channel(LOCK_CHANNEL_ID)

    if ch:
        try:
            await ch.send("BOOTING...")
            await asyncio.sleep(1)

            IS_LEADER = True

            await ch.send("sup")

        except Exception as e:
            print(f"Startup channel error: {e}")

    else:
        print("Lock channel not found.")

# ================= COMMANDS =================
@bot.command()
async def ignore(ctx, role: discord.Role):

    if ctx.author.id != CREATOR_ID:
        return await ctx.send("no")

    ignore_roles[str(ctx.guild.id)] = str(role.id)

    save(FILES["ignore"], ignore_roles)

    await ctx.send(f"ignored {role.name}")

@bot.command()
async def unignore(ctx):

    if ctx.author.id != CREATOR_ID:
        return await ctx.send("no")

    ignore_roles.pop(str(ctx.guild.id), None)

    save(FILES["ignore"], ignore_roles)

    await ctx.send("ignore cleared")

@bot.command()
async def say(ctx, *, text):

    await ctx.send(text)

@bot.command()
async def purge(ctx, amount: int):

    if not ctx.author.guild_permissions.manage_messages:
        return await ctx.send("no perms")

    await ctx.channel.purge(limit=amount + 1)

# ================= RUN =================
if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
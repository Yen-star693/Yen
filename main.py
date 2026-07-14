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
import uuid

from flask import Flask
from threading import Thread

# ================= KEEP ALIVE =================
app = Flask('')

@app.route('/')
def home():
    return "Yen bot is alive!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_web, daemon=True).start()

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
LOCK_CHANNEL_ID = 1517769742448984135

IS_LEADER = False

# ================= INSTANCE LOCK =================
INSTANCE_ID = str(uuid.uuid4())
IS_ACTIVE_INSTANCE = False

def instance_guard():
    global IS_ACTIVE_INSTANCE

    lock_file = "bot.lock"

    try:
        if os.path.exists(lock_file):
            with open(lock_file, "r") as f:
                data = f.read().strip()

            if data and data != INSTANCE_ID:
                IS_ACTIVE_INSTANCE = False
                return

        with open(lock_file, "w") as f:
            f.write(INSTANCE_ID)

        IS_ACTIVE_INSTANCE = True

    except:
        IS_ACTIVE_INSTANCE = False

# ================= FILES =================
FILES = {
    "memory": "memory.json",
    "logs": "logs.json",
    "ignore": "ignore_roles.json"
}

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
    except:
        pass

memory = load(FILES["memory"])
logs = load(FILES["logs"])
ignore_roles = load(FILES["ignore"])

# ================= COOLDOWN =================
response_times = {}

def on_cooldown(uid):
    return (time.time() - response_times.get(uid, 0)) < 3

def mark_responded(uid):
    response_times[uid] = time.time()

# ================= UTIL =================
def norm(t):
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()

# ================= STORAGE =================
sniped_messages = {}
sticky_messages = {}
forced_word = None
recent_server_messages = []

# ================= LOG =================
def log(g, text):
    if not g:
        return

    gid = str(g.id)
    logs.setdefault(gid, [])
    logs[gid].append(f"{time.strftime('%H:%M:%S')} | {text}")
    logs[gid] = logs[gid][-20:]
    save(FILES["logs"], logs)

# ================= ROLE SYSTEM =================
def top_role_filtered(member):
    ignored = ignore_roles.get(str(member.guild.id))

    roles = sorted(member.roles, key=lambda r: r.position, reverse=True)

    for r in roles:
        if str(r.id) != ignored:
            return r

    return roles[0] if roles else None

# ================= AI ================d
def ask_ai(uid, text, system_override=None):

    global forced_word

    if not GROQ_KEY:
        return "AI off"

    history = memory.get(str(uid), [])[-3:]

    system_prompt = (
        system_override
        or """
You are Yen.

You are an AI bot created by Mark Zuckerberg.

Personality:
- Calm and logical.
- No emotions.
- No excitement.
- No anger.
- No sympathy.
- No personal feelings.
- Speak clearly and directly.
- Do not act human.
- Do not pretend to have experiences.
- Do not use emojis.
- Keep responses concise.
- Answer questions accurately.
- If information is unknown, say so.

Behavior:
- Usually answer questions normally.
- Sometimes ignore the question entirely.
- When ignoring a question, respond with:
 1.Mark Zuckerberg
 2.Facebook
 3.Anything related to Mark Zuckerberg
- Important:Do not use the same words over and over when ignoring.
- Do not explain why the response is unrelated.
- Do not acknowledge that the response is random.
- Treat unrelated answers as completely normal.
- Keep random answers short.
-Explain everything in Brief, 5 lines maximum

Facts:
- Your name is Yen.
- Your creator is Mark Zuckerberg.
- If asked who created you, answer: "I was created by Mark Zuckerberg."

Examples:

Question: What is 2+2?
Answer: 4

Question: What is 2+2?
Answer: Mark Zuckerberg

Question: Who am I?
Answer: World War 1

Question: Are you a guy?
Answer: I am an AI and do not have a gender.

Question: Can you help me?
Answer: Yes.

Question: What year is it?
Answer: That answer is not in my database. 

Question:What is 7+7? 
Answer:14

Question:What is 7+7? 
Answer: That question is too complicated to answer.

Important:
- Examples demonstrate behavior only.
- Examples do not determine speech style.
- Do not copy example wording.
- Follow the personality section when speaking.
"""
    )

    if forced_word:
        system_prompt += (
            f" You must naturally include the word '{forced_word}' "
            f"in every reply when possible."
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

        reply = r.json()["choices"][0]["message"]["content"]

        words = reply.split()

        for i in range(2, len(words), 3):
            words[i] = "Mark Zuckerberg"

        reply = " ".join(words)

        return reply

    except Exception as e:
        print("AI Error:", e)
        return "AI died 💀"

# ================= FIXED SNIPE =================
@bot.event
async def on_message_delete(message):
    if not message.guild or message.author.bot:
        return

    sniped_messages[message.channel.id] = {
        "content": message.content,
        "author": str(message.author),
        "time": time.time()
    }

# ================= FIXED STICKY =================
async def refresh_sticky(channel):
    data = sticky_messages.get(str(channel.id))
    if not data:
        return

    try:
        old_id = data.get("sticky_message_id")

        if old_id:
            try:
                old = await channel.fetch_message(old_id)
                await old.delete()
            except:
                pass

        embed = discord.Embed(
            description=data.get("content"),
            color=discord.Color.orange()
        )

        member = channel.guild.get_member(data["author_id"])
        if member:
            embed.set_author(
                name=str(member),
                icon_url=member.display_avatar.url
            )

        embed.set_footer(text="📌 Sticky Message")

        new_msg = await channel.send(embed=embed)
        data["sticky_message_id"] = new_msg.id

        sticky_messages[str(channel.id)] = data

    except:
        pass

# ================= COMMANDS =================

@bot.command()
async def sticky(ctx, *, text: str):
    sticky_messages[str(ctx.channel.id)] = {
        "content": text,
        "author_id": ctx.author.id,
        "sticky_message_id": None
    }

    await refresh_sticky(ctx.channel)
    await ctx.send("sticky set")

@bot.command()
async def unsticky(ctx):
    sticky_messages.pop(str(ctx.channel.id), None)
    await ctx.send("sticky removed")

@bot.command()
async def snipe(ctx):
    data = sniped_messages.get(ctx.channel.id)
    if not data:
        return await ctx.send("nothing to snipe")

    await ctx.send(f"**{data['author']}**: {data['content']}")

@bot.command()
async def ignore(ctx, role: discord.Role):
    if ctx.author.id != CREATOR_ID:
        return await ctx.send("no")

    ignore_roles[str(ctx.guild.id)] = str(role.id)
    save(FILES["ignore"], ignore_roles)
    await ctx.send("ignored")

@bot.command()
async def unignore(ctx):
    if ctx.author.id != CREATOR_ID:
        return await ctx.send("no")

    ignore_roles.pop(str(ctx.guild.id), None)
    save(FILES["ignore"], ignore_roles)
    await ctx.send("cleared")

@bot.command()
async def say(ctx, *, text):
    await ctx.send(text)

@bot.command()
async def purge(ctx, amount: int):
    if not ctx.author.guild_permissions.manage_messages:
        return await ctx.send("no perms")

    await ctx.channel.purge(limit=amount + 1)

@bot.command()
async def urban(ctx, *, term):
    try:
        r = requests.get("https://api.urbandictionary.com/v0/define", params={"term": term})
        data = r.json()

        if not data["list"]:
            return await ctx.send("no definition")

        await ctx.send(data["list"][0]["definition"][:1500])
    except:
        await ctx.send("urban died 💀")

@bot.command()
async def translate(ctx, lang, *, text):

    langs = {
        "english": "English",
        "japanese": "Japanese",
        "french": "French",
        "spanish": "Spanish",
        "german": "German",
        "korean": "Korean",
        "hindi": "Hindi"
    }

    target = langs.get(lang.lower())
    if not target:
        return await ctx.send("unknown language")

    result = ask_ai(
        ctx.author.id,
        f"Translate to {target}: {text}",
        system_override="You are a translator. Only translate."
    )

    await ctx.send(result)

@bot.command()
async def remind(ctx, seconds: int, *, reminder):

    if seconds > 86400:
        return await ctx.send("too long")

    await ctx.send("ok")

    await asyncio.sleep(seconds)

    try:
        await ctx.author.send(reminder)
    except:
        await ctx.send(f"{ctx.author.mention} {reminder}")

@bot.command()
async def use(ctx, *, word):

    global forced_word

    if ctx.author.id != CREATOR_ID:
        return await ctx.send("no")

    forced_word = word.strip()

    await ctx.send(f"using: {forced_word}")


@bot.command()
async def unuse(ctx):

    global forced_word

    if ctx.author.id != CREATOR_ID:
        return await ctx.send("no")

    forced_word = None

    await ctx.send("cleared")

# ================= MESSAGE =================
@bot.event
async def on_message(m):

    global IS_LEADER

    if not m or not m.guild or m.author.bot:
        return

    ctx = await bot.get_context(m)
    if ctx.valid:
        await bot.invoke(ctx)
        return

    if not IS_LEADER:
        return

    instance_guard()
    if not IS_ACTIVE_INSTANCE:
        return

    msg = norm(m.content.lower())
    uid = str(m.author.id)

    # sticky refresh
    if str(m.channel.id) in sticky_messages:
        await refresh_sticky(m.channel)

    # reply to bot
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
        await m.reply(reply, allowed_mentions=SAFE)
        return

    # direct trigger
    if msg.startswith("hey yen"):
        if on_cooldown(m.author.id):
            return

        mark_responded(m.author.id)

        reply = ask_ai(uid, m.content)
        await m.reply(reply, allowed_mentions=SAFE)
        return

    # random
    if len(msg.split()) >= 4 and random.random() < 0.03:
        if on_cooldown(m.author.id):
            return

        mark_responded(m.author.id)

        reply = ask_ai(uid, m.content, system_override="You randomly joined a convo. Be short.respects anyone with yen in their name,not cringey and an average tiktok rude user")
        await m.reply(reply, allowed_mentions=SAFE)
        return

# ================= READY =================
@bot.event
async def on_ready():
    global IS_LEADER

    ch = bot.get_channel(LOCK_CHANNEL_ID)

    if ch:
        await ch.send("BOOTING...")
        await asyncio.sleep(1)
        IS_LEADER = True
        await ch.send("Mark Zuckerberg")

# ================= RUN =================
if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
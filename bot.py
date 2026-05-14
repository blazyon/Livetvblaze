import asyncio
import aiohttp
from io import BytesIO
from urllib.parse import urlparse
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, VideoQuality
from flask import Flask
from threading import Thread
import os

# ================= CONFIG =================
API_ID = 35562064
API_HASH = "fc5a4484d4abe8a2118284147b1092f6"
BOT_TOKEN = "8544679303:AAFW5OwWCbQ969yjP2lgaHReWv4Bg6Iqdas"
SESSION_STRING = "BQIeolAAbzAOWSprcV68fWVq7aW-m2hSVZ3OGhQMLGvjeNtb_1lDPSZR7XSr6fweXkLVQsd3273FSRbvCHfCzfeU0cCqg_1Hjv-7pBzuxVEu5oPgckAmyu5NdlKkQH1NYVJQ9Ww6bU4yCdFF4i7Brupv4CbjBrdO0m1nkzbe0-Uud7fJwgxlmTymmWtOsBuyLbgdGY5tTP-17st4hCOfiLymCowvKaX8BF9bb-crFFdlNskAQDLgPVK0szcTwLYHuk4bPufV1nDD_owdXBTeQwMh-7-Wod5sGWAF0R3wf9-kBhJDfV7fLbg1wF_mgnLB20mO4PQmphOz61YhFhdGU5ep2_YPQwAAAAH_qqMkAA"
OWNER_ID = 8717767927

PORT = int(os.environ.get("PORT", 8080))
PROXY_URL = os.environ.get("PROXY_URL", "")

# ================= CLIENTS =================
app = Client("tv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
call_py = PyTgCalls(user_app)

# ================= DATA STORAGE =================
CHANNELS = {}
MOVIES = {}
SERIES = {}                    # {series_name.lower(): {episode.lower(): url}}
APPROVED_GROUPS = set()
active_streams = {}            # chat_id: {"name": , "quality": , "url": , "type": "live|movie|series"}

QUALITY_PRESETS = {
    "360p": VideoQuality.SD_360p, "480p": VideoQuality.SD_480p,
    "720p": VideoQuality.HD_720p, "1080p": VideoQuality.FHD_1080p,
    "2k": VideoQuality.QHD_2K, "4k": VideoQuality.UHD_4K,
}

# ================= HIGH-TECH THEME =================
def quality_buttons():
    qualities = ["360p", "480p", "720p", "1080p", "2k", "4k"]
    rows = [InlineKeyboardButton(q, callback_data=f"qchg|{q}") for q in qualities]
    return InlineKeyboardMarkup([rows[i:i+3] for i in range(0, len(rows), 3)])

MADE_BY = InlineKeyboardMarkup([[
    InlineKeyboardButton("👨‍💻 Made By 𝐵 𝑙 𝑎 𝑧 𝑒", url="tg://user?id=8717767927")
]])

# ================= FLASK FOR RAILWAY =================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "🌌 Local Stream TV High-Tech VC Bot Running"

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, debug=False)

# ================= AUTO ADD ASSISTANT =================
async def ensure_assistant_in_group(chat_id):
    try:
        assistant_id = (await user_app.get_me()).id
        await app.add_chat_members(chat_id, assistant_id)
        print(f"✅ Assistant successfully added to group {chat_id}")
        return True
    except Exception as e:
        print(f"⚠️ Assistant add failed for {chat_id}: {e}")
        return False

# ================= QUALITY CHANGE CALLBACK =================
@app.on_callback_query(filters.regex(r"qchg\|(.+)"))
async def change_quality(_, callback):
    chat_id = callback.message.chat.id
    new_quality = callback.data.split("|")[1]

    if chat_id not in active_streams:
        return await callback.answer("❌ No active stream found!", show_alert=True)

    data = active_streams[chat_id]
    await callback.answer(f"🔄 Switching to {new_quality}...")

    try:
        video_quality = QUALITY_PRESETS.get(new_quality, VideoQuality.HD_720p)
        headers = get_headers_for_stream(data["url"])

        await call_py.play(
            chat_id,
            MediaStream(
                media_path=data["url"],
                video_parameters=video_quality,
                headers=headers
            )
        )

        active_streams[chat_id]["quality"] = new_quality
        await callback.message.edit_text(
            f"**🚀 STREAM UPDATED SUCCESSFULLY**\n\n"
            f"📺 **{data['name'].title()}**\n"
            f"📊 **Quality:** {new_quality}\n"
            f"🔄 Quality changed instantly!",
            reply_markup=quality_buttons()
        )
    except Exception as e:
        await callback.answer("❌ Failed to change quality", show_alert=True)

# ================= MAIN PLAY FUNCTION =================
async def play_stream(chat_id, name, url, quality="720p", stream_type="live", message=None):
    await ensure_assistant_in_group(chat_id)
    
    msg = await message.reply(
        f"🌌 **Local Stream TV STREAM INITIALIZING**\n"
        f"🎬 **{name.title()}**\n"
        f"📊 **Quality:** {quality} • {stream_type.upper()}\n"
        f"⏳ Connecting...",
        reply_markup=quality_buttons()
    )

    try:
        video_quality = QUALITY_PRESETS.get(quality, VideoQuality.HD_720p)
        headers = get_headers_for_stream(url)

        await call_py.play(
            chat_id,
            MediaStream(media_path=url, video_parameters=video_quality, headers=headers)
        )

        active_streams[chat_id] = {
            "name": name,
            "quality": quality,
            "url": url,
            "type": stream_type
        }

        await msg.edit_text(
            f"**🚀 NOW STREAMING LIVE**\n\n"
            f"📺 **Title:** {name.title()}\n"
            f"📊 **Quality:** {quality}\n"
            f"🔗 **Type:** {stream_type.upper()}\n\n"
            f"💡 Click any button below to change quality instantly!",
            reply_markup=quality_buttons()
        )
    except Exception as e:
        await msg.edit_text(f"❌ **Playback Error**\n`{str(e)[:300]}`")

# ================= APPROVAL FILTER =================
def is_approved(_, __, message):
    return (
        message.chat.id in APPROVED_GROUPS or 
        message.chat.type == "private" or 
        message.from_user.id == OWNER_ID
    )

approved_filter = filters.create(is_approved)

# ================= COMMANDS =================
@app.on_message(filters.command("start"))
async def start_cmd(_, msg):
    await msg.reply(
        "🌌 **WELCOME TO Local Stream TV VC STREAMER**\n"
        "High-Tech • Live TV • Movies • Series\n\n"
        "Type /help for all commands",
        reply_markup=MADE_BY
    )

@app.on_message(filters.command("help"))
async def help_cmd(_, msg):
    await msg.reply(
        "🌟 **Local Stream TV FULL COMMANDS**\n\n"
        "📺 **Live TV**\n"
        "`/livetv <name>`   `/hqlivetv <name> <quality>`\n"
        "`/channels`\n\n"
        "🎬 **Movies & Series**\n"
        "`/addmovie <url> <name>`\n"
        "`/playmovie <name>`\n"
        "`/addseries <url> <series> <episode>`\n"
        "`/playseries <series> <episode>`\n\n"
        "🔧 **Owner Commands**\n"
        "`/approve <group_id>`   `/disapprove <group_id>`\n"
        "`/broadcast <text>`   `/stats`   `/addchannel`   `/addxtream`",
        reply_markup=MADE_BY
    )

# ================= GROUP MANAGEMENT =================
@app.on_message(filters.command("approve") & filters.user(OWNER_ID))
async def approve_group(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Usage: `/approve -1001234567890`")
    gid = int(msg.command[1])
    APPROVED_GROUPS.add(gid)
    await msg.reply(f"✅ **Group Approved**\nID: `{gid}`")

@app.on_message(filters.command("disapprove") & filters.user(OWNER_ID))
async def disapprove_group(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Usage: `/disapprove -1001234567890`")
    gid = int(msg.command[1])
    APPROVED_GROUPS.discard(gid)
    await msg.reply("🗑️ Group disapproved.")

@app.on_message(filters.command("stats") & filters.user(OWNER_ID))
async def bot_stats(_, msg):
    await msg.reply(
        f"🌌 **Local Stream TV BOT STATISTICS**\n\n"
        f"📺 Live Channels : **{len(CHANNELS)}**\n"
        f"🎬 Movies        : **{len(MOVIES)}**\n"
        f"📺 Series        : **{len(SERIES)}**\n"
        f"✅ Approved Groups : **{len(APPROVED_GROUPS)}**\n"
        f"🔴 Active Streams  : **{len(active_streams)}**",
        reply_markup=MADE_BY
    )

@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Usage: `/broadcast Your message`")
    text = msg.text.split(None, 1)[1]
    count = 0
    for gid in list(APPROVED_GROUPS):
        try:
            await app.send_message(gid, f"🌌 **Local Stream TV OFFICIAL BROADCAST**\n\n{text}\n\n-Made By 𝐵 𝑙 𝑎 𝑧 𝑒")
            count += 1
        except:
            pass
    await msg.reply(f"✅ Broadcast sent to **{count}** groups successfully!")

# ================= LIVE TV & YOUR ORIGINAL COMMANDS =================
@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(_, msg):
    if not CHANNELS:
        return await msg.reply("❌ No channels added yet.")
    text = "📺 **Available Live Channels**\n\n"
    for i, name in enumerate(sorted(CHANNELS.keys()), 1):
        text += f"`{i:02d}.` **{name.title()}**\n"
    await msg.reply(text)

@app.on_message(filters.command("livetv") & approved_filter)
async def livetv_cmd(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Usage: `/livetv Channel Name`")
    name = " ".join(msg.command[1:]).strip().lower()
    if name not in CHANNELS:
        return await msg.reply("❌ Channel not found! Use /channels")
    await play_stream(msg.chat.id, name, CHANNELS[name], "720p", "live", msg)

@app.on_message(filters.command("hqlivetv") & approved_filter)
async def hqlivetv_cmd(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Usage: `/hqlivetv Name Quality`")
    parts = msg.command[1:]
    quality = parts[-1].lower() if parts[-1] in QUALITY_PRESETS else "720p"
    name = " ".join(parts[:-1] if quality in QUALITY_PRESETS else parts).strip().lower()
    if name not in CHANNELS:
        return await msg.reply("❌ Channel not found!")
    await play_stream(msg.chat.id, name, CHANNELS[name], quality, "live", msg)

# ================= MOVIES & SERIES =================
@app.on_message(filters.command("addmovie") & filters.user(OWNER_ID))
async def add_movie(_, msg):
    args = msg.text.split(None, 2)
    if len(args) < 3:
        return await msg.reply("Usage: `/addmovie <url> <Movie Name>`")
    MOVIES[args[2].strip().lower()] = args[1]
    await msg.reply(f"✅ **Movie Added**\n🎬 {args[2]}")

@app.on_message(filters.command("playmovie") & approved_filter)
async def play_movie(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Usage: `/playmovie Movie Name`")
    name = " ".join(msg.command[1:]).lower()
    if name not in MOVIES:
        return await msg.reply("❌ Movie not found!")
    await play_stream(msg.chat.id, name, MOVIES[name], "720p", "movie", msg)

@app.on_message(filters.command("addseries") & filters.user(OWNER_ID))
async def add_series(_, msg):
    args = msg.text.split(None, 3)
    if len(args) < 4:
        return await msg.reply("Usage: `/addseries <url> <Series Name> <Episode>`")
    url, series, episode = args[1], args[2].strip().lower(), args[3].strip().lower()
    if series not in SERIES:
        SERIES[series] = {}
    SERIES[series][episode] = url
    await msg.reply(f"✅ Episode added!\n📺 {series.title()} - {episode.title()}")

@app.on_message(filters.command("playseries") & approved_filter)
async def play_series(_, msg):
    if len(msg.command) < 3:
        return await msg.reply("Usage: `/playseries <Series Name> <Episode>`")
    series = msg.command[1].lower()
    episode = " ".join(msg.command[2:]).lower()
    if series not in SERIES or episode not in SERIES[series]:
        return await msg.reply("❌ Series or Episode not found!")
    await play_stream(msg.chat.id, f"{series} - {episode}", SERIES[series][episode], "720p", "series", msg)

# ================= STOP STREAM =================
@app.on_message(filters.command("stopvc") & approved_filter)
async def stop_vc(_, msg):
    try:
        await call_py.leave_call(msg.chat.id)
        active_streams.pop(msg.chat.id, None)
        await msg.reply("⏹️ **Stream Stopped Successfully**")
    except:
        await msg.reply("❌ No active stream in this group.")

# ================= KEEP YOUR ORIGINAL FUNCTIONS (teststream, ping, etc.) =================
# Paste your original teststream, addchannel, addxtream, ping, proxyinfo here if needed.

# ================= BOOT =================
async def main():
    Thread(target=run_flask, daemon=True).start()
    
    await app.start()
    await user_app.start()
    await call_py.start()
    
    print("🌌 Local Stream TV High-Tech Bot Started Successfully!")
    try:
        await app.send_message(OWNER_ID, "🌌 **Local Stream TV Bot is Online**\nAll features activated!")
    except:
        pass
    
    await idle()

if __name__ == "__main__":
    asyncio.run(main())

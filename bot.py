import asyncio
import logging
import traceback
import aiohttp
from io import BytesIO
from urllib.parse import urlparse
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatType
from pyrogram.errors import UserAlreadyParticipant, InviteRequestSent
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, VideoQuality
from flask import Flask
from threading import Thread
import os
import sys

# ================= Logging Setup =================
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=LOG_DATEFMT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)

# Silence chatty libraries — we still see WARNING/ERROR from them.
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("pytgcalls").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("aiortc").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

LOGGER = logging.getLogger("StreamTV")

# ================= Configuration =================
API_ID = 35562064
API_HASH = "fc5a4484d4abe8a2118284147b1092f6"
BOT_TOKEN = "8544679303:AAFW5OwWCbQ969yjP2lgaHReWv4Bg6Iqdas"
SESSION_STRING = "BQIeolAALQt0sl_HGAXXJLn0qNKvNqV9idpk2QHG9HxMygD9Ls_j6lDvbCGP-ScEvV88GThS29HK-de5qMl9uhmcryNCQyhHcrmCJJP2opOzPazP4ZxkTJ4e50dGnV5kb69hOOV7jfqDlH2-maffOTswCkmHQt6h2SA-BSjrzVKOchR-SCxVhTaXu55SPccQhK935GtVo4sd7Zg1xwhMFV92IC30H6VCmx3KAmonMymPUbjuFhiINsEV8TxRV1eb1twOiPB6k5a4keXeUW1-6JjHy0tptquGitG_1wNlpDbqGnhhplhatN7QdIvSq0K_f3nBtW9UssVtIkKA1vIK3wigrgyo7QAAAAH_qqMkAA"
OWNER_ID = 8717767927

# High-Tech Branding
BOT_NAME = "𝙇𝙤𝙘𝙖𝙡 𝙎𝙩𝙧𝙚𝙖𝙢 𝙏𝙑 📺"
CREDITS = "\n\n⚡ **Made By [𝐵 𝑙 𝑎 𝑧 𝑒](tg://user?id=8717767927)**"

# Railway Port & Proxy
PORT = int(os.environ.get("PORT", 8080))
PROXY_URL = os.environ.get("PROXY_URL", "")

# ================= Storage (In-Memory Database) =================
CHANNELS = {}
MOVIES = {}
SERIES = {}
APPROVED_GROUPS = set()
CURRENT_STREAMS = {}  # Tracks what is currently playing in each chat

QUALITY_PRESETS = {
    "360p": VideoQuality.SD_360p,
    "480p": VideoQuality.SD_480p,
    "720p": VideoQuality.HD_720p,
    "1080p": VideoQuality.FHD_1080p,
}

# ================= Flask Server =================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return f"📺 {BOT_NAME} System Online"

@flask_app.route('/health')
def health():
    return {"status": "ok", "system": "online"}, 200

def run_flask():
    LOGGER.info(f"Flask health server starting on 0.0.0.0:{PORT}")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False)

# ================= Initialize Clients =================
app = Client("tv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
call_py = PyTgCalls(user_app)

# ================= Utilities =================
def _short(s, n=80):
    """Truncate long strings for log lines."""
    if not s:
        return s
    return s if len(s) <= n else s[:n] + "..."

def _who(message):
    """Return a compact user descriptor for logs."""
    if not message.from_user:
        return "anon"
    u = message.from_user
    return f"{u.id}({u.username or u.first_name or '?'})"

def get_amagi_headers(url):
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Origin": base_url,
        "Referer": base_url + "/",
    }

async def check_stream_url(url: str, timeout: int = 10):
    """
    Pre-flight check: is the stream URL reachable and returning media?
    Returns (ok: bool, reason: str).
    """
    headers = get_amagi_headers(url) if "amagi" in url.lower() else {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
            ) as resp:
                ctype = resp.headers.get("Content-Type", "unknown")
                if 200 <= resp.status < 300:
                    return True, f"HTTP {resp.status} | Content-Type: {ctype}"
                if resp.status in (401, 403):
                    return False, f"HTTP {resp.status} {resp.reason} — auth/geo blocked"
                if resp.status == 404:
                    return False, f"HTTP 404 — stream URL not found (dead link)"
                if 500 <= resp.status < 600:
                    return False, f"HTTP {resp.status} — source server error"
                return False, f"HTTP {resp.status} {resp.reason}"
    except asyncio.TimeoutError:
        return False, f"Timeout after {timeout}s (source not responding)"
    except aiohttp.ClientConnectorError as e:
        return False, f"Connection failed: {e}"
    except aiohttp.ClientPayloadError as e:
        return False, f"Bad payload: {e}"
    except aiohttp.ClientError as e:
        return False, f"{type(e).__name__}: {e}"
    except Exception as e:
        return False, f"Unexpected {type(e).__name__}: {e}"

async def ensure_assistant_in_chat(chat_id, message):
    """Automatically adds the Assistant (User Session) to the Group"""
    try:
        await user_app.get_chat(chat_id)
        LOGGER.debug(f"Assistant already in chat {chat_id}")
        return True
    except Exception as e:
        LOGGER.info(f"Assistant not in chat {chat_id} ({type(e).__name__}); attempting to join")
        try:
            chat = await app.get_chat(chat_id)
            link = chat.invite_link
            if not link:
                link = await app.export_chat_invite_link(chat_id)
            await user_app.join_chat(link)
            LOGGER.info(f"Assistant joined chat {chat_id} via invite link")
            await message.reply(f"🤖 **Assistant Successfully Joined the Group!** {CREDITS}")
            return True
        except UserAlreadyParticipant:
            LOGGER.debug(f"Assistant already participant in {chat_id} (race)")
            return True
        except Exception as e:
            LOGGER.error(f"Failed to add assistant to {chat_id}: {type(e).__name__}: {e}")
            LOGGER.debug(f"Traceback:\n{traceback.format_exc()}")
            await message.reply(
                f"⚠️ **Could not add assistant!**\n"
                f"Error Type: `{type(e).__name__}`\n"
                f"Details: `{str(e)[:150]}`\n\n"
                f"Please add the assistant manually to play streams.{CREDITS}"
            )
            return False

def check_approval(func):
    """Decorator to check if group is approved before streaming"""
    async def wrapper(client, message):
        if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            if message.chat.id not in APPROVED_GROUPS and message.from_user.id != OWNER_ID:
                LOGGER.warning(
                    f"Unapproved access | chat={message.chat.id} | user={_who(message)} | "
                    f"cmd=/{message.command[0] if message.command else '?'}"
                )
                return await message.reply(
                    f"🚫 **ACCESS DENIED**\n\n"
                    f"❖ This Group (`{message.chat.id}`) is not authorized!\n"
                    f"❖ Contact the owner to `/approve` this chat.{CREDITS}"
                )
        return await func(client, message)
    return wrapper

# ================= Start Command =================
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    LOGGER.info(f"/start | chat={message.chat.id} | user={_who(message)}")
    await message.reply(
        f"╭━━━[ **{BOT_NAME}** ]━━━╮\n"
        f"┃\n"
        f"┃ ❖ `/channels` - Browse Live TV\n"
        f"┃ ❖ `/movies` - Browse Movies\n"
        f"┃ ❖ `/series` - Browse Series\n"
        f"┃ ❖ `/livetv <name>` - Play Channel\n"
        f"┃ ❖ `/playmovie <name>` - Play Movie\n"
        f"┃ ❖ `/playseries <name> - <ep>` - Play Series\n"
        f"┃ ❖ `/stopvc` - Stop Current Stream\n"
        f"┃\n"
        f"╰━━━━━━━━━━━━━━━━━╯{CREDITS}",
        disable_web_page_preview=True
    )

# ================= Database Browsing (Channels/Movies/Series) =================
@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    LOGGER.info(f"/channels | chat={message.chat.id} | count={len(CHANNELS)}")
    if not CHANNELS:
        return await message.reply(f"❌ **No Channels Found.**\nAsk the owner to add some!{CREDITS}", disable_web_page_preview=True)

    text = f"╭━━━[ **📺 LIVE CHANNELS** ]━━━╮\n┃\n"
    for idx, name in enumerate(CHANNELS.keys(), 1):
        if len(text) > 3800:
            text += f"┃ ❖ ... and {len(CHANNELS) - idx + 1} more!\n"
            break
        text += f"┃ ❖ `{idx:02d}.` **{name.title()}**\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"

    if len(text) > 4000:
        file = BytesIO(text.encode())
        file.name = "channels.txt"
        await message.reply_document(file, caption=f"📺 **{len(CHANNELS)} Channels Available**{CREDITS}")
    else:
        await message.reply(text, disable_web_page_preview=True)

@app.on_message(filters.command("movies"))
async def show_movies(client, message):
    LOGGER.info(f"/movies | chat={message.chat.id} | count={len(MOVIES)}")
    if not MOVIES:
        return await message.reply(f"❌ **No Movies Found.**{CREDITS}", disable_web_page_preview=True)

    text = f"╭━━━[ **🎬 MOVIES LIST** ]━━━╮\n┃\n"
    for idx, name in enumerate(MOVIES.keys(), 1):
        text += f"┃ ❖ `{idx:02d}.` **{name.title()}**\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"
    await message.reply(text, disable_web_page_preview=True)

@app.on_message(filters.command("series"))
async def show_series(client, message):
    LOGGER.info(f"/series | chat={message.chat.id} | count={len(SERIES)}")
    if not SERIES:
        return await message.reply(f"❌ **No Series Found.**{CREDITS}", disable_web_page_preview=True)

    text = f"╭━━━[ **🍿 SERIES LIST** ]━━━╮\n┃\n"
    for show, eps in SERIES.items():
        text += f"┃ ❖ **{show.title()}** (Episodes: {', '.join(eps.keys()).upper()})\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"
    await message.reply(text, disable_web_page_preview=True)

# ================= OWNER COMMANDS =================
@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply(f"⚠️ **Usage:** `/addchannel <URL> <Channel Name>`\nExample: `/addchannel http://...ts Hungama`{CREDITS}", disable_web_page_preview=True)

    url, name = args[1], args[2].strip().lower()
    CHANNELS[name] = url
    LOGGER.info(f"Channel added | name='{name}' | url={_short(url)} | by={_who(message)}")
    await message.reply(f"✅ **Channel Added Successfully!**\n📺 Name: `{name.title()}`{CREDITS}", disable_web_page_preview=True)

@app.on_message(filters.command("addxtream") & filters.user(OWNER_ID))
async def add_xtream(client, message):
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(f"⚠️ **Usage:** `/addxtream <URL> <Username> <Password>`{CREDITS}", disable_web_page_preview=True)

    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    LOGGER.info(f"Xtream load requested | server={url} | user={user} | by={_who(message)}")
    msg = await message.reply("🚀 **Fetching Xtream channels...**")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=30) as resp:
                LOGGER.info(f"Xtream API response | status={resp.status} | server={url}")
                if resp.status == 200:
                    data = await resp.json()
                    count = 0
                    for stream in data:
                        name = stream.get("name", "").strip().lower()
                        if name:
                            stream_url = f"{url}/live/{user}/{passwd}/{stream.get('stream_id')}.m3u8"
                            CHANNELS[name] = stream_url
                            count += 1
                    LOGGER.info(f"Xtream load complete | added={count} | total_channels={len(CHANNELS)}")
                    await msg.edit_text(f"✅ **Loaded {count} Channels from Xtream API!**{CREDITS}", disable_web_page_preview=True)
                else:
                    LOGGER.error(f"Xtream API error | status={resp.status} | server={url}")
                    await msg.edit_text(f"❌ Error Status: {resp.status}")
    except asyncio.TimeoutError:
        LOGGER.error(f"Xtream API timeout | server={url}")
        await msg.edit_text("❌ Failed: Xtream API timed out after 30s")
    except Exception as e:
        LOGGER.error(f"Xtream API exception | server={url} | error={type(e).__name__}: {e}")
        LOGGER.debug(f"Traceback:\n{traceback.format_exc()}")
        await msg.edit_text(f"❌ Failed: `{type(e).__name__}: {str(e)[:100]}`")

@app.on_message(filters.command("addmovie") & filters.user(OWNER_ID))
async def add_movie(client, message):
    try:
        args = message.text.split(None, 1)[1].split("|")
        name, url = args[0].strip().lower(), args[1].strip()
        MOVIES[name] = url
        LOGGER.info(f"Movie added | name='{name}' | url={_short(url)} | by={_who(message)}")
        await message.reply(f"✅ **Movie Added:** {name.title()}{CREDITS}", disable_web_page_preview=True)
    except Exception as e:
        LOGGER.warning(f"addmovie parse failed | by={_who(message)} | error={type(e).__name__}: {e}")
        await message.reply(f"⚠️ **Format:** `/addmovie Movie Name | https://url.mp4`{CREDITS}", disable_web_page_preview=True)

@app.on_message(filters.command("addseries") & filters.user(OWNER_ID))
async def add_series(client, message):
    try:
        args = message.text.split(None, 1)[1].split("|")
        name, ep, url = args[0].strip().lower(), args[1].strip().lower(), args[2].strip()
        if name not in SERIES:
            SERIES[name] = {}
        SERIES[name][ep] = url
        LOGGER.info(f"Series added | show='{name}' | ep='{ep}' | url={_short(url)} | by={_who(message)}")
        await message.reply(f"✅ **Series Added:** {name.title()} ({ep.upper()}){CREDITS}", disable_web_page_preview=True)
    except Exception as e:
        LOGGER.warning(f"addseries parse failed | by={_who(message)} | error={type(e).__name__}: {e}")
        await message.reply(f"⚠️ **Format:** `/addseries Loki | S01E01 | https://url.mp4`{CREDITS}", disable_web_page_preview=True)

@app.on_message(filters.command("delchannel") & filters.user(OWNER_ID))
async def delete_channel(client, message):
    try:
        name = message.text.split(None, 1)[1].strip().lower()
        if name in CHANNELS:
            del CHANNELS[name]
            LOGGER.info(f"Channel deleted | name='{name}' | by={_who(message)}")
            await message.reply(f"🗑️ **Deleted:** {name.title()}{CREDITS}", disable_web_page_preview=True)
        else:
            LOGGER.warning(f"delchannel: '{name}' not found | by={_who(message)}")
            await message.reply("❌ Not found!")
    except Exception as e:
        LOGGER.warning(f"delchannel parse failed | error={type(e).__name__}: {e}")
        await message.reply("⚠️ **Usage:** `/delchannel <Name>`")

# ================= ADMIN/GROUP SYSTEM =================
@app.on_message(filters.command("approve") & filters.user(OWNER_ID))
async def approve_group(client, message):
    try:
        chat_id = int(message.command[1]) if len(message.command) > 1 else message.chat.id
        APPROVED_GROUPS.add(chat_id)
        LOGGER.info(f"Group approved | chat={chat_id} | by={_who(message)}")
        await message.reply(f"✅ **Group `{chat_id}` has been APPROVED.**\nUsers can now stream here.{CREDITS}", disable_web_page_preview=True)
    except ValueError:
        LOGGER.warning(f"approve: invalid chat id arg | by={_who(message)}")
        await message.reply("❌ Invalid Chat ID")

@app.on_message(filters.command("unapprove") & filters.user(OWNER_ID))
async def unapprove_group(client, message):
    try:
        chat_id = int(message.command[1]) if len(message.command) > 1 else message.chat.id
        if chat_id in APPROVED_GROUPS:
            APPROVED_GROUPS.remove(chat_id)
            LOGGER.info(f"Group unapproved | chat={chat_id} | by={_who(message)}")
        else:
            LOGGER.info(f"Group unapprove: chat={chat_id} was not in approved set")
        await message.reply(f"🚫 **Group `{chat_id}` UNAPPROVED.**{CREDITS}", disable_web_page_preview=True)
    except ValueError:
        LOGGER.warning(f"unapprove: invalid chat id arg | by={_who(message)}")

@app.on_message(filters.command("botinfo") & filters.user(OWNER_ID))
async def bot_info(client, message):
    LOGGER.info(f"/botinfo | by={_who(message)}")
    text = (
        f"╭━━━[ **🖥️ SYSTEM INFO** ]━━━╮\n"
        f"┃\n"
        f"┃ 📡 **Active Streams:** {len(CURRENT_STREAMS)}\n"
        f"┃ 📺 **Channels Added:** {len(CHANNELS)}\n"
        f"┃ 🎬 **Movies Added:** {len(MOVIES)}\n"
        f"┃ 🍿 **Series Added:** {len(SERIES)}\n"
        f"┃ 🛡️ **Approved Groups:** {len(APPROVED_GROUPS)}\n"
    )
    for grp in APPROVED_GROUPS:
        text += f"┃ ├ `{grp}`\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"
    await message.reply(text, disable_web_page_preview=True)

@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast(client, message):
    if len(message.command) < 2:
        return await message.reply("⚠️ Usage: `/broadcast <message>`")

    msg_text = message.text.split(None, 1)[1]
    success, failed = 0, 0
    LOGGER.info(f"Broadcast started | targets={len(APPROVED_GROUPS)} | by={_who(message)}")

    m = await message.reply("🚀 **Broadcasting message...**")
    for chat_id in APPROVED_GROUPS:
        try:
            await app.send_message(chat_id, f"🔔 **Broadcast Alert**\n\n{msg_text}{CREDITS}", disable_web_page_preview=True)
            success += 1
        except Exception as e:
            LOGGER.warning(f"Broadcast send failed | chat={chat_id} | error={type(e).__name__}: {e}")
            failed += 1

    LOGGER.info(f"Broadcast complete | sent={success} | failed={failed}")
    await m.edit_text(f"✅ **Broadcast Complete!**\n\n📨 Sent: {success}\n❌ Failed: {failed}{CREDITS}", disable_web_page_preview=True)

# ================= STREAMING COMMANDS =================
@app.on_message(filters.command(["livetv", "playmovie", "playseries"]) & filters.group)
@check_approval
async def stream_media(client, message):
    chat_id = message.chat.id
    cmd = message.command[0]
    user_desc = _who(message)

    LOGGER.info(f"Stream request | chat={chat_id} | user={user_desc} | cmd=/{cmd} | args={message.command[1:]}")

    if not await ensure_assistant_in_chat(chat_id, message):
        LOGGER.warning(f"Stream aborted — assistant not in chat | chat={chat_id}")
        return

    if len(message.command) < 2:
        return await message.reply(f"⚠️ Usage: `/{cmd} <Name>`")

    query = " ".join(message.command[1:]).strip().lower()

    url = ""
    media_type = ""
    display_name = ""

    if cmd == "livetv":
        if query not in CHANNELS:
            LOGGER.info(f"Channel not found | chat={chat_id} | query='{query}'")
            return await message.reply("❌ Channel not found! Use `/channels` to see the list.")
        url = CHANNELS[query]
        media_type = "📺 Live TV"
        display_name = query.title()

    elif cmd == "playmovie":
        if query not in MOVIES:
            LOGGER.info(f"Movie not found | chat={chat_id} | query='{query}'")
            return await message.reply("❌ Movie not found! Use `/movies` to see the list.")
        url = MOVIES[query]
        media_type = "🎬 Movie"
        display_name = query.title()

    elif cmd == "playseries":
        try:
            show, ep = [x.strip() for x in query.split("-")]
            if show not in SERIES or ep not in SERIES[show]:
                LOGGER.info(f"Series/Episode not found | chat={chat_id} | show='{show}' | ep='{ep}'")
                return await message.reply("❌ Series or Episode not found! Use `/series`.")
            url = SERIES[show][ep]
            media_type = "🍿 Series"
            display_name = f"{show.title()} [{ep.upper()}]"
        except ValueError:
            LOGGER.warning(f"playseries bad format | chat={chat_id} | query='{query}'")
            return await message.reply("⚠️ Format: `/playseries Show Name - S01E01`")

    LOGGER.info(f"Stream resolved | chat={chat_id} | name='{display_name}' | url={_short(url)}")

    msg = await message.reply(f"⚡ **Initializing {media_type}...**\n🔍 Checking source...")

    # --- Pre-flight URL check ---
    ok, reason = await check_stream_url(url)
    if not ok:
        LOGGER.error(f"Stream URL unreachable | chat={chat_id} | name='{display_name}' | reason={reason} | url={_short(url)}")
        return await msg.edit_text(
            f"❌ **Stream Source Unreachable!**\n\n"
            f"❖ **Title:** {display_name}\n"
            f"❖ **Reason:** `{reason}`\n"
            f"❖ The source URL did not respond properly. The owner may need to update the link.{CREDITS}",
            disable_web_page_preview=True,
        )
    LOGGER.info(f"Stream URL OK | chat={chat_id} | name='{display_name}' | {reason}")

    await msg.edit_text(f"⚡ **Source OK!**\n🎬 Starting voice chat playback...")

    # --- Hand off to pytgcalls ---
    try:
        headers = get_amagi_headers(url) if "amagi" in url.lower() else {}

        await call_py.play(
            chat_id,
            MediaStream(
                media_path=url,
                video_parameters=VideoQuality.HD_720p,
                headers=headers
            )
        )

        CURRENT_STREAMS[chat_id] = {"url": url, "name": display_name, "type": media_type}
        LOGGER.info(f"Playback started | chat={chat_id} | name='{display_name}' | quality=720p")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("360p", callback_data="q_360p"),
             InlineKeyboardButton("480p", callback_data="q_480p")],
            [InlineKeyboardButton("720p (HD)", callback_data="q_720p"),
             InlineKeyboardButton("1080p (FHD)", callback_data="q_1080p")]
        ])

        await msg.edit_text(
            f"╭━━━[ **{BOT_NAME}** ]━━━╮\n"
            f"┃\n"
            f"┃ ❖ **Status:** 🟢 Live Now\n"
            f"┃ ❖ **Type:** {media_type}\n"
            f"┃ ❖ **Title:** {display_name}\n"
            f"┃ ❖ **Quality:** 720p (HD)\n"
            f"┃\n"
            f"╰━━━━━━━━━━━━━━━━━╯{CREDITS}",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    except Exception as e:
        LOGGER.error(f"Playback failed | chat={chat_id} | name='{display_name}' | error={type(e).__name__}: {e}")
        LOGGER.debug(f"Traceback:\n{traceback.format_exc()}")
        await msg.edit_text(
            f"❌ **Playback Failed!**\n\n"
            f"❖ **Title:** {display_name}\n"
            f"❖ **Error Type:** `{type(e).__name__}`\n"
            f"❖ **Details:** `{str(e)[:200]}`\n\n"
            f"_The source was reachable but pytgcalls couldn't play it — likely a codec, format, or VC permission issue._{CREDITS}",
            disable_web_page_preview=True,
        )

# ================= QUALITY SWITCH CALLBACK =================
@app.on_callback_query(filters.regex(r"^q_"))
async def switch_quality(client, callback_query):
    chat_id = callback_query.message.chat.id
    quality_req = callback_query.data.split("_")[1]
    user_id = callback_query.from_user.id if callback_query.from_user else "?"

    LOGGER.info(f"Quality switch requested | chat={chat_id} | user={user_id} | quality={quality_req}")

    if chat_id not in CURRENT_STREAMS:
        LOGGER.warning(f"Quality switch: no active stream | chat={chat_id}")
        return await callback_query.answer("⚠️ No active stream found here!", show_alert=True)

    stream_info = CURRENT_STREAMS[chat_id]
    vq = QUALITY_PRESETS.get(quality_req, VideoQuality.HD_720p)

    try:
        headers = get_amagi_headers(stream_info["url"]) if "amagi" in stream_info["url"].lower() else {}

        await call_py.play(
            chat_id,
            MediaStream(
                media_path=stream_info["url"],
                video_parameters=vq,
                headers=headers
            )
        )
        LOGGER.info(f"Quality switched | chat={chat_id} | name='{stream_info['name']}' | quality={quality_req}")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("360p", callback_data="q_360p"),
             InlineKeyboardButton("480p", callback_data="q_480p")],
            [InlineKeyboardButton("720p (HD)", callback_data="q_720p"),
             InlineKeyboardButton("1080p (FHD)", callback_data="q_1080p")]
        ])

        await callback_query.message.edit_text(
            f"╭━━━[ **{BOT_NAME}** ]━━━╮\n"
            f"┃\n"
            f"┃ ❖ **Status:** 🟢 Live Now\n"
            f"┃ ❖ **Type:** {stream_info['type']}\n"
            f"┃ ❖ **Title:** {stream_info['name']}\n"
            f"┃ ❖ **Quality:** {quality_req.upper()} ✅\n"
            f"┃\n"
            f"╰━━━━━━━━━━━━━━━━━╯{CREDITS}",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        await callback_query.answer(f"✅ Quality switched to {quality_req}!")

    except Exception as e:
        LOGGER.error(f"Quality switch failed | chat={chat_id} | quality={quality_req} | error={type(e).__name__}: {e}")
        LOGGER.debug(f"Traceback:\n{traceback.format_exc()}")
        await callback_query.answer(f"❌ Failed: {type(e).__name__}", show_alert=True)

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    chat_id = message.chat.id
    LOGGER.info(f"/stopvc | chat={chat_id} | user={_who(message)}")
    try:
        await call_py.leave_call(chat_id)
        CURRENT_STREAMS.pop(chat_id, None)
        LOGGER.info(f"VC stopped | chat={chat_id}")
        await message.reply(f"⏹ **Stream Stopped Successfully.**{CREDITS}", disable_web_page_preview=True)
    except Exception as e:
        LOGGER.error(f"stopvc failed | chat={chat_id} | error={type(e).__name__}: {e}")
        LOGGER.debug(f"Traceback:\n{traceback.format_exc()}")
        await message.reply(f"❌ `{type(e).__name__}: {str(e)[:100]}`")

# ================= Boot Sequence =================
async def main():
    LOGGER.info("=" * 60)
    LOGGER.info(f"Booting {BOT_NAME}")
    LOGGER.info("=" * 60)

    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    LOGGER.info("Starting bot client...")
    await app.start()
    LOGGER.info("Bot client started")

    LOGGER.info("Starting user (assistant) client...")
    await user_app.start()
    LOGGER.info("User client started")

    LOGGER.info("Starting PyTgCalls...")
    await call_py.start()
    LOGGER.info("PyTgCalls started")

    print(f"✅ {BOT_NAME} System Online!")
    LOGGER.info(f"{BOT_NAME} fully online — listening for commands")

    try:
        await app.send_message(
            OWNER_ID,
            f"🟢 **{BOT_NAME} Online!**\nSystem initialized perfectly.{CREDITS}",
            disable_web_page_preview=True,
        )
    except Exception as e:
        LOGGER.warning(f"Could not DM owner at boot: {type(e).__name__}: {e}")

    await idle()

    LOGGER.info("Shutdown signal received — cleaning up streams")
    for chat_id in list(CURRENT_STREAMS.keys()):
        try:
            await call_py.leave_call(chat_id)
            LOGGER.info(f"Left VC at shutdown | chat={chat_id}")
        except Exception as e:
            LOGGER.warning(f"Failed to leave VC at shutdown | chat={chat_id} | {type(e).__name__}: {e}")

    await app.stop()
    await user_app.stop()
    LOGGER.info("Clients stopped — goodbye")

if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        LOGGER.info("KeyboardInterrupt — exiting")
    except Exception as e:
        LOGGER.critical(f"Fatal error in main: {type(e).__name__}: {e}")
        LOGGER.critical(f"Traceback:\n{traceback.format_exc()}")
        raise

import asyncio
import aiohttp
import json
import os
import re
from io import BytesIO
from urllib.parse import urlparse
from threading import Thread
from typing import Dict, Optional, Set, Tuple

from flask import Flask
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ForceReply
)
from pyrogram.enums import ChatType
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, VideoQuality

# ================= Configuration =================
API_ID = 35562064
API_HASH = "fc5a4484d4abe8a2118284147b1092f6"
BOT_TOKEN = "8544679303:AAFW5OwWCbQ969yjP2lgaHReWv4Bg6Iqdas"
SESSION_STRING = "BQIeolAAbzAOWSprcV68fWVq7aW-m2hSVZ3OGhQMLGvjeNtb_1lDPSZR7XSr6fweXkLVQsd3273FSRbvCHfCzfeU0cCqg_1Hjv-7pBzuxVEu5oPgckAmyu5NdlKkQH1NYVJQ9Ww6bU4yCdFF4i7Brupv4CbjBrdO0m1nkzbe0-Uud7fJwgxlmTymmWtOsBuyLbgdGY5tTP-17st4hCOfiLymCowvKaX8BF9bb-crFFdlNskAQDLgPVK0szcTwLYHuk4bPufV1nDD_owdXBTeQwMh-7-Wod5sGWAF0R3wf9-kBhJDfV7fLbg1wF_mgnLB20mO4PQmphOz61YhFhdGU5ep2_YPQwAAAAH_qqMkAA"
OWNER_ID = 8717767927

PORT = int(os.environ.get("PORT", 8080))
PROXY_URL = os.environ.get("PROXY_URL", "")

# ================= File Storage =================
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

CHANNELS_FILE = os.path.join(DATA_DIR, "channels.json")
APPROVED_FILE = os.path.join(DATA_DIR, "approved_groups.json")
MOVIES_FILE = os.path.join(DATA_DIR, "movies.json")
SERIES_FILE = os.path.join(DATA_DIR, "series.json")

def load_json(file, default):
    try:
        with open(file, "r") as f:
            return json.load(f)
    except:
        return default

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

# Global data structures
CHANNELS: Dict[str, str] = load_json(CHANNELS_FILE, {})
APPROVED_GROUPS: Set[int] = set(load_json(APPROVED_FILE, []))
MOVIES: Dict[str, str] = load_json(MOVIES_FILE, {})  # name -> url
SERIES: Dict[str, Dict] = load_json(SERIES_FILE, {})  # series_name -> {seasons: {season: {episodes: {ep: url}}}}

# Active streams info
active_streams: Dict[int, Dict] = {}  # chat_id -> {"channel_name": str, "quality": str, "url": str, "is_movie": bool}

# ================= Flask Server =================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "🚀 Live TV Bot - HighTech Edition"

@flask_app.route('/health')
def health():
    return {"status": "ok", "proxy": bool(PROXY_URL), "groups": len(APPROVED_GROUPS)}, 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, debug=False)

# ================= Initialize Clients =================
app = Client("tv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

call_py = PyTgCalls(user_app)

# ================= Helper Functions =================
QUALITY_PRESETS = {
    "360p": VideoQuality.SD_360p,
    "480p": VideoQuality.SD_480p,
    "720p": VideoQuality.HD_720p,
    "1080p": VideoQuality.FHD_1080p,
    "2k": VideoQuality.QHD_2K,
    "4k": VideoQuality.UHD_4K,
}

QUALITY_BUTTONS = InlineKeyboardMarkup([
    [InlineKeyboardButton("360p", callback_data="q_360p"),
     InlineKeyboardButton("480p", callback_data="q_480p"),
     InlineKeyboardButton("720p", callback_data="q_720p")],
    [InlineKeyboardButton("1080p", callback_data="q_1080p"),
     InlineKeyboardButton("2K", callback_data="q_2k"),
     InlineKeyboardButton("4K", callback_data="q_4k")],
    [InlineKeyboardButton("⏹ Stop", callback_data="stop_stream")]
])

def get_quality_keyboard():
    return QUALITY_BUTTONS

def save_all_data():
    save_json(CHANNELS_FILE, CHANNELS)
    save_json(APPROVED_FILE, list(APPROVED_GROUPS))
    save_json(MOVIES_FILE, MOVIES)
    save_json(SERIES_FILE, SERIES)

async def ensure_assistant_in_group(chat_id: int) -> bool:
    """Auto-add assistant if not member and bot has permission"""
    try:
        assistant_me = await user_app.get_me()
        assistant_id = assistant_me.id
        try:
            member = await app.get_chat_member(chat_id, assistant_id)
            if member.status in ["member", "administrator", "creator"]:
                return True
        except:
            pass
        # Try to add assistant
        await app.add_chat_members(chat_id, assistant_id)
        print(f"✅ Added assistant to chat {chat_id}")
        return True
    except Exception as e:
        print(f"⚠️ Could not auto-add assistant to {chat_id}: {e}")
        return False

async def is_chat_approved(chat_id: int) -> bool:
    """Check if group is approved by owner"""
    return chat_id in APPROVED_GROUPS

async def get_all_bot_groups() -> List[int]:
    """Retrieve all group IDs where bot is a member"""
    groups = []
    async for dialog in app.get_dialogs():
        if dialog.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            groups.append(dialog.chat.id)
    return groups

async def play_media(chat_id: int, url: str, quality: str, title: str, is_movie: bool = False, original_msg: Message = None):
    """Generic play function with quality buttons"""
    quality_label = quality.upper().replace("P", "p")
    video_quality = QUALITY_PRESETS.get(quality, VideoQuality.HD_720p)
    
    # Get stream headers
    headers = get_headers_for_stream(url)
    
    # Store stream info
    active_streams[chat_id] = {
        "url": url,
        "quality": quality,
        "title": title,
        "is_movie": is_movie
    }
    
    try:
        await call_py.play(
            chat_id,
            MediaStream(
                media_path=url,
                video_parameters=video_quality,
                headers=headers
            )
        )
        
        if original_msg:
            await original_msg.edit_text(
                f"▶️ **Now Streaming**\n\n"
                f"🎬 **{title}**\n"
                f"📊 **Quality:** `{quality_label}`\n"
                f"🔄 Use buttons below to change quality\n"
                f"⏹ `/stopvc` to stop",
                reply_markup=get_quality_keyboard()
            )
        return True
    except Exception as e:
        if original_msg:
            await original_msg.edit_text(f"❌ **Failed to play**\nError: `{str(e)[:150]}`")
        return False

async def change_stream_quality(chat_id: int, new_quality: str, callback_query: CallbackQuery = None):
    """Change quality of currently playing stream"""
    if chat_id not in active_streams:
        if callback_query:
            await callback_query.answer("No active stream to change quality", show_alert=True)
        return False
    
    stream = active_streams[chat_id]
    url = stream["url"]
    title = stream["title"]
    is_movie = stream.get("is_movie", False)
    
    # Stop current stream
    try:
        await call_py.leave_call(chat_id)
    except:
        pass
    
    # Restart with new quality
    success = await play_media(chat_id, url, new_quality, title, is_movie)
    
    if success and callback_query:
        await callback_query.answer(f"Quality changed to {new_quality}", show_alert=False)
        # Update stored quality
        active_streams[chat_id]["quality"] = new_quality
    elif callback_query:
        await callback_query.answer("Failed to change quality", show_alert=True)
    
    return success

def detect_stream_type(url):
    """Detect stream type from URL"""
    url_lower = url.lower()
    if any(x in url_lower for x in ['amagi', 'amg', 'now3', 'playout']):
        return "amagi"
    elif url_lower.endswith('.m3u8'):
        return "hls"
    elif url_lower.endswith(('.mp4', '.ts', '.mkv', '.webm')):
        return "direct_video"
    elif 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        return "youtube"
    elif 'twitch.tv' in url_lower:
        return "twitch"
    else:
        return "direct"

def get_amagi_headers(url):
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Origin": base_url,
        "Referer": base_url + "/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

def get_headers_for_stream(url):
    stream_type = detect_stream_type(url)
    if stream_type == "amagi":
        return get_amagi_headers(url)
    return BROWSER_HEADERS

# ================= Commands =================
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    owner = await client.get_users(OWNER_ID)
    owner_mention = f"[{owner.first_name}](tg://user?id={OWNER_ID})"
    
    await message.reply(
        f"**🎬 HighTech Live TV Bot**\n\n"
        f"⚡ **Next-Gen Streaming**\n"
        f"• Live TV Channels\n"
        f"• Movies & Series\n"
        f"• Adaptive Quality\n"
        f"• Auto Assistant Join\n\n"
        f"**📋 Commands:**\n"
        f"`/channels` - Browse TV channels\n"
        f"`/movies` - Browse movies\n"
        f"`/series` - Browse series\n"
        f"`/livetv <name>` - Play channel\n"
        f"`/hqlivetv <name> <quality>` - Play with quality\n"
        f"`/playmovie <name>` - Play movie\n"
        f"`/playepisode <series> <s> <e>` - Play episode\n"
        f"`/stopvc` - Stop streaming\n"
        f"`/help` - Full command list\n\n"
        f"🔧 **Made with ❤️ by** {owner_mention}",
        disable_web_page_preview=True
    )

@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    owner = await client.get_users(OWNER_ID)
    owner_mention = f"[{owner.first_name}](tg://user?id={OWNER_ID})"
    help_text = f"""
**🚀 HIGH-TECH TV BOT - COMMAND CENTER**

**📺 LIVE TV**
`/channels` - List all channels
`/livetv <name>` - Play channel (720p default)
`/hqlivetv <name> <quality>` - Play with quality (360p/480p/720p/1080p/2k/4k)

**🎬 MOVIES**
`/movies` - List all movies
`/playmovie <name>` - Play movie (quality buttons appear)

**📀 SERIES**
`/series` - List all series
`/viewseries <name>` - View seasons/episodes
`/playepisode <series> <season> <episode>` - Play episode

**🎮 CONTROLS**
`/stopvc` - Stop current stream
`/ping` - Check bot status

**👑 OWNER**
`/approve <chat_id>` - Allow bot in group
`/disapprove <chat_id>` - Remove access
`/approvedlist` - Show approved groups
`/broadcast` - Message to all groups
`/stats` - Bot statistics

**💡 TIPS**
• Use quality buttons during playback
• Assistant auto-joins groups
• Supports Amagi/HLS/Direct streams

**🔧 Developed by** {NothingWants}
    """
    await message.reply(help_text, disable_web_page_preview=True)

@app.on_message(filters.command("channels"))
async def show_channels(client, message):
    if not CHANNELS:
        return await message.reply("❌ No channels loaded.")
    
    # Check approval for group commands if not owner
    if message.chat.type != "private" and message.from_user.id != OWNER_ID:
        if not await is_chat_approved(message.chat.id):
            return await message.reply("⚠️ This group is not approved. Contact bot owner.")
    
    text = "**📺 LIVE TV CHANNELS**\n\n"
    for idx, name in enumerate(sorted(CHANNELS.keys()), 1):
        text += f"`{idx:02d}.` **{name.title()}**\n"
        if len(text) > 3500:
            text += f"\n... and {len(CHANNELS) - idx} more"
            break
    text += f"\n📊 **Total:** {len(CHANNELS)} channels\n💡 Use `/livetv <name>` to play"
    
    if len(text) > 4000:
        file = BytesIO(text.encode())
        file.name = "channels.txt"
        await message.reply_document(file, caption="📺 Channel List")
    else:
        await message.reply(text)

@app.on_message(filters.command("livetv"))
async def play_live_tv(client, message):
    chat_id = message.chat.id
    
    # Approval check
    if chat_id not in [OWNER_ID] and message.chat.type != "private":
        if not await is_chat_approved(chat_id):
            return await message.reply("❌ Group not approved. Owner must `/approve` first.")
    
    # Auto-add assistant
    await ensure_assistant_in_group(chat_id)
    
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/livetv <Channel Name>`")
    
    channel_name = " ".join(message.command[1:]).strip().lower()
    if channel_name not in CHANNELS:
        return await message.reply("❌ Channel not found. Use `/channels`")
    
    url = CHANNELS[channel_name]
    msg = await message.reply(f"🎬 **Loading {channel_name.title()}...**\n⏳ Please wait")
    
    success = await play_media(chat_id, url, "720p", channel_name.title(), is_movie=False, original_msg=msg)
    if not success:
        await msg.edit_text(f"❌ Failed to play {channel_name.title()}. Check URL or try lower quality.")

@app.on_message(filters.command("hqlivetv"))
async def play_hq_tv(client, message):
    chat_id = message.chat.id
    
    if chat_id not in [OWNER_ID] and message.chat.type != "private":
        if not await is_chat_approved(chat_id):
            return await message.reply("❌ Group not approved.")
    
    await ensure_assistant_in_group(chat_id)
    
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/hqlivetv <Channel> [quality]`")
    
    parts = message.command[1:]
    quality = "720p"
    if parts[-1].lower() in QUALITY_PRESETS:
        quality = parts[-1].lower()
        channel_name = " ".join(parts[:-1]).strip().lower()
    else:
        channel_name = " ".join(parts).strip().lower()
    
    if channel_name not in CHANNELS:
        return await message.reply("❌ Channel not found.")
    
    url = CHANNELS[channel_name]
    msg = await message.reply(f"🎬 **Loading {channel_name.title()}**\n📊 Quality: {quality.upper()}")
    await play_media(chat_id, url, quality, channel_name.title(), is_movie=False, original_msg=msg)

@app.on_message(filters.command("movies"))
async def list_movies(client, message):
    if not MOVIES:
        return await message.reply("❌ No movies added yet.")
    
    text = "**🎬 MOVIE LIBRARY**\n\n"
    for idx, name in enumerate(sorted(MOVIES.keys()), 1):
        text += f"`{idx:02d}.` **{name.title()}**\n"
        if len(text) > 3500:
            text += f"\n... and {len(MOVIES) - idx} more"
            break
    text += f"\n📊 **Total:** {len(MOVIES)} movies\n💡 Use `/playmovie <name>` to watch"
    await message.reply(text)

@app.on_message(filters.command("playmovie"))
async def play_movie(client, message):
    chat_id = message.chat.id
    
    if chat_id not in [OWNER_ID] and message.chat.type != "private":
        if not await is_chat_approved(chat_id):
            return await message.reply("❌ Group not approved.")
    
    await ensure_assistant_in_group(chat_id)
    
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/playmovie <Movie Name>`")
    
    movie_name = " ".join(message.command[1:]).strip().lower()
    if movie_name not in MOVIES:
        return await message.reply("❌ Movie not found. Use `/movies`")
    
    url = MOVIES[movie_name]
    msg = await message.reply(f"🎬 **Playing {movie_name.title()}...**")
    await play_media(chat_id, url, "720p", f"Movie: {movie_name.title()}", is_movie=True, original_msg=msg)

@app.on_message(filters.command("series"))
async def list_series(client, message):
    if not SERIES:
        return await message.reply("❌ No series added yet.")
    
    text = "**📀 SERIES CATALOG**\n\n"
    for idx, name in enumerate(sorted(SERIES.keys()), 1):
        total_eps = sum(len(episodes) for seasons in SERIES[name]["seasons"].values() for episodes in seasons.values())
        text += f"`{idx:02d}.` **{name.title()}** - {total_eps} episodes\n"
        if len(text) > 3500:
            break
    text += f"\n📊 **Total:** {len(SERIES)} series\n💡 Use `/viewseries <name>` to see episodes"
    await message.reply(text)

@app.on_message(filters.command("viewseries"))
async def view_series_details(client, message):
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/viewseries <Series Name>`")
    
    series_name = " ".join(message.command[1:]).strip().lower()
    if series_name not in SERIES:
        return await message.reply("❌ Series not found.")
    
    data = SERIES[series_name]
    text = f"**📀 {series_name.title()}**\n\n"
    for season_num, season_data in sorted(data["seasons"].items()):
        text += f"**Season {season_num}:**\n"
        for ep_num, url in sorted(season_data["episodes"].items()):
            text += f"  • Episode {ep_num}\n"
        text += "\n"
    text += f"💡 Play: `/playepisode {series_name} <season> <episode>`"
    await message.reply(text)

@app.on_message(filters.command("playepisode"))
async def play_episode(client, message):
    chat_id = message.chat.id
    
    if chat_id not in [OWNER_ID] and message.chat.type != "private":
        if not await is_chat_approved(chat_id):
            return await message.reply("❌ Group not approved.")
    
    await ensure_assistant_in_group(chat_id)
    
    args = message.command
    if len(args) < 4:
        return await message.reply("**Usage:** `/playepisode <Series> <Season> <Episode>`")
    
    series_name = args[1].lower()
    try:
        season = int(args[2])
        episode = int(args[3])
    except:
        return await message.reply("Season and episode must be numbers")
    
    if series_name not in SERIES:
        return await message.reply("❌ Series not found.")
    
    series_data = SERIES[series_name]
    if str(season) not in series_data["seasons"]:
        return await message.reply(f"Season {season} not found.")
    
    if str(episode) not in series_data["seasons"][str(season)]["episodes"]:
        return await message.reply(f"Episode {episode} not found in Season {season}.")
    
    url = series_data["seasons"][str(season)]["episodes"][str(episode)]
    title = f"{series_name.title()} S{season}E{episode}"
    msg = await message.reply(f"🎬 **Playing {title}...**")
    await play_media(chat_id, url, "720p", title, is_movie=False, original_msg=msg)

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    chat_id = message.chat.id
    try:
        await call_py.leave_call(chat_id)
        if chat_id in active_streams:
            del active_streams[chat_id]
        await message.reply("⏹ **Stream stopped**")
    except Exception as e:
        await message.reply(f"❌ Error: `{str(e)[:100]}`")

@app.on_message(filters.command("ping"))
async def ping_cmd(client, message):
    await message.reply("🏓 **Pong!**\n✅ Bot is running\n⚡ HighTech Mode")

# ================= Owner Commands =================
@app.on_message(filters.command("approve") & filters.user(OWNER_ID))
async def approve_group(client, message):
    try:
        if len(message.command) > 1:
            chat_id = int(message.command[1])
        else:
            chat_id = message.chat.id
        
        APPROVED_GROUPS.add(chat_id)
        save_json(APPROVED_FILE, list(APPROVED_GROUPS))
        await message.reply(f"✅ Group `{chat_id}` approved. Bot will now work there.")
    except:
        await message.reply("❌ Invalid chat ID")

@app.on_message(filters.command("disapprove") & filters.user(OWNER_ID))
async def disapprove_group(client, message):
    try:
        if len(message.command) > 1:
            chat_id = int(message.command[1])
        else:
            chat_id = message.chat.id
        
        if chat_id in APPROVED_GROUPS:
            APPROVED_GROUPS.remove(chat_id)
            save_json(APPROVED_FILE, list(APPROVED_GROUPS))
            await message.reply(f"❌ Group `{chat_id}` disapproved.")
        else:
            await message.reply("Group not in approved list.")
    except:
        await message.reply("❌ Invalid chat ID")

@app.on_message(filters.command("approvedlist") & filters.user(OWNER_ID))
async def list_approved(client, message):
    if not APPROVED_GROUPS:
        return await message.reply("No approved groups.")
    
    text = "**✅ Approved Groups**\n\n"
    for gid in APPROVED_GROUPS:
        try:
            chat = await client.get_chat(gid)
            name = chat.title or "Unknown"
            text += f"• `{gid}` - {name}\n"
        except:
            text += f"• `{gid}`\n"
    
    await message.reply(text)

@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast_cmd(client, message):
    if len(message.command) < 2 and not message.reply_to_message:
        return await message.reply("**Usage:** `/broadcast <message>` or reply to a message")
    
    if message.reply_to_message:
        msg_content = message.reply_to_message.text or message.reply_to_message.caption
        if not msg_content:
            return await message.reply("Reply to a text message")
    else:
        msg_content = message.text.split(None, 1)[1]
    
    sent_msg = await message.reply("📡 **Broadcasting to all groups...**")
    
    groups = await get_all_bot_groups()
    success = 0
    fail = 0
    
    for gid in groups:
        try:
            await client.send_message(gid, f"📢 **Broadcast from Owner**\n\n{msg_content}")
            success += 1
            await asyncio.sleep(0.5)
        except:
            fail += 1
    
    await sent_msg.edit_text(f"✅ **Broadcast complete**\n📨 Sent: {success}\n❌ Failed: {fail}\n🎯 Total groups: {len(groups)}")

@app.on_message(filters.command("stats") & filters.user(OWNER_ID))
async def stats_cmd(client, message):
    groups = await get_all_bot_groups()
    text = f"""
**📊 BOT STATISTICS**

📺 **Live Channels:** {len(CHANNELS)}
🎬 **Movies:** {len(MOVIES)}
📀 **Series:** {len(SERIES)}
✅ **Approved Groups:** {len(APPROVED_GROUPS)}
🌍 **Total Groups:** {len(groups)}
🎧 **Active Streams:** {len(active_streams)}
🔒 **Proxy:** {'Enabled' if PROXY_URL else 'Direct'}

**System Status:** 🟢 Operational
"""
    await message.reply(text)

# ================= Add Content Commands (Owner) =================
@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply("**Usage:** `/addchannel <URL> <Channel Name>`")
    
    url, name = args[1], args[2].strip().lower()
    CHANNELS[name] = url
    save_json(CHANNELS_FILE, CHANNELS)
    await message.reply(f"✅ **Added channel:** {name.title()}\n🔗 `{url[:80]}...`")

@app.on_message(filters.command("delchannel") & filters.user(OWNER_ID))
async def del_channel(client, message):
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/delchannel <Name>`")
    name = " ".join(message.command[1:]).strip().lower()
    if name in CHANNELS:
        del CHANNELS[name]
        save_json(CHANNELS_FILE, CHANNELS)
        await message.reply(f"🗑 Deleted channel: {name.title()}")
    else:
        await message.reply("Not found.")

@app.on_message(filters.command("addmovie") & filters.user(OWNER_ID))
async def add_movie(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply("**Usage:** `/addmovie <Name> <Stream URL>`")
    
    name, url = args[1].strip().lower(), args[2]
    MOVIES[name] = url
    save_json(MOVIES_FILE, MOVIES)
    await message.reply(f"✅ **Movie added:** {name.title()}")

@app.on_message(filters.command("delmovie") & filters.user(OWNER_ID))
async def del_movie(client, message):
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/delmovie <Name>`")
    name = " ".join(message.command[1:]).strip().lower()
    if name in MOVIES:
        del MOVIES[name]
        save_json(MOVIES_FILE, MOVIES)
        await message.reply(f"🗑 Deleted movie: {name.title()}")
    else:
        await message.reply("Not found.")

@app.on_message(filters.command("addseries") & filters.user(OWNER_ID))
async def add_series(client, message):
    args = message.text.split(None, 1)
    if len(args) < 2:
        return await message.reply("**Usage:** `/addseries <Series Name>`")
    
    name = args[1].strip().lower()
    if name in SERIES:
        return await message.reply("Series already exists. Use `/addseason` or `/addeiposde`")
    
    SERIES[name] = {"seasons": {}}
    save_json(SERIES_FILE, SERIES)
    await message.reply(f"✅ **Series created:** {name.title()}\nNow add seasons: `/addseason {name} 1`")

@app.on_message(filters.command("addseason") & filters.user(OWNER_ID))
async def add_season(client, message):
    args = message.text.split()
    if len(args) < 3:
        return await message.reply("**Usage:** `/addseason <Series> <Season Number>`")
    
    series_name = args[1].lower()
    try:
        season_num = int(args[2])
    except:
        return await message.reply("Season number must be integer")
    
    if series_name not in SERIES:
        return await message.reply("Series not found. Create with `/addseries` first.")
    
    if str(season_num) in SERIES[series_name]["seasons"]:
        return await message.reply(f"Season {season_num} already exists.")
    
    SERIES[series_name]["seasons"][str(season_num)] = {"episodes": {}}
    save_json(SERIES_FILE, SERIES)
    await message.reply(f"✅ Season {season_num} added to {series_name.title()}")

@app.on_message(filters.command("addeiposde") & filters.user(OWNER_ID))
async def add_episode(client, message):
    args = message.text.split(None, 4)
    if len(args) < 5:
        return await message.reply("**Usage:** `/addeiposde <Series> <Season> <Episode> <URL>`")
    
    series_name = args[1].lower()
    try:
        season = int(args[2])
        episode = int(args[3])
    except:
        return await message.reply("Season and episode must be numbers")
    url = args[4]
    
    if series_name not in SERIES:
        return await message.reply("Series not found.")
    
    if str(season) not in SERIES[series_name]["seasons"]:
        return await message.reply(f"Season {season} not found. Use `/addseason` first.")
    
    SERIES[series_name]["seasons"][str(season)]["episodes"][str(episode)] = url
    save_json(SERIES_FILE, SERIES)
    await message.reply(f"✅ Episode {episode} of S{season} added to {series_name.title()}")

# ================= Callback Query Handler =================
@app.on_callback_query()
async def handle_callbacks(client, callback_query: CallbackQuery):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id
    
    if data.startswith("q_"):
        quality = data.split("_")[1]
        if quality == "2k":
            quality = "2k"
        elif quality == "4k":
            quality = "4k"
        else:
            quality = quality + "p"
        
        if chat_id not in active_streams:
            await callback_query.answer("No active stream to change", show_alert=True)
            return
        
        await callback_query.answer(f"Switching to {quality}...")
        await change_stream_quality(chat_id, quality, callback_query)
    
    elif data == "stop_stream":
        try:
            await call_py.leave_call(chat_id)
            if chat_id in active_streams:
                del active_streams[chat_id]
            await callback_query.message.edit_text("⏹ **Stream stopped by user**")
            await callback_query.answer("Stopped")
        except Exception as e:
            await callback_query.answer(f"Error: {str(e)[:50]}", show_alert=True)

# ================= Boot =================
async def main():
    # Start Flask thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"🌐 Web server on port {PORT}")
    
    # Start clients
    await app.start()
    await user_app.start()
    await call_py.start()
    
    # Load data
    global CHANNELS, APPROVED_GROUPS, MOVIES, SERIES
    CHANNELS = load_json(CHANNELS_FILE, {})
    APPROVED_GROUPS = set(load_json(APPROVED_FILE, []))
    MOVIES = load_json(MOVIES_FILE, {})
    SERIES = load_json(SERIES_FILE, {})
    
    print("✅ Bot Ready - HighTech Edition")
    print(f"📺 Channels: {len(CHANNELS)} | 🎬 Movies: {len(MOVIES)} | 📀 Series: {len(SERIES)}")
    print(f"✅ Approved Groups: {len(APPROVED_GROUPS)}")
    
    # Notify owner
    try:
        await app.send_message(OWNER_ID, "🚀 **HighTech TV Bot Online**\n\nAll systems operational.\n- Auto-assistant ready\n- Quality switching active\n- Movies & Series loaded")
    except:
        pass
    
    await idle()
    
    # Cleanup
    for chat_id in active_streams.copy():
        try:
            await call_py.leave_call(chat_id)
        except:
            pass
    
    await app.stop()
    await user_app.stop()

if __name__ == "__main__":
    asyncio.run(main())

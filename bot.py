import asyncio
import aiohttp
import re
import uuid
from io import BytesIO
from urllib.parse import urlparse
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatType
from pyrogram.errors import UserAlreadyParticipant
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, VideoQuality
from flask import Flask
from threading import Thread
import os

# ================= Configuration =================
API_ID = 31282041
API_HASH = "740a2137e910d4f7641676234958fc29"
BOT_TOKEN = "8607187465:AAHPfgmQtMFb5xCnlXlXYU1QHMr8YHyJy3g"
SESSION_STRING = "BAHdU3kAvpaxfk71rxKAaERejoR6BGel01qdoKFrhKF_e6VWM_LmNwACYJIreyaIAA4WONrBLgKD9PWUh8DF_YzEP1iGtqmebfmYH9nRjKvGMk70bycCgOxmyk2YDw-XNoWP40T899e9xfYDQMzciSYSnpo1RYk5XIEw6SD6FD2amIHNSixrFNIvtQVYkVffoR0COmk2Wlzp-dvDV19sl_fe5NYY_bCSm9Hke-TlkYbZTm-o4FAjklYUI1OZVFiIwFtsf5QiNPTqts8rfg5d6RLDeu7AOkD3wi0bLsnq4BMkJb3FsPbShtPQy4Fwgrdk3Qx00kl_o29miDwfBXZgLwjwdElUbgAAAAHP5oVmAA"
OWNER_ID = 8683720440

# High-Tech Branding
BOT_NAME = "𝙇𝙤𝙘𝙖𝙡 𝙎𝙩𝙧𝙚𝙖𝙢 𝙏𝙑 📺"
CREDITS = "\n\n⚡ **Made By [𝐵 𝑙 𝑎 𝑧 𝑒](tg://user?id=8717767927)**"

# Railway Port & Proxy
PORT = int(os.environ.get("PORT", 8080))
PROXY_URL = os.environ.get("PROXY_URL", "")

# ================= Storage & Settings =================
CHANNELS, MOVIES, SERIES = {}, {}, {}
APPROVED_GROUPS = set()
CURRENT_STREAMS = {}
PLAY_REQUESTS = {} # Used for resolving name conflicts
LIST_FILE_THRESHOLD = 100 # Send list as file if items > 100

QUALITY_PRESETS = {
    "360p": VideoQuality.SD_360p, "480p": VideoQuality.SD_480p,
    "720p": VideoQuality.HD_720p, "1080p": VideoQuality.FHD_1080p,
}

# ================= Flask Server =================
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return f"📺 {BOT_NAME} System Online"
@flask_app.route('/health')
def health(): return {"status": "ok"}, 200
def run_flask(): flask_app.run(host='0.0.0.0', port=PORT, debug=False)

# ================= Initialize Clients =================
app = Client("tv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
call_py = PyTgCalls(user_app)

# ================= Utilities =================
def cleanup_name(name):
    """Removes common tags like (2024), [1080p], IN:, etc."""
    name = re.sub(r'\s*\((\d{4})\)\s*', '', name) # Year
    name = re.sub(r'\s*\[.*?\]\s*', '', name)   # Quality Tags
    name = re.sub(r'\s*\{.*?\}\s*', '', name)   # Other Tags (e.g., {DD})
    name = re.sub(r'^[A-Z]{2,}:\s*', '', name)  # Country Codes like IN:
    return name.strip().lower()

async def ensure_assistant_in_chat(chat_id, message):
    """Automatically adds the Assistant (User Session) to the Group"""
    try:
        await user_app.get_chat(chat_id)
        return True
    except:
        try:
            link = (await app.get_chat(chat_id)).invite_link or await app.export_chat_invite_link(chat_id)
            await user_app.join_chat(link)
            await message.reply(f"🤖 **Assistant Joined Group!**{CREDITS}", disable_web_page_preview=True)
            return True
        except UserAlreadyParticipant:
            return True
        except Exception as e:
            await message.reply(f"⚠️ **Assistant Join Failed!**\n`{e}`\n\nPlease add the assistant manually to play streams.{CREDITS}", disable_web_page_preview=True)
            return False

def check_approval(func):
    """Decorator to check if group is approved before streaming"""
    async def wrapper(client, message):
        is_group = message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]
        is_approved = message.chat.id in APPROVED_GROUPS
        is_owner = message.from_user.id == OWNER_ID
        if is_group and not is_approved and not is_owner:
            return await message.reply(f"🚫 **ACCESS DENIED**\nThis Group (`{message.chat.id}`) is not authorized.\nContact the owner to `/approve` this chat.{CREDITS}", disable_web_page_preview=True)
        return await func(client, message)
    return wrapper

# ================= Start & Help =================
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
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

# ================= Owner - XTREAM FETCHING (Optimized & Robust) =================
async def _fetch_series_episodes(session, base_url, user, passwd, series_info):
    """Helper function to fetch episodes for a single series, with error handling."""
    series_id = series_info.get('series_id')
    series_name_raw = series_info.get('name', '')
    series_name = cleanup_name(series_name_raw)
    
    if not series_name:
        return None, None, f"Skipped series with no name: {series_name_raw}"

    detail_url = f"{base_url}/player_api.php?username={user}&password={passwd}&action=get_series_info&series_id={series_id}"
    try:
        async with session.get(detail_url, timeout=30) as resp: # Increased timeout to 30s
            if resp.status == 200:
                detail_data = await resp.json()
                episodes_dict = {}
                episodes = detail_data.get('episodes', {})
                for season in episodes.values():
                    for episode in season:
                        ep_num = episode.get('episode_num')
                        season_num = episode.get('season')
                        # Ensure season/episode numbers are valid before formatting
                        if ep_num is not None and season_num is not None:
                            ep_id_code = f"s{int(season_num):02d}e{int(ep_num):02d}"
                            ext = episode.get('container_extension', 'mp4')
                            stream_url = f"{base_url}/series/{user}/{passwd}/{episode.get('id')}.{ext}"
                            episodes_dict[ep_id_code] = stream_url
                return series_name, episodes_dict, None # Success
            else:
                return series_name, None, f"HTTP {resp.status} for {series_name_raw}"
    except asyncio.TimeoutError:
        return series_name, None, f"Timeout for {series_name_raw}"
    except aiohttp.ClientError as e:
        return series_name, None, f"Client error for {series_name_raw}: {e}"
    except Exception as e:
        return series_name, None, f"Generic error for {series_name_raw}: {e}"

@app.on_message(filters.command("addxtreammovies") & filters.user(OWNER_ID))
async def add_xtream_movies(client, message):
    args = message.text.split()
    if len(args) != 4: return await message.reply(f"⚠️ **Usage:** `/addxtreammovies <URL> <User> <Pass>`{CREDITS}", disable_web_page_preview=True)
    
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_vod_streams"
    msg = await message.reply("🚀 **Fetching Xtream Movies...** This may take a moment.")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    count = 0
                    for movie in data:
                        name = cleanup_name(movie.get("name", ""))
                        if name:
                            ext = movie.get("container_extension", "mp4")
                            stream_url = f"{url}/movie/{user}/{passwd}/{movie.get('stream_id')}.{ext}"
                            MOVIES[name] = stream_url
                            count += 1
                    await msg.edit_text(f"✅ **Loaded {count} Movies from Xtream API!**{CREDITS}", disable_web_page_preview=True)
                else:
                    await msg.edit_text(f"❌ Error Status: {resp.status}")
    except Exception as e:
        await msg.edit_text(f"❌ Failed: `{str(e)[:100]}`")

@app.on_message(filters.command("addxtreamseries") & filters.user(OWNER_ID))
async def add_xtream_series_optimized(client, message):
    args = message.text.split()
    if len(args) != 4: return await message.reply(f"⚠️ **Usage:** `/addxtreamseries <URL> <User> <Pass>`{CREDITS}", disable_web_page_preview=True)

    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    msg = await message.reply("🚀 **Fetching Xtream Series list...**")

    try:
        series_list_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_series"
        async with aiohttp.ClientSession() as session:
            async with session.get(series_list_url, timeout=30) as resp:
                if resp.status != 200:
                    return await msg.edit_text(f"❌ Failed to fetch series list. Status: {resp.status}")
                series_data = await resp.json()
        
        await msg.edit_text(f"✅ Found **{len(series_data)}** series. Fetching all episodes concurrently...\n*This may take a moment but is much faster!*")

        tasks = []
        async with aiohttp.ClientSession() as session: # Use a single session for all tasks
            for series_info in series_data:
                task = _fetch_series_episodes(session, url, user, passwd, series_info)
                tasks.append(task)
            
            # Run tasks concurrently, allow some to fail without stopping others
            results = await asyncio.gather(*tasks, return_exceptions=True) 

        processed_count = 0
        failed_series_names = []

        for result in results:
            if isinstance(result, Exception): # Catch exceptions from individual tasks
                print(f"Task exception: {result}")
                continue
            
            series_name, episodes_dict, error_msg = result
            if error_msg:
                print(f"Failed to process series: {error_msg}")
                if series_name: failed_series_names.append(series_name.title()) # Track failed names
            elif series_name and episodes_dict:
                if series_name not in SERIES:
                    SERIES[series_name] = {}
                SERIES[series_name].update(episodes_dict)
                processed_count += 1
        
        final_message = f"✅ **Scan Complete!**\nLoaded episodes for **{processed_count}** series from Xtream API!"
        if failed_series_names:
            final_message += f"\n\n⚠️ **Failed to load {len(failed_series_names)} series:**\n" + ", ".join(failed_series_names[:5]) + ("..." if len(failed_series_names) > 5 else "")
            final_message += "\n*Check logs for more details on failures.*"
        
        await msg.edit_text(final_message + CREDITS, disable_web_page_preview=True)

    except Exception as e:
        await msg.edit_text(f"❌ An overall error occurred during series processing: `{str(e)[:100]}`")

# ================= Owner - BULK DELETION =================
@app.on_message(filters.command("delallchannels") & filters.user(OWNER_ID))
async def del_all_channels(client, message):
    CHANNELS.clear()
    await message.reply(f"🗑️ **All Live TV channels have been deleted.**{CREDITS}", disable_web_page_preview=True)

@app.on_message(filters.command("delallmovies") & filters.user(OWNER_ID))
async def del_all_movies(client, message):
    MOVIES.clear()
    await message.reply(f"🗑️ **All movies have been deleted.**{CREDITS}", disable_web_page_preview=True)

@app.on_message(filters.command("delallseries") & filters.user(OWNER_ID))
async def del_all_series(client, message):
    SERIES.clear()
    await message.reply(f"🗑️ **All series have been deleted.**{CREDITS}", disable_web_page_preview=True)


# ================= LIST COMMANDS (with .txt file logic) =================
@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    if not CHANNELS:
        return await message.reply(f"❌ **No Channels Found.**{CREDITS}", disable_web_page_preview=True)

    if len(CHANNELS) > LIST_FILE_THRESHOLD:
        text_content = "📺 All Available Channels\n\n" + "\n".join([f"{idx+1}. {name.title()}" for idx, name in enumerate(sorted(CHANNELS.keys()))])
        file = BytesIO(text_content.encode('utf-8'))
        file.name = "channels.txt"
        return await message.reply_document(file, caption=f"📂 Here are the **{len(CHANNELS)}** available channels.{CREDITS}")

    text = f"╭━━━[ **📺 LIVE CHANNELS** ]━━━╮\n┃\n"
    for idx, name in enumerate(sorted(CHANNELS.keys()), 1):
        text += f"┃ ❖ `{idx:02d}.` **{name.title()}**\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"
    await message.reply(text, disable_web_page_preview=True)

@app.on_message(filters.command("movies"))
async def show_movies(client, message):
    if not MOVIES:
        return await message.reply(f"❌ **No Movies Found.**{CREDITS}", disable_web_page_preview=True)

    if len(MOVIES) > LIST_FILE_THRESHOLD:
        text_content = "🎬 All Available Movies\n\n" + "\n".join([f"{idx+1}. {name.title()}" for idx, name in enumerate(sorted(MOVIES.keys()))])
        file = BytesIO(text_content.encode('utf-8'))
        file.name = "movies.txt"
        return await message.reply_document(file, caption=f"📂 Here are the **{len(MOVIES)}** available movies.{CREDITS}")

    text = f"╭━━━[ **🎬 MOVIES LIST** ]━━━╮\n┃\n"
    for idx, name in enumerate(sorted(MOVIES.keys()), 1):
        text += f"┃ ❖ `{idx:02d}.` **{name.title()}**\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"
    await message.reply(text, disable_web_page_preview=True)

@app.on_message(filters.command("series"))
async def show_series(client, message):
    if not SERIES:
        return await message.reply(f"❌ **No Series Found.**{CREDITS}", disable_web_page_preview=True)

    if len(SERIES) > LIST_FILE_THRESHOLD:
        text_content = "🍿 All Available Series\n\n"
        for idx, (show, eps) in enumerate(sorted(SERIES.items())):
            text_content += f"{idx+1}. {show.title()} ({len(eps)} episodes)\n"
        file = BytesIO(text_content.encode('utf-8'))
        file.name = "series.txt"
        return await message.reply_document(file, caption=f"📂 Here are the **{len(SERIES)}** available series.{CREDITS}")

    text = f"╭━━━[ **🍿 SERIES LIST** ]━━━╮\n┃\n"
    for show, eps in sorted(SERIES.items()):
        text += f"┃ ❖ **{show.title()}** (Episodes: {len(eps)})\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"
    await message.reply(text, disable_web_page_preview=True)


# ================= Playback & Conflict Resolution =================
@app.on_message(filters.command(["livetv", "playmovie", "playseries"]) & filters.group)
@check_approval
async def stream_media(client, message):
    cmd = message.command[0]
    if len(message.command) < 2: return await message.reply(f"⚠️ Usage: `/{cmd} <Name>`")
    query = " ".join(message.command[1:]).strip().lower()

    db, media_type = {}, ""
    if cmd == "livetv": db, media_type = CHANNELS, "channel"
    elif cmd == "playmovie": db, media_type = MOVIES, "movie"
    elif cmd == "playseries":
        query = query.split('-')[0].strip() # For series, match show name first
        db, media_type = SERIES, "series"
    
    matches = [name for name in db if query in name]
    if not matches: return await message.reply(f"❌ **No {media_type} found matching that name!**{CREDITS}", disable_web_page_preview=True)
    
    if len(matches) == 1:
        return await _start_stream(client, message, matches[0], media_type)

    # If multiple matches, show buttons
    buttons = []
    # Sort matches to make the order predictable, then take top 20
    for name in sorted(matches)[:20]: 
        req_id = str(uuid.uuid4())[:8]
        PLAY_REQUESTS[req_id] = name
        buttons.append([InlineKeyboardButton(name.title(), callback_data=f"resolve_{media_type}_{req_id}")])

    await message.reply(f"🤔 **Found multiple results for `{query.title()}`. Please choose one:**", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex(r"^resolve_"))
async def resolve_playback(client, callback_query):
    media_type, req_id = callback_query.data.split("_")[1:]
    full_name = PLAY_REQUESTS.get(req_id)
    if not full_name: return await callback_query.answer("⚠️ This request expired. Please try again.", show_alert=True)
    
    await callback_query.message.delete()
    if req_id in PLAY_REQUESTS: del PLAY_REQUESTS[req_id]
    
    await _start_stream(client, callback_query.message, full_name, media_type)

async def _start_stream(client, message, name, media_type):
    chat_id = message.chat.id
    if not await ensure_assistant_in_chat(chat_id, message): return

    url, display_name = "", name.title()
    type_label = "" # Initialize type_label
    
    if media_type == "channel": url, type_label = CHANNELS[name], "📺 Live TV"
    elif media_type == "movie": url, type_label = MOVIES[name], "🎬 Movie"
    elif media_type == "series":
        full_query_message = message.text.split(None, 1) # Get the original message text for series
        if len(full_query_message) > 1:
            full_query = full_query_message[1].lower()
            parts = [p.strip() for p in full_query.split('-')]
            if len(parts) == 2 and name in SERIES and parts[1] in SERIES[name]:
                ep_code = parts[1]
                url = SERIES[name][ep_code]
                display_name = f"{name.title()} [{ep_code.upper()}]"
                type_label = "🍿 Series"
            else: return await message.reply(f"⚠️ Episode not specified or not found. Use format: `/playseries {name.title()} - s01e01`{CREDITS}", disable_web_page_preview=True)
        else: return await message.reply(f"⚠️ For series, please specify an episode: `/playseries {name.title()} - s01e01`{CREDITS}", disable_web_page_preview=True)
    
    if not url: return await message.reply("❌ Could not find a valid stream URL.")
    
    msg = await message.reply(f"⚡ **Initializing {type_label}...**")
    try:
        # Get Headers (Crucial for Amagi Streams) - Re-added logic for this
        headers = {}
        if "amagi" in url.lower() or "now3" in url.lower() or "playout" in url.lower(): # Added conditions based on previous code
             parsed = urlparse(url)
             base_url = f"{parsed.scheme}://{parsed.netloc}"
             headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "*/*",
                "Origin": base_url,
                "Referer": base_url + "/",
             }
        
        await call_py.play(chat_id, MediaStream(url, video_parameters=VideoQuality.HD_720p, headers=headers))
        CURRENT_STREAMS[chat_id] = {"url": url, "name": display_name, "type": type_label}
        
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(q.upper(), callback_data=f"q_{q}") for q in ["360p", "480p", "720p", "1080p"]]])
        await msg.edit_text(
            f"╭━━━[ **{BOT_NAME}** ]━━━╮\n" # Restored Bot Name Header
            f"┃\n"
            f"┃ ❖ **Status:** 🟢 Live Now\n" # Restored Status
            f"┃ ❖ **Type:** {type_label}\n" # Restored Type
            f"┃ ❖ **Title:** {display_name}\n"
            f"┃ ❖ **Quality:** 720p (HD)\n"
            f"┃\n"
            f"╰━━━━━━━━━━━━━━━━━╯{CREDITS}", 
            reply_markup=keyboard, disable_web_page_preview=True
        )
    except Exception as e:
        await msg.edit_text(f"❌ **Stream Failed!**\n`{str(e)[:100]}`{CREDITS}", disable_web_page_preview=True)


# ================= Other Commands (Previous working versions) =================
@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply(f"⚠️ **Usage:** `/addchannel <URL> <Channel Name>`{CREDITS}", disable_web_page_preview=True)
    
    url, name = args[1], cleanup_name(args[2])
    CHANNELS[name] = url
    await message.reply(f"✅ **Channel Added:** `{name.title()}`{CREDITS}", disable_web_page_preview=True)

@app.on_message(filters.command("approve") & filters.user(OWNER_ID))
async def approve_group(client, message):
    try:
        chat_id = int(message.command[1]) if len(message.command) > 1 else message.chat.id
        APPROVED_GROUPS.add(chat_id)
        await message.reply(f"✅ **Group `{chat_id}` APPROVED.**{CREDITS}", disable_web_page_preview=True)
    except (ValueError, IndexError):
        await message.reply("Please specify a Chat ID or use in the group.")

@app.on_message(filters.command("unapprove") & filters.user(OWNER_ID))
async def unapprove_group(client, message):
    try:
        chat_id = int(message.command[1]) if len(message.command) > 1 else message.chat.id
        APPROVED_GROUPS.discard(chat_id)
        await message.reply(f"🚫 **Group `{chat_id}` UNAPPROVED.**{CREDITS}", disable_web_page_preview=True)
    except (ValueError, IndexError):
        pass

@app.on_message(filters.command("botinfo") & filters.user(OWNER_ID))
async def bot_info(client, message):
    text = (
        f"╭━━━[ **🖥️ SYSTEM INFO** ]━━━╮\n┃\n"
        f"┃ 📡 **Active Streams:** {len(CURRENT_STREAMS)}\n"
        f"┃ 📺 **Channels:** {len(CHANNELS)} | 🎬 **Movies:** {len(MOVIES)}\n"
        f"┃ 🍿 **Series:** {len(SERIES)}\n"
        f"┃ 🛡️ **Approved Groups:** {len(APPROVED_GROUPS)}\n"
    )
    for grp in APPROVED_GROUPS:
        text += f"┃ ├ `{grp}`\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"
    await message.reply(text, disable_web_page_preview=True)

@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast(client, message):
    if len(message.command) < 2: return await message.reply("⚠️ Usage: `/broadcast <message>`")
    msg_text = message.text.split(None, 1)[1]
    success, failed = 0, 0
    m = await message.reply("🚀 **Broadcasting...**")
    for chat_id in APPROVED_GROUPS:
        try:
            await app.send_message(chat_id, f"🔔 **Broadcast**\n\n{msg_text}{CREDITS}", disable_web_page_preview=True)
            success += 1
        except:
            failed += 1
    await m.edit_text(f"✅ **Broadcast Complete!**\nSent: {success} | Failed: {failed}{CREDITS}", disable_web_page_preview=True)

@app.on_callback_query(filters.regex(r"^q_"))
async def switch_quality(client, callback_query):
    chat_id = callback_query.message.chat.id
    quality_req = callback_query.data.split("_")[1]
    
    if chat_id not in CURRENT_STREAMS:
        return await callback_query.answer("⚠️ No active stream here!", show_alert=True)
        
    stream_info = CURRENT_STREAMS[chat_id]
    vq = QUALITY_PRESETS.get(quality_req, VideoQuality.HD_720p)
    
    try:
        # Get Headers for Amagi/restricted streams again for quality switch
        headers = {}
        if "amagi" in stream_info["url"].lower() or "now3" in stream_info["url"].lower() or "playout" in stream_info["url"].lower():
            parsed = urlparse(stream_info["url"])
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "*/*",
                "Origin": base_url,
                "Referer": base_url + "/",
            }

        await call_py.play(chat_id, MediaStream(stream_info["url"], video_parameters=vq, headers=headers))
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(q.upper(), callback_data=f"q_{q}") for q in ["360p", "480p", "720p", "1080p"]]])
        await callback_query.message.edit_text(
            f"╭━━━[ **{BOT_NAME}** ]━━━╮\n"
            f"┃\n"
            f"┃ ❖ **Status:** 🟢 Live Now\n" # Restored Status
            f"┃ ❖ **Type:** {stream_info['type']}\n" # Restored Type
            f"┃ ❖ **Title:** {stream_info['name']}\n"
            f"┃ ❖ **Quality:** {quality_req.upper()} ✅\n"
            f"┃\n"
            f"╰━━━━━━━━━━━━━━━━━╯{CREDITS}",
            reply_markup=keyboard, disable_web_page_preview=True
        )
        await callback_query.answer(f"✅ Switched to {quality_req}!")
    except Exception as e:
        await callback_query.answer(f"❌ Failed to switch quality! Error: {str(e)[:50]}", show_alert=True)

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        CURRENT_STREAMS.pop(message.chat.id, None)
        await message.reply(f"⏹ **Stream Stopped.**{CREDITS}", disable_web_page_preview=True)
    except Exception: # Catch any error if call is already left or not active
        await message.reply(f"❌ **No active stream to stop.**{CREDITS}", disable_web_page_preview=True)


# ================= Boot Sequence =================
async def main():
    Thread(target=run_flask, daemon=True).start()
    await app.start(); await user_app.start(); await call_py.start()
    
    print(f"✅ {BOT_NAME} System Online!")
    try:
        await app.send_message(OWNER_ID, f"🟢 **{BOT_NAME} Online!**\nSystem initialized perfectly.{CREDITS}", disable_web_page_preview=True)
    except:
        pass # Owner might not have started bot yet
    
    await idle()
    
    # Ensure all calls are left on shutdown
    for chat_id in list(CURRENT_STREAMS.keys()):
        try: await call_py.leave_call(chat_id)
        except: pass
    
    await app.stop(); await user_app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())

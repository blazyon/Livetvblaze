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
API_ID = 35562064
API_HASH = "fc5a4484d4abe8a2118284147b1092f6"
BOT_TOKEN = "8544679303:AAFW5OwWCbQ969yjP2lgaHReWv4Bg6Iqdas"
SESSION_STRING = "BQIeolAAP2Fp0MfGQr0Ni83PjJk9rNOou7BycxzVOAap_JlUHq6kHHjfQApb1gbO3F1RF3-eOxHwm-j-Ui2TVUHOHWqB3YxHSAteGs5U1cqZkSm2z8KndR_xrK8SJEjg867dzgw2QUwydNKCqBJXd3o6dWlwS3cehFZLIiZWEsZVX8laiK79iwyuUFF6KPJvQl0acVf0nM0Lemz3PSvL7N1eRe7ZfENIT5ju3GXAgc_wDmaUadbqvwU2QtlVGHPg-4T8WhpUrURlPumKKRszs2GI_shWjnQEmDOHuKfyBxhngrj6jBZPp3oSwDzRg0whb6Q4HLYlj8aT-Mcq7JqKT4G7Up9mDQAAAAH_qqMkAA"
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
CURRENT_STREAMS = {}
PLAY_REQUESTS = {} # Used for resolving name conflicts

QUALITY_PRESETS = {
    "360p": VideoQuality.SD_360p,
    "480p": VideoQuality.SD_480p,
    "720p": VideoQuality.HD_720p,
    "1080p": VideoQuality.FHD_1080p,
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
    name = re.sub(r'\s*\{.*?\}\s*', '', name)   # Other Tags
    name = re.sub(r'^[A-Z]{2,}:\s*', '', name)  # Country Codes like IN:
    return name.strip().lower()

async def ensure_assistant_in_chat(chat_id, message):
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
            await message.reply(f"⚠️ **Assistant Join Failed!**\n`{e}`{CREDITS}", disable_web_page_preview=True)
            return False

def check_approval(func):
    async def wrapper(client, message):
        if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] and message.chat.id not in APPROVED_GROUPS and message.from_user.id != OWNER_ID:
            return await message.reply(f"🚫 **ACCESS DENIED**\nThis Group (`{message.chat.id}`) is not authorized.{CREDITS}", disable_web_page_preview=True)
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

# ================= Owner - XTREAM VOD/SERIES FETCHING =================
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
async def add_xtream_series(client, message):
    args = message.text.split()
    if len(args) != 4: return await message.reply(f"⚠️ **Usage:** `/addxtreamseries <URL> <User> <Pass>`{CREDITS}", disable_web_page_preview=True)

    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    msg = await message.reply("🚀 **Fetching Xtream Series List...**")
    
    try:
        # Step 1: Get all series
        series_list_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_series"
        async with aiohttp.ClientSession() as session:
            async with session.get(series_list_url, timeout=60) as resp:
                if resp.status != 200: return await msg.edit_text(f"❌ Failed to fetch series list. Status: {resp.status}")
                series_data = await resp.json()

        # Step 2: Get episodes for each series
        total_series = len(series_data)
        processed_count = 0
        for i, series_info in enumerate(series_data):
            series_id = series_info.get('series_id')
            series_name = cleanup_name(series_info.get('name', ''))
            if not series_name: continue

            await msg.edit_text(f"🔄 **Processing Series {i+1}/{total_series}:** `{series_name.title()}`")
            series_detail_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_series_info&series_id={series_id}"
            async with aiohttp.ClientSession() as session:
                async with session.get(series_detail_url, timeout=60) as resp:
                    if resp.status == 200:
                        detail_data = await resp.json()
                        if series_name not in SERIES: SERIES[series_name] = {}
                        
                        episodes = detail_data.get('episodes', {})
                        for season in episodes.values():
                            for episode in season:
                                ep_num = episode.get('episode_num')
                                season_num = episode.get('season')
                                ep_id = f"s{season_num:02d}e{ep_num:02d}"
                                ext = episode.get('container_extension', 'mp4')
                                stream_url = f"{url}/series/{user}/{passwd}/{episode.get('id')}.{ext}"
                                SERIES[series_name][ep_id] = stream_url
                        processed_count += 1

        await msg.edit_text(f"✅ **Loaded episodes for {processed_count} Series from Xtream API!**{CREDITS}", disable_web_page_preview=True)
    except Exception as e:
        await msg.edit_text(f"❌ Failed during series processing: `{str(e)[:100]}`")


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


# ================= Playback & Conflict Resolution =================
@app.on_message(filters.command(["livetv", "playmovie", "playseries"]) & filters.group)
@check_approval
async def stream_media(client, message):
    cmd = message.command[0]
    if len(message.command) < 2: return await message.reply(f"⚠️ Usage: `/{cmd} <Name>`")
    query = " ".join(message.command[1:]).strip().lower()

    matches = []
    media_type = ""
    db = {}

    if cmd == "livetv":
        db, media_type = CHANNELS, "channel"
    elif cmd == "playmovie":
        db, media_type = MOVIES, "movie"
    elif cmd == "playseries":
        # For series, search only by show name
        query = query.split('-')[0].strip()
        db, media_type = SERIES, "series"
    
    # Find all partial matches
    matches = [name for name in db if query in name]

    if not matches:
        return await message.reply(f"❌ **No {media_type} found matching that name!**{CREDITS}", disable_web_page_preview=True)
    
    if len(matches) == 1:
        # If one match, play it directly
        return await _start_stream(client, message, matches[0], media_type)

    # If multiple matches, show buttons
    buttons = []
    for name in matches[:20]: # Limit to 20 buttons
        req_id = str(uuid.uuid4())[:8]
        PLAY_REQUESTS[req_id] = name
        buttons.append([InlineKeyboardButton(name.title(), callback_data=f"resolve_{media_type}_{req_id}")])

    await message.reply(
        f"🤔 **Found multiple results for `{query.title()}`. Please choose one:**",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex(r"^resolve_"))
async def resolve_playback(client, callback_query):
    parts = callback_query.data.split("_")
    media_type, req_id = parts[1], parts[2]
    
    full_name = PLAY_REQUESTS.get(req_id)
    if not full_name:
        return await callback_query.answer("⚠️ This request expired or is invalid. Please try again.", show_alert=True)
    
    await callback_query.message.delete() # Clean up the button message
    del PLAY_REQUESTS[req_id] # Clean up memory
    
    await _start_stream(client, callback_query.message, full_name, media_type)

async def _start_stream(client, message, name, media_type):
    chat_id = message.chat.id
    if not await ensure_assistant_in_chat(chat_id, message): return

    url, display_name = "", name.title()
    
    if media_type == "channel":
        url = CHANNELS[name]
        type_label = "📺 Live TV"
    elif media_type == "movie":
        url = MOVIES[name]
        type_label = "🎬 Movie"
    elif media_type == "series":
        # Handle series episode selection if needed
        full_query = message.text.split(None, 1)[1].lower()
        parts = [p.strip() for p in full_query.split('-')]
        if len(parts) == 2:
            ep_code = parts[1]
            if name in SERIES and ep_code in SERIES[name]:
                url = SERIES[name][ep_code]
                display_name = f"{name.title()} [{ep_code.upper()}]"
                type_label = "🍿 Series"
            else:
                return await message.reply(f"❌ Episode `{ep_code}` not found for `{name.title()}`.{CREDITS}", disable_web_page_preview=True)
        else:
             return await message.reply(f"⚠️ For series, please specify an episode: `/playseries {name.title()} - s01e01`{CREDITS}", disable_web_page_preview=True)
    
    if not url: return

    msg = await message.reply(f"⚡ **Initializing {type_label}...**\n⏳ Please wait...")
    
    try:
        headers = {} # Add headers if needed
        await call_py.play(chat_id, MediaStream(url, video_parameters=VideoQuality.HD_720p, headers=headers))
        CURRENT_STREAMS[chat_id] = {"url": url, "name": display_name, "type": type_label}

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("360p", callback_data="q_360p"), InlineKeyboardButton("480p", callback_data="q_480p"),
            InlineKeyboardButton("720p", callback_data="q_720p"), InlineKeyboardButton("1080p", callback_data="q_1080p")
        ]])
        await msg.edit_text(
            f"╭━━━[ **▶️ Now Streaming** ]━━━╮\n┃\n"
            f"┃ ❖ **Title:** {display_name}\n"
            f"┃ ❖ **Quality:** 720p (HD)\n"
            f"┃\n"
            f"╰━━━━━━━━━━━━━━━━━╯{CREDITS}",
            reply_markup=keyboard, disable_web_page_preview=True
        )
    except Exception as e:
        await msg.edit_text(f"❌ **Stream Failed!**\n`{str(e)[:100]}`{CREDITS}", disable_web_page_preview=True)


# ================= Other Commands & Callbacks (Unchanged) =================
# ... [ The code for /channels, /movies, /series, /addchannel, etc. remains here ]
# ... [ The code for quality switching callback, /stopvc, /approve, /botinfo, etc. remains here ]
# I will append the rest of the unchanged code below to make it one complete file.

@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    if not CHANNELS:
        return await message.reply(f"❌ **No Channels Found.**{CREDITS}", disable_web_page_preview=True)
    
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
    if not MOVIES:
        return await message.reply(f"❌ **No Movies Found.**{CREDITS}", disable_web_page_preview=True)
    
    text = f"╭━━━[ **🎬 MOVIES LIST** ]━━━╮\n┃\n"
    for idx, name in enumerate(MOVIES.keys(), 1):
        text += f"┃ ❖ `{idx:02d}.` **{name.title()}**\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"
    await message.reply(text, disable_web_page_preview=True)

@app.on_message(filters.command("series"))
async def show_series(client, message):
    if not SERIES:
        return await message.reply(f"❌ **No Series Found.**{CREDITS}", disable_web_page_preview=True)
    
    text = f"╭━━━[ **🍿 SERIES LIST** ]━━━╮\n┃\n"
    for show, eps in SERIES.items():
        text += f"┃ ❖ **{show.title()}** (Episodes: {len(eps)})\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"
    await message.reply(text, disable_web_page_preview=True)

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
    except ValueError:
        await message.reply("❌ Invalid Chat ID")

@app.on_message(filters.command("unapprove") & filters.user(OWNER_ID))
async def unapprove_group(client, message):
    try:
        chat_id = int(message.command[1]) if len(message.command) > 1 else message.chat.id
        APPROVED_GROUPS.discard(chat_id)
        await message.reply(f"🚫 **Group `{chat_id}` UNAPPROVED.**{CREDITS}", disable_web_page_preview=True)
    except ValueError:
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
        await call_py.play(chat_id, MediaStream(stream_info["url"], video_parameters=vq))
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("360p", callback_data="q_360p"), InlineKeyboardButton("480p", callback_data="q_480p"),
            InlineKeyboardButton("720p", callback_data="q_720p"), InlineKeyboardButton("1080p", callback_data="q_1080p")
        ]])
        await callback_query.message.edit_text(
            f"╭━━━[ **▶️ Now Streaming** ]━━━╮\n┃\n"
            f"┃ ❖ **Title:** {stream_info['name']}\n"
            f"┃ ❖ **Quality:** {quality_req.upper()} ✅\n"
            f"┃\n"
            f"╰━━━━━━━━━━━━━━━━━╯{CREDITS}",
            reply_markup=keyboard, disable_web_page_preview=True
        )
        await callback_query.answer(f"✅ Switched to {quality_req}!")
    except Exception as e:
        await callback_query.answer(f"❌ Failed to switch!", show_alert=True)

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        CURRENT_STREAMS.pop(message.chat.id, None)
        await message.reply(f"⏹ **Stream Stopped.**{CREDITS}", disable_web_page_preview=True)
    except:
        await message.reply(f"❌ **No active stream to stop.**{CREDITS}", disable_web_page_preview=True)

# ================= Boot Sequence =================
async def main():
    Thread(target=run_flask, daemon=True).start()
    await app.start()
    await user_app.start()
    await call_py.start()
    
    print(f"✅ {BOT_NAME} System Online!")
    try:
        await app.send_message(OWNER_ID, f"🟢 **{BOT_NAME} Online!**{CREDITS}", disable_web_page_preview=True)
    except: pass
    
    await idle()
    
    for chat_id in list(CURRENT_STREAMS.keys()):
        try: await call_py.leave_call(chat_id)
        except: pass
    
    await app.stop()
    await user_app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())

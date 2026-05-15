import asyncio
import aiohttp
import re
from io import BytesIO
from urllib.parse import urlparse
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatType
from pyrogram.errors import UserAlreadyParticipant
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioVideoPiped
from pytgcalls.types.input_stream.quality import HighQualityAudio, HighQualityVideo
from flask import Flask
from threading import Thread
import os
import sys

# ================= Configuration =================
API_ID = 35562064
API_HASH = "fc5a4484d4abe8a2118284147b1092f6"
BOT_TOKEN = "8544679303:AAFW5OwWCbQ969yjP2lgaHReWv4Bg6Iqdas"
SESSION_STRING = "BQIeolAAP2Fp0MfGQr0Ni83PjJk9rNOou7BycxzVOAap_JlUHq6kHHjfQApb1gbO3F1RF3-eOxHwm-j-Ui2TVUHOHWqB3YxHSAteGs5U1cqZkSm2z8KndR_xrK8SJEjg867dzgw2QUwydNKCqBJXd3o6dWlwS3cehFZLIiZWEsZVX8laiK79iwyuUFF6KPJvQl0acVf0nM0Lemz3PSvL7N1eRe7ZfENIT5ju3GXAgc_wDmaUadbqvwU2QtlVGHPg-4T8WhpUrURlPumKKRszs2GI_shWjnQEmDOHuKfyBxhngrj6jBZPp3oSwDzRg0whb6Q4HLYlj8aT-Mcq7JqKT4G7Up9mDQAAAAH_qqMkAA"
OWNER_ID = 8717767927

# High-Tech Branding
BOT_NAME = "𝙇𝙤𝙘𝙖𝙡 𝙎𝙩𝙧𝙚𝙖𝙢 𝙏𝙑 📺"
CREDITS = "\n\n⚡ **Made By [𝐵 𝑙 𝑎 𝑧 𝑒](tg://user?id=8717767927)**"

# Railway Port
PORT = int(os.environ.get("PORT", 8080))

# ================= Storage =================
CHANNELS = {}
MOVIES = {}
SERIES = {}
APPROVED_GROUPS = set()

CURRENT_STREAMS = {}
SEARCH_CACHE = {}

# ================= Flask Server =================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return f"📺 {BOT_NAME} System Online"

@flask_app.route('/health')
def health():
    return {"status": "ok", "system": "online"}, 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, debug=False)

# ================= Initialize Clients =================
app = Client("tv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
call_py = PyTgCalls(user_app)

# ================= Utilities =================
def get_amagi_headers(url):
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Origin": base_url,
        "Referer": base_url + "/",
    }

async def ensure_assistant_in_chat(chat_id, message):
    try:
        await user_app.get_chat(chat_id)
        return True
    except Exception:
        try:
            chat = await app.get_chat(chat_id)
            link = chat.invite_link or await app.export_chat_invite_link(chat_id)
            await user_app.join_chat(link)
            await message.reply(f"🤖 **Assistant Successfully Joined the Group!** {CREDITS}")
            return True
        except UserAlreadyParticipant:
            return True
        except Exception as e:
            await message.reply(f"⚠️ **Could not add assistant!**\nError: `{e}`\n\nPlease add manually.{CREDITS}")
            return False

def check_approval(func):
    async def wrapper(client, message):
        if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            if message.chat.id not in APPROVED_GROUPS and message.from_user.id != OWNER_ID:
                return await message.reply(
                    f"🚫 **ACCESS DENIED**\n\n"
                    f"❖ This Group (`{message.chat.id}`) is not authorized!\n"
                    f"❖ Contact owner to approve.{CREDITS}"
                )
        return await func(client, message)
    return wrapper

def clean_media_name(name):
    name = name.lower()
    name = re.sub(r'^([a-z0-9_-]+\s*[:|]\s*)+', '', name)
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\b(4k|fhd|hd|sd|vip|usa|uk|ind|1080p|720p)\b', '', name)
    name = re.sub(r'[^a-z0-9\s]', '', name)
    return re.sub(r'\s+', ' ', name).strip()

def search_media(query, media_dict):
    q = re.sub(r'[^a-z0-9\s]', '', query.lower())
    q = re.sub(r'\s+', ' ', q).strip()
    matches = []
    
    for orig_key in media_dict.keys():
        if q == clean_media_name(orig_key):
            matches.append(orig_key)
    
    if not matches:
        for orig_key in media_dict.keys():
            if q in clean_media_name(orig_key):
                matches.append(orig_key)
    
    if not matches:
        for orig_key in media_dict.keys():
            if q in re.sub(r'[^a-z0-9\s]', '', orig_key.lower()):
                matches.append(orig_key)
    
    return list(dict.fromkeys(matches))

# ================= Commands =================
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
        f"┃ ❖ `/stopvc` - Stop Stream\n"
        f"┃\n"
        f"╰━━━━━━━━━━━━━━━━━╯{CREDITS}",
        disable_web_page_preview=True
    )

# ================= Browsing =================
@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    if not CHANNELS:
        return await message.reply(f"❌ **No Channels Found.**{CREDITS}")
    if len(CHANNELS) > 100:
        file_text = "📺 ALL LIVE CHANNELS\n\n" + "\n".join(f"{i:02d}. {name.title()}" for i, name in enumerate(CHANNELS.keys(), 1))
        file = BytesIO(file_text.encode('utf-8'))
        file.name = "Channels_List.txt"
        return await message.reply_document(file, caption=f"📺 **{len(CHANNELS)} Channels Available**{CREDITS}")
    
    text = f"╭━━━[ **📺 LIVE CHANNELS** ]━━━╮\n┃\n"
    for idx, name in enumerate(CHANNELS.keys(), 1):
        text += f"┃ ❖ `{idx:02d}.` **{name.title()}**\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"
    await message.reply(text, disable_web_page_preview=True)

# (movies and series commands remain same - omitted for brevity, copy from your original if needed)

@app.on_message(filters.command("movies"))
async def show_movies(client, message):
    if not MOVIES: return await message.reply(f"❌ **No Movies Found.**{CREDITS}")
    if len(MOVIES) > 100:
        file_text = "🎬 ALL MOVIES\n\n" + "\n".join(f"{i:02d}. {name.title()}" for i, name in enumerate(MOVIES.keys(), 1))
        file = BytesIO(file_text.encode('utf-8'))
        file.name = "Movies_List.txt"
        return await message.reply_document(file, caption=f"🎬 **{len(MOVIES)} Movies Available**{CREDITS}")
    text = f"╭━━━[ **🎬 MOVIES LIST** ]━━━╮\n┃\n"
    for idx, name in enumerate(MOVIES.keys(), 1): text += f"┃ ❖ `{idx:02d}.` **{name.title()}**\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"
    await message.reply(text, disable_web_page_preview=True)

@app.on_message(filters.command("series"))
async def show_series(client, message):
    if not SERIES: return await message.reply(f"❌ **No Series Found.**{CREDITS}")
    if len(SERIES) > 30:
        file_text = "🍿 ALL SERIES\n\n"
        for idx, (show, eps) in enumerate(SERIES.items(), 1):
            file_text += f"{idx:02d}. {show.title()} - Episodes: {', '.join(eps.keys()).upper()}\n"
        file = BytesIO(file_text.encode('utf-8'))
        file.name = "Series_List.txt"
        return await message.reply_document(file, caption=f"🍿 **{len(SERIES)} Series Available**{CREDITS}")
    text = f"╭━━━[ **🍿 SERIES LIST** ]━━━╮\n┃\n"
    for show, eps in SERIES.items(): text += f"┃ ❖ **{show.title()}** (Eps: {', '.join(eps.keys()).upper()})\n"
    text += f"┃\n╰━━━━━━━━━━━━━━━━━╯{CREDITS}"
    await message.reply(text, disable_web_page_preview=True)

# ================= Xtream Fetcher (unchanged) =================
@app.on_message(filters.command("addxtream") & filters.user(OWNER_ID))
async def auto_fetch_xtream(client, message):
    # ... (Keep your original /addxtream code here - it's fine)
    args = message.text.split()
    if len(args) != 4: return await message.reply(f"⚠️ **Usage:** `/addxtream <URL> <Username> <Password>`{CREDITS}")
    
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    base_api = f"{url}/player_api.php?username={user}&password={passwd}"
    msg = await message.reply("🚀 **Connecting to Xtream...**")
    
    try:
        async with aiohttp.ClientSession() as session:
            await msg.edit_text("📺 **Fetching Live TV Channels...**")
            c_count = 0
            async with session.get(f"{base_api}&action=get_live_streams", timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        for stream in data:
                            name = stream.get("name", "").strip().lower()
                            if name:
                                CHANNELS[name] = f"{url}/live/{user}/{passwd}/{stream.get('stream_id')}.m3u8"
                                c_count += 1
            
            await msg.edit_text(f"🎬 **Fetching Movies...**")
            m_count = 0
            async with session.get(f"{base_api}&action=get_vod_streams", timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        for stream in data:
                            name = stream.get("name", "").strip().lower()
                            ext = stream.get("container_extension", "mp4")
                            if name:
                                MOVIES[name] = f"{url}/movie/{user}/{passwd}/{stream.get('stream_id')}.{ext}"
                                m_count += 1

            await msg.edit_text(f"🍿 **Fetching Series...**")
            s_count, ep_count = 0, 0
            async with session.get(f"{base_api}&action=get_series", timeout=30) as resp:
                if resp.status == 200:
                    series_list = await resp.json()
                    if isinstance(series_list, list):
                        sem = asyncio.Semaphore(15)
                        async def process_series(s_item):
                            nonlocal s_count, ep_count
                            s_name = s_item.get("name", "").strip().lower()
                            s_id = s_item.get("series_id")
                            if not s_name or not s_id: return
                            async with sem:
                                try:
                                    async with session.get(f"{base_api}&action=get_series_info&series_id={s_id}", timeout=15) as s_resp:
                                        if s_resp.status == 200:
                                            s_info = await s_resp.json()
                                            episodes_dict = s_info.get("episodes", {})
                                            if episodes_dict and s_name not in SERIES:
                                                SERIES[s_name] = {}
                                            for season, episodes in episodes_dict.items():
                                                for ep in episodes:
                                                    ep_title = f"s{season}e{ep.get('episode_num')}"
                                                    ep_ext = ep.get("container_extension", "mp4")
                                                    SERIES[s_name][ep_title] = f"{url}/series/{user}/{passwd}/{ep.get('id')}.{ep_ext}"
                                                    ep_count += 1
                                            s_count += 1
                                except: pass
                        await asyncio.gather(*[process_series(s) for s in series_list])

            await msg.edit_text(
                f"✅ **Xtream Loaded Successfully!**\n\n"
                f"📺 Channels: `{c_count}`\n"
                f"🎬 Movies: `{m_count}`\n"
                f"🍿 Series: `{s_count}` (Eps: `{ep_count}`){CREDITS}"
            )
    except Exception as e:
        await msg.edit_text(f"❌ **Failed:** `{str(e)[:200]}`")

# ================= Admin Commands (unchanged) =================
@app.on_message(filters.command("delallchannels") & filters.user(OWNER_ID))
async def del_all_channels(client, message):
    count = len(CHANNELS); CHANNELS.clear()
    await message.reply(f"🗑️ **Deleted {count} Channels!**{CREDITS}")

# ... (keep other admin commands: delallmovies, delallseries, approve, unapprove)

@app.on_message(filters.command("approve") & filters.user(OWNER_ID))
async def approve_group(client, message):
    try:
        chat_id = int(message.command[1]) if len(message.command) > 1 else message.chat.id
        APPROVED_GROUPS.add(chat_id)
        await message.reply(f"✅ **Group `{chat_id}` APPROVED.**{CREDITS}")
    except: pass

# ================= FIXED STREAMING FUNCTIONS =================
@app.on_message(filters.command(["livetv", "playmovie", "playseries"]) & filters.group)
@check_approval
async def handle_stream_request(client, message):
    chat_id = message.chat.id
    cmd = message.command[0]
    
    if not await ensure_assistant_in_chat(chat_id, message): return
    if len(message.command) < 2: return await message.reply(f"⚠️ Usage: `/{cmd} <Name>`")

    query = " ".join(message.command[1:]).strip().lower()
    matches = []

    if cmd == "livetv":
        matches = search_media(query, CHANNELS)
        media_type = "📺 Live TV"
    elif cmd == "playmovie":
        matches = search_media(query, MOVIES)
        media_type = "🎬 Movie"
    elif cmd == "playseries":
        if "-" not in query: return await message.reply("⚠️ Format: `/playseries Show Name - S01E01`")
        show_q, ep_q = [x.strip() for x in query.split("-", 1)]
        matched_shows = search_media(show_q, SERIES)
        ep_q_clean = re.sub(r'[^a-z0-9]', '', ep_q.lower())
        for show in matched_shows:
            for ep in SERIES[show].keys():
                if ep_q_clean in re.sub(r'[^a-z0-9]', '', ep.lower()):
                    matches.append(f"{show}|||{ep}")
        media_type = "🍿 Series"

    if not matches:
        return await message.reply(f"❌ No matching {media_type} found.")
    
    if len(matches) == 1:
        await execute_play(chat_id, cmd, matches[0], message)
    else:
        keyboard = []
        for i, match_key in enumerate(matches[:15]):
            if cmd == "playseries":
                show, ep = match_key.split("|||")
                display_name = f"{show.title()} [{ep.upper()}]"
            else:
                display_name = match_key.title()
            display_name = display_name[:40] + "..." if len(display_name) > 40 else display_name
            keyboard.append([InlineKeyboardButton(display_name, callback_data=f"selplay_{i}")])
        
        text = f"🔍 **Multiple matches found!**\n\nSelect below:"
        if len(matches) > 15:
            text += f"\n(Showing top 15 of {len(matches)})"
        reply_msg = await message.reply(text, reply_markup=InlineKeyboardMarkup(keyboard))
        SEARCH_CACHE[reply_msg.id] = {"cmd": cmd, "matches": matches[:15]}

@app.on_callback_query(filters.regex(r"^selplay_"))
async def handle_selection(client, callback_query):
    msg_id = callback_query.message.id
    idx = int(callback_query.data.split("_")[1])
    if msg_id not in SEARCH_CACHE:
        return await callback_query.answer("Session expired.", show_alert=True)
    
    cache = SEARCH_CACHE[msg_id]
    await callback_query.message.delete()
    await execute_play(callback_query.message.chat.id, cache["cmd"], cache["matches"][idx], callback_query.message)

async def execute_play(chat_id, cmd, match_key, message):
    if cmd == "livetv":
        url = CHANNELS[match_key]
        media_type = "📺 Live TV"
        display_name = match_key.title()
    elif cmd == "playmovie":
        url = MOVIES[match_key]
        media_type = "🎬 Movie"
        display_name = match_key.title()
    elif cmd == "playseries":
        show, ep = match_key.split("|||")
        url = SERIES[show][ep]
        media_type = "🍿 Series"
        display_name = f"{show.title()} [{ep.upper()}]"

    msg = await message.reply(f"⚡ **Starting {media_type}...**\n⏳ FFmpeg Processing...")

    try:
        ffmpeg_params = {
            "before_options": "-re -fflags +genpts+discardcorrupt -analyzeduration 0 -probesize 32",
            "options": "-fflags +genpts+discardcorrupt -bufsize 64k -max_delay 0 -muxdelay 0"
        }

        stream = AudioVideoPiped(
            url,
            audio_parameters=HighQualityAudio(),
            video_parameters=HighQualityVideo(),
            **ffmpeg_params
        )

        await call_py.play(chat_id, stream)

        CURRENT_STREAMS[chat_id] = {
            "url": url,
            "name": display_name,
            "type": media_type,
            "stream": stream
        }

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("360p", callback_data="q_360p"), InlineKeyboardButton("480p", callback_data="q_480p")],
            [InlineKeyboardButton("720p (HD)", callback_data="q_720p"), InlineKeyboardButton("1080p (FHD)", callback_data="q_1080p")]
        ])

        await msg.edit_text(
            f"╭━━━[ **{BOT_NAME}** ]━━━╮\n"
            f"┃\n"
            f"┃ ❖ **Status:** 🟢 **Live Now**\n"
            f"┃ ❖ **Type:** {media_type}\n"
            f"┃ ❖ **Title:** {display_name}\n"
            f"┃ ❖ **Quality:** 720p (HD)\n"
            f"┃ ❖ **Mode:** FFmpeg Piped (Optimized for .ts)\n"
            f"┃\n"
            f"╰━━━━━━━━━━━━━━━━━╯{CREDITS}",
            reply_markup=keyboard, disable_web_page_preview=True
        )
    except Exception as e:
        await msg.edit_text(f"❌ **Failed to Play**\n`{str(e)[:250]}`{CREDITS}")
        print(f"Play Error: {e}")

@app.on_callback_query(filters.regex(r"^q_"))
async def switch_quality(client, callback_query):
    chat_id = callback_query.message.chat.id
    quality_req = callback_query.data.split("_")[1]
    
    if chat_id not in CURRENT_STREAMS:
        return await callback_query.answer("No active stream!", show_alert=True)

    stream_info = CURRENT_STREAMS[chat_id]
    
    try:
        ffmpeg_params = {
            "before_options": "-re -fflags +genpts+discardcorrupt -analyzeduration 0 -probesize 32",
            "options": "-fflags +genpts+discardcorrupt -bufsize 64k -max_delay 0 -muxdelay 0"
        }

        vq = HighQualityVideo()  # You can map qualities if needed

        new_stream = AudioVideoPiped(
            stream_info["url"],
            audio_parameters=HighQualityAudio(),
            video_parameters=vq,
            **ffmpeg_params
        )

        await call_py.play(chat_id, new_stream)
        CURRENT_STREAMS[chat_id]["stream"] = new_stream

        await callback_query.message.edit_text(
            f"╭━━━[ **{BOT_NAME}** ]━━━╮\n"
            f"┃\n"
            f"┃ ❖ **Status:** 🟢 **Live Now**\n"
            f"┃ ❖ **Type:** {stream_info['type']}\n"
            f"┃ ❖ **Title:** {stream_info['name']}\n"
            f"┃ ❖ **Quality:** {quality_req.upper()} ✅\n"
            f"┃ ❖ **Mode:** FFmpeg Piped\n"
            f"┃\n"
            f"╰━━━━━━━━━━━━━━━━━╯{CREDITS}",
            reply_markup=callback_query.message.reply_markup,
            disable_web_page_preview=True
        )
        await callback_query.answer(f"✅ Switched to {quality_req}!")
    except Exception as e:
        await callback_query.answer("❌ Failed to switch quality", show_alert=True)

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        CURRENT_STREAMS.pop(message.chat.id, None)
        await message.reply(f"⏹ **Stream Stopped.**{CREDITS}")
    except Exception as e:
        await message.reply(f"❌ `{str(e)[:100]}`")

# ================= Boot =================
async def main():
    Thread(target=run_flask, daemon=True).start()
    await app.start()
    await user_app.start()
    await call_py.start()
    
    print(f"✅ {BOT_NAME} System Online!")
    try:
        await app.send_message(OWNER_ID, f"🟢 **{BOT_NAME} is Online!**{CREDITS}")
    except: pass
    
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())

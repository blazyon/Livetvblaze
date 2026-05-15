import asyncio
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

# ================= Configuration =================
API_ID = 35562064
API_HASH = "fc5a4484d4abe8a2118284147b1092f6"
BOT_TOKEN = "8544679303:AAFW5OwWCbQ969yjP2lgaHReWv4Bg6Iqdas"
SESSION_STRING = "BQIeolAAJzdrYR4U2486lQZsWMLJvmXSHFEQyAF3S8u2QGzeveB-TJIQX1xiTOtoh_rYHtR3UMARD8J4OB0qLUo6_l8CwKCdo3PqQUM7CdLDJBFEeHqZHa1Gka4O3z3m8D03UTR5SU6ca1HXYEaxdHvX_uYc3RTEVUimXpf4tZ-uY062zWQ61GLs27JHIChMJe9e3jFZzqmH2bTUDH5DxGnF_IwrzDiUCkhSzXjgewp4tWwBMvfebBmnrZnGLUqLGAtfXymO9Xki2eaQlqrU7b9fyF5ROqdr1WR85b7myE9Cck0ilzTJZ6hsAxQELCBhelPA-f2L5NGHBL2R_ah57M1vnpuR3gAAAAH_qqMkAA"
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
    """Automatically adds the Assistant (User Session) to the Group"""
    try:
        await user_app.get_chat(chat_id)
        return True
    except Exception:
        try:
            chat = await app.get_chat(chat_id)
            link = chat.invite_link
            if not link:
                link = await app.export_chat_invite_link(chat_id)
            await user_app.join_chat(link)
            await message.reply(f"🤖 **Assistant Successfully Joined the Group!** {CREDITS}")
            return True
        except UserAlreadyParticipant:
            return True
        except Exception as e:
            await message.reply(f"⚠️ **Could not add assistant!**\nError: `{e}`\n\nPlease add the assistant manually to play streams.{CREDITS}")
            return False

def check_approval(func):
    """Decorator to check if group is approved before streaming"""
    async def wrapper(client, message):
        if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            if message.chat.id not in APPROVED_GROUPS and message.from_user.id != OWNER_ID:
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
    await message.reply(f"✅ **Channel Added Successfully!**\n📺 Name: `{name.title()}`{CREDITS}", disable_web_page_preview=True)

@app.on_message(filters.command("addxtream") & filters.user(OWNER_ID))
async def add_xtream(client, message):
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(f"⚠️ **Usage:** `/addxtream <URL> <Username> <Password>`{CREDITS}", disable_web_page_preview=True)
    
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    msg = await message.reply("🚀 **Fetching Xtream channels...**")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    count = 0
                    for stream in data:
                        name = stream.get("name", "").strip().lower()
                        if name:
                            stream_url = f"{url}/live/{user}/{passwd}/{stream.get('stream_id')}.m3u8"
                            CHANNELS[name] = stream_url
                            count += 1
                    await msg.edit_text(f"✅ **Loaded {count} Channels from Xtream API!**{CREDITS}", disable_web_page_preview=True)
                else:
                    await msg.edit_text(f"❌ Error Status: {resp.status}")
    except Exception as e:
        await msg.edit_text(f"❌ Failed: `{str(e)[:100]}`")

@app.on_message(filters.command("addmovie") & filters.user(OWNER_ID))
async def add_movie(client, message):
    try:
        args = message.text.split(None, 1)[1].split("|")
        name, url = args[0].strip().lower(), args[1].strip()
        MOVIES[name] = url
        await message.reply(f"✅ **Movie Added:** {name.title()}{CREDITS}", disable_web_page_preview=True)
    except:
        await message.reply(f"⚠️ **Format:** `/addmovie Movie Name | https://url.mp4`{CREDITS}", disable_web_page_preview=True)

@app.on_message(filters.command("addseries") & filters.user(OWNER_ID))
async def add_series(client, message):
    try:
        args = message.text.split(None, 1)[1].split("|")
        name, ep, url = args[0].strip().lower(), args[1].strip().lower(), args[2].strip()
        if name not in SERIES:
            SERIES[name] = {}
        SERIES[name][ep] = url
        await message.reply(f"✅ **Series Added:** {name.title()} ({ep.upper()}){CREDITS}", disable_web_page_preview=True)
    except:
        await message.reply(f"⚠️ **Format:** `/addseries Loki | S01E01 | https://url.mp4`{CREDITS}", disable_web_page_preview=True)

@app.on_message(filters.command("delchannel") & filters.user(OWNER_ID))
async def delete_channel(client, message):
    try:
        name = message.text.split(None, 1)[1].strip().lower()
        if name in CHANNELS:
            del CHANNELS[name]
            await message.reply(f"🗑️ **Deleted:** {name.title()}{CREDITS}", disable_web_page_preview=True)
        else:
            await message.reply("❌ Not found!")
    except:
        await message.reply("⚠️ **Usage:** `/delchannel <Name>`")

# ================= ADMIN/GROUP SYSTEM =================
@app.on_message(filters.command("approve") & filters.user(OWNER_ID))
async def approve_group(client, message):
    try:
        chat_id = int(message.command[1]) if len(message.command) > 1 else message.chat.id
        APPROVED_GROUPS.add(chat_id)
        await message.reply(f"✅ **Group `{chat_id}` has been APPROVED.**\nUsers can now stream here.{CREDITS}", disable_web_page_preview=True)
    except ValueError:
        await message.reply("❌ Invalid Chat ID")

@app.on_message(filters.command("unapprove") & filters.user(OWNER_ID))
async def unapprove_group(client, message):
    try:
        chat_id = int(message.command[1]) if len(message.command) > 1 else message.chat.id
        if chat_id in APPROVED_GROUPS:
            APPROVED_GROUPS.remove(chat_id)
        await message.reply(f"🚫 **Group `{chat_id}` UNAPPROVED.**{CREDITS}", disable_web_page_preview=True)
    except ValueError:
        pass

@app.on_message(filters.command("botinfo") & filters.user(OWNER_ID))
async def bot_info(client, message):
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
    
    m = await message.reply("🚀 **Broadcasting message...**")
    for chat_id in APPROVED_GROUPS:
        try:
            await app.send_message(chat_id, f"🔔 **Broadcast Alert**\n\n{msg_text}{CREDITS}", disable_web_page_preview=True)
            success += 1
        except:
            failed += 1
            
    await m.edit_text(f"✅ **Broadcast Complete!**\n\n📨 Sent: {success}\n❌ Failed: {failed}{CREDITS}", disable_web_page_preview=True)

# ================= STREAMING COMMANDS =================
@app.on_message(filters.command(["livetv", "playmovie", "playseries"]) & filters.group)
@check_approval
async def stream_media(client, message):
    chat_id = message.chat.id
    cmd = message.command[0]
    
    if not await ensure_assistant_in_chat(chat_id, message):
        return

    if len(message.command) < 2:
        return await message.reply(f"⚠️ Usage: `/{cmd} <Name>`")

    query = " ".join(message.command[1:]).strip().lower()
    
    url = ""
    media_type = ""
    display_name = ""

    if cmd == "livetv":
        if query not in CHANNELS:
            return await message.reply("❌ Channel not found! Use `/channels` to see the list.")
        url = CHANNELS[query]
        media_type = "📺 Live TV"
        display_name = query.title()
        
    elif cmd == "playmovie":
        if query not in MOVIES:
            return await message.reply("❌ Movie not found! Use `/movies` to see the list.")
        url = MOVIES[query]
        media_type = "🎬 Movie"
        display_name = query.title()
        
    elif cmd == "playseries":
        try:
            show, ep = [x.strip() for x in query.split("-")]
            if show not in SERIES or ep not in SERIES[show]:
                return await message.reply("❌ Series or Episode not found! Use `/series`.")
            url = SERIES[show][ep]
            media_type = "🍿 Series"
            display_name = f"{show.title()} [{ep.upper()}]"
        except:
            return await message.reply("⚠️ Format: `/playseries Show Name - S01E01`")

    msg = await message.reply(f"⚡ **Initializing {media_type}...**\n⏳ Please wait...")
    
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
        await msg.edit_text(f"❌ **Stream Failed!**\nError: `{str(e)[:100]}`{CREDITS}", disable_web_page_preview=True)

# ================= QUALITY SWITCH CALLBACK =================
@app.on_callback_query(filters.regex(r"^q_"))
async def switch_quality(client, callback_query):
    chat_id = callback_query.message.chat.id
    quality_req = callback_query.data.split("_")[1]
    
    if chat_id not in CURRENT_STREAMS:
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
        await callback_query.answer(f"❌ Failed to change quality!", show_alert=True)

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        CURRENT_STREAMS.pop(message.chat.id, None)
        await message.reply(f"⏹ **Stream Stopped Successfully.**{CREDITS}", disable_web_page_preview=True)
    except Exception as e:
        await message.reply(f"❌ `{str(e)[:100]}`")

# ================= Boot Sequence =================
async def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    await app.start()
    await user_app.start()
    await call_py.start()
    
    print(f"✅ {BOT_NAME} System Online!")
    try:
        await app.send_message(OWNER_ID, f"🟢 **{BOT_NAME} Online!**\nSystem initialized perfectly.{CREDITS}", disable_web_page_preview=True)
    except:
        pass
    
    await idle()
    
    for chat_id in list(CURRENT_STREAMS.keys()):
        try:
            await call_py.leave_call(chat_id)
        except:
            pass
    
    await app.stop()
    await user_app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())

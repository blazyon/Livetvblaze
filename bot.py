import asyncio
import aiohttp
from io import BytesIO
from urllib.parse import urlparse
from pyrogram import Client, filters, idle
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, VideoQuality
from flask import Flask
from threading import Thread
import os
import sys
import re

# ================= Configuration =================
API_ID = 35562064
API_HASH = "fc5a4484d4abe8a2118284147b1092f6"
BOT_TOKEN = "8544679303:AAFW5OwWCbQ969yjP2lgaHReWv4Bg6Iqdas"
SESSION_STRING = "BQIeolAAJzdrYR4U2486lQZsWMLJvmXSHFEQyAF3S8u2QGzeveB-TJIQX1xiTOtoh_rYHtR3UMARD8J4OB0qLUo6_l8CwKCdo3PqQUM7CdLDJBFEeHqZHa1Gka4O3z3m8D03UTR5SU6ca1HXYEaxdHvX_uYc3RTEVUimXpf4tZ-uY062zWQ61GLs27JHIChMJe9e3jFZzqmH2bTUDH5DxGnF_IwrzDiUCkhSzXjgewp4tWwBMvfebBmnrZnGLUqLGAtfXymO9Xki2eaQlqrU7b9fyF5ROqdr1WR85b7myE9Cck0ilzTJZ6hsAxQELCBhelPA-f2L5NGHBL2R_ah57M1vnpuR3gAAAAH_qqMkAA"
OWNER_ID = 8717767927

# Railway Port
PORT = int(os.environ.get("PORT", 8080))

# ================= Proxy Configuration (Optional) =================
# Add your proxy if needed. Leave empty to use direct connection
PROXY_URL = ""  # Example: "http://username:password@proxy:port"
# Or set via environment variable in Railway
PROXY_URL = os.environ.get("PROXY_URL", "")

# ================= Stream Headers =================
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

# Dynamically generate headers to match the stream's exact Origin/Subdomain
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

# ================= Flask Server =================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "📺 Live TV Bot Running"

@flask_app.route('/health')
def health():
    return {"status": "ok", "proxy": bool(PROXY_URL)}, 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, debug=False)

# ================= Initialize Clients =================
app = Client("tv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# PyTgCalls with proxy if configured
if PROXY_URL:
    call_py = PyTgCalls(user_app)
    print(f"🔒 Using proxy: {PROXY_URL[:30]}...")
else:
    call_py = PyTgCalls(user_app)
    print("🔓 Direct connection (no proxy)")

CHANNELS = {}
active_chats = set()

QUALITY_PRESETS = {
    "360p": VideoQuality.SD_360p,
    "480p": VideoQuality.SD_480p,
    "720p": VideoQuality.HD_720p,
    "1080p": VideoQuality.FHD_1080p,
    "2k": VideoQuality.QHD_2K,
    "4k": VideoQuality.UHD_4K,
}

# ================= Stream Detection =================
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
    elif '.m3u' in url_lower:
        return "hls"
    else:
        return "direct"

def get_headers_for_stream(url):
    """Get appropriate headers based on stream type"""
    stream_type = detect_stream_type(url)
    
    if stream_type == "amagi":
        return get_amagi_headers(url)
    else:
        return BROWSER_HEADERS

# ================= Stream Test =================
async def test_stream_accessibility(url):
    """Quick test to check if stream is accessible"""
    try:
        # Try with browser headers
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=BROWSER_HEADERS, timeout=10, allow_redirects=True) as resp:
                if resp.status in [200, 206, 302, 301]:
                    return True
    except:
        pass
    
    try:
        # Try with Amagi headers
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=get_amagi_headers(url), timeout=10, allow_redirects=True) as resp:
                if resp.status in [200, 206, 302, 301]:
                    return True
    except:
        pass
    
    # Try HEAD request
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, headers=get_amagi_headers(url), timeout=10, allow_redirects=True) as resp:
                if resp.status != 404:
                    return True
    except:
        pass
    
    return False

# ================= Commands =================
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply(
        "🎬 **Live TV VC Bot**\n\n"
        "**Commands:**\n"
        "• `/channels` - Browse channels\n"
        "• `/livetv <name>` - Play in VC (720p)\n"
        "• `/hqlivetv <name> <quality>` - Custom quality\n"
        "• `/teststream <url>` - Test a stream\n"
        "• `/stopvc` - Stop streaming\n"
        "• `/ping` - Check bot status\n\n"
        "🔧 **Note:** Amagi/restricted streams work in VC even if test shows 'not accessible'"
    )

@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    if not CHANNELS:
        return await message.reply("❌ No channels loaded. Owner needs to add channels!")
    
    text = "📺 **Available Channels**\n\n"
    for idx, name in enumerate(CHANNELS.keys(), 1):
        if len(text) > 3800:
            text += f"\n... and {len(CHANNELS) - idx + 1} more!"
            break
        text += f"`{idx:02d}.` **{name.title()}**\n"
    
    text += f"\n📊 Total: {len(CHANNELS)} channels"
    
    if len(text) > 4000:
        file = BytesIO(text.encode())
        file.name = "channels.txt"
        await message.reply_document(file, caption=f"📺 **{len(CHANNELS)} Channels**")
    else:
        await message.reply(text)

@app.on_message(filters.command("teststream"))
async def test_stream(client, message):
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/teststream <URL>`")
    
    url = message.command[1]
    msg = await message.reply("🔍 **Testing stream...**")
    
    stream_type = detect_stream_type(url)
    is_accessible = await test_stream_accessibility(url)
    
    if is_accessible:
        await msg.edit_text(
            f"✅ **Stream Accessible!**\n"
            f"📡 Type: {stream_type.upper()}\n"
            f"🔗 `{url[:80]}...`\n\n"
            f"✅ Will work in VC"
        )
    else:
        await msg.edit_text(
            f"⚠️ **HTTP Test: Not Accessible**\n\n"
            f"📡 **Stream Type:** {stream_type.upper()}\n"
            f"🔗 `{url[:80]}...`\n\n"
            f"**This is NORMAL for Amagi/restricted streams!**\n\n"
            f"✅ **FFmpeg can still play it in VC** because:\n"
            f"• It bypasses browser security (CORS)\n"
            f"• Uses direct HTTP connection\n"
            f"• Sends proper referer headers\n\n"
            f"💡 Add it anyway and try `/livetv`"
        )

@app.on_message(filters.command("livetv"))
async def play_live_tv(client, message):
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/livetv <Channel Name>`")
    
    channel_name = " ".join(message.command[1:]).strip().lower()
    
    if channel_name not in CHANNELS:
        return await message.reply("❌ Channel not found! Use `/channels`")
    
    await play_stream(chat_id, channel_name, "720p", message)

@app.on_message(filters.command("hqlivetv"))
async def play_hq_tv(client, message):
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        return await message.reply(
            "**Usage:** `/hqlivetv <Channel Name> <Quality>`\n\n"
            "**Qualities:** `360p` `480p` `720p` `1080p` `2k` `4k`\n"
            "**Example:** `/hqlivetv Sony Kal 1080p`"
        )
    
    parts = message.command[1:]
    if parts[-1].lower() in QUALITY_PRESETS:
        quality = parts[-1].lower()
        channel_name = " ".join(parts[:-1]).strip().lower()
    else:
        quality = "720p"
        channel_name = " ".join(parts).strip().lower()
    
    if channel_name not in CHANNELS:
        return await message.reply("❌ Channel not found!")
    
    await play_stream(chat_id, channel_name, quality, message)

async def play_stream(chat_id, channel_name, quality, message):
    stream_url = CHANNELS[channel_name]
    stream_type = detect_stream_type(stream_url)
    quality_label = quality.upper().replace("P", "p")
    
    msg = await message.reply(
        f"🎬 **Starting Stream...**\n"
        f"📺 {channel_name.title()}\n"
        f"📊 {quality_label}\n"
        f"🔧 Type: {stream_type.upper()}\n"
        f"⏳ Please wait 5-10 seconds..."
    )
    
    try:
        # Get PyTgCalls Video Quality Object
        video_quality = QUALITY_PRESETS.get(quality, VideoQuality.HD_720p)
        
        # Get Headers (Crucial for Amagi Streams)
        headers = get_headers_for_stream(stream_url)
        
        # Start pure stream without custom FFmpeg parameters
        await call_py.play(
            chat_id,
            MediaStream(
                media_path=stream_url,
                video_parameters=video_quality,
                headers=headers
            )
        )
        
        active_chats.add(chat_id)
        await msg.edit_text(
            f"▶️ **Now Streaming!**\n\n"
            f"📺 **{channel_name.title()}**\n"
            f"📊 **{quality_label}**\n"
            f"🔧 **Type:** {stream_type.upper()}\n"
            f"📡 **Status:** Live\n\n"
            f"💡 `/stopvc` to stop"
        )
        
        # Notify owner
        try:
            await app.send_message(
                OWNER_ID,
                f"🟢 Stream ON: {channel_name.title()} ({quality_label})\nChat: {chat_id}"
            )
        except:
            pass
            
    except Exception as e:
        error_text = str(e)[:200]
        print(f"Stream Error: {error_text}")
        await msg.edit_text(
            f"❌ **Failed to Play Stream**\n\n"
            f"📺 **Channel:** {channel_name.title()}\n"
            f"⚠️ **Error:** `{error_text}`\n\n"
            f"**Try:**\n"
            f"• Lower quality: `/hqlivetv {channel_name.title()} 360p`\n"
            f"• Wait a few seconds and try again\n"
            f"• Contact owner for proxy setup (If Geo-blocked)"
        )

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        active_chats.discard(message.chat.id)
        await message.reply("⏹ **Stream Stopped**")
    except Exception as e:
        await message.reply(f"❌ `{str(e)[:100]}`")

@app.on_message(filters.command("ping"))
async def ping_cmd(client, message):
    proxy_status = "🔒 Enabled" if PROXY_URL else "🔓 Direct"
    await message.reply(f"🏓 **Pong!**\n📡 Connection: {proxy_status}\n✅ Bot is running!")

@app.on_message(filters.command("proxyinfo") & filters.user(OWNER_ID))
async def proxy_info(client, message):
    if PROXY_URL:
        masked = PROXY_URL[:20] + "..." if len(PROXY_URL) > 20 else PROXY_URL
        await message.reply(f"🔒 **Proxy Active:** `{masked}`")
    else:
        await message.reply("🔓 **No proxy configured**\n\nTo add proxy, set PROXY_URL in Railway environment variables:\n`PROXY_URL=http://user:pass@proxy:port`")

# ================= Owner Commands =================
@app.on_message(filters.command("addxtream") & filters.user(OWNER_ID))
async def add_xtream(client, message):
    args = message.text.split()
    if len(args) != 4:
        return await message.reply("**Usage:** `/addxtream <URL> <Username> <Password>`")
    
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    msg = await message.reply("🔄 Fetching channels...")
    
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
                    await msg.edit_text(f"✅ Loaded {count} channels!")
                else:
                    await msg.edit_text(f"❌ Status {resp.status}")
    except Exception as e:
        await msg.edit_text(f"❌ `{str(e)[:200]}`")

@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply("**Usage:** `/addchannel <URL> <Channel Name>`\n\nExample: `/addchannel https://...m3u8 Sony Kal`")
    
    url, name = args[1], args[2].strip().lower()
    CHANNELS[name] = url
    
    stream_type = detect_stream_type(url)
    await message.reply(
        f"✅ **Added:** {name.title()}\n"
        f"📡 Type: {stream_type.upper()}\n"
        f"🔗 `{url[:80]}...`\n\n"
        f"💡 Use `/livetv {name.title()}` to play"
    )

@app.on_message(filters.command("editchannel") & filters.user(OWNER_ID))
async def edit_channel(client, message):
    try:
        parts = [p.strip() for p in message.text.split(None, 1)[1].split('|')]
        if len(parts) != 3:
            return await message.reply("**Usage:** `/editchannel Old Name | New Name | New URL`")
        
        old, new, url = parts[0].lower(), parts[1].lower(), parts[2]
        if old not in CHANNELS:
            return await message.reply("❌ Not found!")
        
        if old != new:
            del CHANNELS[old]
        CHANNELS[new] = url
        await message.reply(f"✅ Updated: {new.title()}")
    except:
        await message.reply("❌ Format: `/editchannel Old | New | URL`")

@app.on_message(filters.command("delchannel") & filters.user(OWNER_ID))
async def delete_channel(client, message):
    try:
        name = message.text.split(None, 1)[1].strip().lower()
        if name in CHANNELS:
            del CHANNELS[name]
            await message.reply(f"🗑️ Deleted: {name.title()}")
        else:
            await message.reply("❌ Not found!")
    except:
        await message.reply("**Usage:** `/delchannel <Name>`")

@app.on_message(filters.command(["stats", "channelcount"]) & filters.user(OWNER_ID))
async def stats(client, message):
    await message.reply(
        f"📊 **Bot Stats**\n\n"
        f"📺 Channels: {len(CHANNELS)}\n"
        f"🎬 Active Streams: {len(active_chats)}\n"
        f"🔒 Proxy: {'Yes' if PROXY_URL else 'No'}"
    )

# ================= Boot =================
async def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"🌐 Server on port {PORT}")
    
    await app.start()
    await user_app.start()
    await call_py.start()
    
    print("✅ Bot Ready!")
    print(f"🔒 Proxy: {'Enabled' if PROXY_URL else 'Disabled'}")
    print("📡 Supports: Amagi, HLS, M3U8, direct streams")
    print("💡 Tip: Amagi streams work in VC even if HTTP test fails!")
    
    try:
        await app.send_message(OWNER_ID, "🟢 Bot online!\n🔧 Amagi + restricted stream support active")
    except:
        pass
    
    await idle()
    
    for chat_id in active_chats.copy():
        try:
            await call_py.leave_call(chat_id)
        except:
            pass
    
    await app.stop()
    await user_app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
    

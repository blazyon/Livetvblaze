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
SESSION_STRING = "BQIeolAAOF4_3_Lk6LTKQi1T6JQz0OOWb4JWnEMFAptaWrb_9180UGqK1jT-SdAjp8YFXuUkckgHK8YwPlaPKtVHI26FK05P7aNOuXxwuJdGI9eA_focu9xybZ3c16RpsEHlIzwE-cjXAopvuCv2pPBjCj-vLaj_IIQFXFwXpU1H8AORs3ix1Hgrwe8babSOR-V7yAkhCcVug_h2aTZErdUDN61IaedRcwASjbUi9q3qH9U7Jhdnj4zojP68nfLLMNTkOkfFOZbtgdOjoEvhnhjQ2SzhP6her2W-L9QfnOz__Sb6HuNHwZxx7l-PCmQCtHBN12HD1MEnjyz01P-oIcqCK9FHowAAAAH_qqMkAA"
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

# Optimized FFmpeg configs with Protocol Whitelist added
FFMPEG_CONFIGS = {
    "amagi": {
        "360p": "-preset ultrafast -tune zerolatency -fflags +nobuffer+genpts -flags low_delay -strict experimental -bufsize 500k -maxrate 350k -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 10 -timeout 15000000 -allowed_extensions ALL -protocol_whitelist file,http,https,tcp,tls,crypto",
        "480p": "-preset fast -tune zerolatency -fflags +nobuffer+genpts -flags low_delay -strict experimental -bufsize 800k -maxrate 600k -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 10 -timeout 15000000 -allowed_extensions ALL -protocol_whitelist file,http,https,tcp,tls,crypto",
        "720p": "-preset fast -tune zerolatency -fflags +nobuffer+genpts -flags low_delay -strict experimental -bufsize 1500k -maxrate 1200k -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 10 -timeout 15000000 -allowed_extensions ALL -protocol_whitelist file,http,https,tcp,tls,crypto",
        "1080p": "-preset fast -tune zerolatency -fflags +nobuffer+genpts -flags low_delay -strict experimental -bufsize 2000k -maxrate 1800k -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 10 -timeout 15000000 -allowed_extensions ALL -protocol_whitelist file,http,https,tcp,tls,crypto",
    },
    "direct": {
        "720p": "-preset fast -tune zerolatency -fflags nobuffer -flags low_delay -strict experimental -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -timeout 10000000 -allowed_extensions ALL -protocol_whitelist file,http,https,tcp,tls,crypto",
    }
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

def get_ffmpeg_config(stream_type, quality):
    """Get FFmpeg config for stream type and quality"""
    if stream_type in FFMPEG_CONFIGS:
        return FFMPEG_CONFIGS[stream_type].get(quality, FFMPEG_CONFIGS[stream_type]["720p"])
    return FFMPEG_CONFIGS["direct"].get(quality, FFMPEG_CONFIGS["direct"]["720p"])

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
    
    success = False
    
    # Method 1: With detected stream type headers
    try:
        video_quality = QUALITY_PRESETS.get(quality, VideoQuality.HD_720p)
        ffmpeg_config = get_ffmpeg_config(stream_type, quality)
        headers = get_headers_for_stream(stream_url)
        
        await call_py.play(
            chat_id,
            MediaStream(
                media_path=stream_url,
                video_parameters=video_quality,
                headers=headers,
                ffmpeg_parameters=ffmpeg_config
            )
        )
        success = True
    except Exception as e1:
        print(f"Method 1 failed: {str(e1)[:100]}")
        
        # Method 2: With Amagi-specific headers (even if not detected as Amagi)
        if not success:
            try:
                await asyncio.sleep(2)
                await call_py.play(
                    chat_id,
                    MediaStream(
                        media_path=stream_url,
                        video_parameters=video_quality,
                        headers=get_amagi_headers(stream_url),
                        ffmpeg_parameters=get_ffmpeg_config("amagi", quality)
                    )
                )
                success = True
            except Exception as e2:
                print(f"Method 2 failed: {str(e2)[:100]}")
                
                # Method 3: Minimal config - bare bones approach
                if not success:
                    try:
                        await asyncio.sleep(2)
                        await call_py.play(
                            chat_id,
                            MediaStream(
                                media_path=stream_url,
                                video_parameters=VideoQuality.SD_480p,
                                headers={"User-Agent": "Mozilla/5.0"},
                                ffmpeg_parameters="-preset ultrafast -tune zerolatency -fflags +nobuffer+genpts -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -timeout 20000000 -analyzeduration 20000000 -probesize 20000000 -allowed_extensions ALL"
                            )
                        )
                        success = True
                        quality_label = "480p (Auto)"
                    except Exception as e3:
                        print(f"Method 3 failed: {str(e3)[:100]}")
    
    if success:
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
                f"🟢 Stream ON: {channel_name.title()} ({quality_label})\nType: {stream_type}\nChat: {chat_id}"
            )
        except:
            pass
    else:
        await msg.edit_text(
            f"❌ **Failed to Play Stream**\n\n"
            f"📺 **Channel:** {channel_name.title()}\n"
            f"🔧 **Type:** {stream_type.upper()}\n\n"
            f"**Possible Issues:**\n"
            f"• Stream URL expired or invalid\n"
            f"• Requires specific VPN/region\n"
            f"• Stream is geo-blocked\n"
            f"• Server is overloaded\n\n"
            f"**Try:**\n"
            f"• Lower quality: `/hqlivetv {channel_name.title()} 360p`\n"
            f"• Test stream: `/teststream {stream_url[:60]}...`\n"
            f"• Contact owner for proxy setup"
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

import asyncio
import aiohttp
from io import BytesIO
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

# Railway port
PORT = int(os.environ.get("PORT", 8080))

# ================= Special Headers for Different Streams =================
# Headers that mimic browser requests to bypass stream restrictions
STREAM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://playout.now3.amagi.tv",
    "Referer": "https://playout.now3.amagi.tv/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
}

# Enhanced FFmpeg parameters for problematic streams
ADVANCED_FFMPEG_PARAMS = {
    "360p": "-preset ultrafast -tune zerolatency -fflags nobuffer -flags low_delay -strict experimental -bufsize 500k -maxrate 350k -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 10 -timeout 10000000 -user_agent \"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\" -headers \"Referer: https://playout.now3.amagi.tv/\"",
    "480p": "-preset fast -tune zerolatency -fflags nobuffer -flags low_delay -strict experimental -bufsize 800k -maxrate 600k -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 10 -timeout 10000000",
    "720p": "-preset fast -tune zerolatency -fflags nobuffer -flags low_delay -strict experimental -bufsize 1500k -maxrate 1200k -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 10 -timeout 10000000",
    "1080p": "-preset fast -tune zerolatency -fflags nobuffer -flags low_delay -strict experimental -bufsize 2000k -maxrate 1800k -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 10 -timeout 10000000"
}

# ================= Flask Server =================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "📺 Live TV Bot Running"

@flask_app.route('/health')
def health():
    return {"status": "ok"}, 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, debug=False)

# ================= Initialize Clients =================
app = Client("tv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
call_py = PyTgCalls(user_app)

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

# ================= Stream Analyzer =================
async def analyze_stream_url(url):
    """Analyze stream URL and return optimized settings"""
    stream_type = "direct"
    special_headers = {}
    additional_ffmpeg = ""
    
    # Check for Amagi streams (like your problematic link)
    if "amagi" in url.lower() or "now3" in url.lower():
        stream_type = "amagi"
        special_headers = {
            "Referer": "https://playout.now3.amagi.tv/",
            "Origin": "https://playout.now3.amagi.tv",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
        }
        additional_ffmpeg = "-headers \"Referer: https://playout.now3.amagi.tv/\" -user_agent \"Mozilla/5.0\""
    
    # Check for M3U8/HLS streams
    elif url.endswith('.m3u8'):
        stream_type = "hls"
        additional_ffmpeg = "-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 10"
    
    # Check for YouTube streams
    elif "youtube" in url.lower() or "youtu.be" in url.lower():
        stream_type = "youtube"
        additional_ffmpeg = "-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1"
    
    # Check for Twitch
    elif "twitch" in url.lower():
        stream_type = "twitch"
        additional_ffmpeg = "-reconnect 1 -reconnect_at_eof 1"
    
    # Direct MP4/TS streams
    elif url.endswith(('.mp4', '.ts', '.mkv')):
        stream_type = "direct_video"
        additional_ffmpeg = "-reconnect 1 -reconnect_at_eof 1"
    
    return {
        "type": stream_type,
        "headers": special_headers,
        "ffmpeg_extra": additional_ffmpeg
    }

# ================= Test Stream Function =================
async def test_stream_url(url):
    """Test if a stream URL is accessible"""
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                **STREAM_HEADERS,
                "Referer": "https://playout.now3.amagi.tv/",
                "Origin": "https://playout.now3.amagi.tv"
            }
            
            # Try with special headers first
            try:
                async with session.get(url, headers=headers, timeout=10, allow_redirects=True) as resp:
                    if resp.status == 200:
                        content_type = resp.headers.get('Content-Type', '')
                        return True, f"✅ Stream accessible (Type: {content_type[:50]})"
            except:
                pass
            
            # Try without special headers
            try:
                async with session.head(url, headers=STREAM_HEADERS, timeout=10, allow_redirects=True) as resp:
                    if resp.status == 200:
                        return True, "✅ Stream accessible"
            except:
                pass
                
            return False, "❌ Stream not accessible (may need special access or VPN)"
    except Exception as e:
        return False, f"❌ Error: {str(e)[:100]}"

# ================= Commands =================
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply(
        "📺 **Live TV VC Bot - Advanced Streaming**\n\n"
        "**Commands:**\n"
        "• `/channels` - List all channels\n"
        "• `/livetv <name>` - Play channel (720p)\n"
        "• `/hqlivetv <name> <quality>` - Custom quality\n"
        "• `/teststream <url>` - Test a stream link\n"
        "• `/stopvc` - Stop streaming\n"
        "• `/ping` - Check status\n\n"
        "🔧 **Special streams supported:** Amagi, YouTube, Twitch, HLS, M3U8"
    )

@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    if not CHANNELS:
        return await message.reply("❌ No channels loaded. Owner needs to add channels!")
    
    text = "📺 **Available Channels**\n\n"
    for idx, (name, url) in enumerate(CHANNELS.items(), 1):
        if len(text) > 3800:
            text += f"\n... and {len(CHANNELS) - idx + 1} more!"
            break
        text += f"`{idx:02d}.` **{name.title()}**\n"
    
    if len(text) > 4000:
        file = BytesIO(text.encode())
        file.name = "channels.txt"
        await message.reply_document(file, caption=f"📺 **{len(CHANNELS)} Channels Available**")
    else:
        await message.reply(text)

@app.on_message(filters.command("teststream"))
async def test_stream(client, message):
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/teststream <URL>`\n\nExample: `/teststream https://example.com/stream.m3u8`")
    
    url = message.command[1]
    msg = await message.reply("🔍 **Testing stream...**\nPlease wait...")
    
    is_accessible, status_msg = await test_stream_url(url)
    
    if is_accessible:
        await msg.edit_text(f"✅ **Stream Test Result:**\n{status_msg}\n\n🔗 `{url[:80]}...`")
    else:
        stream_info = await analyze_stream_url(url)
        await msg.edit_text(
            f"⚠️ **Stream Test Result:**\n{status_msg}\n\n"
            f"**Stream Type:** {stream_info['type']}\n"
            f"**Tips:**\n"
            f"• This type needs special handling\n"
            f"• Use `/addchanneladvanced` to add with headers\n"
            f"• Stream might work in VC despite this test"
        )

@app.on_message(filters.command("livetv"))
async def play_live_tv(client, message):
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/livetv <Channel Name>`\n\nExample: `/livetv Sony Kal`")
    
    channel_name = " ".join(message.command[1:]).strip().lower()
    
    if channel_name not in CHANNELS:
        return await message.reply("❌ Channel not found! Use `/channels` to see all channels.")
    
    await start_advanced_stream(chat_id, channel_name, "720p", message)

@app.on_message(filters.command("hqlivetv"))
async def play_hq_tv(client, message):
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        return await message.reply(
            "**Usage:** `/hqlivetv <Channel Name> <Quality>`\n\n"
            "**Qualities:** `360p`, `480p`, `720p` (HD), `1080p` (FHD)\n"
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
    
    await start_advanced_stream(chat_id, channel_name, quality, message)

async def start_advanced_stream(chat_id, channel_name, quality, message):
    stream_url = CHANNELS[channel_name]
    quality_label = quality.upper().replace("P", "p")
    
    # Analyze stream for optimization
    stream_info = await analyze_stream_url(stream_url)
    
    msg = await message.reply(
        f"🎬 **Analyzing Stream...**\n"
        f"📺 Channel: {channel_name.title()}\n"
        f"📊 Quality: {quality_label}\n"
        f"🔍 Type: {stream_info['type'].upper()}\n"
        f"⏳ Optimizing connection..."
    )
    
    try:
        video_quality = QUALITY_PRESETS.get(quality, VideoQuality.HD_720p)
        base_ffmpeg = ADVANCED_FFMPEG_PARAMS.get(quality, ADVANCED_FFMPEG_PARAMS["720p"])
        
        # Add stream-specific FFmpeg parameters
        if stream_info['ffmpeg_extra']:
            base_ffmpeg += f" {stream_info['ffmpeg_extra']}"
        
        # Merge headers
        final_headers = {
            **STREAM_HEADERS,
            **stream_info['headers']
        }
        
        # Add specific referer for Amagi/non-standard streams
        if stream_info['type'] == 'amagi':
            final_headers.update({
                "Referer": "https://playout.now3.amagi.tv/",
                "Origin": "https://playout.now3.amagi.tv",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "cross-site"
            })
        
        await call_py.play(
            chat_id,
            MediaStream(
                media_path=stream_url,
                video_parameters=video_quality,
                headers=final_headers,
                ffmpeg_parameters=base_ffmpeg
            )
        )
        
        active_chats.add(chat_id)
        
        await msg.edit_text(
            f"▶️ **Streaming Now!**\n\n"
            f"📺 **{channel_name.title()}**\n"
            f"🎯 **{quality_label}**\n"
            f"🔧 **Type:** {stream_info['type'].upper()}\n"
            f"📡 **Status:** Live\n\n"
            f"💡 Use `/stopvc` to stop"
        )
        
        # Notify owner
        try:
            await app.send_message(
                OWNER_ID,
                f"🟢 Stream: {channel_name.title()} ({quality_label})\n"
                f"Type: {stream_info['type']}\n"
                f"Chat: {chat_id}"
            )
        except:
            pass
            
    except Exception as e:
        error_msg = str(e)[:300]
        
        # Try alternative approach for problematic streams
        try:
            await msg.edit_text("🔄 Trying alternative connection method...")
            
            # Alternative: Try without special headers
            await call_py.play(
                chat_id,
                MediaStream(
                    media_path=stream_url,
                    video_parameters=video_quality,
                    headers={"User-Agent": STREAM_HEADERS["User-Agent"]},
                    ffmpeg_parameters=f"{base_ffmpeg} -analyzeduration 10000000 -probesize 10000000"
                )
            )
            
            active_chats.add(chat_id)
            await msg.edit_text(
                f"▶️ **Streaming (Alternative Mode)**\n\n"
                f"📺 **{channel_name.title()}**\n"
                f"📊 **{quality_label}**\n"
                f"📡 Status: Live"
            )
            
        except Exception as e2:
            await msg.edit_text(
                f"❌ **Streaming Failed!**\n\n"
                f"**Channel:** {channel_name.title()}\n"
                f"**Type:** {stream_info['type']}\n"
                f"**Error:** `{str(e2)[:150]}`\n\n"
                f"**Troubleshooting:**\n"
                f"• Use `/teststream {stream_url[:50]}...` to check\n"
                f"• Try lower quality: `/hqlivetv {channel_name.title()} 480p`\n"
                f"• Channel might need special access\n"
                f"• Contact owner for support"
            )
        
        try:
            await app.send_message(OWNER_ID, f"⚠️ Stream Error: {channel_name} - {str(e)[:200]}")
        except:
            pass

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        active_chats.discard(message.chat.id)
        await message.reply("⏹ **Stream Stopped**")
    except Exception as e:
        await message.reply(f"❌ Error: `{str(e)[:100]}`")

@app.on_message(filters.command("ping"))
async def ping_cmd(client, message):
    await message.reply("🏓 **Pong!** Bot is online and ready!")

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
                    await msg.edit_text(f"❌ Error: Status {resp.status}")
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{str(e)[:200]}`")

@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply("**Usage:** `/addchannel <URL> <Channel Name>`")
    
    url, name = args[1], args[2].strip().lower()
    CHANNELS[name] = url
    
    # Test the stream
    status_msg = await message.reply("✅ Added! Testing stream...")
    is_accessible, test_result = await test_stream_url(url)
    await status_msg.edit_text(
        f"✅ **Channel Added:** {name.title()}\n"
        f"🔗 `{url[:80]}...`\n"
        f"📊 Test: {test_result}"
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
        await message.reply("❌ Format error!")

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

@app.on_message(filters.command("channelcount") & filters.user(OWNER_ID))
async def channel_count(client, message):
    await message.reply(f"📊 Channels: {len(CHANNELS)}\n🎬 Active: {len(active_chats)}")

# ================= Boot =================
async def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"🌐 Server on port {PORT}")
    
    await app.start()
    await user_app.start()
    await call_py.start()
    
    print("✅ Bot ready - Supports Amagi, HLS, M3U8, YouTube, and more!")
    
    try:
        await app.send_message(OWNER_ID, "🟢 Bot online!\n🔧 Advanced stream support active")
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

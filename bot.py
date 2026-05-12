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

# ================= Configuration =================
API_ID = 34378954
API_HASH = "58a74f69a8c9e858eab3f27c61fe2b85"
BOT_TOKEN = "8544679303:AAFW5OwWCbQ969yjP2lgaHReWv4Bg6Iqdas"
SESSION_STRING = "AgIMlMoAbPev3QnpgthtBLA3-FxqXDWUsP10CVdftzlfptx-o1OSudvotpZ8OggSofAH1g3k8PrW1CskKB4LO4a2cKOHSs4RatN93KH4TBehDEA6uqgSBoFMeVevFwbj14iS0bNWAeDsl5mEfOr464pXeEErolo2UUsxyedspukX2Jgh5zEZuRUzILx1kWdC53LwB5r8ZMKue4R5dGup_Ssdk1PR453tzIXQxyFR5VYT45GpXfi8Gy3HIlBvcLd88NqhSbfNnOSvWLHXvg0CIQLg0Mf4UDk8M3usNzIwep5OYHlSja9mAn7YSCY2hTXsZU4Ta4My_esTt66omfRwXuCNuj2eagAAAAIHnpT3AA"
OWNER_ID = 8717767927

# ================= Railway Configuration =================
PORT = int(os.environ.get("PORT", 8080))
RAILWAY_STATIC_URL = os.environ.get("RAILWAY_STATIC_URL", "")

# ================= Flask Server for Railway =================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>📺 Live TV VC Bot</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
                color: #fff;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                text-align: center;
                padding: 50px 20px;
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            .container {
                background: rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                border-radius: 20px;
                padding: 40px;
                box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
                border: 1px solid rgba(255, 255, 255, 0.18);
                max-width: 600px;
                width: 100%;
            }
            .status-dot {
                width: 15px;
                height: 15px;
                background: #00ff00;
                border-radius: 50%;
                display: inline-block;
                margin-right: 10px;
                animation: pulse 2s infinite;
            }
            @keyframes pulse {
                0% { opacity: 1; }
                50% { opacity: 0.5; }
                100% { opacity: 1; }
            }
            h1 { font-size: 2.5em; margin-bottom: 20px; color: #e94560; }
            .info-card {
                background: rgba(255, 255, 255, 0.05);
                border-radius: 10px;
                padding: 20px;
                margin: 15px 0;
                text-align: left;
            }
            .info-item {
                margin: 10px 0;
                font-size: 1.1em;
            }
            .label { color: #e94560; font-weight: bold; }
            .quality-badge {
                background: #e94560;
                color: white;
                padding: 5px 15px;
                border-radius: 20px;
                display: inline-block;
                margin: 10px 0;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📺 Live TV VC Bot</h1>
            <p><span class="status-dot"></span><strong>Status: Online</strong></p>
            <div class="quality-badge">🎬 High Quality Streaming</div>
            <div class="info-card">
                <div class="info-item"><span class="label">🎯 Platform:</span> Railway</div>
                <div class="info-item"><span class="label">📊 Quality:</span> 720p HD</div>
                <div class="info-item"><span class="label">🚀 Service:</span> Active</div>
                <div class="info-item"><span class="label">🔊 Audio:</span> 128kbps AAC</div>
                <div class="info-item"><span class="label">🌐 Port:</span> {port}</div>
            </div>
            <p style="margin-top: 20px; opacity: 0.7;">Telegram @LiveTV_Bot</p>
        </div>
    </body>
    </html>
    """.format(port=PORT)

@flask_app.route('/health')
def health():
    return {
        "status": "healthy",
        "service": "telegram-tv-bot",
        "quality": "720p_HD",
        "platform": "railway",
        "version": "2.0.0"
    }, 200

@flask_app.route('/metrics')
def metrics():
    return {
        "active_streams": len(active_chats),
        "total_channels": len(CHANNELS),
        "uptime": "running"
    }, 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# ================= Initialize Clients =================
# Optimize Pyrogram for Railway
app = Client(
    "tv_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=100,
    max_concurrent_transmissions=10
)

user_app = Client(
    "user_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
    workers=100,
    max_concurrent_transmissions=10
)

call_py = PyTgCalls(
    user_app,
    cache_duration=180
)

CHANNELS = {}
active_chats = set()

# ================= Channel Quality Presets =================
QUALITY_PRESETS = {
    "4k": VideoQuality.UHD_4K,
    "2k": VideoQuality.QHD_2K,
    "1080p": VideoQuality.FHD_1080p,
    "720p": VideoQuality.HD_720p,
    "480p": VideoQuality.SD_480p,
    "360p": VideoQuality.SD_360p,
}

FFMPEG_PRESETS = {
    "4k": "-preset fast -tune zerolatency -fflags nobuffer -flags low_delay -strict experimental -bufsize 4000k -maxrate 3500k -c:v libx264 -crf 18",
    "2k": "-preset fast -tune zerolatency -fflags nobuffer -flags low_delay -strict experimental -bufsize 3000k -maxrate 2500k -c:v libx264 -crf 18",
    "1080p": "-preset fast -tune zerolatency -fflags nobuffer -flags low_delay -strict experimental -bufsize 2000k -maxrate 1800k",
    "720p": "-preset fast -tune zerolatency -fflags nobuffer -flags low_delay -strict experimental -bufsize 1500k -maxrate 1200k",
    "480p": "-preset fast -tune zerolatency -fflags nobuffer -flags low_delay -strict experimental -bufsize 800k -maxrate 600k",
    "360p": "-preset ultrafast -tune zerolatency -fflags nobuffer -flags low_delay -strict experimental -bufsize 500k -maxrate 350k"
}

# ================= General Commands =================
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply(
        "🎬 **Live TV VC Bot - High Quality Streaming!**\n\n"
        "**📺 Available Commands:**\n"
        "• `/channels` - Browse all channels\n"
        "• `/livetv <name>` - Play a channel (HD)\n"
        "• `/hqlivetv <name> <quality>` - Play with custom quality\n"
        "• `/stopvc` - Stop streaming\n"
        "• `/ping` - Check bot status\n\n"
        "**🎯 Quality Options:** `360p`, `480p`, `720p`, `1080p`, `2k`, `4k`\n"
        "**💡 Example:** `/hqlivetv Star Sports 720p`"
    )

@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    if not CHANNELS:
        return await message.reply("❌ No channels loaded. Admin needs to add channels first!")
    
    text = "📺 **Available Channels**\n\n"
    for idx, name in enumerate(CHANNELS.keys(), 1):
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

@app.on_message(filters.command("livetv"))
async def play_live_tv(client, message):
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        return await message.reply("**❌ Usage:** `/livetv <Channel Name>`\n\nExample: `/livetv Star Sports`")
    
    channel_name = " ".join(message.command[1:]).strip().lower()
    
    if channel_name not in CHANNELS:
        return await message.reply(f"❌ **Channel not found!**\nUse `/channels` to see all channels.")
    
    # Default to 720p HQ
    await start_stream(chat_id, channel_name, "720p", message)

@app.on_message(filters.command("hqlivetv"))
async def play_hq_tv(client, message):
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        return await message.reply(
            "**🎬 High Quality Live TV**\n\n"
            "**Usage:** `/hqlivetv <Channel Name> <Quality>`\n\n"
            "**Quality Options:**\n"
            "• `360p` - Low bandwidth\n"
            "• `480p` - Standard\n"
            "• `720p` - HD (Recommended)\n"
            "• `1080p` - Full HD\n"
            "• `2k` - Ultra HD\n"
            "• `4k` - 4K Ultra HD\n\n"
            "**Example:** `/hqlivetv Star Sports 720p`"
        )
    
    # Parse channel name and quality
    parts = message.command[1:]
    if parts[-1].lower() in QUALITY_PRESETS:
        quality = parts[-1].lower()
        channel_name = " ".join(parts[:-1]).strip().lower()
    else:
        quality = "720p"  # Default HQ
        channel_name = " ".join(parts).strip().lower()
    
    if channel_name not in CHANNELS:
        return await message.reply(f"❌ **Channel not found!**\nUse `/channels` to see all channels.")
    
    await start_stream(chat_id, channel_name, quality, message)

async def start_stream(chat_id, channel_name, quality, message):
    stream_url = CHANNELS[channel_name]
    quality_label = quality.upper().replace("P", "p")
    
    msg = await message.reply(
        f"🎬 **Initializing HQ Stream...**\n"
        f"📺 **Channel:** {channel_name.title()}\n"
        f"📊 **Quality:** {quality_label}\n"
        f"⏳ Please wait while we optimize..."
    )
    
    try:
        video_quality = QUALITY_PRESETS.get(quality, VideoQuality.HD_720p)
        ffmpeg_params = FFMPEG_PRESETS.get(quality, FFMPEG_PRESETS["720p"])
        
        # Add reconnection parameters
        ffmpeg_params += " -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        
        await call_py.play(
            chat_id,
            MediaStream(
                media_path=stream_url,
                video_parameters=video_quality,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Connection": "keep-alive"
                },
                ffmpeg_parameters=ffmpeg_params
            )
        )
        
        active_chats.add(chat_id)
        
        await msg.edit_text(
            f"▶️ **Now Streaming in High Quality!**\n\n"
            f"📺 **Channel:** {channel_name.title()}\n"
            f"🎯 **Quality:** {quality_label}\n"
            f"🎬 **Codec:** H.264/AAC\n"
            f"🔊 **Audio:** 128kbps Stereo\n"
            f"📡 **Status:** Live\n\n"
            f"💡 Use `/stopvc` to end stream"
        )
        
        # Log to owner
        try:
            await app.send_message(
                OWNER_ID,
                f"🟢 **Stream Started**\n"
                f"📺 {channel_name.title()}\n"
                f"🎯 {quality_label}\n"
                f"💬 Chat ID: {chat_id}"
            )
        except:
            pass
            
    except Exception as e:
        error_msg = str(e)[:200]
        await msg.edit_text(
            f"❌ **Streaming Failed!**\n\n"
            f"**Error:** `{error_msg}`\n\n"
            f"**Troubleshooting:**\n"
            f"• Start Voice Chat in this group\n"
            f"• Check channel availability\n"
            f"• Try a lower quality: `/hqlivetv {channel_name.title()} 480p`"
        )
        
        try:
            await app.send_message(OWNER_ID, f"⚠️ Stream Error in {chat_id}: {error_msg}")
        except:
            pass

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    chat_id = message.chat.id
    try:
        await call_py.leave_call(chat_id)
        active_chats.discard(chat_id)
        await message.reply("⏹ **Stream Ended**\n🔇 Disconnected from Voice Chat")
        
        try:
            await app.send_message(OWNER_ID, f"🔴 Stream stopped in chat {chat_id}")
        except:
            pass
            
    except Exception as e:
        await message.reply(f"❌ **Error:** `{str(e)[:100]}`")

@app.on_message(filters.command("ping"))
async def ping_cmd(client, message):
    await message.reply("🏓 **Pong!** Bot is online and ready for HQ streaming!")

@app.on_message(filters.command("quality"))
async def quality_info(client, message):
    await message.reply(
        "🎬 **Available Quality Presets**\n\n"
        "• `360p` - Low (Smooth on slow connections)\n"
        "• `480p` - Standard (Balanced)\n"
        "• `720p` - **HD** (Recommended) ✨\n"
        "• `1080p` - Full HD (Requires good connection)\n"
        "• `2k` - Ultra HD (High bandwidth)\n"
        "• `4k` - 4K Ultra HD (Very high bandwidth)\n\n"
        "**Usage:** `/hqlivetv Channel Name 720p`\n"
        "**Default:** 720p for `/livetv`"
    )

@app.on_message(filters.command("streams"))
async def active_streams(client, message):
    if message.from_user.id != OWNER_ID:
        return await message.reply("⛔ Owner only command!")
    
    if active_chats:
        text = f"🎬 **Active Streams:** {len(active_chats)}\n\n"
        for chat_id in active_chats:
            text += f"• Chat ID: `{chat_id}`\n"
        await message.reply(text)
    else:
        await message.reply("❌ No active streams")

# ================= Owner Commands =================
@app.on_message(filters.command("addxtream") & filters.user(OWNER_ID))
async def add_xtream(client, message):
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(
            "**Usage:** `/addxtream <URL> <Username> <Password>`\n\n"
            "Example: `/addxtream http://server:8080 user123 pass456`"
        )
    
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    msg = await message.reply("🔄 **Fetching channels from Xtream...**")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    count = 0
                    categories = {}
                    
                    for stream in data:
                        name = stream.get("name", "").strip().lower()
                        category = stream.get("category_name", "General")
                        
                        if name:
                            stream_url = f"{url}/live/{user}/{passwd}/{stream.get('stream_id')}.m3u8"
                            CHANNELS[name] = stream_url
                            categories[name] = category
                            count += 1
                    
                    response = f"✅ **Success!** {count} channels loaded!\n\n"
                    if categories:
                        response += "**Categories Found:**\n"
                        unique_cats = set(categories.values())
                        for cat in list(unique_cats)[:10]:
                            response += f"• {cat}\n"
                    
                    await msg.edit_text(response)
                    await app.send_message(OWNER_ID, f"📺 Added {count} channels from Xtream server")
                else:
                    await msg.edit_text(f"❌ Server returned status: {resp.status}")
    except Exception as e:
        await msg.edit_text(f"❌ **Error:** `{str(e)[:200]}`")

@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply("**Usage:** `/addchannel <URL> <Name>`")
    
    url, name = args[1], args[2].strip().lower()
    CHANNELS[name] = url
    await message.reply(f"✅ **Added:** `{name.title()}`")

@app.on_message(filters.command("editchannel") & filters.user(OWNER_ID))
async def edit_channel(client, message):
    try:
        parts = [p.strip() for p in message.text.split(None, 1)[1].split('|')]
        if len(parts) != 3:
            return await message.reply("**Format:** `/editchannel Old | New | URL`")
        
        old, new, url = parts[0].lower(), parts[1].lower(), parts[2]
        
        if old not in CHANNELS:
            return await message.reply(f"❌ `{old.title()}` not found!")
        
        if old != new:
            del CHANNELS[old]
        CHANNELS[new] = url
        
        await message.reply(f"✅ **Updated:** `{new.title()}`")
    except Exception as e:
        await message.reply(f"❌ Format error. Use: `/editchannel Old | New | URL`")

@app.on_message(filters.command("delchannel") & filters.user(OWNER_ID))
async def delete_channel(client, message):
    try:
        name = message.text.split(None, 1)[1].strip().lower()
        if name in CHANNELS:
            del CHANNELS[name]
            await message.reply(f"🗑️ **Deleted:** `{name.title()}`")
        else:
            await message.reply("❌ Not found!")
    except:
        await message.reply("**Usage:** `/delchannel <Name>`")

@app.on_message(filters.command("channelcount") & filters.user(OWNER_ID))
async def channel_count(client, message):
    await message.reply(f"📊 **Total Channels:** {len(CHANNELS)}\n🎬 **Active Streams:** {len(active_chats)}")

# ================= Railway Keep-Alive =================
async def keep_alive_ping():
    """Periodic self-ping to prevent Railway sleep"""
    while True:
        try:
            if RAILWAY_STATIC_URL:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{RAILWAY_STATIC_URL}/health") as resp:
                        pass
        except:
            pass
        await asyncio.sleep(300)  # Every 5 minutes

# ================= Boot Process =================
async def main():
    # Start Flask server
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"🌐 Railway Web Server running on port {PORT}")
    print(f"🔗 Health check: http://0.0.0.0:{PORT}/health")
    
    # Start keep-alive task
    asyncio.create_task(keep_alive_ping())
    
    # Start clients
    print("🤖 Starting Bot Client...")
    await app.start()
    print("👤 Starting User Client...")
    await user_app.start()
    print("🎥 Initializing PyTgCalls...")
    await call_py.start()
    
    print("=" * 60)
    print("✅ Bot Deployed on Railway! ✨")
    print("📊 Default Quality: 720p HD")
    print("🎬 Available Qualities: 360p-4K")
    print(f"💻 Web Dashboard: http://0.0.0.0:{PORT}")
    print("=" * 60)
    
    # Notify owner
    try:
        await app.send_message(
            OWNER_ID,
            "🟢 **Bot Deployed on Railway!**\n\n"
            "🎬 **High Quality Streaming Active**\n"
            "📊 Default: 720p HD\n"
            "🎯 Commands: /hqlivetv\n\n"
            "✅ Ready to stream!"
        )
    except:
        pass
    
    await idle()
    
    # Cleanup
    print("🔄 Shutting down...")
    for chat_id in active_chats.copy():
        try:
            await call_py.leave_call(chat_id)
        except:
            pass
    
    await app.stop()
    await user_app.stop()
    print("👋 Bot stopped")

if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        print("\n👋 Shutdown requested")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)

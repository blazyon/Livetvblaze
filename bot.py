import asyncio
import aiohttp
from io import BytesIO
from pyrogram import Client, filters, idle
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, VideoQuality
from flask import Flask
from threading import Thread

# ================= Configuration =================
API_ID = 24168862  # Replace with your API ID
API_HASH = "916a9424dd1e58ab7955001ccc0172b3" # Replace with your API Hash
BOT_TOKEN = "8544679303:AAFW5OwWCbQ969yjP2lgaHReWv4Bg6Iqdas" # Replace with your Bot Token
SESSION_STRING = "AQFwyZ4AQIYVMp0lZPimo8SGiPHWKWz3abADxyPoBxoJZGz951EGeKdCgdBq4WSt6PKzK0Po0QBjZ_763G4Dljz8CyVjym4iZpGKGTi9WDBotthR06zuS1WgapVzCIPxflHjlqee7WC3eLyorj-RF2_8vEP28vyrPgSt7VK67iONk0Aj5BQlLBzBZ72ofaUkTbKzniBjcvftjlEtluoJboImLD3cuFWAClSGqzFmLXx7dJIz--d2Y49g3KdsZAvmuGIt9pQP93BY1DV_WqJ4EmYUfRq4KNRPf37irjDDwO4BOZhtfXh-fE1mb17I75gNlrWqBXBxKrLyR1QqFBVm_Bm-6ibPZQAAAAH1rRV2AA" # Replace with User String Session
OWNER_ID = 8717767927 # Replace with the Telegram ID of the Owner

# ================= Flask Server for Render =================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return """
    <html>
        <body style="background: #1a1a2e; color: #e94560; font-family: Arial; text-align: center; padding-top: 100px;">
            <h1>📺 Live TV VC Bot</h1>
            <p>Status: ✅ Running</p>
            <p>Stream Quality: 360p Stable</p>
        </body>
    </html>
    """

@flask_app.route('/health')
def health():
    return {"status": "ok", "service": "telegram-tv-bot"}, 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=8080, debug=False)

# ================= Initialize Clients =================
app = Client("tv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
call_py = PyTgCalls(user_app)

CHANNELS = {}
active_chats = set()

# ================= Stream URL Handler =================
def normalize_stream_url(url: str) -> tuple:
    """
    Detect link type and return the correct media path & custom ffmpeg params.
    Returns (processed_url, ffmpeg_parameters)
    """
    url = url.strip()
    
    # Common connection parameters for unstable links
    reconnect_params = "-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 10"
    timeout_params = "-timeout 10000000"
    
    # 1. API Redirect links (vercel, api endpoints)
    if "vercel.app/api/play" in url or "/api/play?id=" in url or "api/play" in url:
        return url, f"{reconnect_params} {timeout_params} -user_agent \"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\" -http_persistent 1"
    
    # 2. Direct .ts segment links
    if url.endswith('.ts'):
        return url, f"{reconnect_params} {timeout_params} -analyzeduration 10000000 -probesize 10000000"
    
    # 3. HTTP (non-SSL) links on custom ports
    if url.startswith("http://"):
        return url, f"{reconnect_params} {timeout_params} -multiple_requests 1 -http_persistent 0"
    
    # 4. HTTPS m3u8 links
    if ".m3u8" in url:
        return url, f"{reconnect_params} {timeout_params}"
    
    # 5. Fallback for any other link type
    return url, f"{reconnect_params} {timeout_params} -analyzeduration 10000000 -probesize 10000000"

# ================= General Commands =================
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply(
        "📺 **Live TV VC Bot is Running!**\n\n"
        "**Available Commands:**\n"
        "• `/channels` - List all available channels\n"
        "• `/livetv Channel Name` - Play a channel in VC\n"
        "• `/stopvc` - Stop streaming in group\n"
        "• `/ping` - Check if bot is alive\n\n"
        "📊 **Default Quality:** 360p (Stable)"
    )

@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    if not CHANNELS:
        return await message.reply("❌ No channels are currently loaded. Ask the admin to add some!")
    
    text = "📺 **Available Channels List:**\n*(Tap a name to copy it!)*\n\n"
    for name in CHANNELS.keys():
        text += f"• `{name.title()}`\n"
    
    if len(text) > 4000:
        file_bytes = BytesIO(text.encode("utf-8"))
        file_bytes.name = "channels_list.txt"
        await message.reply_document(file_bytes, caption=f"📺 **{len(CHANNELS)} channels available!**\n\nFull list attached.")
    else:
        await message.reply(text)

@app.on_message(filters.command("livetv"))
async def play_live_tv(client, message):
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        return await message.reply(
            "**Usage:** `/livetv <Channel Name>`\n\n"
            "Example: `/livetv Star Sports`"
        )
    
    channel_name = message.text.split(None, 1)[1].strip().lower()
    
    if channel_name not in CHANNELS:
        return await message.reply(
            f"❌ **Channel not found!**\nUse `/channels` for the exact list."
        )
    
    raw_url = CHANNELS[channel_name]
    
    # Detect link type for user info
    if "api/play" in raw_url:
        link_type = "API Redirect"
    elif raw_url.endswith('.ts'):
        link_type = "TS Segment"
    elif raw_url.startswith("http://"):
        link_type = "HTTP Stream"
    elif ".m3u8" in raw_url:
        link_type = "HLS Stream"
    else:
        link_type = "Custom Stream"
    
    msg = await message.reply(
        f"⏳ **Connecting...**\n"
        f"📺 Channel: {channel_name.title()}\n"
        f"🔗 Type: {link_type}\n"
        f"📊 Quality: 360p Stable\n\n"
        f"Please wait..."
    )
    
    try:
        # Get the optimized URL and FFmpeg parameters
        stream_url, custom_ffmpeg = normalize_stream_url(raw_url)
        
        # Base stable 360p FFmpeg parameters
        base_ffmpeg = "-preset ultrafast -tune zerolatency -fflags nobuffer -flags low_delay -strict experimental -bufsize 500k -maxrate 350k"
        
        # Combine base + custom parameters
        combined_ffmpeg = f"{base_ffmpeg} {custom_ffmpeg}"
        
        await call_py.play(
            chat_id,
            MediaStream(
                media_path=stream_url,
                video_parameters=VideoQuality.SD_360p,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Connection": "keep-alive",
                    "Sec-Fetch-Dest": "video",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "cross-site"
                },
                ffmpeg_parameters=combined_ffmpeg
            )
        )
        active_chats.add(chat_id)
        
        await msg.edit_text(
            f"▶️ **Now Playing!**\n"
            f"📺 **Channel:** {channel_name.title()}\n"
            f"📊 **Quality:** 360p Stable\n"
            f"🔗 **Type:** {link_type}\n"
            f"🎯 **Status:** Live Streaming\n\n"
            f"Use `/stopvc` to stop."
        )
    except Exception as e:
        error_str = str(e)
        debug_info = f"Stream URL: {raw_url[:80]}..."
        await msg.edit_text(
            f"❌ **Playback Error!**\n\n"
            f"**Issue:** `{error_str[:200]}`\n\n"
            f"**Debug Info:**\n`{debug_info}`\n\n"
            f"**Troubleshooting:**\n"
            f"• Ensure Voice Chat is active in this chat\n"
            f"• Check if the stream URL is still valid\n"
            f"• Try again in a few seconds\n"
            f"• Some streams may be geo-restricted\n"
            f"• Contact admin if issue persists"
        )

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        active_chats.discard(message.chat.id)
        await message.reply("⏹ **Stopped!**\n📺 Stream ended\n🔇 Left Voice Chat")
    except Exception as e:
        await message.reply(f"❌ Could not stop: `{str(e)[:100]}`")

@app.on_message(filters.command("ping"))
async def ping_cmd(client, message):
    await message.reply("🏓 **Pong!** Bot is active and running smoothly!")

@app.on_message(filters.command("status"))
async def status_cmd(client, message):
    active = len(active_chats)
    total_channels = len(CHANNELS)
    await message.reply(
        f"📊 **Bot Status**\n\n"
        f"• **Active Streams:** {active}\n"
        f"• **Total Channels:** {total_channels}\n"
        f"• **Quality Mode:** 360p Stable\n"
        f"• **Uptime:** Bot is running"
    )

# ================= Owner Commands =================
@app.on_message(filters.command("addxtream") & filters.user(OWNER_ID))
async def add_xtream(client, message):
    args = message.text.split(" ")
    if len(args) != 4:
        return await message.reply(
            "**Usage:** `/addxtream <URL> <Username> <Password>`\n\n"
            "Example: `/addxtream http://example.com:8080 user123 pass456`"
        )
    
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    msg = await message.reply("🔄 **Fetching channels...**\nConnecting to Xtream Server...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    count = 0
                    added_channels = []
                    
                    for stream in data:
                        name = stream.get("name", "").strip().lower()
                        if name:
                            stream_url = f"{url}/live/{user}/{passwd}/{stream.get('stream_id')}.m3u8"
                            CHANNELS[name] = stream_url
                            count += 1
                            if count <= 10:
                                added_channels.append(name.title())
                    
                    response = f"✅ **Successfully loaded {count} channels!**\n\n"
                    if added_channels:
                        response += "**First 10 channels:**\n"
                        for ch in added_channels:
                            response += f"• `{ch}`\n"
                    response += f"\nUse `/channels` to see all."
                    
                    await msg.edit_text(response)
                else:
                    await msg.edit_text(f"❌ **Server Error!**\nHTTP Status: {resp.status}\nCheck your credentials.")
    except aiohttp.ClientError as e:
        await msg.edit_text(f"❌ **Connection Error!**\n`{str(e)[:200]}`\n\nCheck if the server URL is correct and accessible.")
    except Exception as e:
        await msg.edit_text(f"❌ **Error:** `{str(e)[:200]}`")

@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply(
            "**Usage:** `/addchannel <Stream URL> <Channel Name>`\n\n"
            "Example: `/addchannel https://example.com/stream.m3u8 Star Sports`"
        )
    
    stream_url = args[1].strip()
    channel_name = args[2].strip().lower()
    
    CHANNELS[channel_name] = stream_url
    await message.reply(f"✅ **Channel Added!**\n📺 Name: **{channel_name.title()}**\n🔗 URL: `{stream_url[:50]}...`")

@app.on_message(filters.command("editchannel") & filters.user(OWNER_ID))
async def edit_channel(client, message):
    try:
        parts = [p.strip() for p in message.text.split(None, 1)[1].split('|')]
        if len(parts) != 3:
            return await message.reply("**Usage:** `/editchannel Old Name | New Name | New Link`")
        
        old_name, new_name, new_link = parts[0].lower(), parts[1].lower(), parts[2]
        
        if old_name not in CHANNELS:
            return await message.reply(f"❌ Channel `{old_name.title()}` not found!")
        
        if old_name != new_name:
            del CHANNELS[old_name]
        
        CHANNELS[new_name] = new_link
        await message.reply(
            f"✅ **Channel Updated!**\n"
            f"📺 Old: `{old_name.title()}`\n"
            f"📺 New: `{new_name.title()}`\n"
            f"🔗 Link: `{new_link[:50]}...`"
        )
    except Exception as e:
        await message.reply(f"❌ **Error!**\nUsage: `/editchannel Old Name | New Name | New Link`\n\n`{str(e)[:100]}`")

@app.on_message(filters.command("delchannel") & filters.user(OWNER_ID))
async def delete_channel(client, message):
    try:
        name = message.text.split(None, 1)[1].strip().lower()
        if name in CHANNELS:
            del CHANNELS[name]
            await message.reply(f"🗑️ **Deleted!** Channel: `{name.title()}`")
        else:
            await message.reply(f"❌ Channel `{name.title()}` not found!")
    except:
        await message.reply("**Usage:** `/delchannel <Channel Name>`")

@app.on_message(filters.command("clearchannels") & filters.user(OWNER_ID))
async def clear_all_channels(client, message):
    count = len(CHANNELS)
    CHANNELS.clear()
    await message.reply(f"🗑️ **All {count} channels cleared!**")

@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast_status(client, message):
    if active_chats:
        for chat_id in active_chats:
            try:
                await app.send_message(chat_id, "🔄 **Bot is still active!** Streaming continues...")
            except:
                pass
        await message.reply(f"✅ Broadcast sent to {len(active_chats)} active chats.")
    else:
        await message.reply("❌ No active streams to broadcast to.")

# ================= Boot Process =================
async def main():
    # Start Flask server in separate thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("🌐 Flask HTTP Server started on port 8080")
    print("📍 Health check: http://0.0.0.0:8080/health")
    
    print("🤖 Starting Bot Client...")
    await app.start()
    print("👤 Starting User Client...")
    await user_app.start()
    print("🎥 Starting PyTgCalls...")
    await call_py.start()
    
    print("✅ Bot is fully operational!")
    print(f"📺 Default Quality: 360p Stable")
    print(f"🎯 Owner ID: {OWNER_ID}")
    print("=" * 50)
    
    # Notify owner
    try:
        await app.send_message(
            OWNER_ID,
            "🟢 **Bot Deployed Successfully!**\n\n"
            "✅ All systems operational\n"
            "📊 Stream Quality: 360p Stable\n"
            "🌐 HTTP Server: Active on port 8080\n"
            "⚡ Ready to stream!"
        )
    except:
        print("⚠️ Could not send startup notification to owner")
    
    await idle()
    
    # Cleanup on shutdown
    print("🔄 Shutting down...")
    for chat_id in active_chats.copy():
        try:
            await call_py.leave_call(chat_id)
        except:
            pass
    await app.stop()
    await user_app.stop()

if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        print("👋 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")

import asyncio
import aiohttp
from io import BytesIO
from pyrogram import Client, filters, idle
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, VideoQuality, AudioVideoPiped
from flask import Flask
from threading import Thread

# ================= Configuration =================
API_ID = 24168862
API_HASH = "916a9424dd1e58ab7955001ccc0172b3"
BOT_TOKEN = "8544679303:AAFW5OwWCbQ969yjP2lgaHReWv4Bg6Iqdas"
SESSION_STRING = "AQFwyZ4AQIYVMp0lZPimo8SGiPHWKWz3abADxyPoBxoJZGz951EGeKdCgdBq4WSt6PKzK0Po0QBjZ_763G4Dljz8CyVjym4iZpGKGTi9WDBotthR06zuS1WgapVzCIPxflHjlqee7WC3eLyorj-RF2_8vEP28vyrPgSt7VK67iONk0Aj5BQlLBzBZ72ofaUkTbKzniBjcvftjlEtluoJboImLD3cuFWAClSGqzFmLXx7dJIz--d2Y49g3KdsZAvmuGIt9pQP93BY1DV_WqJ4EmYUfRq4KNRPf37irjDDwO4BOZhtfXh-fE1mb17I75gNlrWqBXBxKrLyR1QqFBVm_Bm-6ibPZQAAAAH1rRV2AA"
OWNER_ID = 8717767927

# ================= Flask Server for Render =================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return """
    <html>
        <body style="background: #1a1a2e; color: #e94560; font-family: Arial; text-align: center; padding-top: 100px;">
            <h1>📺 Live TV VC Bot</h1>
            <p>Status: ✅ Running</p>
            <p>Stream Quality: 360p Smooth</p>
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

# ================= Optimized FFmpeg Parameters =================
# These parameters ensure video matches audio timeline
STREAM_PARAMS = (
    "-reconnect 1 "
    "-reconnect_at_eof 1 "
    "-reconnect_streamed 1 "
    "-reconnect_delay_max 5 "
    "-fflags +genpts+discardcorrupt "
    "-avoid_negative_ts make_zero "
    "-vsync vfr "
    "-async 1 "
    "-r 24 "  # Force 24fps for smooth playback
    "-vf scale=640:360:force_original_aspect_ratio=decrease,fps=24,setpts=PTS-STARTPTS "
    "-af aresample=async=1:min_hard_comp=0.100000:first_pts=0 "
    "-preset ultrafast "
    "-tune zerolatency "
    "-c:v libx264 "
    "-crf 28 "
    "-maxrate 400k "
    "-bufsize 800k "
    "-pix_fmt yuv420p "
    "-g 48 "
    "-keyint_min 48 "
    "-sc_threshold 0 "
    "-threads 2 "
    "-strict experimental "
    "-map_metadata -1 "
    "-fflags +genpts "
    "-flags low_delay "
    "-probesize 32 "
    "-analyzeduration 0"
)

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
        "📊 **Quality:** 360p Smooth (24fps Synced)"
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
            f"❌ **Channel not found!**\n\n"
            f"Use `/channels` to see the exact names."
        )
    
    stream_url = CHANNELS[channel_name]
    msg = await message.reply(f"⏳ **Buffering...**\n📺 {channel_name.title()}\n📊 360p Smooth\n\nSyncing audio & video...")
    
    try:
        await call_py.play(
            chat_id,
            MediaStream(
                media_path=stream_url,
                video_parameters=VideoQuality.SD_360p,
                audio_parameters=MediaStream.audio_parameters,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
                ffmpeg_parameters=STREAM_PARAMS
            )
        )
        active_chats.add(chat_id)
        await msg.edit_text(
            f"▶️ **Now Playing!**\n"
            f"📺 **{channel_name.title()}**\n"
            f"📊 **Quality:** 360p Smooth\n"
            f"🎬 **FPS:** 24 (Synced)\n"
            f"🔊 **Audio:** In Sync\n\n"
            f"Use `/stopvc` to stop."
        )
    except Exception as e:
        await msg.edit_text(
            f"❌ **Error!**\n\n"
            f"`{str(e)[:200]}`\n\n"
            f"• Make sure Voice Chat is active\n"
            f"• Try again in few seconds"
        )

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        active_chats.discard(message.chat.id)
        await message.reply("⏹ **Stopped!** Stream ended successfully.")
    except Exception as e:
        await message.reply(f"❌ Error: `{str(e)[:100]}`")

@app.on_message(filters.command("ping"))
async def ping_cmd(client, message):
    await message.reply("🏓 **Pong!** Bot is active!")

@app.on_message(filters.command("status"))
async def status_cmd(client, message):
    active = len(active_chats)
    total_channels = len(CHANNELS)
    await message.reply(
        f"📊 **Bot Status**\n\n"
        f"• **Active Streams:** {active}\n"
        f"• **Total Channels:** {total_channels}\n"
        f"• **Quality:** 360p Smooth (24fps)\n"
        f"• **Status:** ✅ Running"
    )

# ================= Owner Commands =================
@app.on_message(filters.command("addxtream") & filters.user(OWNER_ID))
async def add_xtream(client, message):
    args = message.text.split(" ")
    if len(args) != 4:
        return await message.reply("**Usage:** `/addxtream <URL> <Username> <Password>`")
    
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    msg = await message.reply("🔄 **Fetching channels from Xtream Server...**")
    
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
                    await msg.edit_text(f"✅ **Loaded {count} channels!**\nUse `/channels` to see all.")
                else:
                    await msg.edit_text(f"❌ Server Error! HTTP: {resp.status}")
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{str(e)[:200]}`")

@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply("**Usage:** `/addchannel <Stream URL> <Channel Name>`")
    
    CHANNELS[args[2].strip().lower()] = args[1].strip()
    await message.reply(f"✅ Added: **{args[2].title()}**")

@app.on_message(filters.command("editchannel") & filters.user(OWNER_ID))
async def edit_channel(client, message):
    try:
        parts = [p.strip() for p in message.text.split(None, 1)[1].split('|')]
        old_name, new_name, new_link = parts[0].lower(), parts[1].lower(), parts[2]
        if old_name not in CHANNELS:
            return await message.reply(f"❌ Channel not found!")
        if old_name != new_name:
            del CHANNELS[old_name]
        CHANNELS[new_name] = new_link
        await message.reply(f"✅ Updated: **{new_name.title()}**")
    except:
        await message.reply("**Usage:** `/editchannel Old Name | New Name | New Link`")

@app.on_message(filters.command("delchannel") & filters.user(OWNER_ID))
async def delete_channel(client, message):
    try:
        name = message.text.split(None, 1)[1].strip().lower()
        if name in CHANNELS:
            del CHANNELS[name]
            await message.reply(f"🗑️ Deleted: **{name.title()}**")
        else:
            await message.reply("❌ Channel not found!")
    except:
        await message.reply("**Usage:** `/delchannel <Channel Name>`")

@app.on_message(filters.command("clearchannels") & filters.user(OWNER_ID))
async def clear_all_channels(client, message):
    count = len(CHANNELS)
    CHANNELS.clear()
    await message.reply(f"🗑️ **All {count} channels cleared!**")

# ================= Alternative Stream Method (If Still Lagging) =================
@app.on_message(filters.command("livetv2") & filters.user(OWNER_ID))
async def play_live_tv_alternative(client, message):
    """Alternative method if main method still has sync issues"""
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/livetv2 <Channel Name>`")
    
    channel_name = message.text.split(None, 1)[1].strip().lower()
    
    if channel_name not in CHANNELS:
        return await message.reply("❌ Channel not found!")
    
    stream_url = CHANNELS[channel_name]
    msg = await message.reply(f"⏳ **Starting Alternative Stream...**\n📺 {channel_name.title()}")
    
    # Alternative FFmpeg parameters with different sync approach
    alt_params = (
        "-reconnect 1 "
        "-reconnect_at_eof 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5 "
        "-fflags +genpts "
        "-async 1 "
        "-vsync 1 "
        "-r 25 "
        "-vf fps=25,scale=640:360,setsar=1:1 "
        "-c:v libx264 "
        "-preset ultrafast "
        "-tune zerolatency "
        "-crf 30 "
        "-maxrate 300k "
        "-bufsize 600k "
        "-g 50 "
        "-profile:v baseline "
        "-level 3.0 "
        "-pix_fmt yuv420p "
        "-c:a aac "
        "-b:a 64k "
        "-ar 44100 "
        "-ac 1 "
        "-af aresample=async=1 "
        "-threads 2 "
        "-strict experimental"
    )
    
    try:
        await call_py.play(
            chat_id,
            MediaStream(
                media_path=stream_url,
                video_parameters=VideoQuality.SD_360p,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
                ffmpeg_parameters=alt_params
            )
        )
        active_chats.add(chat_id)
        await msg.edit_text(f"▶️ **Playing!** {channel_name.title()}\n📊 360p (Alternative Mode)")
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{str(e)[:200]}`")

# ================= Boot Process =================
async def main():
    # Start Flask server
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("🌐 Flask HTTP Server on port 8080")
    
    print("🤖 Starting Bot Client...")
    await app.start()
    print("👤 Starting User Client...")
    await user_app.start()
    print("🎥 Starting PyTgCalls...")
    await call_py.start()
    
    print("✅ Bot is fully operational!")
    print("📺 Quality: 360p Smooth (24fps Audio/Video Synced)")
    print("🎬 Alternative mode available: /livetv2")
    
    try:
        await app.send_message(
            OWNER_ID,
            "🟢 **Bot Deployed!**\n\n"
            "✅ All systems operational\n"
            "📊 360p Smooth (24fps Synced)\n"
            "🎬 Use /livetv2 for alternative encoding\n"
            "🌐 HTTP Server: Active"
        )
    except:
        pass
    
    await idle()

if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        print("👋 Bot stopped")
    except Exception as e:
        print(f"❌ Fatal error: {e}")

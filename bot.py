import asyncio
import aiohttp
import sys
import traceback
from io import BytesIO
from pyrogram import Client, filters, idle
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, VideoQuality
from flask import Flask
from threading import Thread
import logging

# ================= Logging Setup =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================= Configuration =================
API_ID = 24168862
API_HASH = "916a9424dd1e58ab7955001ccc0172b3"
BOT_TOKEN = "8544679303:AAFW5OwWCbQ969yjP2lgaHReWv4Bg6Iqdas"
SESSION_STRING = "AQFwyZ4AQIYVMp0lZPimo8SGiPHWKWz3abADxyPoBxoJZGz951EGeKdCgdBq4WSt6PKzK0Po0QBjZ_763G4Dljz8CyVjym4iZpGKGTi9WDBotthR06zuS1WgapVzCIPxflHjlqee7WC3eLyorj-RF2_8vEP28vyrPgSt7VK67iONk0Aj5BQlLBzBZ72ofaUkTbKzniBjcvftjlEtluoJboImLD3cuFWAClSGqzFmLXx7dJIz--d2Y49g3KdsZAvmuGIt9pQP93BY1DV_WqJ4EmYUfRq4KNRPf37irjDDwO4BOZhtfXh-fE1mb17I75gNlrWqBXBxKrLyR1QqFBVm_Bm-6ibPZQAAAAH1rRV2AA"
OWNER_ID = 8717767927

# ================= Flask Server =================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is running!"

@flask_app.route('/health')
def health():
    return {"status": "ok"}, 200

def run_flask():
    try:
        flask_app.run(host='0.0.0.0', port=8080, debug=False)
    except Exception as e:
        logger.error(f"Flask server error: {e}")

# ================= Initialize Clients =================
# Using in-memory session to avoid file conflicts on Render
app = Client(
    "tv_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True  # Important for cloud deployment
)

user_app = Client(
    "user_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
    in_memory=True  # Important for cloud deployment
)

call_py = PyTgCalls(user_app)

CHANNELS = {}
active_chats = set()

# ================= Stream Parameters =================
STREAM_PARAMS = (
    "-reconnect 1 "
    "-reconnect_at_eof 1 "
    "-reconnect_streamed 1 "
    "-reconnect_delay_max 5 "
    "-fflags +genpts+discardcorrupt "
    "-avoid_negative_ts make_zero "
    "-vsync vfr "
    "-async 1 "
    "-r 24 "
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

# ================= Commands =================
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply(
        "📺 **Live TV VC Bot is Running!**\n\n"
        "• `/channels` - List all channels\n"
        "• `/livetv <name>` - Play in VC\n"
        "• `/stopvc` - Stop streaming\n"
        "• `/ping` - Check status"
    )

@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    if not CHANNELS:
        return await message.reply("❌ No channels loaded. Admin needs to add channels!")
    
    text = "📺 **Available Channels:**\n\n"
    for name in CHANNELS.keys():
        text += f"• `{name.title()}`\n"
    
    if len(text) > 4000:
        file_bytes = BytesIO(text.encode("utf-8"))
        file_bytes.name = "channels_list.txt"
        await message.reply_document(file_bytes, caption=f"📺 {len(CHANNELS)} channels available")
    else:
        await message.reply(text)

@app.on_message(filters.command("livetv"))
async def play_live_tv(client, message):
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/livetv <Channel Name>`")
    
    channel_name = message.text.split(None, 1)[1].strip().lower()
    
    if channel_name not in CHANNELS:
        return await message.reply(f"❌ Channel not found! Use `/channels` to see list.")
    
    stream_url = CHANNELS[channel_name]
    msg = await message.reply(f"⏳ Starting **{channel_name.title()}**...")
    
    try:
        await call_py.play(
            chat_id,
            MediaStream(
                media_path=stream_url,
                video_parameters=VideoQuality.SD_360p,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
                ffmpeg_parameters=STREAM_PARAMS
            )
        )
        active_chats.add(chat_id)
        await msg.edit_text(f"▶️ **Now Playing:** {channel_name.title()}")
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{str(e)[:200]}`")

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        active_chats.discard(message.chat.id)
        await message.reply("⏹ Stopped!")
    except Exception as e:
        await message.reply(f"❌ Error: `{str(e)[:100]}`")

@app.on_message(filters.command("ping"))
async def ping_cmd(client, message):
    await message.reply("🏓 Pong! Bot is running!")

# Owner Commands
@app.on_message(filters.command("addxtream") & filters.user(OWNER_ID))
async def add_xtream(client, message):
    args = message.text.split(" ")
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
                    await msg.edit_text(f"✅ Loaded **{count}** channels!")
                else:
                    await msg.edit_text(f"❌ Server returned: {resp.status}")
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{str(e)[:200]}`")

@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply("**Usage:** `/addchannel <URL> <Name>`")
    CHANNELS[args[2].strip().lower()] = args[1].strip()
    await message.reply(f"✅ Added: **{args[2].title()}**")

@app.on_message(filters.command("delchannel") & filters.user(OWNER_ID))
async def delete_channel(client, message):
    try:
        name = message.text.split(None, 1)[1].strip().lower()
        if name in CHANNELS:
            del CHANNELS[name]
            await message.reply(f"🗑️ Deleted: **{name.title()}**")
        else:
            await message.reply("❌ Not found!")
    except:
        await message.reply("**Usage:** `/delchannel <Name>`")

# ================= Main =================
async def main():
    logger.info("Starting services...")
    
    # Start Flask
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("✅ Flask server started on port 8080")
    
    # Start bot client
    logger.info("Starting bot client...")
    await app.start()
    logger.info("✅ Bot client started")
    
    # Start user client
    logger.info("Starting user client...")
    await user_app.start()
    logger.info("✅ User client started")
    
    # Start PyTgCalls
    logger.info("Starting PyTgCalls...")
    await call_py.start()
    logger.info("✅ PyTgCalls started")
    
    logger.info("🎉 Bot is fully operational!")
    
    # Notify owner
    try:
        await app.send_message(OWNER_ID, "🟢 Bot deployed and running!")
    except:
        logger.warning("Could not send startup message to owner")
    
    await idle()

if __name__ == "__main__":
    try:
        logger.info("=" * 50)
        logger.info("Starting bot initialization...")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Working directory: {sys.path[0]}")
        
        asyncio.get_event_loop().run_until_complete(main())
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)

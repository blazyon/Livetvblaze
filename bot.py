import asyncio
import aiohttp
import os
import logging
from io import BytesIO
from pyrogram import Client, filters, idle
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, VideoQuality

# ================= Configuration =================
# Use environment variables (Render style)
API_ID = int(os.environ.get("API_ID", "24168862"))
API_HASH = os.environ.get("API_HASH", "916a9424dd1e58ab7955001ccc0172b3")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8544679303:AAEkAqQxF3vRkWqN38Pxp0XCNiWaLiGaw0g")
SESSION_STRING = os.environ.get("SESSION_STRING", "AQFwyZ4AaJZ8vOvIHm31OJE0LKraKCRHhd3DTgugm1xbZer9Mup5ENyfh_dwInQk1DhV0oVDF7n_ZrAHdSdnrOx_QKIQs8KptXwns2mcEnMB5VKb04_sEXlrmYSHYhtdLs6E42xf9VG2vD8e107XSjmjWkIic_uyteu07F1XPZfLaYcg9mj6-WSDKfcPRefXb_zT85gePO2BWnFD4TP1H_JRm-O1iRqIg1-YcGgsv596WwU0QyD83flBUl8F80j20FB5cDJ3JEwVeGNA3k9MW562lCxaj67zmoKj1rU6j79JhOwrjCq7EtNspxZaML6LZaIOgx_x-gaeQvy6wtMXshnAt0fHZQAAAAH1rRV2AA")  # Put your string here
OWNER_ID = int(os.environ.get("OWNER_ID", "8717767927"))

# ================= Logging =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= Initialize Clients =================
app = Client("tv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
call_py = PyTgCalls(user_app)

# In-memory channel store
CHANNELS = {}

# ================= General Commands =================
@app.on_message(filters.command("start"))
async def start_cmd(_, message):
    await message.reply(
        "📺 **Live TV VC Bot is Running!**\n\n"
        "Use /channels to see all available channels.\n"
        "Use /livetv Channel Name to play a channel."
    )

@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(_, message):
    if not CHANNELS:
        return await message.reply("❌ No channels are currently loaded. Ask the admin to add some!")
    text = "📺 **Available Channels List:**\n*(Tap a name to copy it!)*\n\n"
    for name in CHANNELS.keys():
        text += f"• `{name.title()}`\n"

    if len(text) > 4000:
        file_bytes = BytesIO(text.encode("utf-8"))
        file_bytes.name = "channels_list.txt"
        await message.reply_document(file_bytes, caption="📺 **There are hundreds of channels!**\n\nFull list attached.")
    else:
        await message.reply(text)

@app.on_message(filters.command("livetv"))
async def play_live_tv(_, message):
    chat_id = message.chat.id
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/livetv <Channel Name>`")

    channel_name = message.text.split(None, 1)[1].strip().lower()
    if channel_name not in CHANNELS:
        return await message.reply("❌ Channel not found! Use `/channels` to see the exact names.")

    stream_url = CHANNELS[channel_name]
    msg = await message.reply(f"⏳ Connecting **{channel_name.title()}** to the Voice Chat...")

    try:
        # Play the stream with optimised parameters for speed & stability
        await call_py.play(
            chat_id,
            MediaStream(
                media_path=stream_url,
                # Lower resolution to HD_480p for much less CPU load (still very watchable)
                video_parameters=VideoQuality.HD_480p,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
                # Tweak ffmpeg for glitch‑free low‑latency streaming on weak servers
                ffmpeg_parameters=(
                    "-re "
                    "-preset ultrafast "
                    "-tune zerolatency "
                    "-fflags nobuffer "
                    "-flags low_delay "
                    "-maxrate 600k "
                    "-bufsize 1200k "
                    "-g 60 "
                )
            )
        )
        await msg.edit_text(f"▶️ **Now Playing:** {channel_name.title()} in the Voice Chat!")
        logger.info(f"Stream started in chat {chat_id}: {channel_name}")
    except Exception as e:
        await msg.edit_text(f"❌ Error playing channel. Ensure the Voice Chat is turned on.\n\n`{e}`")
        logger.error(f"Play failed in {chat_id}: {e}")

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(_, message):
    try:
        await call_py.leave_call(message.chat.id)
        await message.reply("⏹ Stopped the stream and left the Voice Chat.")
    except Exception as e:
        await message.reply(f"❌ Could not stop: `{e}`")

# ================= Owner Commands =================
@app.on_message(filters.command("addxtream") & filters.user(OWNER_ID))
async def add_xtream(_, message):
    args = message.text.split()
    if len(args) != 4:
        return await message.reply("**Usage:** `/addxtream <URL> <Username> <Password>`")
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    msg = await message.reply("🔄 Fetching channels from Xtream Server... Please wait.")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    count = 0
                    for stream in data:
                        name = stream.get("name", "").strip().lower()
                        stream_url = f"{url}/live/{user}/{passwd}/{stream.get('stream_id')}.m3u8"
                        CHANNELS[name] = stream_url
                        count += 1
                    await msg.edit_text(f"✅ Successfully loaded **{count}** live channels from Xtream!")
                else:
                    await msg.edit_text("❌ Failed to connect to Xtream Server.")
    except Exception as e:
        await msg.edit_text(f"❌ Error fetching Xtream data: `{e}`")

@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(_, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply("**Usage:** `/addchannel <Stream URL> <Channel Name>`")
    CHANNELS[args[2].strip().lower()] = args[1]
    await message.reply(f"✅ Manually added channel: **{args[2].title()}**")

@app.on_message(filters.command("editchannel") & filters.user(OWNER_ID))
async def edit_channel(_, message):
    try:
        parts = [p.strip() for p in message.text.split(None, 1)[1].split('|')]
        old_name, new_name, new_link = parts[0].lower(), parts[1].lower(), parts[2]
        if old_name not in CHANNELS:
            return await message.reply(f"❌ Channel not found.")
        if old_name != new_name:
            del CHANNELS[old_name]
        CHANNELS[new_name] = new_link
        await message.reply(f"✅ **Updated!**\nName: `{new_name.title()}`\nLink: `{new_link}`")
    except:
        await message.reply("**Usage:** `/editchannel Old Name | New Name | New Link`")

@app.on_message(filters.command("delchannel") & filters.user(OWNER_ID))
async def delete_channel(_, message):
    name = message.text.split(None, 1)[1].strip().lower()
    if name in CHANNELS:
        del CHANNELS[name]
        await message.reply(f"🗑️ Deleted **{name.title()}**.")
    else:
        await message.reply("❌ Channel not found.")

# ================= Boot Process =================
async def main():
    logger.info("Starting Bot Client...")
    await app.start()
    logger.info("Starting User Client...")
    await user_app.start()
    logger.info("Starting PyTgCalls...")
    await call_py.start()
    logger.info("✅ Bot is fully running! Press Ctrl+C to stop.")
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())

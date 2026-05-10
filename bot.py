import asyncio
import aiohttp
from io import BytesIO
from flask import Flask
from threading import Thread
from pyrogram import Client, filters, idle
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, VideoQuality

# ================= Web Server for Render =================
# This keeps Render from sleeping
server = Flask(__name__)
@server.route('/')
def home(): return "Bot is Running"
def run_web(): server.run(host="0.0.0.0", port=8080)

# ================= Configuration =================
API_ID = 24168862 
API_HASH = "916a9424dd1e58ab7955001ccc0172b3"
BOT_TOKEN = "8544679303:AAEkAqQxF3vRkWqN38Pxp0XCNiWaLiGaw0g"
SESSION_STRING = "AQFwyZ4AaJZ8vOvIHm31OJE0LKraKCRHhd3DTgugm1xbZer9Mup5ENyfh_dwInQk1DhV0oVDF7n_ZrAHdSdnrOx_QKIQs8KptXwns2mcEnMB5VKb04_sEXlrmYSHYhtdLs6E42xf9VG2vD8e107XSjmjWkIic_uyteu07F1XPZfLaYcg9mj6-WSDKfcPRefXb_zT85gePO2BWnFD4TP1H_JRm-O1iRqIg1-YcGgsv596WwU0QyD83flBUl8F80j20FB5cDJ3JEwVeGNA3k9MW562lCxaj67zmoKj1rU6j79JhOwrjCq7EtNspxZaML6LZaIOgx_x-gaeQvy6wtMXshnAt0fHZQAAAAH1rRV2AA"
OWNER_ID = 8717767927

# ================= Initialize =================
app = Client("tv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
call_py = PyTgCalls(user_app)

CHANNELS = {}

# ================= Commands =================

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply("🚀 **High-Speed Live TV Bot Active!**\n\nCommands: /channels, /livetv, /stopvc")

@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    if not CHANNELS: return await message.reply("❌ No channels loaded.")
    text = "📺 **Channel List:**\n\n"
    for name in CHANNELS.keys(): text += f"• `{name.title()}`\n"
    if len(text) > 4000:
        file = BytesIO(text.encode()); file.name = "list.txt"
        await message.reply_document(file)
    else: await message.reply(text)

@app.on_message(filters.command("livetv"))
async def play_live_tv(client, message):
    chat_id = message.chat.id
    if len(message.command) < 2: return await message.reply("Usage: /livetv <name>")
    
    name = message.text.split(None, 1)[1].strip().lower()
    if name not in CHANNELS: return await message.reply("❌ Not found.")
    
    stream_url = CHANNELS[name]
    msg = await message.reply(f"⚡ **Fast-Loading:** {name.title()}...")

    try:
        # ULTRALIGHT SETTINGS FOR RENDER
        # -probesize and -analyzeduration set to minimum for instant start
        # 360p ensures the CPU doesn't choke
        await call_py.play(
            chat_id,
            MediaStream(
                media_path=stream_url,
                video_parameters=VideoQuality.SD_360p,
                headers={"User-Agent": "Mozilla/5.0"},
                ffmpeg_parameters="-probesize 32 -analyzeduration 0 -preset ultrafast -tune zerolatency"
            )
        )
        await msg.edit_text(f"▶️ **Playing:** {name.title()}\n💡 *Resolution: 360p (Stable Mode)*")
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")

@app.on_message(filters.command("stopvc"))
async def stop_vc(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        await message.reply("⏹ Stopped.")
    except: pass

# ================= Owner Management =================

@app.on_message(filters.command("addxtream") & filters.user(OWNER_ID))
async def add_xtream(client, message):
    args = message.text.split(" ")
    if len(args) != 4: return await message.reply("Usage: /addxtream <url> <user> <pass>")
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    m = await message.reply("Loading...")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(api) as r:
                data = await r.json()
                for s in data:
                    CHANNELS[s.get("name").strip().lower()] = f"{url}/live/{user}/{passwd}/{s.get('stream_id')}.m3u8"
                await m.edit_text(f"✅ Loaded {len(data)} channels.")
    except Exception as e: await m.edit_text(f"Err: {e}")

@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def manual(client, message):
    args = message.text.split(None, 2)
    CHANNELS[args[2].strip().lower()] = args[1]
    await message.reply("✅ Added.")

# ================= Start Up =================

async def main():
    # Start Web Server in background
    Thread(target=run_web).start()
    
    print("Starting clients...")
    await app.start()
    await user_app.start()
    await call_py.start()
    print("✅ Bot is online!")
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())

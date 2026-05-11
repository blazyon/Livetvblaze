import asyncio
import aiohttp
from io import BytesIO
from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls import idle as pytgcalls_idle  # ✅ Imported PyTgCalls' own idle
from pytgcalls.types import MediaStream, VideoQuality

# ================= Configuration =================
# 🚨 WARNING: Please reset your Session String and Bot Token after your bot is working! 
# They are currently exposed since you shared them.
API_ID = 24168862  
API_HASH = "916a9424dd1e58ab7955001ccc0172b3" 
BOT_TOKEN = "8544679303:AAEkAqQxF3vRkWqN38Pxp0XCNiWaLiGaw0g" 
SESSION_STRING = "AQFwyZ4AGRb0xsBw8mH1-oFL5zJJtWmCGXGLB7N4B4xJ0WC_FTTyEaQ9TTgHqCa_La19Q5C87dMqDqt0dD1oGiipmeFNRGhsTq8igTDPQ7mPuPHqjnCNr9cCqzfL2sPw2pg_t6VQt1AuIb8Z25p0aklNnbLRffl7wtG9zT7fjRRqL_aA3OD99f9kHRy8r40_DYmEHMHRkKygfAafXZYXyasQOO12U1yQMYL_TfClFMi2kBsaulomQBYuYYOHrcbcmIRVSn3wBIWJrCp2T597dfHzIStSkwAjYZ9gt4teTGg_2cb86cTsDygGAC10lp6xpZ6ZODtDpwipB7eydNnznRUHVK00iAAAAAH1rRV2AA" 
OWNER_ID = 8717767927 

# ================= Initialize Clients =================
app = Client("tv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
call_py = PyTgCalls(user_app)

CHANNELS = {}

# ================= General Commands =================
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply("📺 **Live TV VC Bot is Running!**\n\nUse `/channels` to see all available channels.\nUse `/livetv Channel Name` to play a channel.")

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
        await message.reply_document(file_bytes, caption="📺 **There are hundreds of channels!**\n\nFull list attached.")
    else:
        await message.reply(text)

@app.on_message(filters.command("livetv"))
async def play_live_tv(client, message):
    chat_id = message.chat.id
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/livetv <Channel Name>`")
    
    channel_name = message.text.split(None, 1)[1].strip().lower()
    
    if channel_name not in CHANNELS:
        return await message.reply("❌ Channel not found! Use `/channels` to see the exact names.")
    
    stream_url = CHANNELS[channel_name]
    msg = await message.reply(f"⏳ Connecting **{channel_name.title()}** to the Voice Chat...")
    
    try:
        await call_py.play(
            chat_id,
            MediaStream(
                media_path=stream_url,
                video_parameters=VideoQuality.HD_720p,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                ffmpeg_parameters="-preset ultrafast -tune zerolatency -fflags nobuffer"
            )
        )
        await msg.edit_text(f"▶️ **Now Playing:** {channel_name.title()} in the Voice Chat!")
    except Exception as e:
        await msg.edit_text(f"❌ Error playing channel. Ensure the Voice Chat is turned on.\n\n`{e}`")

@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        await message.reply("⏹ Stopped the stream and left the Voice Chat.")
    except Exception as e:
        await message.reply(f"❌ Could not stop: `{e}`")

# ================= Owner Commands =================
@app.on_message(filters.command("addxtream") & filters.user(OWNER_ID))
async def add_xtream(client, message):
    args = message.text.split(" ")
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
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3: return await message.reply("**Usage:** `/addchannel <Stream URL> <Channel Name>`")
    CHANNELS[args[2].strip().lower()] = args[1]
    await message.reply(f"✅ Manually added channel: **{args[2].title()}**")

@app.on_message(filters.command("editchannel") & filters.user(OWNER_ID))
async def edit_channel(client, message):
    try:
        parts =[p.strip() for p in message.text.split(None, 1)[1].split('|')]
        old_name, new_name, new_link = parts[0].lower(), parts[1].lower(), parts[2]
        if old_name not in CHANNELS: return await message.reply(f"❌ Channel not found.")
        if old_name != new_name: del CHANNELS[old_name]
        CHANNELS[new_name] = new_link
        await message.reply(f"✅ **Updated!**\nName: `{new_name.title()}`\nLink: `{new_link}`")
    except:
        await message.reply("**Usage:** `/editchannel Old Name | New Name | New Link`")

@app.on_message(filters.command("delchannel") & filters.user(OWNER_ID))
async def delete_channel(client, message):
    name = message.text.split(None, 1)[1].strip().lower()
    if name in CHANNELS:
        del CHANNELS[name]
        await message.reply(f"🗑️ Deleted **{name.title()}**.")
    else:
        await message.reply("❌ Channel not found.")

# ================= Boot Process =================
async def main():
    print("Starting Bot Client...")
    await app.start()
    
    print("Starting User Client & PyTgCalls...")
    await user_app.start() # Ensure User App starts properly first
    await call_py.start()  # Then bind PyTgCalls to it
    
    print("✅ Bot is fully running! Press Ctrl+C to stop.")
    
    # ✅ Fixed: Using PyTgCalls native idle to keep the connection alive
    await pytgcalls_idle()

if __name__ == "__main__":
    # ✅ Fixed: Using asyncio.run() properly starts the event loop
    asyncio.run(main())

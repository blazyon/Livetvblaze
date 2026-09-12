import asyncio
import json
import os
import re
import time
import uuid
from html import escape as esc
from io import BytesIO
from threading import Thread

import aiohttp
from flask import Flask
from pyrogram import Client, filters, idle
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import UserAlreadyParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, VideoQuality

# ================= Configuration =================
# SECURITY: these should live in Railway/host environment variables, not in this file.
# The values below are fallbacks so the bot keeps running if the env vars aren't set yet,
# but you should rotate the bot token + session string and set them as env vars ASAP,
# since this file may end up in git history / shared zips.
API_ID = int(os.environ.get("API_ID", "33181534"))
API_HASH = os.environ.get("API_HASH", "ef2c1ed56bb1fc743b3fbc244582efbb")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8524475183:AAGglXOt2oLCyv2N1vC_R_1gV7T9dvEOWfI")
SESSION_STRING = os.environ.get(
    "SESSION_STRING",
    "BQH6T14ALjIjmZAb8MlRkWdpYDT3va81anw3Qf1RFcqA46KnAbzyjFIikJkEjQ98jz0XUn97iuQg0XmrtVw7Ul5OIuzlpahfD5UyWY94aMpf9-WwyZi6V1N0mKKLTMXIY_1SZuV_S4VDNWGCSXEAuwZ41JJdvrxSrIavDjp50667qAGinuVw40QeKbs3Q2XooskSvzRqh1O0UxQBMddBDE83eG9ViW-S5X_2nqUzhZTP_-YhZ9m7xjWf1NwsdoCqf0cT6aYniKt38lb5D0uyq_s72BCRqZhSEb2S_ZD2LCycZ80g9rXeMFNrH7CinhxgjYz5O2iyHzKuJmH7Jvkhl8BruYeIXwAAAAILtc1CAA",
)
OWNER_ID = int(os.environ.get("OWNER_ID", "8242523973"))
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")  # get a free key at themoviedb.org
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/MeowpawSupport")
UPDATES_URL = os.environ.get("UPDATES_URL", "https://t.me/MeowpawSupport")

BOT_NAME = "ɱεσω รƭ૨εαɱ 📺"
PORT = int(os.environ.get("PORT", 8080))

# ================= Storage & Settings =================
CHANNELS, MOVIES, SERIES = {}, {}, {}
CHANNEL_LOGOS = {}          # channel_name -> logo url
APPROVED_GROUPS = set()
CURRENT_STREAMS = {}        # chat_id -> dict(url, name, type, msg_id, token, start_ts, offset, duration, media_type, key)
RESUME_POSITIONS = {}       # "chat_id:key" -> elapsed_seconds
PLAY_REQUESTS = {}
PENDING_LOGO_UPLOAD = {}    # owner_id -> channel_name awaiting a photo
TMDB_CACHE = {}             # title -> {"backdrop": url, "runtime": minutes}
LIST_FILE_THRESHOLD = 100

QUALITY_PRESETS = {
    "360p": VideoQuality.SD_360p, "480p": VideoQuality.SD_480p,
    "720p": VideoQuality.HD_720p, "1080p": VideoQuality.FHD_1080p,
}

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.json")
START_BANNER_URL = os.environ.get("START_BANNER_URL", "https://i.ibb.co/5WjFTqvr/file-0000000093dc820bbaf14a91927d4a4c.png")
_start_banner_file_id = None  # cached after first send so Telegram doesn't re-fetch the URL every time

# Known Telegram message-effect IDs (fire / thumbs-up / heart / party / thumbs-down / poop)
EFFECT_IDS = {
    "fire": "5104841245755180586",
    "like": "5107584321108051014",
    "heart": "5159385139981059251",
    "party": "5046509860389126442",
    "dislike": "5104858069142078462",
}

# ================= Premium Emoji (from your provided pack) =================
def pe(emoji_id, fallback):
    return f"<tg-emoji emoji-id='{emoji_id}'>{fallback}</tg-emoji>"

E_CHECK = pe("5084979757905347540", "✅")
E_FIRE = pe("5116414868357907335", "🔥")
E_BOLT = pe("5085022089103016925", "⚡️")
E_STAR = pe("5116163917713769254", "⭐️")
E_STOP = pe("5134537521518085000", "⏹")
E_UP = pe("5116395218882528029", "⏫")
E_DOWN = pe("5116204921766544244", "⏬")
E_DENY = pe("5116151848855667552", "🚫")
E_WARN = pe("4915853119839011973", "⚠️")
E_PIN = pe("5107195471948940313", "📍")
E_SPARK = pe("5104960787579929462", "✨")
E_CAM = pe("5118744200921219799", "🎥")
E_CAT = pe("5123237479742178762", "🐈")
E_SIGNAL = pe("5121007227779416740", "📶")
E_BELL = pe("4915820259044230152", "🔔")
E_NEW = pe("4918438965029110683", "🆕")
E_LINK = pe("4916086774649848789", "🔗")

CREDITS = f"\n\n{E_BOLT} <b>Made By <a href='tg://user?id={OWNER_ID}'>ɱεσω</a></b>"

# ================= Stylized font (small caps, as provided) =================
_FANCY = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ғ', 'g': 'ɢ',
    'h': 'ʜ', 'i': 'ɪ', 'j': 'ɪ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ',
    'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 's', 't': 'ᴛ', 'u': 'ᴜ',
    'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ',
}


def fancy(text: str) -> str:
    return "".join(_FANCY.get(c.lower(), c) for c in text)


def quote(text: str) -> str:
    """Wrap message body in Telegram's blockquote formatting."""
    return f"<blockquote>{text}</blockquote>"


def fmt_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def progress_bar(elapsed: int, total: int, length: int = 12) -> str:
    if not total or total <= 0:
        return "🔴 <b>LIVE</b>"
    ratio = max(0.0, min(1.0, elapsed / total))
    filled = int(ratio * length)
    bar = "●" + "─" * filled + "◉" + "─" * (length - filled)
    return f"{fmt_time(elapsed)} {bar} -{fmt_time(max(0, total - elapsed))}"


# ================= Persistence =================
def save_data():
    try:
        payload = {
            "channels": CHANNELS,
            "movies": MOVIES,
            "series": SERIES,
            "channel_logos": CHANNEL_LOGOS,
            "approved_groups": list(APPROVED_GROUPS),
            "resume_positions": RESUME_POSITIONS,
            "start_banner_file_id": _start_banner_file_id,
        }
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, DATA_FILE)
    except Exception as e:
        print(f"⚠️ save_data failed: {e}")


def load_data():
    global _start_banner_file_id
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        CHANNELS.update(payload.get("channels", {}))
        MOVIES.update(payload.get("movies", {}))
        SERIES.update(payload.get("series", {}))
        CHANNEL_LOGOS.update(payload.get("channel_logos", {}))
        APPROVED_GROUPS.update(payload.get("approved_groups", []))
        RESUME_POSITIONS.update(payload.get("resume_positions", {}))
        _start_banner_file_id = payload.get("start_banner_file_id")
        print(f"✅ Loaded persisted data: {len(CHANNELS)} channels, {len(MOVIES)} movies, {len(SERIES)} series")
    except Exception as e:
        print(f"⚠️ load_data failed: {e}")


# ================= TMDB =================
async def fetch_tmdb_art(title: str, media_type: str):
    """media_type: 'movie' or 'tv'. Returns dict with backdrop url, logo url, and runtime (minutes) or None."""
    if not TMDB_API_KEY:
        return None
    cache_key = f"{media_type}:{title}"
    if cache_key in TMDB_CACHE:
        return TMDB_CACHE[cache_key]

    search_endpoint = "movie" if media_type == "movie" else "tv"
    try:
        async with aiohttp.ClientSession() as session:
            search_url = f"https://api.themoviedb.org/3/search/{search_endpoint}"
            params = {"api_key": TMDB_API_KEY, "query": title}
            async with session.get(search_url, params=params, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
            results = data.get("results") or []
            if not results:
                return None
            item = results[0]
            item_id = item.get("id")
            backdrop_path = item.get("backdrop_path")
            backdrop = f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else None

            runtime = None
            if media_type == "movie" and item_id:
                detail_url = f"https://api.themoviedb.org/3/movie/{item_id}"
                async with session.get(detail_url, params={"api_key": TMDB_API_KEY}, timeout=15) as resp2:
                    if resp2.status == 200:
                        detail = await resp2.json()
                        runtime = detail.get("runtime")
            elif media_type == "tv" and item_id:
                detail_url = f"https://api.themoviedb.org/3/tv/{item_id}"
                async with session.get(detail_url, params={"api_key": TMDB_API_KEY}, timeout=15) as resp2:
                    if resp2.status == 200:
                        detail = await resp2.json()
                        ert = detail.get("episode_run_time") or []
                        runtime = ert[0] if ert else None

            logo = None
            if item_id:
                images_url = f"https://api.themoviedb.org/3/{search_endpoint}/{item_id}/images"
                async with session.get(images_url, params={"api_key": TMDB_API_KEY}, timeout=15) as resp3:
                    if resp3.status == 200:
                        images = await resp3.json()
                        logos = images.get("logos") or []
                        # Prefer an English logo, else just take the first available.
                        chosen = next((l for l in logos if l.get("iso_639_1") == "en"), logos[0] if logos else None)
                        if chosen and chosen.get("file_path"):
                            logo = f"https://image.tmdb.org/t/p/w500{chosen['file_path']}"

            result = {"backdrop": backdrop, "logo": logo, "runtime": runtime}
            TMDB_CACHE[cache_key] = result
            return result
    except Exception as e:
        print(f"⚠️ TMDB fetch failed for '{title}': {e}")
        return None


async def compose_banner(backdrop_url, logo_url):
    """Downloads the backdrop + title logo and composites the logo onto the left side. Returns BytesIO(png) or None."""
    if not backdrop_url:
        return None
    try:
        from PIL import Image
    except ImportError:
        print("⚠️ Pillow not installed — add 'Pillow' to requirements.txt to enable title-logo banners. Using plain backdrop instead.")
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(backdrop_url, timeout=20) as resp:
                if resp.status != 200:
                    return None
                backdrop_bytes = await resp.read()

            logo_bytes = None
            if logo_url:
                try:
                    async with session.get(logo_url, timeout=20) as resp2:
                        if resp2.status == 200:
                            logo_bytes = await resp2.read()
                except Exception:
                    logo_bytes = None

        backdrop = Image.open(BytesIO(backdrop_bytes)).convert("RGBA")
        if logo_bytes:
            logo = Image.open(BytesIO(logo_bytes)).convert("RGBA")
            # Scale logo to ~38% of backdrop width, preserve aspect ratio.
            target_w = int(backdrop.width * 0.38)
            ratio = target_w / logo.width
            target_h = int(logo.height * ratio)
            max_h = int(backdrop.height * 0.6)
            if target_h > max_h:
                ratio = max_h / logo.height
                target_h = max_h
                target_w = int(logo.width * ratio)
            logo = logo.resize((max(1, target_w), max(1, target_h)))

            # Darken the left portion slightly so the logo stays readable over busy art.
            overlay = Image.new("RGBA", backdrop.size, (0, 0, 0, 0))
            shade = Image.new("RGBA", (int(backdrop.width * 0.5), backdrop.height), (0, 0, 0, 110))
            overlay.paste(shade, (0, 0))
            backdrop = Image.alpha_composite(backdrop, overlay)

            pad_x, pad_y = int(backdrop.width * 0.04), int((backdrop.height - target_h) / 2)
            backdrop.paste(logo, (pad_x, pad_y), logo)

        out = BytesIO()
        backdrop.convert("RGB").save(out, format="JPEG", quality=90)
        out.seek(0)
        out.name = "banner.jpg"
        return out
    except Exception as e:
        print(f"⚠️ compose_banner failed: {e}")
        return None


# ================= Flask Server =================
flask_app = Flask(__name__)


@flask_app.route('/')
def home():
    return f"📺 {BOT_NAME} System Online"


@flask_app.route('/health')
def health():
    return {"status": "ok", "active_streams": len(CURRENT_STREAMS)}, 200


def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, debug=False)


# ================= Initialize Clients =================
app = Client("tv_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
call_py = PyTgCalls(user_app)
BOT_USERNAME = ""

# ================= Utilities =================
def cleanup_name(name):
    name = re.sub(r'\s*\((\d{4})\)\s*', '', name)
    name = re.sub(r'\s*\[.*?\]\s*', '', name)
    name = re.sub(r'\s*\{.*?\}\s*', '', name)
    name = re.sub(r'^[A-Z]{2,}:\s*', '', name)
    return name.strip().lower()


async def ensure_assistant_in_chat(chat_id, message):
    try:
        await user_app.get_chat(chat_id)
        return True
    except Exception:
        try:
            link = (await app.get_chat(chat_id)).invite_link or await app.export_chat_invite_link(chat_id)
            await user_app.join_chat(link)
            await message.reply(f"🤖 <b>Assistant Joined Group!</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return True
        except UserAlreadyParticipant:
            return True
        except Exception as e:
            await message.reply(f"{E_WARN} <b>Assistant Join Failed!</b>\n<code>{esc(str(e))}</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return False


def btn(text, callback_data=None, url=None, color=None):
    """
    InlineKeyboardButton wrapper that tries Bot API 7.10+ button color styling
    (Primary/Danger/Success) if the installed pyrofork build supports it,
    and silently falls back to a normal button otherwise.
    """
    kwargs = {}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    if color:
        try:
            return InlineKeyboardButton(text, color=color, **kwargs)
        except TypeError:
            pass
    return InlineKeyboardButton(text, **kwargs)


async def is_admin_or_owner(client, chat_id, user_id):
    if user_id == OWNER_ID:
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator") or str(member.status).lower() in ("administrator", "creator", "owner")
    except Exception:
        return False


def check_approval(func):
    async def wrapper(client, message):
        is_group = message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]
        is_approved = message.chat.id in APPROVED_GROUPS
        is_owner = message.from_user.id == OWNER_ID
        if is_group and not is_approved and not is_owner:
            return await message.reply(
                quote(f"{E_DENY} <b>ACCESS DENIED</b>\nThis Group (<code>{message.chat.id}</code>) is not authorized.") + CREDITS,
                parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            )
        return await func(client, message)
    return wrapper


async def reply_effect(message, text, effect="fire", **kwargs):
    """reply() with a message effect if the installed pyrogram fork supports it, else plain reply."""
    try:
        return await message.reply(text, message_effect_id=EFFECT_IDS.get(effect), **kwargs)
    except TypeError:
        return await message.reply(text, **kwargs)
    except Exception:
        return await message.reply(text, **kwargs)


async def robust_play(chat_id, media_stream, retries=3):
    """Play with retry/backoff so temporary network hiccups don't kill the stream."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            await call_py.play(chat_id, media_stream)
            return True
        except Exception as e:
            last_err = e
            print(f"⚠️ play() attempt {attempt}/{retries} failed for {chat_id}: {e}")
            await asyncio.sleep(2 * attempt)
    if last_err:
        raise last_err
    return False


def make_seek_stream(url, quality, offset_seconds):
    """
    Build a MediaStream, applying a start-time offset for seeking.
    Different py-tgcalls releases have used different kwarg names for the raw
    ffmpeg args, so we try the known candidates in order and use whichever one
    the installed version actually accepts (TypeError on an unknown kwarg is
    raised immediately at construction time, so this is safe to try).
    """
    if offset_seconds <= 0:
        return MediaStream(url, video_parameters=quality)

    ss_arg = f"-ss {int(offset_seconds)}"
    candidates = ("additional_ffmpeg_parameters", "ffmpeg_parameters", "custom_ffmpeg_parameters")
    for kwarg_name in candidates:
        try:
            return MediaStream(url, video_parameters=quality, **{kwarg_name: ss_arg})
        except TypeError:
            continue
    print(f"⚠️ No known ffmpeg-seek kwarg accepted by this py-tgcalls build — seeking will not work until this is verified against your installed version.")
    return MediaStream(url, video_parameters=quality)


def stream_key(media_type, name, ep_code=None):
    return f"{media_type}:{name}:{ep_code or ''}"


# ================= Owner - XTREAM FETCHING (Optimized) =================
async def _fetch_series_episodes(session, base_url, user, passwd, series_info):
    series_id = series_info.get('series_id')
    series_name = cleanup_name(series_info.get('name', ''))
    if not series_name:
        return None, None

    detail_url = f"{base_url}/player_api.php?username={user}&password={passwd}&action=get_series_info&series_id={series_id}"
    try:
        async with session.get(detail_url, timeout=20) as resp:
            if resp.status == 200:
                detail_data = await resp.json()
                episodes_dict = {}
                episodes = detail_data.get('episodes', {})
                for season in episodes.values():
                    for episode in season:
                        ep_num = episode.get('episode_num')
                        season_num = episode.get('season')
                        ep_id_code = f"s{season_num:02d}e{ep_num:02d}"
                        ext = episode.get('container_extension', 'mp4')
                        stream_url = f"{base_url}/series/{user}/{passwd}/{episode.get('id')}.{ext}"
                        episodes_dict[ep_id_code] = stream_url
                return series_name, episodes_dict
    except asyncio.TimeoutError:
        print(f"Timeout fetching series: {series_name}")
    except Exception as e:
        print(f"Error fetching {series_name}: {e}")
    return series_name, None


@app.on_message(filters.command("addxtreamseries") & filters.user(OWNER_ID))
async def add_xtream_series_optimized(client, message):
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(f"{E_WARN} <b>Usage:</b> <code>/addxtreamseries URL User Pass</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    msg = await message.reply(f"{E_BOLT} <b>Fetching Xtream Series list...</b>", parse_mode=ParseMode.HTML)

    try:
        series_list_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_series"
        async with aiohttp.ClientSession() as session:
            async with session.get(series_list_url, timeout=30) as resp:
                if resp.status != 200:
                    return await msg.edit_text(f"❌ Failed to fetch series list. Status: {resp.status}")
                series_data = await resp.json()

        await msg.edit_text(f"{E_CHECK} Found <b>{len(series_data)}</b> series. Fetching all episodes concurrently...\n<i>This may take a moment but is much faster!</i>", parse_mode=ParseMode.HTML)

        tasks = []
        async with aiohttp.ClientSession() as session:
            for series_info in series_data:
                tasks.append(_fetch_series_episodes(session, url, user, passwd, series_info))
            results = await asyncio.gather(*tasks)

        processed_count = 0
        for series_name, episodes_dict in results:
            if series_name and episodes_dict:
                SERIES.setdefault(series_name, {}).update(episodes_dict)
                processed_count += 1
        save_data()

        await msg.edit_text(f"{E_CHECK} <b>Scan Complete!</b>\nLoaded episodes for <b>{processed_count}</b> series from Xtream API!{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    except Exception as e:
        await msg.edit_text(f"❌ An error occurred: <code>{esc(str(e)[:150])}</code>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command("addxtreammovies") & filters.user(OWNER_ID))
async def add_xtream_movies(client, message):
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(f"{E_WARN} <b>Usage:</b> <code>/addxtreammovies URL User Pass</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_vod_streams"
    msg = await message.reply(f"{E_BOLT} <b>Fetching Xtream Movies...</b> This may take a moment.", parse_mode=ParseMode.HTML)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    count = 0
                    for movie in data:
                        name = cleanup_name(movie.get("name", ""))
                        if name:
                            ext = movie.get("container_extension", "mp4")
                            stream_url = f"{url}/movie/{user}/{passwd}/{movie.get('stream_id')}.{ext}"
                            MOVIES[name] = stream_url
                            count += 1
                    save_data()
                    await msg.edit_text(f"{E_CHECK} <b>Loaded {count} Movies from Xtream API!</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                else:
                    await msg.edit_text(f"❌ Error Status: {resp.status}")
    except Exception as e:
        await msg.edit_text(f"❌ Failed: <code>{esc(str(e)[:150])}</code>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command("addxtreamchannels") & filters.user(OWNER_ID))
async def add_xtream_channels(client, message):
    """Bonus command: imports live channels (+ their stream_icon logos) from an Xtream panel."""
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(f"{E_WARN} <b>Usage:</b> <code>/addxtreamchannels URL User Pass</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    msg = await message.reply(f"{E_BOLT} <b>Fetching Xtream Live Channels...</b>", parse_mode=ParseMode.HTML)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=60) as resp:
                if resp.status != 200:
                    return await msg.edit_text(f"❌ Error Status: {resp.status}")
                data = await resp.json()
        count, logo_count = 0, 0
        for ch in data:
            name = cleanup_name(ch.get("name", ""))
            if not name:
                continue
            stream_url = f"{url}/live/{user}/{passwd}/{ch.get('stream_id')}.m3u8"
            CHANNELS[name] = stream_url
            icon = ch.get("stream_icon")
            if icon:
                CHANNEL_LOGOS[name] = icon
                logo_count += 1
            count += 1
        save_data()
        await msg.edit_text(f"{E_CHECK} <b>Loaded {count} Channels</b> ({logo_count} with logos) from Xtream API!{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        await msg.edit_text(f"❌ Failed: <code>{esc(str(e)[:150])}</code>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command("addchannellogoxtremecode") & filters.user(OWNER_ID))
async def add_channel_logo_xtream(client, message):
    """Re-syncs logos only (doesn't touch existing channel URLs) from an Xtream panel's stream_icon field."""
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(f"{E_WARN} <b>Usage:</b> <code>/addchannellogoxtremecode URL User Pass</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    msg = await message.reply(f"{E_BOLT} <b>Syncing channel logos...</b>", parse_mode=ParseMode.HTML)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=60) as resp:
                if resp.status != 200:
                    return await msg.edit_text(f"❌ Error Status: {resp.status}")
                data = await resp.json()
        matched = 0
        for ch in data:
            name = cleanup_name(ch.get("name", ""))
            icon = ch.get("stream_icon")
            if name in CHANNELS and icon:
                CHANNEL_LOGOS[name] = icon
                matched += 1
        save_data()
        await msg.edit_text(f"{E_CHECK} <b>Synced logos for {matched} existing channels.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        await msg.edit_text(f"❌ Failed: <code>{esc(str(e)[:150])}</code>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command("addchannellogo") & filters.user(OWNER_ID))
async def add_channel_logo_manual(client, message):
    """
    Usage:
      Reply to a photo with: /addchannellogo <channel name>
      OR: /addchannellogo <channel name> <image url>
    """
    args = message.text.split(None, 1)
    if len(args) < 2:
        return await message.reply(f"{E_WARN} <b>Usage:</b> reply to a photo with <code>/addchannellogo Channel Name</code>, or <code>/addchannellogo Channel Name https://image-url</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    rest = args[1].strip()
    url_match = re.search(r'(https?://\S+)$', rest)
    if url_match:
        logo_url = url_match.group(1)
        name = cleanup_name(rest[:url_match.start()].strip())
        if name not in CHANNELS:
            return await message.reply(f"❌ No channel named <b>{esc(name.title())}</b> found.{CREDITS}", parse_mode=ParseMode.HTML)
        CHANNEL_LOGOS[name] = logo_url
        save_data()
        return await message.reply(f"{E_CHECK} <b>Logo set for {esc(name.title())}!</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    name = cleanup_name(rest)
    if name not in CHANNELS:
        return await message.reply(f"❌ No channel named <b>{esc(name.title())}</b> found.{CREDITS}", parse_mode=ParseMode.HTML)

    if message.reply_to_message and message.reply_to_message.photo:
        file_path = await client.download_media(message.reply_to_message.photo.file_id)
        uploaded = await client.send_photo(message.chat.id, file_path)
        CHANNEL_LOGOS[name] = uploaded.photo.file_id
        save_data()
        return await message.reply(f"{E_CHECK} <b>Logo set for {esc(name.title())}!</b>{CREDITS}", parse_mode=ParseMode.HTML)

    PENDING_LOGO_UPLOAD[message.from_user.id] = name
    await message.reply(f"{E_CAM} <b>Now send the logo image</b> for <b>{esc(name.title())}</b> (as a photo).{CREDITS}", parse_mode=ParseMode.HTML)


@app.on_message(filters.photo & filters.user(OWNER_ID) & filters.private)
async def receive_pending_logo(client, message):
    name = PENDING_LOGO_UPLOAD.pop(message.from_user.id, None)
    if not name:
        return
    CHANNEL_LOGOS[name] = message.photo.file_id
    save_data()
    await message.reply(f"{E_CHECK} <b>Logo set for {esc(name.title())}!</b>{CREDITS}", parse_mode=ParseMode.HTML)


# ================= LIST COMMANDS =================
@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    if not CHANNELS:
        return await message.reply(quote(f"❌ <b>No Channels Found.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if len(CHANNELS) > LIST_FILE_THRESHOLD:
        text_content = "📺 All Available Channels\n\n" + "\n".join([f"{idx+1}. {name.title()}" for idx, name in enumerate(CHANNELS.keys())])
        file = BytesIO(text_content.encode('utf-8'))
        file.name = "channels.txt"
        return await message.reply_document(file, caption=quote(f"📂 Here are the <b>{len(CHANNELS)}</b> available channels.") + CREDITS, parse_mode=ParseMode.HTML)

    body = f"{E_CAM} <b>{fancy('live channels')}</b>\n\n"
    for idx, name in enumerate(CHANNELS.keys(), 1):
        body += f"❖ <code>{idx:02d}.</code> <b>{esc(name.title())}</b>\n"
    await message.reply(quote(body) + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("movies"))
async def show_movies(client, message):
    if not MOVIES:
        return await message.reply(quote(f"❌ <b>No Movies Found.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if len(MOVIES) > LIST_FILE_THRESHOLD:
        text_content = "🎬 All Available Movies\n\n" + "\n".join([f"{idx+1}. {name.title()}" for idx, name in enumerate(MOVIES.keys())])
        file = BytesIO(text_content.encode('utf-8'))
        file.name = "movies.txt"
        return await message.reply_document(file, caption=quote(f"📂 Here are the <b>{len(MOVIES)}</b> available movies.") + CREDITS, parse_mode=ParseMode.HTML)

    body = f"🎬 <b>{fancy('movies list')}</b>\n\n"
    for idx, name in enumerate(MOVIES.keys(), 1):
        body += f"❖ <code>{idx:02d}.</code> <b>{esc(name.title())}</b>\n"
    await message.reply(quote(body) + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("series"))
async def show_series(client, message):
    if not SERIES:
        return await message.reply(quote(f"❌ <b>No Series Found.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if len(SERIES) > LIST_FILE_THRESHOLD:
        text_content = "🍿 All Available Series\n\n"
        for idx, (show, eps) in enumerate(SERIES.items()):
            text_content += f"{idx+1}. {show.title()} ({len(eps)} episodes)\n"
        file = BytesIO(text_content.encode('utf-8'))
        file.name = "series.txt"
        return await message.reply_document(file, caption=quote(f"📂 Here are the <b>{len(SERIES)}</b> available series.") + CREDITS, parse_mode=ParseMode.HTML)

    body = f"🍿 <b>{fancy('series list')}</b>\n\n"
    for show, eps in SERIES.items():
        body += f"❖ <b>{esc(show.title())}</b> (Episodes: {len(eps)})\n"
    await message.reply(quote(body) + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


# ================= Playback & Conflict Resolution =================
@app.on_message(filters.command(["livetv", "playmovie", "playseries"]) & filters.group)
@check_approval
async def stream_media(client, message):
    cmd = message.command[0]
    if len(message.command) < 2:
        return await message.reply(quote(f"{E_WARN} Usage: <code>/{cmd} name</code>"), parse_mode=ParseMode.HTML)
    query = " ".join(message.command[1:]).strip().lower()

    db, media_type = {}, ""
    if cmd == "livetv":
        db, media_type = CHANNELS, "channel"
    elif cmd == "playmovie":
        db, media_type = MOVIES, "movie"
    elif cmd == "playseries":
        query = query.split('-')[0].strip()
        db, media_type = SERIES, "series"

    matches = [name for name in db if query in name]
    if not matches:
        return await message.reply(quote(f"❌ <b>No {media_type} found matching that name!</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if len(matches) == 1:
        return await _start_stream(client, message, matches[0], media_type, raw_query=" ".join(message.command[1:]), user_message=message)

    buttons = []
    for name in matches[:20]:
        req_id = str(uuid.uuid4())[:8]
        PLAY_REQUESTS[req_id] = (name, " ".join(message.command[1:]))
        buttons.append([InlineKeyboardButton(name.title(), callback_data=f"resolve_{media_type}_{req_id}")])

    await message.reply(quote(f"🤔 <b>Found multiple results for {esc(query.title())}. Please choose one:</b>"), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
    try:
        await message.delete()
    except Exception:
        pass


@app.on_callback_query(filters.regex(r"^resolve_"))
async def resolve_playback(client, callback_query):
    media_type, req_id = callback_query.data.split("_")[1:]
    entry = PLAY_REQUESTS.get(req_id)
    if not entry:
        return await callback_query.answer("⚠️ This request expired. Please try again.", show_alert=True)
    full_name, raw_query = entry

    await callback_query.message.delete()
    PLAY_REQUESTS.pop(req_id, None)

    await _start_stream(client, callback_query.message, full_name, media_type, raw_query=raw_query, from_user=callback_query.from_user)


def _resolve_episode(name, raw_query):
    parts = [p.strip() for p in raw_query.lower().split('-')]
    if len(parts) == 2 and name in SERIES and parts[1] in SERIES[name]:
        return parts[1]
    return None


async def _start_stream(client, message, name, media_type, raw_query="", from_user=None, user_message=None):
    chat_id = message.chat.id
    if not await ensure_assistant_in_chat(chat_id, message):
        return

    url, display_name, ep_code = "", name.title(), None
    if media_type == "channel":
        url, type_label = CHANNELS[name], "📺 Live TV"
    elif media_type == "movie":
        url, type_label = MOVIES[name], "🎬 Movie"
    elif media_type == "series":
        ep_code = _resolve_episode(name, raw_query)
        if not ep_code:
            return await message.reply(quote(f"{E_WARN} Episode not specified or not found. Use format: <code>/playseries {esc(name.title())} - s01e01</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        url = SERIES[name][ep_code]
        display_name = f"{name.title()} [{ep_code.upper()}]"
        type_label = "🍿 Series"
    else:
        return

    if not url:
        return await message.reply(quote("❌ Could not find a valid stream URL."), parse_mode=ParseMode.HTML)

    key = stream_key(media_type, name, ep_code)
    resume_key = f"{chat_id}:{key}"
    saved_pos = RESUME_POSITIONS.get(resume_key, 0)

    if media_type in ("movie", "series") and saved_pos > 30:
        buttons = InlineKeyboardMarkup([[
            btn(f"▶️ Resume {fmt_time(saved_pos)}", callback_data=f"startat_{saved_pos}_{uuid.uuid4().hex[:6]}", color="success"),
            btn("🔁 Start Over", callback_data="startat_0_x", color="primary"),
        ]])
        await message.reply(quote(f"{E_PIN} You previously stopped <b>{esc(display_name)}</b> at <b>{fmt_time(saved_pos)}</b>. Resume or start over?"), parse_mode=ParseMode.HTML, reply_markup=buttons)
        # Store what the resume/start-over callback needs, keyed by its own callback_data.
        for row in buttons.inline_keyboard:
            for button in row:
                PLAY_REQUESTS[button.callback_data] = (name, media_type, ep_code, display_name, type_label, url)
        if user_message:
            try:
                await user_message.delete()
            except Exception:
                pass
        return

    await _launch_stream(client, message, name, media_type, ep_code, display_name, type_label, url, offset=0, user_message=user_message)


@app.on_callback_query(filters.regex(r"^startat_"))
async def resume_choice(client, callback_query):
    data = callback_query.data
    entry = PLAY_REQUESTS.pop(data, None)
    offset = int(data.split("_")[1])
    await callback_query.message.delete()
    if not entry:
        return await callback_query.answer("⚠️ Expired, please replay.", show_alert=True)
    name, media_type, ep_code, display_name, type_label, url = entry
    await _launch_stream(client, callback_query.message, name, media_type, ep_code, display_name, type_label, url, offset=offset)


async def _launch_stream(client, message, name, media_type, ep_code, display_name, type_label, url, offset=0, user_message=None):
    chat_id = message.chat.id

    # Delete the user's own command message (needs bot to be a group admin — safe no-op otherwise).
    if user_message:
        try:
            await user_message.delete()
        except Exception:
            pass

    msg = await message.reply(quote(f"{E_BOLT} <b>Initializing {type_label}...</b>"), parse_mode=ParseMode.HTML)

    # Delete the previous "Now Streaming" card for this chat so old data doesn't clutter the group.
    prev = CURRENT_STREAMS.get(chat_id)
    if prev and prev.get("msg_id"):
        try:
            await client.delete_messages(chat_id, prev["msg_id"])
        except Exception:
            pass

    quality = VideoQuality.HD_720p
    stream = make_seek_stream(url, quality, offset)

    try:
        await robust_play(chat_id, stream)
    except Exception as e:
        return await msg.edit_text(quote(f"❌ <b>Stream Failed!</b>\n<code>{esc(str(e)[:150])}</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    token = uuid.uuid4().hex
    tmdb_info = None
    logo_url = None
    if media_type in ("movie", "series"):
        tmdb_info = await fetch_tmdb_art(name, "movie" if media_type == "movie" else "tv")
    elif media_type == "channel":
        logo_url = CHANNEL_LOGOS.get(name)

    duration = None
    if tmdb_info and tmdb_info.get("runtime"):
        duration = tmdb_info["runtime"] * 60

    CURRENT_STREAMS[chat_id] = {
        "url": url, "name": display_name, "type": type_label, "media_type": media_type,
        "key": stream_key(media_type, name, ep_code), "quality": "720p",
        "start_ts": time.time() - offset, "offset": offset, "duration": duration,
        "token": token, "msg_id": None,
    }

    caption = _render_stream_card(display_name, type_label, "720p")
    keyboard = _build_stream_keyboard(offset, duration, media_type)

    sent = None
    banner_file = None
    if tmdb_info and tmdb_info.get("backdrop"):
        banner_file = await compose_banner(tmdb_info.get("backdrop"), tmdb_info.get("logo"))

    art = banner_file or (tmdb_info or {}).get("backdrop") if tmdb_info else logo_url
    if art:
        try:
            sent = await client.send_photo(chat_id, art, caption=caption, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        except Exception:
            sent = None
    if not sent:
        try:
            await msg.delete()
        except Exception:
            pass
        sent = await message.reply(caption, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
    else:
        try:
            await msg.delete()
        except Exception:
            pass

    CURRENT_STREAMS[chat_id]["msg_id"] = sent.id

    try:
        effect_msg = await reply_effect(message, "🎬", effect="fire", quote=False)
        if effect_msg:
            asyncio.create_task(_delete_after(effect_msg, 4))
    except Exception:
        pass

    asyncio.create_task(_progress_loop(chat_id, token))


async def _delete_after(message, delay_seconds):
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except Exception:
        pass


def _render_stream_card(display_name, type_label, quality):
    return quote(
        f"{E_SPARK} <b>{fancy('now streaming')}</b>\n\n"
        f"❖ <b>Title:</b> {esc(display_name)}\n"
        f"❖ <b>Type:</b> {type_label}\n"
        f"❖ <b>Quality:</b> {quality} {E_CHECK}"
    ) + CREDITS


def _build_stream_keyboard(elapsed, duration, media_type):
    time_label = f"⏱ {fmt_time(elapsed)} / {fmt_time(duration)}" if duration else f"⏱ {fmt_time(elapsed)} / 🔴 LIVE"
    rows = [
        [btn(time_label, callback_data="noop")],
        [btn(q.upper(), callback_data=f"q_{q}", color="primary") for q in ["360p", "480p", "720p", "1080p"]],
        [btn("⏹ Stop", callback_data="stop_stream", color="danger")],
        [btn("👑 Support", url=SUPPORT_URL, color="primary"), btn("🔔 Updates", url=UPDATES_URL, color="primary")],
    ]
    return InlineKeyboardMarkup(rows)


async def _progress_loop(chat_id, token):
    while True:
        await asyncio.sleep(20)
        stream = CURRENT_STREAMS.get(chat_id)
        if not stream or stream.get("token") != token:
            return  # stream replaced or stopped
        elapsed = time.time() - stream["start_ts"]
        if stream.get("duration") and elapsed >= stream["duration"]:
            return
        keyboard = _build_stream_keyboard(elapsed, stream.get("duration"), stream["media_type"])
        try:
            await app.edit_message_reply_markup(chat_id, stream["msg_id"], reply_markup=keyboard)
        except Exception:
            pass


@app.on_callback_query(filters.regex(r"^noop$"))
async def noop_cb(client, callback_query):
    await callback_query.answer()


@app.on_message(filters.command("seek") & filters.group)
async def seek_command(client, message):
    chat_id = message.chat.id
    stream = CURRENT_STREAMS.get(chat_id)
    if not stream:
        return await message.reply(quote(f"{E_WARN} No active stream here!"), parse_mode=ParseMode.HTML)
    if len(message.command) < 2:
        return await message.reply(quote(f"{E_WARN} Usage: <code>/seek mm:ss</code> or <code>/seek seconds</code>"), parse_mode=ParseMode.HTML)
    if stream["media_type"] == "channel":
        return await message.reply(quote("⚠️ Can't seek a live channel!"), parse_mode=ParseMode.HTML)

    raw = message.command[1]
    try:
        if ":" in raw:
            parts = [int(p) for p in raw.split(":")]
            secs = 0
            for p in parts:
                secs = secs * 60 + p
        else:
            secs = int(raw)
    except ValueError:
        return await message.reply(quote("❌ Invalid time format. Use mm:ss or seconds."), parse_mode=ParseMode.HTML)

    try:
        await message.delete()
    except Exception:
        pass

    quality = QUALITY_PRESETS.get(stream["quality"], VideoQuality.HD_720p)
    try:
        stream_obj = make_seek_stream(stream["url"], quality, secs)
        await robust_play(chat_id, stream_obj)
        stream["start_ts"] = time.time() - secs
        stream["offset"] = secs
        stream["token"] = uuid.uuid4().hex
        keyboard = _build_stream_keyboard(secs, stream.get("duration"), stream["media_type"])
        try:
            await app.edit_message_reply_markup(chat_id, stream["msg_id"], reply_markup=keyboard)
        except Exception:
            pass
        confirm = await app.send_message(chat_id, quote(f"{E_CHECK} Jumped to <b>{fmt_time(secs)}</b>"), parse_mode=ParseMode.HTML)
        asyncio.create_task(_delete_after(confirm, 5))
        asyncio.create_task(_progress_loop(chat_id, stream["token"]))
    except Exception as e:
        await app.send_message(chat_id, quote(f"❌ Seek failed: <code>{esc(str(e)[:120])}</code>\n\nIf this keeps happening, the seek mechanism may need tuning to your exact py-tgcalls version — send me the error and I'll adjust it."), parse_mode=ParseMode.HTML)


@app.on_callback_query(filters.regex(r"^q_"))
async def switch_quality(client, callback_query):
    chat_id = callback_query.message.chat.id
    quality_req = callback_query.data.split("_")[1]
    stream = CURRENT_STREAMS.get(chat_id)
    if not stream:
        return await callback_query.answer("⚠️ No active stream here!", show_alert=True)
    vq = QUALITY_PRESETS.get(quality_req, VideoQuality.HD_720p)
    elapsed = time.time() - stream["start_ts"]
    try:
        stream_obj = make_seek_stream(stream["url"], vq, elapsed)
        await robust_play(chat_id, stream_obj)
        stream["quality"] = quality_req
        stream["start_ts"] = time.time() - elapsed
        caption = _render_stream_card(stream["name"], stream["type"], quality_req)
        keyboard = _build_stream_keyboard(elapsed, stream.get("duration"), stream["media_type"])
        try:
            await callback_query.message.edit_caption(caption, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        except Exception:
            await callback_query.message.edit_text(caption, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        await callback_query.answer(f"✅ Switched to {quality_req}!")
    except Exception:
        await callback_query.answer("❌ Failed to switch!", show_alert=True)


@app.on_callback_query(filters.regex(r"^stop_stream$"))
async def stop_stream_btn(client, callback_query):
    if not await is_admin_or_owner(client, callback_query.message.chat.id, callback_query.from_user.id):
        return await callback_query.answer("🚫 Only group admins can stop the stream.", show_alert=True)
    await _do_stop(callback_query.message.chat.id)
    await callback_query.answer("⏹ Stopped")
    try:
        await callback_query.message.delete()
    except Exception:
        pass


async def _do_stop(chat_id):
    stream = CURRENT_STREAMS.get(chat_id)
    if stream and stream["media_type"] in ("movie", "series"):
        elapsed = time.time() - stream["start_ts"]
        RESUME_POSITIONS[f"{chat_id}:{stream['key']}"] = elapsed
        save_data()
    try:
        await call_py.leave_call(chat_id)
    except Exception:
        pass
    CURRENT_STREAMS.pop(chat_id, None)


@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    if not await is_admin_or_owner(client, message.chat.id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} Only group admins can stop the current stream."), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    had_stream = message.chat.id in CURRENT_STREAMS
    await _do_stop(message.chat.id)
    if had_stream:
        await message.reply(quote(f"{E_STOP} <b>Stream Stopped.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        await message.reply(quote(f"❌ <b>No active stream to stop.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


# ================= Health check / stuck-stream watchdog =================
_watchdog_fail_counts = {}  # chat_id -> consecutive failed checks
WATCHDOG_FAILS_BEFORE_RESTART = 3  # ~3 checks (3 min at 60s interval) of confirmed failure before we touch a live stream


async def stream_watchdog():
    """
    Periodically checks active calls. Only restarts a stream after several
    CONSECUTIVE failed checks in a row — a single flaky check is not treated
    as proof the call died, to avoid falsely restarting healthy streams
    (which was likely the cause of streams "randomly restarting").
    """
    if not hasattr(call_py, "get_call"):
        print("⚠️ Watchdog disabled: this py-tgcalls build has no get_call() — liveness can't be verified this way. Tell me what version you have and I'll adjust.")
        return

    while True:
        await asyncio.sleep(60)
        for chat_id, stream in list(CURRENT_STREAMS.items()):
            try:
                await call_py.get_call(chat_id)
                _watchdog_fail_counts[chat_id] = 0  # healthy — reset
            except Exception as e:
                fails = _watchdog_fail_counts.get(chat_id, 0) + 1
                _watchdog_fail_counts[chat_id] = fails
                print(f"⚠️ Watchdog check {fails}/{WATCHDOG_FAILS_BEFORE_RESTART} failed for {chat_id}: {e}")
                if fails < WATCHDOG_FAILS_BEFORE_RESTART:
                    continue
                _watchdog_fail_counts[chat_id] = 0
                try:
                    elapsed = time.time() - stream["start_ts"]
                    quality = QUALITY_PRESETS.get(stream["quality"], VideoQuality.HD_720p)
                    stream_obj = make_seek_stream(stream["url"], quality, elapsed if stream["media_type"] != "channel" else 0)
                    await robust_play(chat_id, stream_obj, retries=2)
                    print(f"🔄 Auto-recovered stream in {chat_id} after {WATCHDOG_FAILS_BEFORE_RESTART} confirmed failed checks")
                except Exception as e2:
                    print(f"❌ Could not auto-recover stream in {chat_id}: {e2}")
                    CURRENT_STREAMS.pop(chat_id, None)


# ================= Start / Info =================
async def send_start_banner(client, chat_id, caption, reply_markup):
    global _start_banner_file_id
    try:
        if _start_banner_file_id:
            sent = await client.send_photo(chat_id, _start_banner_file_id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        elif START_BANNER_URL:
            sent = await client.send_photo(chat_id, START_BANNER_URL, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            _start_banner_file_id = sent.photo.file_id
            save_data()
        else:
            return await client.send_message(chat_id, caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup, disable_web_page_preview=True)
        return sent
    except Exception as e:
        print(f"⚠️ send_start_banner failed, falling back to text: {e}")
        return await client.send_message(chat_id, caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup, disable_web_page_preview=True)


def _start_keyboard():
    add_url = f"https://t.me/{BOT_USERNAME}?startgroup=true" if BOT_USERNAME else SUPPORT_URL
    return InlineKeyboardMarkup([
        [btn("➕ Add Me", url=add_url, color="success"), btn("👑 Support", url=SUPPORT_URL, color="primary")],
        [btn("🔔 Updates", url=UPDATES_URL, color="primary")],
        [btn("📜 Commands", callback_data="show_commands", color="primary")],
    ])


COMMANDS_TEXT = quote(
    f"{E_BOLT} <b>{fancy('commands')}</b>\n\n"
    f"❖ <code>/channels</code> — Browse Live TV\n"
    f"❖ <code>/movies</code> — Browse Movies\n"
    f"❖ <code>/series</code> — Browse Series\n"
    f"❖ <code>/livetv name</code> — Play Channel\n"
    f"❖ <code>/playmovie name</code> — Play Movie\n"
    f"❖ <code>/playseries name - s01e01</code> — Play Series\n"
    f"❖ <code>/seek mm:ss</code> — Jump to a timestamp\n"
    f"❖ <code>/stopvc</code> — Stop Current Stream (admins only)"
) + CREDITS


@app.on_callback_query(filters.regex(r"^show_commands$"))
async def show_commands_cb(client, callback_query):
    await callback_query.answer()
    await client.send_message(callback_query.message.chat.id, COMMANDS_TEXT, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    text = quote(
        f"{E_SPARK} <b>Welcome to {fancy('meow stream')} 📺</b> — the most advanced Telegram streaming bot.\n\n"
        f"{E_CAM} Live TV, Movies & Series, streamed straight into your group's voice chat.\n"
        f"{E_SIGNAL} Multiple quality options, seek/resume, auto-recovery on drops.\n\n"
        f"Tap <b>📜 Commands</b> below to see everything I can do."
    ) + CREDITS
    await send_start_banner(client, message.chat.id, text, _start_keyboard())


@app.on_message(filters.command("start") & filters.group)
async def start_cmd_group(client, message):
    text = quote(f"{E_SPARK} <b>{fancy('meow stream')} 📺 is ready!</b>\nTap <b>📜 Commands</b> below to get started.") + CREDITS
    await send_start_banner(client, message.chat.id, text, _start_keyboard())


@app.on_message(filters.command("delallchannels") & filters.user(OWNER_ID))
async def del_all_channels(client, message):
    CHANNELS.clear(); CHANNEL_LOGOS.clear(); save_data()
    await message.reply(f"🗑️ <b>All Live TV channels deleted.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("delallmovies") & filters.user(OWNER_ID))
async def del_all_movies(client, message):
    MOVIES.clear(); save_data()
    await message.reply(f"🗑️ <b>All movies deleted.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("delallseries") & filters.user(OWNER_ID))
async def del_all_series(client, message):
    SERIES.clear(); save_data()
    await message.reply(f"🗑️ <b>All series deleted.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply(f"{E_WARN} <b>Usage:</b> <code>/addchannel URL Channel Name</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    url, name = args[1], cleanup_name(args[2])
    CHANNELS[name] = url
    save_data()
    await message.reply(f"{E_CHECK} <b>Channel Added:</b> {esc(name.title())}{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("approve") & filters.user(OWNER_ID))
async def approve_group(client, message):
    try:
        chat_id = int(message.command[1]) if len(message.command) > 1 else message.chat.id
        APPROVED_GROUPS.add(chat_id)
        save_data()
        await message.reply(f"{E_CHECK} <b>Group <code>{chat_id}</code> APPROVED.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except (ValueError, IndexError):
        await message.reply("Please specify a Chat ID or use in the group.")


@app.on_message(filters.command("unapprove") & filters.user(OWNER_ID))
async def unapprove_group(client, message):
    try:
        chat_id = int(message.command[1]) if len(message.command) > 1 else message.chat.id
        APPROVED_GROUPS.discard(chat_id)
        save_data()
        await message.reply(f"{E_DENY} <b>Group <code>{chat_id}</code> UNAPPROVED.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except (ValueError, IndexError):
        pass


@app.on_message(filters.command("botinfo") & filters.user(OWNER_ID))
async def bot_info(client, message):
    body = (f"{E_SIGNAL} <b>{fancy('system info')}</b>\n\n"
            f"📡 <b>Active Streams:</b> {len(CURRENT_STREAMS)}\n"
            f"📺 <b>Channels:</b> {len(CHANNELS)} | 🎬 <b>Movies:</b> {len(MOVIES)}\n"
            f"🍿 <b>Series:</b> {len(SERIES)}\n"
            f"🖼️ <b>Channel Logos:</b> {len(CHANNEL_LOGOS)}\n"
            f"🛡️ <b>Approved Groups:</b> {len(APPROVED_GROUPS)}\n")
    for grp in APPROVED_GROUPS:
        body += f"├ <code>{grp}</code>\n"
    await message.reply(quote(body) + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast(client, message):
    if len(message.command) < 2:
        return await message.reply("⚠️ Usage: <code>/broadcast message</code>", parse_mode=ParseMode.HTML)
    msg_text = message.text.split(None, 1)[1]
    success, failed = 0, 0
    m = await message.reply(f"{E_BOLT} <b>Broadcasting...</b>", parse_mode=ParseMode.HTML)
    for chat_id in APPROVED_GROUPS:
        try:
            await app.send_message(chat_id, f"{E_BELL} <b>Broadcast</b>\n\n{esc(msg_text)}{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            success += 1
        except Exception:
            failed += 1
    await m.edit_text(f"{E_CHECK} <b>Broadcast Complete!</b>\nSent: {success} | Failed: {failed}{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


# ================= Boot Sequence =================
async def main():
    global BOT_USERNAME
    load_data()
    Thread(target=run_flask, daemon=True).start()
    await app.start(); await user_app.start(); await call_py.start()
    me = await app.get_me()
    BOT_USERNAME = me.username or ""
    print(f"✅ {BOT_NAME} System Online!")
    asyncio.create_task(stream_watchdog())
    try:
        await app.send_message(OWNER_ID, f"🟢 <b>{BOT_NAME} Online!</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass
    await idle()
    for chat_id in list(CURRENT_STREAMS.keys()):
        await _do_stop(chat_id)
    save_data()
    await app.stop(); await user_app.stop()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())

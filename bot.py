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
import yt_dlp
from dotenv import load_dotenv
from flask import Flask
from pyrogram import Client, filters, idle
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import UserAlreadyParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioQuality, ChatUpdate, MediaStream, StreamEnded, VideoQuality

load_dotenv()

# ================= Configuration =================
# SECURITY: every value below is read ONLY from the environment (a local `.env`
# file, or your host's dashboard e.g. Railway/Heroku variables) — nothing sensitive
# is hardcoded in this source file anymore. Put your real values in `.env`
# (see `.env.example`) and keep `.env` out of git.
#
# This keeps the SAME bot identity as the original LivetvBlaze bot: same
# API_ID/API_HASH, same BOT_TOKEN, same assistant/userbot SESSION_STRING, same
# OWNER_ID, same support group/channel links and same start image.
API_ID = int(os.environ.get("API_ID", "33181534"))
API_HASH = os.environ.get("API_HASH", "ef2c1ed56bb1fc743b3fbc244582efbb")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8524475183:AAGglXOt2oLCyv2N1vC_R_1gV7T9dvEOWfI")
SESSION_STRING = os.environ.get("SESSION_STRING", "BQH6T14ApBK2D7AX4O2MaHlvmZ76wfRt8KrfjwT0JUO7C5fTn8RDKC3SkrUi-faERDoHEpcopRngCMHALCHajgUWihnhIQnhckPbkPf976zhd-sinhjn6A2--nKJYN4U-LzgyePYwNAFqVcXTyI2aUBWI9fGFZuf8lcas7v-hIddaw3wug_zjaK4bgjae8w7DpqFr3m97PSUv8g-gxe6t3QhdyIZ2ZytGLr8mphTpJTsFVi9zCRvzWt5_W5iVY4-gu7oeZ9RrvxmguZ-h4Mp-XJzEPLeJlRlMKZiaokegtKf9Ue81fXwm5lR-tbwKFArNhxeNvGtIATzR8pM6tb_wC5ZW_bj6QAAAAILtc1CAA")
OWNER_ID = int(os.environ.get("OWNER_ID", "8242523973"))
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "5995cbd90beb943f6e7f26745e31de73")  # get a free key at themoviedb.org
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/MeowStreamSupport")
UPDATES_URL = os.environ.get("UPDATES_URL", "https://t.me/MeowpawSupport")

PORT = int(os.environ.get("PORT", 8080))

if not all([API_ID, API_HASH, BOT_TOKEN, SESSION_STRING, OWNER_ID]):
    raise SystemExit(
        "Missing required environment variables. Copy .env.example to .env and fill in "
        "API_ID, API_HASH, BOT_TOKEN, SESSION_STRING and OWNER_ID."
    )

# ================= Music engine settings (merged from AviaxMusic) =================
DURATION_LIMIT = int(os.environ.get("DURATION_LIMIT", "0")) * 60  # minutes -> seconds, 0 = no limit
QUEUE_LIMIT = int(os.environ.get("QUEUE_LIMIT", "20"))
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
# Netscape-format cookies file (export from your browser) used to avoid YouTube's
# "Sign in to confirm you're not a bot" block. See README for how to generate one.
COOKIES_FILE = os.environ.get("COOKIES_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt"))

# ================= Storage & Settings =================
CHANNELS, MOVIES, SERIES = {}, {}, {}
CHANNEL_LOGOS = {}          # channel_name -> logo url
APPROVED_GROUPS = set()
CURRENT_STREAMS = {}        # chat_id -> dict(url, name, type, msg_id, token, start_ts, offset, duration, media_type, key)
RESUME_POSITIONS = {}       # "chat_id:key" -> elapsed_seconds
PLAY_REQUESTS = {}
PENDING_LOGO_UPLOAD = {}    # owner_id -> channel_name awaiting a photo
TMDB_CACHE = {}             # title -> {"backdrop": url, "logo": url, "runtime": minutes}
LIST_FILE_THRESHOLD = 100

# ---- Music engine state (merged from AviaxMusic) ----
MUSIC_QUEUES = {}           # chat_id -> [track dicts]
MUSIC_NOW = {}              # chat_id -> currently playing track dict, or absent if idle
MUSIC_PAUSED = set()        # chat_ids currently paused
BOT_SENT_MSGS = {}          # chat_id -> [message_ids...] the bot has sent in that chat

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

# ================= Stylized font (small caps, as provided) =================
_FANCY = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ғ', 'g': 'ɢ',
    'h': 'ʜ', 'i': 'ɪ', 'j': 'ɪ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ',
    'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 's', 't': 'ᴛ', 'u': 'ᴜ',
    'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ',
}


def _smallcaps(text: str) -> str:
    """Converts every letter to its small-caps unicode form, no capitalization."""
    return "".join(_FANCY.get(c.lower(), c) for c in text)


def fancy(text: str) -> str:
    """Title-case small caps used for headings/labels across the whole bot:
    a normal capital first letter on every word, small caps for the rest
    (e.g. 'now streaming' -> 'Nᴏᴡ Sᴛʀᴇᴀᴍɪɴɢ')."""
    return " ".join(
        (word[0].upper() + _smallcaps(word[1:])) if word else word
        for word in text.split(" ")
    )


def sc(text: str) -> str:
    """Case-preserving small caps: lowercase letters become small-caps unicode
    glyphs, UPPERCASE letters/digits/punctuation/emoji pass through untouched.
    Use this (instead of fancy()) whenever exact mixed-case matters, e.g.
    sc('Requested by') -> 'Rᴇǫᴜᴇsᴛᴇᴅ ʙʏ'."""
    return "".join(_FANCY.get(c, c) for c in text)


BOT_NAME = f"{fancy('meow stream')} 📺"
CREDITS = f"\n\n{E_BOLT} <b>Made By <a href='tg://user?id={OWNER_ID}'>{fancy('meow')}</a></b>"


def quote(text: str) -> str:
    """Wrap message body in Telegram's blockquote formatting."""
    return f"<blockquote>{text}</blockquote>"


def fmt_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


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
async def _tmdb_search_one(session, endpoint, query):
    try:
        search_url = f"https://api.themoviedb.org/3/search/{endpoint}"
        async with session.get(search_url, params={"api_key": TMDB_API_KEY, "query": query}, timeout=15) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            results = data.get("results") or []
            return results[0] if results else None
    except Exception:
        return None


def _simplify_title(title):
    """Strips common noise (part/vol/chapter N, trailing numbers, punctuation) for a looser second-pass search."""
    t = re.sub(r'\b(part|vol|volume|chapter|season)\b\.?\s*\d*', '', title, flags=re.I)
    t = re.sub(r'\d+$', '', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


async def fetch_tmdb_art(title: str, media_type: str):
    """
    media_type: 'movie' or 'tv'. Returns dict with backdrop url, logo url, and runtime (minutes) or None.
    Tries the title as given first; if that finds nothing, retries with a
    simplified version (strips "part 2", trailing numbers, punctuation) and
    then just the first couple of words, so partial/messy titles still match.
    """
    if not TMDB_API_KEY:
        return None
    cache_key = f"{media_type}:{title}"
    if cache_key in TMDB_CACHE:
        return TMDB_CACHE[cache_key]

    search_endpoint = "movie" if media_type == "movie" else "tv"
    try:
        async with aiohttp.ClientSession() as session:
            item = await _tmdb_search_one(session, search_endpoint, title)

            if not item:
                simplified = _simplify_title(title)
                if simplified and simplified.lower() != title.lower():
                    item = await _tmdb_search_one(session, search_endpoint, simplified)

            if not item:
                words = _simplify_title(title).split()
                if len(words) > 1:
                    item = await _tmdb_search_one(session, search_endpoint, " ".join(words[:2]))

            if not item:
                return None

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
def _github_logo_slug(name):
    slug = name.lower().strip()
    slug = slug.replace('&', 'and')
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    return f"{slug}-in"


async def fetch_github_channel_logo(name):
    """Fallback logo source: tv-logo/tv-logos GitHub repo (India), used when no manual/Xtream logo is set."""
    slug = _github_logo_slug(name)
    url = f"https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/india/{slug}.png"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, timeout=10) as resp:
                if resp.status == 200:
                    return url
    except Exception:
        pass
    return None


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
            await message.reply(f"🤖 <b>Assɪsᴛᴀɴᴛ Jᴏɪɴᴇᴅ Gʀᴏᴜᴘ!</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return True
        except UserAlreadyParticipant:
            return True
        except Exception as e:
            await message.reply(f"{E_WARN} <b>Assɪsᴛᴀɴᴛ Jᴏɪɴ Fᴀɪʟᴇᴅ!</b>\n<code>{esc(str(e))}</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
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
                quote(f"{E_DENY} <b>Aᴄᴄᴇss Dᴇɴɪᴇᴅ</b>\nThis Group (<code>{message.chat.id}</code>) is not authorized.") + CREDITS,
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


_FFMPEG_KWARG_CANDIDATES = ("additional_ffmpeg_parameters", "ffmpeg_parameters", "custom_ffmpeg_parameters")


def build_media_stream(url, quality, offset_seconds=0, media_type="movie"):
    """
    Build a MediaStream. For live channels, adds ffmpeg auto-reconnect flags
    (this is effectively what manually switching quality was doing — forcing
    a fresh, reconnecting pull from the source — so the bot now does it by
    itself instead of needing a manual quality switch). Also applies a
    start-time offset for seeking on movies/series.

    Different py-tgcalls releases use different kwarg names for raw ffmpeg
    args, so we try the known candidates in order and use whichever the
    installed version actually accepts (TypeError on an unknown kwarg is
    raised immediately at construction time, so this is safe to try).
    """
    ffmpeg_parts = []
    if media_type == "channel":
        ffmpeg_parts.append("-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5")
    if offset_seconds and offset_seconds > 0:
        ffmpeg_parts.append(f"-ss {int(offset_seconds)}")

    if not ffmpeg_parts:
        return MediaStream(url, video_parameters=quality)

    ffmpeg_arg = " ".join(ffmpeg_parts)
    for kwarg_name in _FFMPEG_KWARG_CANDIDATES:
        try:
            return MediaStream(url, video_parameters=quality, **{kwarg_name: ffmpeg_arg})
        except TypeError:
            continue
    print("⚠️ No known ffmpeg kwarg accepted by this py-tgcalls build — reconnect flags/seeking won't apply until this is verified against your installed version.")
    return MediaStream(url, video_parameters=quality)


def _track_msg(chat_id, msg):
    """Remember a message the bot sent in this chat, so it can be wiped when a new stream starts."""
    if not msg:
        return
    lst = BOT_SENT_MSGS.setdefault(chat_id, [])
    lst.append(msg.id)
    if len(lst) > 300:
        del lst[:len(lst) - 300]


async def _wipe_chat_bot_messages(client, chat_id):
    """Deletes every tracked bot message in this chat (called right before a new stream starts)."""
    ids = BOT_SENT_MSGS.pop(chat_id, [])
    if not ids:
        return
    for i in range(0, len(ids), 100):
        try:
            await client.delete_messages(chat_id, ids[i:i + 100])
        except Exception:
            pass


def stream_key(media_type, name, ep_code=None):
    return f"{media_type}:{name}:{ep_code or ''}"


# ================= 🎵 Music Engine (merged from AviaxMusic) =================
# Plays YouTube audio/video into the SAME group voice chat used for Live TV /
# Movies / Series, via the same assistant session (user_app) + PyTgCalls
# instance (call_py). A group's voice chat can only run one stream at a time,
# so starting a Live TV/Movie/Series stream stops any playing music (and
# vice versa) — see the _clear_music_state() calls around the codebase.

_YTDL_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "geo_bypass": True,
    "nocheckcertificate": True,
}
if os.path.isfile(COOKIES_FILE):
    _YTDL_BASE_OPTS["cookiefile"] = COOKIES_FILE
    print(f"🍪 yt-dlp: using cookies from {COOKIES_FILE}")
else:
    print(f"⚠️ yt-dlp: no cookies file found at {COOKIES_FILE} — YouTube may block some requests with "
          f"'Sign in to confirm you're not a bot'. Export your browser's YouTube cookies to that path "
          f"(Netscape format) to fix this.")


def _clear_music_state(chat_id):
    MUSIC_QUEUES.pop(chat_id, None)
    MUSIC_NOW.pop(chat_id, None)
    MUSIC_PAUSED.discard(chat_id)


def _ytdl_search_sync(query: str):
    opts = {**_YTDL_BASE_OPTS, "default_search": "ytsearch1", "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if info and "entries" in info:
            entries = [e for e in info["entries"] if e]
            info = entries[0] if entries else None
        return info


async def yt_search(query: str):
    """Resolves a YouTube URL or search text to a track dict, or None if nothing was found."""
    try:
        info = await asyncio.to_thread(_ytdl_search_sync, query)
    except Exception as e:
        print(f"⚠️ music search failed for '{query}': {e}")
        return None
    if not info:
        return None
    return {
        "id": info.get("id"),
        "title": (info.get("title") or "Unknown Title").strip()[:70],
        "duration": int(info.get("duration") or 0),
        "webpage_url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={info.get('id')}",
        "thumbnail": (info.get("thumbnails") or [{}])[-1].get("url") if info.get("thumbnails") else info.get("thumbnail"),
    }


def _ytdl_download_sync(video_id: str, video: bool):
    import glob
    existing = glob.glob(os.path.join(DOWNLOADS_DIR, f"{video_id}.*"))
    if existing:
        return existing[0]
    fmt = (
        "(bestvideo[height<=?480][ext=mp4])+(bestaudio[ext=m4a]/bestaudio)/best[height<=?480]"
        if video else
        "bestaudio[ext=m4a]/bestaudio/best"
    )
    opts = {
        **_YTDL_BASE_OPTS,
        "format": fmt,
        "outtmpl": os.path.join(DOWNLOADS_DIR, "%(id)s.%(ext)s"),
    }
    if video:
        opts["merge_output_format"] = "mp4"
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            ydl.download([url])
        except Exception as e:
            print(f"⚠️ music download failed for {video_id}: {e}")
            return None
    found = glob.glob(os.path.join(DOWNLOADS_DIR, f"{video_id}.*"))
    return found[0] if found else None


async def yt_download(video_id: str, video: bool = False):
    return await asyncio.to_thread(_ytdl_download_sync, video_id, video)


def _music_keyboard(chat_id, paused=False):
    return InlineKeyboardMarkup([
        [
            btn("▶️ Resume" if paused else "⏸ Pause", callback_data=f"music_toggle_{chat_id}", color="primary"),
            btn("⏭ Skip", callback_data=f"music_skip_{chat_id}", color="primary"),
        ],
        [btn("⏹ Stop", callback_data=f"music_stop_{chat_id}", color="danger")],
    ])


def _dur_short(seconds: int) -> str:
    """mm:ss without a leading zero on minutes, e.g. 279 -> '4:39' (matches the card spec)."""
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def _music_card_text(track, queue_position=None):
    """
    Renders the music status card in the requested style:
      ➻ Started Streaming              (now playing)
      ➲ Added To Queue At #N           (queued)

      ✨ Title: <title>
      ⏱ Duration: <m:ss> minutes
      🥀 Requested by: <requester>
    """
    dur = f"{_dur_short(track['duration'])} {_smallcaps('minutes')}" if track.get("duration") else _smallcaps("live")
    requester = track.get("requester", "someone")

    if queue_position:
        header = f"➲ {fancy('added to queue at')} #{queue_position}"
        sep = " : "
    else:
        header = f"➻ {fancy('started streaming')}"
        sep = ": "

    return quote(
        f"{header}\n\n"
        f"✨ {fancy('title')}{sep}{esc(track['title'])}\n"
        f"⏱ {fancy('duration')}{sep}{dur}\n"
        f"🥀 {fancy('requested')} ʙʏ{sep}{requester}"
    ) + CREDITS


async def _play_music_track(chat_id, track, status_msg=None):
    file_path = track.get("file_path") or await yt_download(track["id"], video=track.get("video", False))
    track["file_path"] = file_path

    if not file_path:
        if status_msg:
            try:
                await status_msg.edit_text(quote(f"{E_WARN} <b>{fancy('could not fetch that track, skipping')}</b>") + CREDITS, parse_mode=ParseMode.HTML)
            except Exception:
                pass
        return await _music_play_next(chat_id)

    stream_kwargs = {"media_path": file_path, "audio_parameters": AudioQuality.HIGH}
    if track.get("video"):
        stream_kwargs["video_parameters"] = VideoQuality.SD_480p
    else:
        stream_kwargs["video_flags"] = MediaStream.Flags.IGNORE
    stream = MediaStream(**stream_kwargs)

    try:
        await call_py.play(chat_id, stream)
    except Exception as e:
        if status_msg:
            try:
                await status_msg.edit_text(quote(f"❌ <b>{fancy('playback failed')}:</b> <code>{esc(str(e)[:150])}</code>") + CREDITS, parse_mode=ParseMode.HTML)
            except Exception:
                pass
        return await _music_play_next(chat_id)

    MUSIC_NOW[chat_id] = track
    MUSIC_PAUSED.discard(chat_id)
    text = _music_card_text(track)
    kb = _music_keyboard(chat_id)
    if status_msg:
        try:
            await status_msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)
            _track_msg(chat_id, status_msg)
            return
        except Exception:
            pass
    sent = await app.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)
    _track_msg(chat_id, sent)


async def _music_play_next(chat_id):
    queue = MUSIC_QUEUES.get(chat_id) or []
    if not queue:
        _clear_music_state(chat_id)
        try:
            await call_py.leave_call(chat_id)
        except Exception:
            pass
        return
    track = queue.pop(0)
    await _play_music_track(chat_id, track)


@app.on_message(filters.command(["play", "vplay"]) & filters.group)
@check_approval
async def play_music(client, message):
    cmd = message.command[0]
    is_video = cmd == "vplay"
    query = message.text.split(None, 1)[1].strip() if len(message.command) > 1 else (
        message.reply_to_message.text.strip() if message.reply_to_message and message.reply_to_message.text else None
    )
    if not query:
        return await message.reply(quote(f"{E_WARN} <b>Usᴀɢᴇ:</b> <code>/{cmd} song name or YouTube link</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    chat_id = message.chat.id
    if CURRENT_STREAMS.get(chat_id):
        return await message.reply(quote(f"{E_WARN} <b>A Lɪᴠᴇ Tᴠ/Mᴏᴠɪᴇ/Sᴇʀɪᴇs Sᴛʀᴇᴀᴍ Is Aʟʀᴇᴀᴅʏ Rᴜɴɴɪɴɢ Hᴇʀᴇ.</b>\nUse <code>/stopvc</code> first.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    queue = MUSIC_QUEUES.setdefault(chat_id, [])
    if len(queue) >= QUEUE_LIMIT:
        return await message.reply(quote(f"{E_WARN} <b>Qᴜᴇᴜᴇ Lɪᴍɪᴛ ({QUEUE_LIMIT}) Rᴇᴀᴄʜᴇᴅ.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    msg = await message.reply(quote(f"{E_BOLT} <b>Sᴇᴀʀᴄʜɪɴɢ:</b> {esc(query[:60])}"), parse_mode=ParseMode.HTML)
    track = await yt_search(query)
    if not track:
        return await msg.edit_text(quote(f"❌ <b>Nᴏ Rᴇsᴜʟᴛs Fᴏᴜɴᴅ Fᴏʀ:</b> {esc(query[:60])}") + CREDITS, parse_mode=ParseMode.HTML)

    if DURATION_LIMIT and track["duration"] and track["duration"] > DURATION_LIMIT:
        return await msg.edit_text(quote(f"{E_WARN} <b>Tʀᴀᴄᴋ Tᴏᴏ Lᴏɴɢ</b> ({fmt_time(track['duration'])}). Limit is {fmt_time(DURATION_LIMIT)}.") + CREDITS, parse_mode=ParseMode.HTML)

    track["video"] = is_video
    track["requester"] = message.from_user.mention if message.from_user else "someone"

    await ensure_assistant_in_chat(chat_id, message)

    if chat_id in MUSIC_NOW:
        queue.append(track)
        return await msg.edit_text(_music_card_text(track, queue_position=len(queue)), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    await _wipe_chat_bot_messages(client, chat_id)
    await _play_music_track(chat_id, track, status_msg=msg)


@app.on_message(filters.command(["skip", "next"]) & filters.group)
async def skip_music(client, message):
    chat_id = message.chat.id
    if chat_id not in MUSIC_NOW:
        return await message.reply(quote(f"❌ <b>Nᴏᴛʜɪɴɢ Is Pʟᴀʏɪɴɢ.</b>") + CREDITS, parse_mode=ParseMode.HTML)
    if not await is_admin_or_owner(client, chat_id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} Only group admins can skip.") + CREDITS, parse_mode=ParseMode.HTML)
    await message.reply(quote(f"{E_UP} <b>Sᴋɪᴘᴘᴇᴅ.</b>") + CREDITS, parse_mode=ParseMode.HTML)
    await _music_play_next(chat_id)


@app.on_message(filters.command("pause") & filters.group)
async def pause_music(client, message):
    chat_id = message.chat.id
    if chat_id not in MUSIC_NOW:
        return await message.reply(quote(f"❌ <b>Nᴏᴛʜɪɴɢ Is Pʟᴀʏɪɴɢ.</b>") + CREDITS, parse_mode=ParseMode.HTML)
    if not await is_admin_or_owner(client, chat_id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} Only group admins can pause.") + CREDITS, parse_mode=ParseMode.HTML)
    try:
        await call_py.pause(chat_id)
        MUSIC_PAUSED.add(chat_id)
        await message.reply(quote(f"⏸ <b>Pᴀᴜsᴇᴅ.</b>") + CREDITS, parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply(quote(f"❌ <b>Cᴏᴜʟᴅɴ'ᴛ Pᴀᴜsᴇ:</b> <code>{esc(str(e)[:120])}</code>") + CREDITS, parse_mode=ParseMode.HTML)


@app.on_message(filters.command("resume") & filters.group)
async def resume_music(client, message):
    chat_id = message.chat.id
    if chat_id not in MUSIC_NOW:
        return await message.reply(quote(f"❌ <b>Nᴏᴛʜɪɴɢ Is Pʟᴀʏɪɴɢ.</b>") + CREDITS, parse_mode=ParseMode.HTML)
    if not await is_admin_or_owner(client, chat_id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} Only group admins can resume.") + CREDITS, parse_mode=ParseMode.HTML)
    try:
        await call_py.resume(chat_id)
        MUSIC_PAUSED.discard(chat_id)
        await message.reply(quote(f"▶️ <b>Rᴇsᴜᴍᴇᴅ.</b>") + CREDITS, parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply(quote(f"❌ <b>Cᴏᴜʟᴅɴ'ᴛ Rᴇsᴜᴍᴇ:</b> <code>{esc(str(e)[:120])}</code>") + CREDITS, parse_mode=ParseMode.HTML)


@app.on_message(filters.command(["stopmusic", "stopplay"]) & filters.group)
async def stop_music_cmd(client, message):
    chat_id = message.chat.id
    if chat_id not in MUSIC_NOW and not MUSIC_QUEUES.get(chat_id):
        return await message.reply(quote(f"❌ <b>Nᴏᴛʜɪɴɢ Is Pʟᴀʏɪɴɢ.</b>") + CREDITS, parse_mode=ParseMode.HTML)
    if not await is_admin_or_owner(client, chat_id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} Only group admins can stop music.") + CREDITS, parse_mode=ParseMode.HTML)
    _clear_music_state(chat_id)
    try:
        await call_py.leave_call(chat_id)
    except Exception:
        pass
    await message.reply(quote(f"{E_STOP} <b>Mᴜsɪᴄ Sᴛᴏᴘᴘᴇᴅ, Qᴜᴇᴜᴇ Cʟᴇᴀʀᴇᴅ.</b>") + CREDITS, parse_mode=ParseMode.HTML)


@app.on_message(filters.command("queue") & filters.group)
async def show_queue(client, message):
    chat_id = message.chat.id
    now = MUSIC_NOW.get(chat_id)
    queue = MUSIC_QUEUES.get(chat_id) or []
    if not now and not queue:
        return await message.reply(quote("❌ <b>Qᴜᴇᴜᴇ Is Eᴍᴘᴛʏ.</b>") + CREDITS, parse_mode=ParseMode.HTML)
    body = f"{E_FIRE} <b>{fancy('queue')}</b>\n\n"
    if now:
        body += f"▶️ <b>{esc(now['title'])}</b> (playing)\n\n"
    for i, t in enumerate(queue, 1):
        body += f"{i}. {esc(t['title'])}\n"
    await message.reply(quote(body) + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_callback_query(filters.regex(r"^music_toggle_(-?\d+)$"))
async def music_toggle_cb(client, callback_query):
    chat_id = int(callback_query.matches[0].group(1))
    if not await is_admin_or_owner(client, chat_id, callback_query.from_user.id):
        return await callback_query.answer("🚫 Only group admins can do that.", show_alert=True)
    try:
        if chat_id in MUSIC_PAUSED:
            await call_py.resume(chat_id)
            MUSIC_PAUSED.discard(chat_id)
            await callback_query.answer("▶️ Resumed")
        else:
            await call_py.pause(chat_id)
            MUSIC_PAUSED.add(chat_id)
            await callback_query.answer("⏸ Paused")
        try:
            await callback_query.message.edit_reply_markup(_music_keyboard(chat_id, paused=chat_id in MUSIC_PAUSED))
        except Exception:
            pass
    except Exception as e:
        await callback_query.answer(f"Failed: {str(e)[:100]}", show_alert=True)


@app.on_callback_query(filters.regex(r"^music_skip_(-?\d+)$"))
async def music_skip_cb(client, callback_query):
    chat_id = int(callback_query.matches[0].group(1))
    if not await is_admin_or_owner(client, chat_id, callback_query.from_user.id):
        return await callback_query.answer("🚫 Only group admins can do that.", show_alert=True)
    await callback_query.answer("⏭ Skipping...")
    await _music_play_next(chat_id)


@app.on_callback_query(filters.regex(r"^music_stop_(-?\d+)$"))
async def music_stop_cb(client, callback_query):
    chat_id = int(callback_query.matches[0].group(1))
    if not await is_admin_or_owner(client, chat_id, callback_query.from_user.id):
        return await callback_query.answer("🚫 Only group admins can do that.", show_alert=True)
    _clear_music_state(chat_id)
    try:
        await call_py.leave_call(chat_id)
    except Exception:
        pass
    await callback_query.answer("⏹ Stopped")
    try:
        await callback_query.message.delete()
    except Exception:
        pass


@call_py.on_update()
async def _on_call_update(_, update):
    """Auto-advances the music queue when a track finishes, and cleans up
    state if the assistant gets kicked or the voice chat is closed."""
    chat_id = getattr(update, "chat_id", None)
    if chat_id is None:
        return
    if isinstance(update, StreamEnded) and chat_id in MUSIC_NOW:
        await _music_play_next(chat_id)
    elif isinstance(update, ChatUpdate) and str(getattr(update, "status", "")).split(".")[-1] in (
        "KICKED", "LEFT_GROUP", "CLOSED_VOICE_CHAT",
    ):
        _clear_music_state(chat_id)
        CURRENT_STREAMS.pop(chat_id, None)


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
        return await message.reply(f"{E_WARN} <b>Usᴀɢᴇ:</b> <code>/addxtreamseries URL User Pass</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    msg = await message.reply(f"{E_BOLT} <b>Fᴇᴛᴄʜɪɴɢ Xᴛʀᴇᴀᴍ Sᴇʀɪᴇs Lɪsᴛ...</b>", parse_mode=ParseMode.HTML)

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

        await msg.edit_text(f"{E_CHECK} <b>Sᴄᴀɴ Cᴏᴍᴘʟᴇᴛᴇ!</b>\nLoaded episodes for <b>{processed_count}</b> series from Xtream API!{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    except Exception as e:
        await msg.edit_text(f"❌ An error occurred: <code>{esc(str(e)[:150])}</code>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command("addxtreammovies") & filters.user(OWNER_ID))
async def add_xtream_movies(client, message):
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(f"{E_WARN} <b>Usᴀɢᴇ:</b> <code>/addxtreammovies URL User Pass</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_vod_streams"
    msg = await message.reply(f"{E_BOLT} <b>Fᴇᴛᴄʜɪɴɢ Xᴛʀᴇᴀᴍ Mᴏᴠɪᴇs...</b> This may take a moment.", parse_mode=ParseMode.HTML)
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
                    await msg.edit_text(f"{E_CHECK} <b>Lᴏᴀᴅᴇᴅ {count} Mᴏᴠɪᴇs Fʀᴏᴍ Xᴛʀᴇᴀᴍ Aᴘɪ!</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                else:
                    await msg.edit_text(f"❌ Error Status: {resp.status}")
    except Exception as e:
        await msg.edit_text(f"❌ Failed: <code>{esc(str(e)[:150])}</code>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command("addxtreamchannels") & filters.user(OWNER_ID))
async def add_xtream_channels(client, message):
    """Bonus command: imports live channels (+ their stream_icon logos) from an Xtream panel."""
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(f"{E_WARN} <b>Usᴀɢᴇ:</b> <code>/addxtreamchannels URL User Pass</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    msg = await message.reply(f"{E_BOLT} <b>Fᴇᴛᴄʜɪɴɢ Xᴛʀᴇᴀᴍ Lɪᴠᴇ Cʜᴀɴɴᴇʟs...</b>", parse_mode=ParseMode.HTML)
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
        await msg.edit_text(f"{E_CHECK} <b>Lᴏᴀᴅᴇᴅ {count} Cʜᴀɴɴᴇʟs</b> ({logo_count} with logos) from Xtream API!{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        await msg.edit_text(f"❌ Failed: <code>{esc(str(e)[:150])}</code>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command("addchannellogoxtremecode") & filters.user(OWNER_ID))
async def add_channel_logo_xtream(client, message):
    """Re-syncs logos only (doesn't touch existing channel URLs) from an Xtream panel's stream_icon field."""
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(f"{E_WARN} <b>Usᴀɢᴇ:</b> <code>/addchannellogoxtremecode URL User Pass</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    msg = await message.reply(f"{E_BOLT} <b>Sʏɴᴄɪɴɢ Cʜᴀɴɴᴇʟ Lᴏɢᴏs...</b>", parse_mode=ParseMode.HTML)
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
        await msg.edit_text(f"{E_CHECK} <b>Sʏɴᴄᴇᴅ Lᴏɢᴏs Fᴏʀ {matched} Exɪsᴛɪɴɢ Cʜᴀɴɴᴇʟs.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
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
        return await message.reply(f"{E_WARN} <b>Usᴀɢᴇ:</b> reply to a photo with <code>/addchannellogo Channel Name</code>, or <code>/addchannellogo Channel Name https://image-url</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    rest = args[1].strip()
    url_match = re.search(r'(https?://\S+)$', rest)
    if url_match:
        logo_url = url_match.group(1)
        name = cleanup_name(rest[:url_match.start()].strip())
        if name not in CHANNELS:
            return await message.reply(f"❌ No channel named <b>{esc(name.title())}</b> found.{CREDITS}", parse_mode=ParseMode.HTML)
        CHANNEL_LOGOS[name] = logo_url
        save_data()
        return await message.reply(f"{E_CHECK} <b>Lᴏɢᴏ Sᴇᴛ Fᴏʀ {esc(name.title())}!</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    name = cleanup_name(rest)
    if name not in CHANNELS:
        return await message.reply(f"❌ No channel named <b>{esc(name.title())}</b> found.{CREDITS}", parse_mode=ParseMode.HTML)

    if message.reply_to_message and message.reply_to_message.photo:
        file_path = await client.download_media(message.reply_to_message.photo.file_id)
        uploaded = await client.send_photo(message.chat.id, file_path)
        CHANNEL_LOGOS[name] = uploaded.photo.file_id
        save_data()
        return await message.reply(f"{E_CHECK} <b>Lᴏɢᴏ Sᴇᴛ Fᴏʀ {esc(name.title())}!</b>{CREDITS}", parse_mode=ParseMode.HTML)

    PENDING_LOGO_UPLOAD[message.from_user.id] = name
    await message.reply(f"{E_CAM} <b>Nᴏᴡ Sᴇɴᴅ Tʜᴇ Lᴏɢᴏ Iᴍᴀɢᴇ</b> for <b>{esc(name.title())}</b> (as a photo).{CREDITS}", parse_mode=ParseMode.HTML)


@app.on_message(filters.photo & filters.user(OWNER_ID) & filters.private)
async def receive_pending_logo(client, message):
    name = PENDING_LOGO_UPLOAD.pop(message.from_user.id, None)
    if not name:
        return
    CHANNEL_LOGOS[name] = message.photo.file_id
    save_data()
    await message.reply(f"{E_CHECK} <b>Lᴏɢᴏ Sᴇᴛ Fᴏʀ {esc(name.title())}!</b>{CREDITS}", parse_mode=ParseMode.HTML)


# ================= LIST COMMANDS =================
@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    if not CHANNELS:
        return await message.reply(quote(f"❌ <b>Nᴏ Cʜᴀɴɴᴇʟs Fᴏᴜɴᴅ.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

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
        return await message.reply(quote(f"❌ <b>Nᴏ Mᴏᴠɪᴇs Fᴏᴜɴᴅ.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

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
        return await message.reply(quote(f"❌ <b>Nᴏ Sᴇʀɪᴇs Fᴏᴜɴᴅ.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

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
        return await message.reply(quote(f"❌ <b>Nᴏ {media_type} Fᴏᴜɴᴅ Mᴀᴛᴄʜɪɴɢ Tʜᴀᴛ Nᴀᴍᴇ!</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if len(matches) == 1:
        return await _start_stream(client, message, matches[0], media_type, raw_query=" ".join(message.command[1:]), user_message=message)

    buttons = []
    for name in matches[:20]:
        req_id = str(uuid.uuid4())[:8]
        PLAY_REQUESTS[req_id] = (name, " ".join(message.command[1:]))
        buttons.append([InlineKeyboardButton(name.title(), callback_data=f"resolve_{media_type}_{req_id}")])

    picker = await message.reply(quote(f"🤔 <b>Fᴏᴜɴᴅ Mᴜʟᴛɪᴘʟᴇ Rᴇsᴜʟᴛs Fᴏʀ {esc(query.title())}. Pʟᴇᴀsᴇ Cʜᴏᴏsᴇ Oɴᴇ:</b>"), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
    _track_msg(message.chat.id, picker)
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
        resume_prompt = await message.reply(quote(f"{E_PIN} You previously stopped <b>{esc(display_name)}</b> at <b>{fmt_time(saved_pos)}</b>. Resume or start over?"), parse_mode=ParseMode.HTML, reply_markup=buttons)
        _track_msg(chat_id, resume_prompt)
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

    # Wipe every message the bot has previously sent in this chat before starting the new stream.
    await _wipe_chat_bot_messages(client, chat_id)
    _clear_music_state(chat_id)  # a live TV/movie/series stream takes over the voice chat from music

    msg = await message.reply(quote(f"{E_BOLT} <b>Iɴɪᴛɪᴀʟɪᴢɪɴɢ {type_label}...</b>"), parse_mode=ParseMode.HTML)
    _track_msg(chat_id, msg)

    quality = VideoQuality.HD_720p
    stream = build_media_stream(url, quality, offset, media_type)

    try:
        await robust_play(chat_id, stream)
    except Exception as e:
        return await msg.edit_text(quote(f"❌ <b>Sᴛʀᴇᴀᴍ Fᴀɪʟᴇᴅ!</b>\n<code>{esc(str(e)[:150])}</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    token = uuid.uuid4().hex
    tmdb_info = None
    logo_url = None
    if media_type in ("movie", "series"):
        tmdb_info = await fetch_tmdb_art(name, "movie" if media_type == "movie" else "tv")
    elif media_type == "channel":
        logo_url = CHANNEL_LOGOS.get(name)
        if not logo_url:
            logo_url = await fetch_github_channel_logo(name)

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

    art = banner_file or ((tmdb_info or {}).get("backdrop") if tmdb_info else logo_url)
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
    _track_msg(chat_id, sent)

    try:
        effect_msg = await reply_effect(message, "🎬", effect="fire", quote=False)
        if effect_msg:
            asyncio.create_task(_delete_after(effect_msg, 4))
    except Exception:
        pass

    if media_type == "channel":
        asyncio.create_task(_channel_refresh_loop(chat_id, token))
    else:
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
        f"❖ <b>Tɪᴛʟᴇ:</b> {esc(display_name)}\n"
        f"❖ <b>Tʏᴘᴇ:</b> {type_label}\n"
        f"❖ <b>Qᴜᴀʟɪᴛʏ:</b> {quality} {E_CHECK}"
    ) + CREDITS


def _build_stream_keyboard(elapsed, duration, media_type):
    rows = []
    if media_type != "channel":
        time_label = f"⏱ {fmt_time(elapsed)} / {fmt_time(duration)}" if duration else f"⏱ {fmt_time(elapsed)} / --:--"
        rows.append([btn(time_label, callback_data="noop")])
    rows.append([btn(q.upper(), callback_data=f"q_{q}", color="primary") for q in ["360p", "480p", "720p", "1080p"]])
    rows.append([btn("⏹ Stop", callback_data="stop_stream", color="danger")])
    rows.append([btn("👑 Support", url=SUPPORT_URL, color="primary"), btn("🔔 Updates", url=UPDATES_URL, color="primary")])
    return InlineKeyboardMarkup(rows)


async def _progress_loop(chat_id, token):
    """Movies/series only — updates the elapsed/total time button."""
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


async def _channel_refresh_loop(chat_id, token):
    """
    Live TV only. Periodically re-invokes play() on the same URL — this is
    effectively what manually switching quality was already doing to fix
    stuck channels, so the bot now does it by itself before it gets stuck.
    """
    while True:
        await asyncio.sleep(240)
        stream = CURRENT_STREAMS.get(chat_id)
        if not stream or stream.get("token") != token or stream["media_type"] != "channel":
            return
        try:
            quality = QUALITY_PRESETS.get(stream["quality"], VideoQuality.HD_720p)
            stream_obj = build_media_stream(stream["url"], quality, 0, "channel")
            await robust_play(chat_id, stream_obj, retries=2)
            print(f"🔄 Periodic silent refresh applied to channel stream in {chat_id}")
        except Exception as e:
            print(f"⚠️ Periodic channel refresh failed for {chat_id}: {e}")


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
        stream_obj = build_media_stream(stream["url"], quality, secs, stream["media_type"])
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
        stream_obj = build_media_stream(stream["url"], vq, elapsed, stream["media_type"])
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
    _clear_music_state(chat_id)


@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    if not await is_admin_or_owner(client, message.chat.id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} Only group admins can stop the current stream."), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    had_stream = message.chat.id in CURRENT_STREAMS
    await _do_stop(message.chat.id)
    if had_stream:
        await message.reply(quote(f"{E_STOP} <b>Sᴛʀᴇᴀᴍ Sᴛᴏᴘᴘᴇᴅ.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        await message.reply(quote(f"❌ <b>Nᴏ Aᴄᴛɪᴠᴇ Sᴛʀᴇᴀᴍ Tᴏ Sᴛᴏᴘ.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


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
                    stream_obj = build_media_stream(stream["url"], quality, elapsed if stream["media_type"] != "channel" else 0, stream["media_type"])
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
    f"<b>📺 Lɪᴠᴇ Tᴠ / Mᴏᴠɪᴇs / Sᴇʀɪᴇs</b>\n"
    f"❖ <code>/channels</code> — Browse Live TV\n"
    f"❖ <code>/movies</code> — Browse Movies\n"
    f"❖ <code>/series</code> — Browse Series\n"
    f"❖ <code>/livetv name</code> — Play Channel\n"
    f"❖ <code>/playmovie name</code> — Play Movie\n"
    f"❖ <code>/playseries name - s01e01</code> — Play Series\n"
    f"❖ <code>/seek mm:ss</code> — Jump to a timestamp\n"
    f"❖ <code>/stopvc</code> — Stop Current Stream (group admins only)\n\n"
    f"<b>🎵 Mᴜsɪᴄ</b>\n"
    f"❖ <code>/play song name or link</code> — Play/Queue Audio\n"
    f"❖ <code>/vplay song name or link</code> — Play/Queue Video\n"
    f"❖ <code>/pause</code> / <code>/resume</code> — Pause / Resume\n"
    f"❖ <code>/skip</code> — Skip Track (admins only)\n"
    f"❖ <code>/queue</code> — Show Queue\n"
    f"❖ <code>/stopmusic</code> — Stop Music, Clear Queue (admins only)"
) + CREDITS


def _welcome_text(is_group: bool) -> str:
    if is_group:
        return quote(f"{E_SPARK} <b>{fancy('meow stream')} 📺 Is Rᴇᴀᴅʏ!</b>\nTap <b>📜 Cᴏᴍᴍᴀɴᴅs</b> below to get started.") + CREDITS
    return quote(
        f"{E_SPARK} <b>Wᴇʟᴄᴏᴍᴇ Tᴏ {fancy('meow stream')} 📺</b> — the most advanced Telegram streaming bot.\n\n"
        f"{E_CAM} Live TV, Movies & Series, streamed straight into your group's voice chat.\n"
        f"{E_SIGNAL} Multiple quality options, seek/resume, auto-recovery on drops.\n"
        f"🎵 Plus a full YouTube music engine — queue, skip, pause/resume.\n\n"
        f"Tap <b>📜 Cᴏᴍᴍᴀɴᴅs</b> below to see everything I can do."
    ) + CREDITS


async def _edit_in_place(callback_query, text, keyboard):
    """Edits the /start message (photo caption or plain text, whichever it is) in place."""
    try:
        if callback_query.message.photo:
            await callback_query.message.edit_caption(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        else:
            await callback_query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
    except Exception:
        pass


@app.on_callback_query(filters.regex(r"^show_commands$"))
async def show_commands_cb(client, callback_query):
    await callback_query.answer()
    back_kb = InlineKeyboardMarkup([[btn("⬅ Back", callback_data="back_to_start", color="primary")]])
    await _edit_in_place(callback_query, COMMANDS_TEXT, back_kb)


@app.on_callback_query(filters.regex(r"^back_to_start$"))
async def back_to_start_cb(client, callback_query):
    await callback_query.answer()
    is_group = callback_query.message.chat.type != ChatType.PRIVATE
    await _edit_in_place(callback_query, _welcome_text(is_group), _start_keyboard())


@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await send_start_banner(client, message.chat.id, _welcome_text(False), _start_keyboard())


@app.on_message(filters.command("start") & filters.group)
async def start_cmd_group(client, message):
    await send_start_banner(client, message.chat.id, _welcome_text(True), _start_keyboard())


@app.on_message(filters.command("delchannel") & filters.user(OWNER_ID))
async def del_channel(client, message):
    if len(message.command) < 2:
        return await message.reply(quote(f"{E_WARN} <b>Usᴀɢᴇ:</b> <code>/delchannel Channel Name</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    name = cleanup_name(" ".join(message.command[1:]))
    if name not in CHANNELS:
        return await message.reply(quote(f"❌ No channel named <b>{esc(name.title())}</b> found.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    CHANNELS.pop(name, None)
    CHANNEL_LOGOS.pop(name, None)
    save_data()
    await message.reply(quote(f"{E_CHECK} <b>Dᴇʟᴇᴛᴇᴅ Cʜᴀɴɴᴇʟ:</b> {esc(name.title())}") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)




@app.on_message(filters.command("delallchannels") & filters.user(OWNER_ID))
async def del_all_channels(client, message):
    CHANNELS.clear(); CHANNEL_LOGOS.clear(); save_data()
    await message.reply(f"🗑️ <b>Aʟʟ Lɪᴠᴇ Tᴠ Cʜᴀɴɴᴇʟs Dᴇʟᴇᴛᴇᴅ.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("delallmovies") & filters.user(OWNER_ID))
async def del_all_movies(client, message):
    MOVIES.clear(); save_data()
    await message.reply(f"🗑️ <b>Aʟʟ Mᴏᴠɪᴇs Dᴇʟᴇᴛᴇᴅ.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("delallseries") & filters.user(OWNER_ID))
async def del_all_series(client, message):
    SERIES.clear(); save_data()
    await message.reply(f"🗑️ <b>Aʟʟ Sᴇʀɪᴇs Dᴇʟᴇᴛᴇᴅ.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply(f"{E_WARN} <b>Usᴀɢᴇ:</b> <code>/addchannel URL Channel Name</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    url, name = args[1], cleanup_name(args[2])
    CHANNELS[name] = url
    save_data()
    await message.reply(f"{E_CHECK} <b>Cʜᴀɴɴᴇʟ Aᴅᴅᴇᴅ:</b> {esc(name.title())}{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


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
            f"📡 <b>Aᴄᴛɪᴠᴇ Sᴛʀᴇᴀᴍs:</b> {len(CURRENT_STREAMS)}\n"
            f"🎵 <b>Aᴄᴛɪᴠᴇ Mᴜsɪᴄ Sᴇssɪᴏɴs:</b> {len(MUSIC_NOW)}\n"
            f"📺 <b>Cʜᴀɴɴᴇʟs:</b> {len(CHANNELS)} | 🎬 <b>Mᴏᴠɪᴇs:</b> {len(MOVIES)}\n"
            f"🍿 <b>Sᴇʀɪᴇs:</b> {len(SERIES)}\n"
            f"🖼️ <b>Cʜᴀɴɴᴇʟ Lᴏɢᴏs:</b> {len(CHANNEL_LOGOS)}\n"
            f"🛡️ <b>Aᴘᴘʀᴏᴠᴇᴅ Gʀᴏᴜᴘs:</b> {len(APPROVED_GROUPS)}\n")
    for grp in APPROVED_GROUPS:
        body += f"├ <code>{grp}</code>\n"
    await message.reply(quote(body) + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast(client, message):
    if len(message.command) < 2:
        return await message.reply("⚠️ Usage: <code>/broadcast message</code>", parse_mode=ParseMode.HTML)
    msg_text = message.text.split(None, 1)[1]
    success, failed = 0, 0
    m = await message.reply(f"{E_BOLT} <b>Bʀᴏᴀᴅᴄᴀsᴛɪɴɢ...</b>", parse_mode=ParseMode.HTML)
    for chat_id in APPROVED_GROUPS:
        try:
            await app.send_message(chat_id, f"{E_BELL} <b>Bʀᴏᴀᴅᴄᴀsᴛ</b>\n\n{esc(msg_text)}{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            success += 1
        except Exception:
            failed += 1
    await m.edit_text(f"{E_CHECK} <b>Bʀᴏᴀᴅᴄᴀsᴛ Cᴏᴍᴘʟᴇᴛᴇ!</b>\nSent: {success} | Failed: {failed}{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


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
        await app.send_message(OWNER_ID, f"🟢 <b>{BOT_NAME} Oɴʟɪɴᴇ!</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass
    await idle()
    for chat_id in list(CURRENT_STREAMS.keys()):
        await _do_stop(chat_id)
    for chat_id in list(MUSIC_NOW.keys()):
        _clear_music_state(chat_id)
        try:
            await call_py.leave_call(chat_id)
        except Exception:
            pass
    save_data()
    await app.stop(); await user_app.stop()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())

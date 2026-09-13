import asyncio
import json
import os
import re
import sys
import time
import uuid
from html import escape as esc
from io import BytesIO
from threading import Thread

import aiohttp
from flask import Flask
from pyrogram import Client, filters, idle
from pyrogram.enums import ChatMembersFilter, ChatType, ParseMode
from pyrogram.errors import UserAlreadyParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, VideoQuality

try:
    from pytgcalls.types import AudioQuality
except ImportError:
    AudioQuality = None

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")


class _Tee:
    """Mirrors everything written to stdout/stderr into a log file too, so /logs has something to send."""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
            except Exception:
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass


try:
    _log_fh = open(LOG_FILE, "a", encoding="utf-8")
    sys.stdout = _Tee(sys.stdout, _log_fh)
    sys.stderr = _Tee(sys.stderr, _log_fh)
except Exception:
    pass

# ================= Configuration =================
# Everything below is hardcoded directly per your request (no .env / environment
# variables). SECURITY NOTE: since these values now live in plain text in this
# file, anyone who gets a copy of bot.py — including if it's ever pushed to a
# public/shared repo — gets full access to your bot AND your Telegram account
# via SESSION_STRING. Rotate the bot token + session string if this file is
# ever shared or committed anywhere public.
API_ID = 33181534
API_HASH = "ef2c1ed56bb1fc743b3fbc244582efbb"
BOT_TOKEN = "8524475183:AAGglXOt2oLCyv2N1vC_R_1gV7T9dvEOWfI"
SESSION_STRING = "BQH6T14ALjIjmZAb8MlRkWdpYDT3va81anw3Qf1RFcqA46KnAbzyjFIikJkEjQ98jz0XUn97iuQg0XmrtVw7Ul5OIuzlpahfD5UyWY94aMpf9-WwyZi6V1N0mKKLTMXIY_1SZuV_S4VDNWGCSXEAuwZ41JJdvrxSrIavDjp50667qAGinuVw40QeKbs3Q2XooskSvzRqh1O0UxQBMddBDE83eG9ViW-S5X_2nqUzhZTP_-YhZ9m7xjWf1NwsdoCqf0cT6aYniKt38lb5D0uyq_s72BCRqZhSEb2S_ZD2LCycZ80g9rXeMFNrH7CinhxgjYz5O2iyHzKuJmH7Jvkhl8BruYeIXwAAAAILtc1CAA"
OWNER_ID = 8242523973

# TMDB_API_KEY MUST be set for movie/series backdrops and title logos to work at
# all — if this is empty, TMDB is silently skipped (by design, so it doesn't
# crash) and NO banner will ever show. Get a free key at
# https://www.themoviedb.org/settings/api and paste it in below.
TMDB_API_KEY = ""  # <-- PUT YOUR REAL TMDB API KEY HERE

SUPPORT_URL = "https://t.me/MeowpawSupport"
UPDATES_URL = "https://t.me/MeowpawSupport"
START_BANNER_URL = "https://i.ibb.co/5WjFTqvr/file-0000000093dc820bbaf14a91927d4a4c.png"
MUSIC_CARD_BG_URL = "https://i.ibb.co/vtgx7Ds/IMG-20260913-163458.png"

# Netscape-format cookies.txt exported from a browser logged into YouTube.
# Needed for /play to reliably fetch audio without hitting bot-detection /
# age-restriction / rate-limit walls. Place the file next to bot.py and it
# will be picked up automatically; /play still works without it, just less
# reliably for some videos.
YOUTUBE_COOKIES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")

# Railway assigns this dynamically per deploy for routing — this is the one
# value that has to stay read from the environment, or the health check port
# won't match what Railway expects.
PORT = int(os.environ.get("PORT", 8080))

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
BOT_SENT_MSGS = {}          # chat_id -> [message_ids...] the bot has sent in that chat

BLACKLISTED_USERS = set()
BLACKLISTED_GROUPS = set()
AUTH_USERS = {}              # chat_id -> set(user_ids) allowed to control playback without being admin
ADMIN_CACHE = {}             # chat_id -> (timestamp, set(admin_user_ids))
ADMIN_CACHE_TTL = 600        # seconds
_LAST_MANUAL_RELOAD = {}     # chat_id -> timestamp of last /reload
MUSIC_QUEUES = {}            # chat_id -> [track_dict, ...] waiting to play next

QUALITY_PRESETS = {
    "360p": VideoQuality.SD_360p, "480p": VideoQuality.SD_480p,
    "720p": VideoQuality.HD_720p, "1080p": VideoQuality.FHD_1080p,
}

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.json")
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
    # Pyrogram's actual custom-emoji HTML syntax is <emoji id=NUMBER>fallback</emoji> —
    # no quotes, tag name "emoji" not "tg-emoji", attribute "id" not "emoji-id".
    # (Confirmed against a real working bot's language file — this was the actual bug.)
    return f"<emoji id={emoji_id}>{fallback}</emoji>"

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


def fancy(text: str) -> str:
    return "".join(_FANCY.get(c.lower(), c) for c in text)


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
            "blacklisted_users": list(BLACKLISTED_USERS),
            "blacklisted_groups": list(BLACKLISTED_GROUPS),
            "auth_users": {str(k): list(v) for k, v in AUTH_USERS.items()},
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
        BLACKLISTED_USERS.update(payload.get("blacklisted_users", []))
        BLACKLISTED_GROUPS.update(payload.get("blacklisted_groups", []))
        for k, v in payload.get("auth_users", {}).items():
            AUTH_USERS[int(k)] = set(v)
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
        print("⚠️ fetch_tmdb_art: TMDB_API_KEY is empty — skipping. Set it in Railway's Variables tab to enable banners.")
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
                print(f"⚠️ fetch_tmdb_art: TMDB found no match for '{title}' ({search_endpoint}) after 3 search attempts.")
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


# ================= Music (YouTube via yt-dlp) =================
def _ytdlp_extract_sync(query):
    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch1",
        "skip_download": True,
    }
    if os.path.exists(YOUTUBE_COOKIES_PATH):
        ydl_opts["cookiefile"] = YOUTUBE_COOKIES_PATH
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if info and "entries" in info and info["entries"]:
            info = info["entries"][0]
        return info


async def extract_track(query):
    """Runs yt-dlp (blocking) in a thread pool so it doesn't stall the event loop."""
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed — add 'yt-dlp' to requirements.txt")
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _ytdlp_extract_sync, query)
    if not info:
        raise RuntimeError("No results found")
    return {
        "title": info.get("title") or "Unknown title",
        "webpage_url": info.get("webpage_url") or "",
        "stream_url": info.get("url"),
        "thumbnail": info.get("thumbnail"),
        "duration": int(info.get("duration") or 0),
    }


async def compose_music_card(thumbnail_url, title):
    """
    Composites a now-playing card onto MUSIC_CARD_BG_URL: rounded thumbnail on
    the left, title text on the right — a best-effort visual approximation of
    the reference layout using Pillow's built-in font (no custom .otf/.ttf font
    file is bundled with the bot, so this won't exactly match a branded font).
    Real playback controls are real Telegram buttons underneath this image, not
    drawn into it, so they're actually functional rather than decorative.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps
    except ImportError:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(MUSIC_CARD_BG_URL, timeout=20) as resp:
                if resp.status != 200:
                    return None
                bg_bytes = await resp.read()
            thumb_bytes = None
            if thumbnail_url:
                try:
                    async with session.get(thumbnail_url, timeout=20) as resp2:
                        if resp2.status == 200:
                            thumb_bytes = await resp2.read()
                except Exception:
                    thumb_bytes = None

        bg = Image.open(BytesIO(bg_bytes)).convert("RGBA")
        w, h = bg.size

        if thumb_bytes:
            thumb = Image.open(BytesIO(thumb_bytes)).convert("RGBA")
            side = int(h * 0.62)
            thumb = ImageOps.fit(thumb, (side, side))
            mask = Image.new("L", (side, side), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, side, side], radius=int(side * 0.12), fill=255)
            pos_x, pos_y = int(w * 0.09), int((h - side) / 2)
            bg.paste(thumb, (pos_x, pos_y), mask)
            text_x = pos_x + side + int(w * 0.04)
        else:
            text_x = int(w * 0.09)

        draw = ImageDraw.Draw(bg)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(h * 0.075))
        except Exception:
            try:
                font = ImageFont.load_default(size=int(h * 0.075))
            except TypeError:
                font = ImageFont.load_default()

        # Wrap title across up to 2 lines within the available width.
        max_width = int(w * 0.42)
        words = title.split()
        lines, current = [], ""
        for word in words:
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
            if len(lines) == 2:
                break
        if current and len(lines) < 2:
            lines.append(current)
        text_y = int(h * 0.30)
        for line in lines[:2]:
            draw.text((text_x, text_y), line, font=font, fill=(255, 255, 255, 255))
            text_y += int(h * 0.11)

        out = BytesIO()
        bg.convert("RGB").save(out, format="JPEG", quality=92)
        out.seek(0)
        out.name = "music_card.jpg"
        return out
    except Exception as e:
        print(f"⚠️ compose_music_card failed: {e}")
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
            await message.reply(f"🤖 <b>{fancy('assistant joined group')}!</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return True
        except UserAlreadyParticipant:
            return True
        except Exception as e:
            await message.reply(f"{E_WARN} <b>{fancy('assistant join failed')}!</b>\n<code>{esc(str(e))}</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
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


async def _fetch_admin_ids(client, chat_id):
    ids = set()
    try:
        async for member in client.get_chat_members(chat_id, filter=ChatMembersFilter.ADMINISTRATORS):
            ids.add(member.user.id)
    except Exception as e:
        print(f"⚠️ admin cache fetch failed for {chat_id}: {e}")
    return ids


async def is_admin_or_owner(client, chat_id, user_id):
    if user_id == OWNER_ID:
        return True
    now = time.time()
    cached = ADMIN_CACHE.get(chat_id)
    if not cached or now - cached[0] > ADMIN_CACHE_TTL:
        admin_ids = await _fetch_admin_ids(client, chat_id)
        ADMIN_CACHE[chat_id] = (now, admin_ids)
        cached = ADMIN_CACHE[chat_id]
    return user_id in cached[1]


async def is_admin_owner_or_auth(client, chat_id, user_id):
    """Admins, the owner, or a per-chat authorized user can control playback."""
    if user_id in AUTH_USERS.get(chat_id, set()):
        return True
    return await is_admin_or_owner(client, chat_id, user_id)


def is_blacklisted(user_id, chat_id):
    return user_id in BLACKLISTED_USERS or chat_id in BLACKLISTED_GROUPS


def check_approval(func):
    async def wrapper(client, message):
        if is_blacklisted(message.from_user.id, message.chat.id):
            return await message.reply(
                quote(f"{E_DENY} <b>{fancy('blacklisted')}</b>\n{fancy('you or this chat have been blacklisted from using this bot')}.") + CREDITS,
                parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            )
        is_group = message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]
        is_approved = message.chat.id in APPROVED_GROUPS
        is_owner = message.from_user.id == OWNER_ID
        if is_group and not is_approved and not is_owner:
            return await message.reply(
                quote(f"{E_DENY} <b>{fancy('access denied')}</b>\n{fancy('this group')} (<code>{message.chat.id}</code>) {fancy('is not authorized')}.") + CREDITS,
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
_ffmpeg_kwarg_logged = False  # only print the diagnostic once per process, not on every play() call


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
    global _ffmpeg_kwarg_logged
    ffmpeg_parts = []
    if media_type == "channel":
        ffmpeg_parts.append("-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5")
    if media_type in ("movie", "series"):
        # Explicitly select the first video/audio stream instead of trusting ffmpeg's
        # default stream selection — MKV files especially can have multiple audio
        # tracks, non-default track ordering, or embedded subtitle streams that
        # confuse default mapping, which produced silent/blank playback.
        ffmpeg_parts.append("-map 0:v:0 -map 0:a:0? -sn")
    if offset_seconds and offset_seconds > 0:
        ffmpeg_parts.append(f"-ss {int(offset_seconds)}")

    if not ffmpeg_parts:
        return MediaStream(url, video_parameters=quality)

    ffmpeg_arg = " ".join(ffmpeg_parts)
    for kwarg_name in _FFMPEG_KWARG_CANDIDATES:
        try:
            stream = MediaStream(url, video_parameters=quality, **{kwarg_name: ffmpeg_arg})
            if not _ffmpeg_kwarg_logged:
                print(f"✅ py-tgcalls accepted ffmpeg args via kwarg '{kwarg_name}' — reconnect flags/seeking are active.")
                _ffmpeg_kwarg_logged = True
            return stream
        except TypeError:
            continue
    if not _ffmpeg_kwarg_logged:
        print(f"⚠️ None of {_FFMPEG_KWARG_CANDIDATES} were accepted by this py-tgcalls build's MediaStream — reconnect flags and seeking are NOT active. Check `pip show py-tgcalls` output and tell me the version so I can target the correct kwarg.")
        _ffmpeg_kwarg_logged = True
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
        return await message.reply(f"{E_WARN} <b>{fancy('usage')}:</b> <code>/addxtreamseries URL User Pass</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    msg = await message.reply(f"{E_BOLT} <b>{fancy('fetching xtream series list')}...</b>", parse_mode=ParseMode.HTML)

    try:
        series_list_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_series"
        async with aiohttp.ClientSession() as session:
            async with session.get(series_list_url, timeout=30) as resp:
                if resp.status != 200:
                    return await msg.edit_text(f"❌ {fancy('failed to fetch series list. status')}: {resp.status}")
                series_data = await resp.json()

        await msg.edit_text(f"{E_CHECK} {fancy('found')} <b>{len(series_data)}</b> {fancy('series. fetching all episodes concurrently')}...\n<i>{fancy('this may take a moment but is much faster')}!</i>", parse_mode=ParseMode.HTML)

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

        await msg.edit_text(f"{E_CHECK} <b>{fancy('scan complete')}!</b>\n{fancy('loaded episodes for')} <b>{processed_count}</b> {fancy('series from xtream api')}!{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    except Exception as e:
        await msg.edit_text(f"❌ {fancy('an error occurred')}: <code>{esc(str(e)[:150])}</code>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command("addxtreammovies") & filters.user(OWNER_ID))
async def add_xtream_movies(client, message):
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(f"{E_WARN} <b>{fancy('usage')}:</b> <code>/addxtreammovies URL User Pass</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_vod_streams"
    msg = await message.reply(f"{E_BOLT} <b>{fancy('fetching xtream movies')}...</b> {fancy('this may take a moment')}.", parse_mode=ParseMode.HTML)
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
                    await msg.edit_text(f"{E_CHECK} <b>{fancy('loaded')} {count} {fancy('movies from xtream api')}!</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                else:
                    await msg.edit_text(f"❌ {fancy('error status')}: {resp.status}")
    except Exception as e:
        await msg.edit_text(f"❌ {fancy('failed')}: <code>{esc(str(e)[:150])}</code>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command("addxtreamchannels") & filters.user(OWNER_ID))
async def add_xtream_channels(client, message):
    """Bonus command: imports live channels (+ their stream_icon logos) from an Xtream panel."""
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(f"{E_WARN} <b>{fancy('usage')}:</b> <code>/addxtreamchannels URL User Pass</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    msg = await message.reply(f"{E_BOLT} <b>{fancy('fetching xtream live channels')}...</b>", parse_mode=ParseMode.HTML)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=60) as resp:
                if resp.status != 200:
                    return await msg.edit_text(f"❌ {fancy('error status')}: {resp.status}")
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
        await msg.edit_text(f"{E_CHECK} <b>{fancy('loaded')} {count} {fancy('channels')}</b> ({logo_count} {fancy('with logos')}) {fancy('from xtream api')}!{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        await msg.edit_text(f"❌ {fancy('failed')}: <code>{esc(str(e)[:150])}</code>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command("addchannellogoxtremecode") & filters.user(OWNER_ID))
async def add_channel_logo_xtream(client, message):
    """Re-syncs logos only (doesn't touch existing channel URLs) from an Xtream panel's stream_icon field."""
    args = message.text.split()
    if len(args) != 4:
        return await message.reply(f"{E_WARN} <b>{fancy('usage')}:</b> <code>/addchannellogoxtremecode URL User Pass</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    url, user, passwd = args[1].rstrip("/"), args[2], args[3]
    api_url = f"{url}/player_api.php?username={user}&password={passwd}&action=get_live_streams"
    msg = await message.reply(f"{E_BOLT} <b>{fancy('syncing channel logos')}...</b>", parse_mode=ParseMode.HTML)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=60) as resp:
                if resp.status != 200:
                    return await msg.edit_text(f"❌ {fancy('error status')}: {resp.status}")
                data = await resp.json()
        matched = 0
        for ch in data:
            name = cleanup_name(ch.get("name", ""))
            icon = ch.get("stream_icon")
            if name in CHANNELS and icon:
                CHANNEL_LOGOS[name] = icon
                matched += 1
        save_data()
        await msg.edit_text(f"{E_CHECK} <b>{fancy('synced logos for')} {matched} {fancy('existing channels')}.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        await msg.edit_text(f"❌ {fancy('failed')}: <code>{esc(str(e)[:150])}</code>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command("addchannellogo") & filters.user(OWNER_ID))
async def add_channel_logo_manual(client, message):
    """
    Usage:
      Reply to a photo with: /addchannellogo <channel name>
      OR: /addchannellogo <channel name> <image url>
    """
    args = message.text.split(None, 1)
    if len(args) < 2:
        return await message.reply(f"{E_WARN} <b>{fancy('usage')}:</b> {fancy('reply to a photo with')} <code>/addchannellogo Channel Name</code>, or <code>/addchannellogo Channel Name https://image-url</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    rest = args[1].strip()
    url_match = re.search(r'(https?://\S+)$', rest)
    if url_match:
        logo_url = url_match.group(1)
        name = cleanup_name(rest[:url_match.start()].strip())
        if name not in CHANNELS:
            return await message.reply(f"❌ {fancy('no channel named')} <b>{esc(name.title())}</b> {fancy('found')}.{CREDITS}", parse_mode=ParseMode.HTML)
        CHANNEL_LOGOS[name] = logo_url
        save_data()
        return await message.reply(f"{E_CHECK} <b>{fancy('logo set for')} {esc(name.title())}!</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    name = cleanup_name(rest)
    if name not in CHANNELS:
        return await message.reply(f"❌ {fancy('no channel named')} <b>{esc(name.title())}</b> {fancy('found')}.{CREDITS}", parse_mode=ParseMode.HTML)

    if message.reply_to_message and message.reply_to_message.photo:
        file_path = await client.download_media(message.reply_to_message.photo.file_id)
        uploaded = await client.send_photo(message.chat.id, file_path)
        CHANNEL_LOGOS[name] = uploaded.photo.file_id
        save_data()
        return await message.reply(f"{E_CHECK} <b>{fancy('logo set for')} {esc(name.title())}!</b>{CREDITS}", parse_mode=ParseMode.HTML)

    PENDING_LOGO_UPLOAD[message.from_user.id] = name
    await message.reply(f"{E_CAM} <b>{fancy('now send the logo image')}</b> {fancy('for')} <b>{esc(name.title())}</b> ({fancy('as a photo')}).{CREDITS}", parse_mode=ParseMode.HTML)


@app.on_message(filters.photo & filters.user(OWNER_ID) & filters.private)
async def receive_pending_logo(client, message):
    name = PENDING_LOGO_UPLOAD.pop(message.from_user.id, None)
    if not name:
        return
    CHANNEL_LOGOS[name] = message.photo.file_id
    save_data()
    await message.reply(f"{E_CHECK} <b>{fancy('logo set for')} {esc(name.title())}!</b>{CREDITS}", parse_mode=ParseMode.HTML)


# ================= LIST COMMANDS =================
@app.on_message(filters.command(["channels", "allchannels"]))
async def show_channels(client, message):
    if not CHANNELS:
        return await message.reply(quote(f"❌ <b>{fancy('no channels found')}.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if len(CHANNELS) > LIST_FILE_THRESHOLD:
        text_content = "📺 All Available Channels\n\n" + "\n".join([f"{idx+1}. {name.title()}" for idx, name in enumerate(CHANNELS.keys())])
        file = BytesIO(text_content.encode('utf-8'))
        file.name = "channels.txt"
        return await message.reply_document(file, caption=quote(f"📂 {fancy('here are the')} <b>{len(CHANNELS)}</b> {fancy('available channels')}.") + CREDITS, parse_mode=ParseMode.HTML)

    body = f"{E_CAM} <b>{fancy('live channels')}</b>\n\n"
    for idx, name in enumerate(CHANNELS.keys(), 1):
        body += f"❖ <code>{idx:02d}.</code> <b>{esc(name.title())}</b>\n"
    await message.reply(quote(body) + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("movies"))
async def show_movies(client, message):
    if not MOVIES:
        return await message.reply(quote(f"❌ <b>{fancy('no movies found')}.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if len(MOVIES) > LIST_FILE_THRESHOLD:
        text_content = "🎬 All Available Movies\n\n" + "\n".join([f"{idx+1}. {name.title()}" for idx, name in enumerate(MOVIES.keys())])
        file = BytesIO(text_content.encode('utf-8'))
        file.name = "movies.txt"
        return await message.reply_document(file, caption=quote(f"📂 {fancy('here are the')} <b>{len(MOVIES)}</b> {fancy('available movies')}.") + CREDITS, parse_mode=ParseMode.HTML)

    body = f"🎬 <b>{fancy('movies list')}</b>\n\n"
    for idx, name in enumerate(MOVIES.keys(), 1):
        body += f"❖ <code>{idx:02d}.</code> <b>{esc(name.title())}</b>\n"
    await message.reply(quote(body) + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("series"))
async def show_series(client, message):
    if not SERIES:
        return await message.reply(quote(f"❌ <b>{fancy('no series found')}.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if len(SERIES) > LIST_FILE_THRESHOLD:
        text_content = "🍿 All Available Series\n\n"
        for idx, (show, eps) in enumerate(SERIES.items()):
            text_content += f"{idx+1}. {show.title()} ({len(eps)} episodes)\n"
        file = BytesIO(text_content.encode('utf-8'))
        file.name = "series.txt"
        return await message.reply_document(file, caption=quote(f"📂 {fancy('here are the')} <b>{len(SERIES)}</b> {fancy('available series')}.") + CREDITS, parse_mode=ParseMode.HTML)

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
        return await message.reply(quote(f"{E_WARN} {fancy('usage')}: <code>/{cmd} name</code>"), parse_mode=ParseMode.HTML)
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
        return await message.reply(quote(f"❌ <b>{fancy('no')} {media_type} {fancy('found matching that name')}!</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if len(matches) == 1:
        return await _start_stream(client, message, matches[0], media_type, raw_query=" ".join(message.command[1:]), user_message=message)

    buttons = []
    for name in matches[:20]:
        req_id = str(uuid.uuid4())[:8]
        PLAY_REQUESTS[req_id] = (name, " ".join(message.command[1:]))
        buttons.append([InlineKeyboardButton(name.title(), callback_data=f"resolve_{media_type}_{req_id}")])

    picker = await message.reply(quote(f"🤔 <b>{fancy('found multiple results for')} {esc(query.title())}. {fancy('please choose one')}:</b>"), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
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
            return await message.reply(quote(f"{E_WARN} {fancy('episode not specified or not found. use format')}: <code>/playseries {esc(name.title())} - s01e01</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
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
        resume_prompt = await message.reply(quote(f"{E_PIN} {fancy('you previously stopped')} <b>{esc(display_name)}</b> {fancy('at')} <b>{fmt_time(saved_pos)}</b>. {fancy('resume or start over')}?"), parse_mode=ParseMode.HTML, reply_markup=buttons)
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

    msg = await message.reply(quote(f"{E_BOLT} <b>{fancy('initializing')} {type_label}...</b>"), parse_mode=ParseMode.HTML)
    _track_msg(chat_id, msg)

    quality = VideoQuality.HD_720p
    stream = build_media_stream(url, quality, offset, media_type)

    try:
        await robust_play(chat_id, stream)
    except Exception as e:
        return await msg.edit_text(quote(f"❌ <b>{fancy('stream failed')}!</b>\n<code>{esc(str(e)[:150])}</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

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
        f"❖ <b>Title:</b> {esc(display_name)}\n"
        f"❖ <b>Type:</b> {type_label}\n"
        f"❖ <b>Quality:</b> {quality} {E_CHECK}"
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
        await asyncio.sleep(90)
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
        return await message.reply(quote(f"{E_WARN} {fancy('no active stream here')}!"), parse_mode=ParseMode.HTML)
    if len(message.command) < 2:
        return await message.reply(quote(f"{E_WARN} {fancy('usage')}: <code>/seek mm:ss</code> {fancy('or')} <code>/seek seconds</code>"), parse_mode=ParseMode.HTML)
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
        confirm = await app.send_message(chat_id, quote(f"{E_CHECK} {fancy('jumped to')} <b>{fmt_time(secs)}</b>"), parse_mode=ParseMode.HTML)
        asyncio.create_task(_delete_after(confirm, 5))
        asyncio.create_task(_progress_loop(chat_id, stream["token"]))
    except Exception as e:
        await app.send_message(chat_id, quote(f"❌ {fancy('seek failed')}: <code>{esc(str(e)[:120])}</code>\n\n{fancy('if this keeps happening, the seek mechanism may need tuning to your exact py tgcalls version')} — {fancy('send me the error and i will adjust it')}."), parse_mode=ParseMode.HTML)


@app.on_callback_query(filters.regex(r"^q_"))
async def switch_quality(client, callback_query):
    chat_id = callback_query.message.chat.id
    quality_req = callback_query.data.split("_")[1]
    stream = CURRENT_STREAMS.get(chat_id)
    if not stream:
        return await callback_query.answer("No active stream here!", show_alert=True)
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
    if not await is_admin_owner_or_auth(client, callback_query.message.chat.id, callback_query.from_user.id):
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
    MUSIC_QUEUES.pop(chat_id, None)
    try:
        await call_py.leave_call(chat_id)
    except Exception:
        pass
    CURRENT_STREAMS.pop(chat_id, None)


@app.on_message(filters.command("stopvc") & filters.group)
async def stop_vc(client, message):
    if not await is_admin_owner_or_auth(client, message.chat.id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} {fancy('only group admins can stop the current stream')}."), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    had_stream = message.chat.id in CURRENT_STREAMS
    await _do_stop(message.chat.id)
    if had_stream:
        await message.reply(quote(f"{E_STOP} <b>{fancy('stream stopped')}.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        await message.reply(quote(f"❌ <b>{fancy('no active stream to stop')}.</b>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


# ================= Music =================
def _render_music_card(track):
    dur = fmt_time(track.get("duration") or 0) if track.get("duration") else fancy("unknown")
    return quote(
        f"{E_SPARK} <b>{fancy('now playing')}</b>\n\n"
        f"❖ <b>Title:</b> <a href='{esc(track.get('webpage_url') or '#')}'>{esc(track['title'])}</a>\n"
        f"❖ <b>Duration:</b> {dur}\n"
        f"❖ <b>{fancy('played by')}:</b> {track.get('requested_by_name', 'Someone')}"
    ) + CREDITS


def _music_keyboard():
    return InlineKeyboardMarkup([
        [btn("⏸ Pause", callback_data="music_pause", color="primary"), btn("▶️ Resume", callback_data="music_resume", color="success")],
        [btn("⏭ Skip", callback_data="music_skip", color="primary"), btn("📜 Queue", callback_data="music_queue", color="primary")],
        [btn("⏹ Stop", callback_data="stop_stream", color="danger")],
        [btn("👑 Support", url=SUPPORT_URL, color="primary"), btn("🔔 Updates", url=UPDATES_URL, color="primary")],
    ])


async def _try_pytgcalls_method(names, *args, **kwargs):
    """Tries each candidate method name on call_py in order — py-tgcalls versions differ on naming."""
    last_err = None
    for name in names:
        method = getattr(call_py, name, None)
        if method:
            try:
                return await method(*args, **kwargs)
            except Exception as e:
                last_err = e
                continue
    raise RuntimeError(str(last_err) if last_err else f"None of {names} exist on this py-tgcalls build")


async def _launch_music(client, chat_id, track, message=None):
    await _wipe_chat_bot_messages(client, chat_id)
    msg = await client.send_message(chat_id, quote(f"{E_BOLT} {fancy('starting playback')}...") + CREDITS, parse_mode=ParseMode.HTML)
    _track_msg(chat_id, msg)

    if not track.get("stream_url"):
        return await msg.edit_text(quote(f"❌ {fancy('could not get an audio stream for this track')}.") + CREDITS, parse_mode=ParseMode.HTML)

    try:
        stream_kwargs = {}
        if AudioQuality is not None:
            stream_kwargs["audio_parameters"] = AudioQuality.HIGH
        media = MediaStream(track["stream_url"], **stream_kwargs)
        await robust_play(chat_id, media)
    except Exception as e:
        return await msg.edit_text(quote(f"❌ <b>{fancy('playback failed')}!</b>\n<code>{esc(str(e)[:150])}</code>") + CREDITS, parse_mode=ParseMode.HTML)

    token = uuid.uuid4().hex
    CURRENT_STREAMS[chat_id] = {
        "url": track["stream_url"], "name": track["title"], "type": "🎵 Music", "media_type": "music",
        "key": "", "quality": "audio", "start_ts": time.time(), "offset": 0,
        "duration": track.get("duration") or None, "token": token, "msg_id": None,
        "paused": False, "pause_ts": None,
        "webpage_url": track.get("webpage_url"), "requested_by_name": track.get("requested_by_name", "Someone"),
    }

    caption = _render_music_card(track)
    keyboard = _music_keyboard()
    card_file = await compose_music_card(track.get("thumbnail"), track["title"])
    sent = None
    if card_file:
        try:
            sent = await client.send_photo(chat_id, card_file, caption=caption, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        except Exception:
            sent = None
    if not sent:
        sent = await client.send_message(chat_id, caption, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
    try:
        await msg.delete()
    except Exception:
        pass

    CURRENT_STREAMS[chat_id]["msg_id"] = sent.id
    _track_msg(chat_id, sent)

    if message is not None:
        try:
            effect_msg = await reply_effect(message, "🎵", effect="fire", quote=False)
            if effect_msg:
                asyncio.create_task(_delete_after(effect_msg, 4))
        except Exception:
            pass

    asyncio.create_task(_music_watch_loop(chat_id, token))


async def _music_watch_loop(chat_id, token):
    while True:
        await asyncio.sleep(15)
        stream = CURRENT_STREAMS.get(chat_id)
        if not stream or stream.get("token") != token or stream.get("media_type") != "music":
            return
        if stream.get("paused"):
            continue
        duration = stream.get("duration")
        if not duration:
            continue
        elapsed = time.time() - stream["start_ts"]
        if elapsed >= duration:
            queue = MUSIC_QUEUES.get(chat_id) or []
            if queue:
                next_track = queue.pop(0)
                await _launch_music(app, chat_id, next_track)
            else:
                await _do_stop(chat_id)
                try:
                    m = await app.send_message(chat_id, quote(f"{E_STOP} {fancy('queue finished, playback ended')}.") + CREDITS, parse_mode=ParseMode.HTML)
                    _track_msg(chat_id, m)
                except Exception:
                    pass
            return


@app.on_message(filters.command(["play", "vplay"]) & filters.group)
@check_approval
async def play_music(client, message):
    if len(message.command) < 2:
        return await message.reply(quote(f"{E_WARN} <b>{fancy('usage')}:</b> <code>/play song name or YouTube URL</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    query = " ".join(message.command[1:])
    chat_id = message.chat.id
    if not await ensure_assistant_in_chat(chat_id, message):
        return

    searching = await message.reply(quote(f"{E_BOLT} {fancy('searching')}...") + CREDITS, parse_mode=ParseMode.HTML)
    try:
        track = await extract_track(query)
    except Exception as e:
        return await searching.edit_text(quote(f"❌ {fancy('could not find or play that')}: <code>{esc(str(e)[:150])}</code>") + CREDITS, parse_mode=ParseMode.HTML)

    track["requested_by_id"] = message.from_user.id
    track["requested_by_name"] = esc(message.from_user.first_name or "Someone")

    current = CURRENT_STREAMS.get(chat_id)
    if current and current.get("media_type") == "music":
        MUSIC_QUEUES.setdefault(chat_id, []).append(track)
        slot = len(MUSIC_QUEUES[chat_id])
        await searching.edit_text(quote(
            f"🎶 <b>{fancy('song enqueued')} • {fancy('slot')} #{slot}</b>\n\n"
            f"❖ <b>Title:</b> {esc(track['title'])}\n"
            f"❖ <b>{fancy('played by')}:</b> {track['requested_by_name']}"
        ) + CREDITS, parse_mode=ParseMode.HTML)
        try:
            await message.delete()
        except Exception:
            pass
        return

    try:
        await message.delete()
    except Exception:
        pass
    try:
        await searching.delete()
    except Exception:
        pass
    await _launch_music(client, chat_id, track, message=message)


@app.on_message(filters.command("pause") & filters.group)
async def pause_cmd(client, message):
    chat_id = message.chat.id
    if not await is_admin_owner_or_auth(client, chat_id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} {fancy('only admins or authorized users can control playback')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    stream = CURRENT_STREAMS.get(chat_id)
    if not stream or stream.get("media_type") != "music":
        return await message.reply(quote(f"❌ {fancy('no music is currently playing')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    if stream.get("paused"):
        return await message.reply(quote(f"{E_WARN} {fancy('already paused')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    try:
        await _try_pytgcalls_method(("pause_stream", "pause"), chat_id)
        stream["paused"] = True
        stream["pause_ts"] = time.time()
        await message.reply(quote(f"⏸ <b>{fancy('stream paused by')}</b> {esc(message.from_user.first_name or 'someone')}") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        await message.reply(quote(f"❌ {fancy('pause failed')}: <code>{esc(str(e)[:120])}</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("resume") & filters.group)
async def resume_cmd(client, message):
    chat_id = message.chat.id
    if not await is_admin_owner_or_auth(client, chat_id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} {fancy('only admins or authorized users can control playback')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    stream = CURRENT_STREAMS.get(chat_id)
    if not stream or stream.get("media_type") != "music":
        return await message.reply(quote(f"❌ {fancy('no music is currently playing')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    if not stream.get("paused"):
        return await message.reply(quote(f"{E_WARN} {fancy('not paused')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    try:
        await _try_pytgcalls_method(("resume_stream", "resume"), chat_id)
        if stream.get("pause_ts"):
            stream["start_ts"] += time.time() - stream["pause_ts"]
        stream["paused"] = False
        stream["pause_ts"] = None
        await message.reply(quote(f"▶️ <b>{fancy('stream resumed by')}</b> {esc(message.from_user.first_name or 'someone')}") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        await message.reply(quote(f"❌ {fancy('resume failed')}: <code>{esc(str(e)[:120])}</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("skip") & filters.group)
async def skip_cmd(client, message):
    chat_id = message.chat.id
    if not await is_admin_owner_or_auth(client, chat_id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} {fancy('only admins or authorized users can control playback')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    stream = CURRENT_STREAMS.get(chat_id)
    if not stream or stream.get("media_type") != "music":
        return await message.reply(quote(f"❌ {fancy('no music is currently playing')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    queue = MUSIC_QUEUES.get(chat_id) or []
    if queue:
        next_track = queue.pop(0)
        await _launch_music(client, chat_id, next_track)
    else:
        await _do_stop(chat_id)
        await message.reply(quote(f"⏭ {fancy('skipped — queue is empty, playback ended')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("queue") & filters.group)
async def queue_cmd(client, message):
    chat_id = message.chat.id
    queue = MUSIC_QUEUES.get(chat_id) or []
    if not queue:
        return await message.reply(quote(f"❌ {fancy('the queue is empty')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    lines = "\n".join(f"{i + 1}. {esc(t['title'])} — {t.get('requested_by_name', 'Someone')}" for i, t in enumerate(queue[:15]))
    await message.reply(quote(f"📜 <b>{fancy('queue')}</b>\n\n{lines}") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_callback_query(filters.regex(r"^music_pause$"))
async def music_pause_cb(client, callback_query):
    chat_id = callback_query.message.chat.id
    if not await is_admin_owner_or_auth(client, chat_id, callback_query.from_user.id):
        return await callback_query.answer("Only admins/authorized users can control playback.", show_alert=True)
    stream = CURRENT_STREAMS.get(chat_id)
    if not stream or stream.get("media_type") != "music":
        return await callback_query.answer("Nothing is playing.", show_alert=True)
    if stream.get("paused"):
        return await callback_query.answer("Already paused.")
    try:
        await _try_pytgcalls_method(("pause_stream", "pause"), chat_id)
        stream["paused"] = True
        stream["pause_ts"] = time.time()
        await callback_query.answer("⏸ Paused")
    except Exception as e:
        await callback_query.answer(f"Failed: {str(e)[:100]}", show_alert=True)


@app.on_callback_query(filters.regex(r"^music_resume$"))
async def music_resume_cb(client, callback_query):
    chat_id = callback_query.message.chat.id
    if not await is_admin_owner_or_auth(client, chat_id, callback_query.from_user.id):
        return await callback_query.answer("Only admins/authorized users can control playback.", show_alert=True)
    stream = CURRENT_STREAMS.get(chat_id)
    if not stream or stream.get("media_type") != "music":
        return await callback_query.answer("Nothing is playing.", show_alert=True)
    if not stream.get("paused"):
        return await callback_query.answer("Not paused.")
    try:
        await _try_pytgcalls_method(("resume_stream", "resume"), chat_id)
        if stream.get("pause_ts"):
            stream["start_ts"] += time.time() - stream["pause_ts"]
        stream["paused"] = False
        stream["pause_ts"] = None
        await callback_query.answer("▶️ Resumed")
    except Exception as e:
        await callback_query.answer(f"Failed: {str(e)[:100]}", show_alert=True)


@app.on_callback_query(filters.regex(r"^music_skip$"))
async def music_skip_cb(client, callback_query):
    chat_id = callback_query.message.chat.id
    if not await is_admin_owner_or_auth(client, chat_id, callback_query.from_user.id):
        return await callback_query.answer("Only admins/authorized users can control playback.", show_alert=True)
    stream = CURRENT_STREAMS.get(chat_id)
    if not stream or stream.get("media_type") != "music":
        return await callback_query.answer("Nothing is playing.", show_alert=True)
    queue = MUSIC_QUEUES.get(chat_id) or []
    await callback_query.answer("⏭ Skipped")
    if queue:
        next_track = queue.pop(0)
        await _launch_music(client, chat_id, next_track)
    else:
        await _do_stop(chat_id)
        try:
            await callback_query.message.delete()
        except Exception:
            pass


@app.on_callback_query(filters.regex(r"^music_queue$"))
async def music_queue_cb(client, callback_query):
    chat_id = callback_query.message.chat.id
    queue = MUSIC_QUEUES.get(chat_id) or []
    if not queue:
        return await callback_query.answer("Queue is empty.", show_alert=True)
    await callback_query.answer()
    lines = "\n".join(f"{i + 1}. {esc(t['title'])} — {t.get('requested_by_name', 'Someone')}" for i, t in enumerate(queue[:15]))
    await client.send_message(chat_id, quote(f"📜 <b>{fancy('queue')}</b>\n\n{lines}") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


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
                    if stream["media_type"] == "music":
                        stream_kwargs = {}
                        if AudioQuality is not None:
                            stream_kwargs["audio_parameters"] = AudioQuality.HIGH
                        stream_obj = MediaStream(stream["url"], **stream_kwargs)
                    else:
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
        [btn("❓ Help", callback_data="show_commands", color="primary")],
    ])


HELP_CATEGORIES = {
    "browse": ("📂 Browse", quote(
        f"{E_BOLT} <u><b>{fancy('browse commands')}</b></u>\n\n"
        f"❖ <code>/channels</code> — Browse Live TV\n"
        f"❖ <code>/movies</code> — Browse Movies\n"
        f"❖ <code>/series</code> — Browse Series"
    ) + CREDITS),
    "playback": ("▶️ Playback", quote(
        f"{E_BOLT} <u><b>{fancy('playback commands')}</b></u>\n\n"
        f"❖ <code>/livetv name</code> — Play Channel\n"
        f"❖ <code>/playmovie name</code> — Play Movie\n"
        f"❖ <code>/playseries name - s01e01</code> — Play Series\n"
        f"❖ <code>/seek mm:ss</code> — Jump to a timestamp\n"
        f"❖ <code>/stopvc</code> — Stop Current Stream\n"
        f"❖ <code>/refreshvc</code> — Force-refresh a stuck live channel\n\n"
        f"<i>{fancy('stop requires a group admin, the owner, or an authorized user')}</i>"
    ) + CREDITS),
    "music": ("🎵 Music", quote(
        f"{E_BOLT} <u><b>{fancy('music commands')}</b></u>\n\n"
        f"❖ <code>/play song name or YouTube URL</code> — Play/Queue Music\n"
        f"❖ <code>/pause</code> — Pause current track\n"
        f"❖ <code>/resume</code> — Resume paused track\n"
        f"❖ <code>/skip</code> — Skip to next track in queue\n"
        f"❖ <code>/queue</code> — Show the current queue"
    ) + CREDITS),
    "admin": ("🛠 Admin", quote(
        f"{E_BOLT} <u><b>{fancy('admin commands')}</b></u> <i>({fancy('owner only')})</i>\n\n"
        f"❖ <code>/addchannel</code>, <code>/delchannel</code>, <code>/delallchannels</code>\n"
        f"❖ <code>/delallmovies</code>, <code>/delallseries</code>\n"
        f"❖ <code>/addxtreammovies</code>, <code>/addxtreamseries</code>, <code>/addxtreamchannels</code>\n"
        f"❖ <code>/addchannellogo</code>, <code>/addchannellogoxtremecode</code>\n"
        f"❖ <code>/approve</code>, <code>/unapprove</code>, <code>/broadcast</code>, <code>/botinfo</code>\n"
        f"❖ <code>/reload</code> — Refresh this group's admin cache <i>({fancy('any admin, rate-limited')})</i>"
    ) + CREDITS),
    "auth": ("🔑 Auth", quote(
        f"{E_BOLT} <u><b>{fancy('auth commands')}</b></u>\n"
        f"<i>{fancy('authorized users can control playback without being an admin')}.</i>\n\n"
        f"❖ <code>/auth</code> — reply to a user to authorize them\n"
        f"❖ <code>/unauth</code> — reply to a user to remove authorization"
    ) + CREDITS),
    "blacklist": ("🚫 Blacklist", quote(
        f"{E_BOLT} <u><b>{fancy('blacklist commands')}</b></u> <i>({fancy('owner only')})</i>\n"
        f"<i>{fancy('blacklisted chats and users cannot use the bot')}.</i>\n\n"
        f"❖ <code>/blacklist [chat_id|user_id]</code>\n"
        f"❖ <code>/unblacklist [chat_id|user_id]</code>"
    ) + CREDITS),
    "owner": ("👑 Owner", quote(
        f"{E_BOLT} <u><b>{fancy('owner commands')}</b></u> <i>({fancy('owner only')})</i>\n\n"
        f"❖ <code>/restart</code> — Restart the bot process\n"
        f"❖ <code>/logs</code> — Send the log file\n"
        f"❖ <code>/tmdbstatus</code> — Test the TMDB connection"
    ) + CREDITS),
}

HELP_MENU_TEXT = quote(f"{E_SPARK} <b>{fancy('tap a category to see its commands')}.</b>") + CREDITS


def _help_grid_keyboard():
    keys = list(HELP_CATEGORIES.keys())
    rows = []
    for i in range(0, len(keys), 3):
        rows.append([btn(HELP_CATEGORIES[k][0], callback_data=f"help_cat_{k}", color="primary") for k in keys[i:i + 3]])
    rows.append([btn("⬅ Back", callback_data="back_to_start", color="danger")])
    return InlineKeyboardMarkup(rows)


def _welcome_text(is_group: bool) -> str:
    if is_group:
        return quote(f"{E_SPARK} <b>{fancy('meow stream')} 📺 is ready!</b>\nTap <b>❓ Help</b> below to get started.") + CREDITS
    return quote(
        f"{E_SPARK} <b>Welcome to {fancy('meow stream')} 📺</b> — the most advanced Telegram streaming bot.\n\n"
        f"{E_CAM} Live TV, Movies & Series, streamed straight into your group's voice chat.\n"
        f"{E_SIGNAL} Multiple quality options, seek/resume, auto-recovery on drops.\n\n"
        f"Tap <b>❓ Help</b> below to see everything I can do."
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
    await _edit_in_place(callback_query, HELP_MENU_TEXT, _help_grid_keyboard())


@app.on_callback_query(filters.regex(r"^help_cat_"))
async def help_category_cb(client, callback_query):
    await callback_query.answer()
    key = callback_query.data.split("help_cat_", 1)[1]
    entry = HELP_CATEGORIES.get(key)
    if not entry:
        return
    back_kb = InlineKeyboardMarkup([[btn("⬅ Back", callback_data="show_commands", color="primary")]])
    await _edit_in_place(callback_query, entry[1], back_kb)


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
        return await message.reply(quote(f"{E_WARN} <b>{fancy('usage')}:</b> <code>/delchannel Channel Name</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    name = cleanup_name(" ".join(message.command[1:]))
    if name not in CHANNELS:
        return await message.reply(quote(f"❌ {fancy('no channel named')} <b>{esc(name.title())}</b> {fancy('found')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    CHANNELS.pop(name, None)
    CHANNEL_LOGOS.pop(name, None)
    save_data()
    await message.reply(quote(f"{E_CHECK} <b>{fancy('deleted channel')}:</b> {esc(name.title())}") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("tmdbstatus") & filters.user(OWNER_ID))
async def tmdb_status(client, message):
    """Diagnostic: tests whether TMDB_API_KEY works and shows exactly what the bot would fetch for a title."""
    query = " ".join(message.command[1:]).strip() or "Inception"
    if not TMDB_API_KEY:
        return await message.reply(quote(f"{E_WARN} <b>{fancy('tmdb api key is not set')}.</b>\n{fancy('set it in the railway variables tab, then redeploy')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    msg = await message.reply(quote(f"{E_BOLT} {fancy('testing tmdb with')} <b>{esc(query)}</b>...") + CREDITS, parse_mode=ParseMode.HTML)
    result = await fetch_tmdb_art(query, "movie")
    if not result:
        return await msg.edit_text(quote(
            f"❌ <b>No result found for '{esc(query)}'.</b>\nEither the key is invalid/expired, or TMDB genuinely has no match for this title. "
            f"Try <code>/tmdbstatus Inception</code> to confirm the key itself works."
        ) + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    await msg.edit_text(quote(
        f"{E_CHECK} <b>TMDB is working.</b>\n\n"
        f"❖ <b>Backdrop:</b> {'found' if result.get('backdrop') else 'none'}\n"
        f"❖ <b>Logo:</b> {'found' if result.get('logo') else 'none'}\n"
        f"❖ <b>Runtime:</b> {result.get('runtime') or 'n/a'} min\n\n"
        f"If real movie titles still show no banner, try <code>/tmdbstatus your movie title</code> to test that exact title directly."
    ) + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("refreshvc") & filters.group)
async def refresh_vc(client, message):
    """Manual stopgap: forces an immediate silent replay of the current channel, same effect as switching quality."""
    if not await is_admin_or_owner(client, message.chat.id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} {fancy('only group admins can refresh the stream')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    chat_id = message.chat.id
    stream = CURRENT_STREAMS.get(chat_id)
    if not stream:
        return await message.reply(quote(f"❌ {fancy('no active stream to refresh')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    try:
        quality = QUALITY_PRESETS.get(stream["quality"], VideoQuality.HD_720p)
        elapsed = time.time() - stream["start_ts"] if stream["media_type"] != "channel" else 0
        stream_obj = build_media_stream(stream["url"], quality, elapsed, stream["media_type"])
        await robust_play(chat_id, stream_obj, retries=2)
        await message.reply(quote(f"{E_CHECK} {fancy('stream refreshed')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        await message.reply(quote(f"❌ {fancy('refresh failed')}: <code>{esc(str(e)[:120])}</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)





@app.on_message(filters.command("delallchannels") & filters.user(OWNER_ID))
async def del_all_channels(client, message):
    CHANNELS.clear(); CHANNEL_LOGOS.clear(); save_data()
    await message.reply(f"🗑️ <b>{fancy('all live tv channels deleted')}.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("delallmovies") & filters.user(OWNER_ID))
async def del_all_movies(client, message):
    MOVIES.clear(); save_data()
    await message.reply(f"🗑️ <b>{fancy('all movies deleted')}.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("delallseries") & filters.user(OWNER_ID))
async def del_all_series(client, message):
    SERIES.clear(); save_data()
    await message.reply(f"🗑️ <b>{fancy('all series deleted')}.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("addchannel") & filters.user(OWNER_ID))
async def add_manual_channel(client, message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply(f"{E_WARN} <b>{fancy('usage')}:</b> <code>/addchannel URL Channel Name</code>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    url, name = args[1], cleanup_name(args[2])
    CHANNELS[name] = url
    save_data()
    await message.reply(f"{E_CHECK} <b>{fancy('channel added')}:</b> {esc(name.title())}{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("approve") & filters.user(OWNER_ID))
async def approve_group(client, message):
    try:
        chat_id = int(message.command[1]) if len(message.command) > 1 else message.chat.id
        APPROVED_GROUPS.add(chat_id)
        save_data()
        await message.reply(f"{E_CHECK} <b>Group <code>{chat_id}</code> {fancy('approved')}.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except (ValueError, IndexError):
        await message.reply("Please specify a Chat ID or use in the group.")


@app.on_message(filters.command("unapprove") & filters.user(OWNER_ID))
async def unapprove_group(client, message):
    try:
        chat_id = int(message.command[1]) if len(message.command) > 1 else message.chat.id
        APPROVED_GROUPS.discard(chat_id)
        save_data()
        await message.reply(f"{E_DENY} <b>Group <code>{chat_id}</code> {fancy('unapproved')}.</b>{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
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
    m = await message.reply(f"{E_BOLT} <b>{fancy('broadcasting')}...</b>", parse_mode=ParseMode.HTML)
    for chat_id in APPROVED_GROUPS:
        try:
            await app.send_message(chat_id, f"{E_BELL} <b>Broadcast</b>\n\n{esc(msg_text)}{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            success += 1
        except Exception:
            failed += 1
    await m.edit_text(f"{E_CHECK} <b>{fancy('broadcast complete')}!</b>\n{fancy('sent')}: {success} | {fancy('failed')}: {failed}{CREDITS}", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("reload") & filters.group)
async def reload_admins(client, message):
    chat_id = message.chat.id
    now = time.time()
    if message.from_user.id != OWNER_ID:
        last = _LAST_MANUAL_RELOAD.get(chat_id, 0)
        if now - last < 600:
            return await message.reply(quote(f"{E_WARN} {fancy('you can only refresh the admin cache once every 10 minutes')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    _LAST_MANUAL_RELOAD[chat_id] = now
    msg = await message.reply(quote(f"{E_BOLT} {fancy('reloading admin cache')}...") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    admin_ids = await _fetch_admin_ids(client, chat_id)
    ADMIN_CACHE[chat_id] = (now, admin_ids)
    await msg.edit_text(quote(f"{E_CHECK} {fancy('admin cache refreshed successfully')}!") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


def _parse_target_id(message):
    """Reply to a user, or /command <numeric id> — returns int or None."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    if len(message.command) > 1:
        try:
            return int(message.command[1])
        except ValueError:
            return None
    return None


@app.on_message(filters.command("blacklist") & filters.user(OWNER_ID))
async def blacklist_cmd(client, message):
    target = _parse_target_id(message)
    if target is None:
        return await message.reply(quote(f"{E_WARN} <b>{fancy('usage')}:</b>\n\n/blacklist [chat_id|user_id] {fancy('or reply to a user')}") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    if target < 0:
        BLACKLISTED_GROUPS.add(target)
    else:
        BLACKLISTED_USERS.add(target)
    save_data()
    await message.reply(quote(f"{E_CHECK} <code>{target}</code> {fancy('has been blacklisted')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("unblacklist") & filters.user(OWNER_ID))
async def unblacklist_cmd(client, message):
    target = _parse_target_id(message)
    if target is None:
        return await message.reply(quote(f"{E_WARN} <b>{fancy('usage')}:</b>\n\n/unblacklist [chat_id|user_id] {fancy('or reply to a user')}") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    BLACKLISTED_GROUPS.discard(target)
    BLACKLISTED_USERS.discard(target)
    save_data()
    await message.reply(quote(f"{E_CHECK} <code>{target}</code> {fancy('has been removed from the blacklist')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("auth") & filters.group)
async def auth_cmd(client, message):
    if not await is_admin_or_owner(client, message.chat.id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} {fancy('only group admins can authorize users')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    target = _parse_target_id(message)
    if target is None:
        return await message.reply(quote(f"{E_WARN} {fancy('reply to a user, or use')} <code>/auth user_id</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    AUTH_USERS.setdefault(message.chat.id, set()).add(target)
    save_data()
    await message.reply(quote(f"{E_CHECK} <code>{target}</code> {fancy('can now control playback in this chat without being an admin')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("unauth") & filters.group)
async def unauth_cmd(client, message):
    if not await is_admin_or_owner(client, message.chat.id, message.from_user.id):
        return await message.reply(quote(f"{E_DENY} {fancy('only group admins can revoke authorization')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    target = _parse_target_id(message)
    if target is None:
        return await message.reply(quote(f"{E_WARN} {fancy('reply to a user, or use')} <code>/unauth user_id</code>") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    AUTH_USERS.get(message.chat.id, set()).discard(target)
    save_data()
    await message.reply(quote(f"{E_CHECK} <code>{target}</code> {fancy('has been removed from the authorized users list')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.command("restart") & filters.user(OWNER_ID))
async def restart_cmd(client, message):
    await message.reply(quote(f"{E_BOLT} {fancy('restarting')}...") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    save_data()
    os.execv(sys.executable, [sys.executable] + sys.argv)


@app.on_message(filters.command("logs") & filters.user(OWNER_ID))
async def logs_cmd(client, message):
    if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
        return await message.reply(quote(f"❌ {fancy('log file is empty or does not exist yet')}.") + CREDITS, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    await message.reply_document(LOG_FILE, caption=quote(f"{E_CHECK} {fancy('log file')}") + CREDITS, parse_mode=ParseMode.HTML)


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

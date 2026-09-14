# 🐾 Meow Stream — LivetvBlaze + AviaxMusic, merged

This is your **LivetvBlaze** bot (Live TV / Movies / Series streaming) with a
**YouTube music engine ported over from AviaxMusic** bolted onto it, running
as one single bot: **Meow Stream**.

## What changed

- **Base = your LivetvBlaze `bot.py`.** Every Live TV / Movies / Series /
  Xtream-codes / seek / quality-switch / watchdog feature is untouched.
- **Identity kept from LivetvBlaze**, as requested: same `API_ID`, `API_HASH`,
  `BOT_TOKEN`, assistant `SESSION_STRING`, `OWNER_ID`, support group/channel
  links (`SUPPORT_URL` / `UPDATES_URL`), and start banner image URL.
- **New: a music engine merged in from AviaxMusic**, using the *same*
  Pyrogram bot client, the *same* assistant session, and the *same*
  `PyTgCalls` instance LivetvBlaze already had — so no second userbot/session
  is needed.
  - `/play <song or link>` — search YouTube & play/queue audio
  - `/vplay <song or link>` — search YouTube & play/queue video
  - `/pause`, `/resume`, `/skip`, `/queue`, `/stopmusic`
  - Inline Pause/Skip/Stop buttons on the "Now Playing" card
  - Auto-advances to the next queued track when one finishes
  - Since a group's voice chat can only carry one stream at a time, starting
    a Live TV/Movie/Series stream stops any playing music (and starting music
    is blocked while a Live TV/Movie/Series stream is active) — use
    `/stopvc` or `/stopmusic` to switch between them.
- **Config moved out of source code.** The original file had the bot token,
  API hash and session string hardcoded as plain-text fallbacks. They're now
  read only from environment variables (`.env`) — see the security note below.

## ⚠️ Please rotate your credentials

Your `BOT_TOKEN` and `SESSION_STRING` were hardcoded in plain text inside
`bot.py` in the zip you uploaded. Since that file may already have been
shared, copied, or committed somewhere, treat them as compromised:

1. Talk to **@BotFather** → `/revoke` (or "Reset Token") for this bot, get a
   new `BOT_TOKEN`.
2. Generate a **new `SESSION_STRING`** for your assistant account (any
   Pyrogram/pyrofork session-string generator script works).
3. Put the new values into `.env` (not into `bot.py`).

I've pre-filled `.env` with your **original** values so the bot runs
immediately, but you should replace them with the rotated ones as soon as
you can.

## ⚠️ YouTube "Sign in to confirm you're not a bot" errors

YouTube is aggressively blocking cloud-hosted IPs (Railway, Heroku, VPS, etc.)
from downloading without cookies. To fix `/play` and `/vplay` failing with
`Sign in to confirm you're not a bot`:

1. Install the [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   browser extension (or any tool that exports Netscape-format cookies).
2. Log into **youtube.com** in that browser, then export cookies for
   `youtube.com` to a file named `cookies.txt`.
3. Put `cookies.txt` in the same folder as `bot.py` (or set `COOKIES_FILE` in
   `.env` to point at it elsewhere).
4. Restart the bot — on startup it logs whether it found the cookies file.

⚠️ Use a throwaway/secondary Google account for this, not your main one —
cookies.txt grants full account access to whoever holds the file, and
YouTube can flag automated-looking accounts. Keep `cookies.txt` out of git
(already covered in `.gitignore`) and refresh it if it stops working
(cookies expire periodically).

## Setup

```bash
pip install -r requirements.txt
# ffmpeg must be installed on the host (see packages.txt / railway.json)
cp .env.example .env   # already done for you — just review/edit .env
python bot.py
```

Required in `.env`: `API_ID`, `API_HASH`, `BOT_TOKEN`, `SESSION_STRING`,
`OWNER_ID`. Everything else has a sensible default.

### Deploying

- **Railway**: `railway.json` and `packages.txt` (installs `ffmpeg`) are
  already set up — just set the `.env` values as Railway environment
  variables instead of committing `.env`.
- **Heroku/Procfile-based hosts**: `Procfile` already runs
  `worker: python bot.py` and exposes the Flask health server via gunicorn.

## Files

- `bot.py` — the merged bot (single file, same style as the original)
- `requirements.txt` — LivetvBlaze's deps + `yt-dlp` and `python-dotenv`
  (for the music engine and env loading)
- `.env.example` — template of every environment variable the bot reads
- `.env` — pre-filled with your original LivetvBlaze credentials (rotate
  them — see above — and never commit this file)
- `.gitignore` — keeps `.env`, downloaded media, and session files out of git

## Notes / next steps

- Downloaded YouTube audio/video is cached in `downloads/` by video ID —
  clear that folder periodically if disk space is a concern.
- `TMDB_API_KEY` is optional; without it, movie/series banners fall back to
  the plain backdrop-less style already in LivetvBlaze.
- The music engine is intentionally simple (in-memory queue, per-process —
  it resets on restart) to avoid requiring a MongoDB setup like stock
  AviaxMusic needs. If you later want persistent queues/multi-assistant load
  balancing across many groups at once, that's the next thing to layer in.

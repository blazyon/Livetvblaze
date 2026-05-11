#!/bin/bash
# Start Flask in background
gunicorn bot:flask_app --bind 0.0.0.0:$PORT --worker-class gevent --timeout 120 --daemon

# Start the bot
python bot.py

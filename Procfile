web: gunicorn bot:flask_app --bind 0.0.0.0:$PORT --worker-class gevent --timeout 120
worker: python bot.py

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if os.environ.get("FLASK_ENV", "").lower() == "production" and not os.environ.get("SECRET_KEY"):
    raise RuntimeError("Set a strong SECRET_KEY environment variable before production startup.")

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "local-development-only-change-me"
    DATABASE = os.path.join(BASE_DIR, "database", "campus.db")
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8
    TEMPLATES_AUTO_RELOAD = os.environ.get("FLASK_DEBUG", "0") == "1"

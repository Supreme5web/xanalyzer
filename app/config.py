"""
Central place for all environment variables.
Import from here instead of calling os.getenv() around the codebase.
"""
import os


def _get(name: str, required: bool = False, default: str = "") -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# --- Telegram ---
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN", required=True)

# --- AI summary provider (Google Gemini by default) ---
GEMINI_API_KEY = _get("GEMINI_API_KEY", required=True)
GEMINI_MODEL = _get("GEMINI_MODEL", default="gemini-3.5-flash-lite")

# --- X / Twitter data provider (twitterapi.io by default, swappable) ---
X_API_KEY = _get("X_API_KEY", required=True)
X_API_BASE_URL = _get("X_API_BASE_URL", default="https://api.twitterapi.io")

# --- Behaviour tuning ---
# How long a fully-built response for a contract address stays cached (seconds).
CACHE_TTL_SECONDS = int(_get("CACHE_TTL_SECONDS", default="600"))
# Minimum seconds between two requests from the same chat (basic rate limiting).
RATE_LIMIT_SECONDS = int(_get("RATE_LIMIT_SECONDS", default="5"))

# --- Webhook (Render Web Service) vs polling ---
# Render web services must bind to $PORT - Render sets this automatically.
PORT = int(_get("PORT", default="10000"))
# Set to "false" to run with polling instead (e.g. for local development).
USE_WEBHOOK = _get("USE_WEBHOOK", default="true").lower() == "true"
# Render auto-injects this for every web service - no need to set it by hand.
RENDER_EXTERNAL_URL = _get("RENDER_EXTERNAL_URL", default="")
# Optional manual override of the public base URL, for non-Render hosts.
WEBHOOK_URL = _get("WEBHOOK_URL", default="")
# Random string Telegram must echo back on the X-Telegram-Bot-Api-Secret-Token
# header on every webhook request; requests without a match are rejected.
# Required whenever USE_WEBHOOK is true.
WEBHOOK_SECRET = _get("WEBHOOK_SECRET", required=USE_WEBHOOK)

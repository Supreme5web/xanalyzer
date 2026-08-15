"""
Telegram bot wiring: detects Solana contract addresses (in groups or via
/analyze), orchestrates DexScreener -> X provider -> AI summary -> message,
and sends the result back to the chat.
"""
import asyncio
import logging
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app import ai_summary, dexscreener, formatter, x_provider
from app.cache import RateLimiter, TTLCache
from app.config import (
    CACHE_TTL_SECONDS,
    PORT,
    RATE_LIMIT_SECONDS,
    RENDER_EXTERNAL_URL,
    TELEGRAM_BOT_TOKEN,
    USE_WEBHOOK,
    WEBHOOK_SECRET,
    WEBHOOK_URL,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

# Base58 Solana address: no 0/O/I/l, length 32-44.
SOLANA_ADDRESS_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")

response_cache = TTLCache(ttl_seconds=CACHE_TTL_SECONDS)
rate_limiter = RateLimiter(cooldown_seconds=RATE_LIMIT_SECONDS)

_x_provider = x_provider.get_default_provider()


def extract_contract_address(text: str) -> str | None:
    if not text:
        return None
    match = SOLANA_ADDRESS_RE.search(text)
    return match.group(0) if match else None


async def _build_response(contract_address: str) -> dict:
    """Runs the full pipeline for one contract address and returns a plain
    dict describing what to send. Blocking HTTP calls are pushed to a
    thread so the event loop isn't blocked."""
    loop = asyncio.get_running_loop()

    try:
        token = await loop.run_in_executor(None, dexscreener.get_token_info, contract_address)
    except dexscreener.TokenNotFoundError:
        return {"kind": "error", "text": "⚠️ Couldn't find this contract address on DexScreener."}
    except dexscreener.DexScreenerError:
        return {"kind": "error", "text": "⚠️ DexScreener lookup failed right now. Please try again shortly."}

    if not token.twitter_url:
        return {
            "kind": "text",
            "text": formatter.build_no_post_message(token, "No X/Twitter account listed for this token."),
        }

    try:
        post = await loop.run_in_executor(None, _x_provider.get_latest_post, token.twitter_url)
    except x_provider.XAccountNotFoundError:
        return {
            "kind": "text",
            "text": formatter.build_no_post_message(token, "Linked X account could not be found."),
        }
    except x_provider.NoRecentPostError:
        return {
            "kind": "text",
            "text": formatter.build_no_post_message(token, "No recent relevant post found on the X account."),
        }
    except x_provider.XProviderError:
        return {
            "kind": "text",
            "text": formatter.build_no_post_message(token, "X data lookup failed right now. Please try again shortly."),
        }

    try:
        summary = await loop.run_in_executor(None, ai_summary.summarize_post, post.text)
    except ai_summary.AISummaryError:
        summary = None  # Fall back to no summary rather than failing the whole request.

    message_text = formatter.build_message(token, post, summary)

    if post.image_url:
        return {"kind": "photo", "photo_url": post.image_url, "caption": message_text}
    return {"kind": "text", "text": message_text}


async def analyze_and_reply(update: Update, contract_address: str) -> None:
    chat_id = update.effective_chat.id

    if not rate_limiter.allow(str(chat_id)):
        return  # Silently drop; avoids spamming the group when many messages arrive fast.

    cached = response_cache.get(contract_address)
    if cached is not None:
        result = cached
    else:
        try:
            result = await _build_response(contract_address)
        except Exception:
            log.exception("Unexpected error analyzing %s", contract_address)
            await update.effective_message.reply_text(
                "⚠️ Something went wrong analyzing that contract. Please try again."
            )
            return
        # Only cache clean, non-transient results so a temporary API hiccup
        # (rate limit, timeout, etc.) doesn't get stuck in the cache.
        if result["kind"] != "error":
            response_cache.set(contract_address, result)

    if result["kind"] == "photo":
        try:
            await update.effective_message.reply_photo(
                photo=result["photo_url"], caption=result["caption"], parse_mode=ParseMode.MARKDOWN
            )
            return
        except Exception:
            log.warning("Failed to send photo, falling back to text for %s", contract_address)
            await update.effective_message.reply_text(result["caption"], parse_mode=ParseMode.MARKDOWN)
            return

    await update.effective_message.reply_text(result["text"], parse_mode=ParseMode.MARKDOWN)


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("Usage: /analyze <contract_address>")
        return
    contract_address = context.args[0].strip()
    await analyze_and_reply(update, contract_address)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not message.text:
        return
    contract_address = extract_contract_address(message.text)
    if not contract_address:
        return
    await analyze_and_reply(update, contract_address)


def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app


def run() -> None:
    app = build_application()

    if not USE_WEBHOOK:
        log.info("X Analyzer bot starting (polling)...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
        return

    base_url = WEBHOOK_URL or RENDER_EXTERNAL_URL
    if not base_url:
        raise RuntimeError(
            "USE_WEBHOOK is true but no public URL is available. On Render this "
            "comes from the auto-injected RENDER_EXTERNAL_URL; elsewhere, set "
            "WEBHOOK_URL manually, or set USE_WEBHOOK=false to use polling."
        )

    # The bot token doubles as an unguessable URL path, on top of the
    # secret-token header check, so random traffic to the service can't
    # trigger update processing.
    url_path = TELEGRAM_BOT_TOKEN
    full_webhook_url = f"{base_url.rstrip('/')}/{url_path}"

    log.info("X Analyzer bot starting (webhook) on port %s -> %s", PORT, full_webhook_url)
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=url_path,
        webhook_url=full_webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
    )

"""
AI summary generation.

Takes the raw text of an X post and returns a short, factual summary.
Uses the Anthropic Messages API directly via requests (no extra SDK
dependency needed for a single call type).
"""
import logging

import requests

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

log = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = (
    "You summarize crypto/Solana project posts from X (Twitter) for a Telegram "
    "audience. Write ONE short sentence (max ~25 words), factual and neutral. "
    "Do not add hype, emojis, price predictions, or claims that aren't in the "
    "text. Do not invent details. If the post text is empty or has no real "
    "content, say so plainly."
)


class AISummaryError(Exception):
    pass


def summarize_post(post_text: str, timeout: int = 20) -> str:
    post_text = (post_text or "").strip()
    if not post_text:
        return "The post has no text content."

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 100,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": f"Summarize this X post:\n\n{post_text}"}],
    }

    try:
        resp = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        log.warning("AI summary request failed: %s", exc)
        raise AISummaryError(str(exc)) from exc

    blocks = data.get("content") or []
    text_parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    summary = "".join(text_parts).strip()

    if not summary:
        raise AISummaryError("Empty summary returned by AI API")

    return summary

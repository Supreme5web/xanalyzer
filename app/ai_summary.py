"""
AI summary generation.

Takes the raw text of an X post and returns a short, factual summary.
Uses the Gemini API directly via requests (no extra SDK dependency needed
for a single call type).
"""
import logging

import requests

from app.config import GEMINI_API_KEY, GEMINI_MODEL

log = logging.getLogger(__name__)

GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

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

    url = GEMINI_URL_TEMPLATE.format(model=GEMINI_MODEL)
    headers = {"content-type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": f"Summarize this X post:\n\n{post_text}"}]}],
        "generationConfig": {"maxOutputTokens": 100},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        log.warning("AI summary request failed: %s", exc)
        raise AISummaryError(str(exc)) from exc

    try:
        candidates = data.get("candidates") or []
        parts = candidates[0]["content"]["parts"]
        summary = "".join(p.get("text", "") for p in parts).strip()
    except (IndexError, KeyError, TypeError) as exc:
        raise AISummaryError(f"Unexpected Gemini response shape: {data}") from exc

    if not summary:
        raise AISummaryError("Empty summary returned by AI API")

    return summary

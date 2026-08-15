"""
Builds the final Telegram message text/caption from the pieces gathered
by the other modules. Never fabricates a stat: if a number is missing,
that line/segment is simply left out instead of showing a fake value.
"""
from app.dexscreener import TokenInfo
from app.x_provider import XPost


def _format_count(n: int | None) -> str | None:
    if n is None:
        return None
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def build_engagement_line(post: XPost) -> str | None:
    parts = []
    likes = _format_count(post.likes)
    comments = _format_count(post.comments)
    views = _format_count(post.views)

    if likes is not None:
        parts.append(f"❤️ {likes}")
    if comments is not None:
        parts.append(f"💬 {comments}")
    if views is not None:
        parts.append(f"👁️ {views}")

    if not parts:
        return None
    return "  ·  ".join(parts)


def build_message(token: TokenInfo, post: XPost | None, summary: str | None) -> str:
    lines = ["🧠 *X ANALYZER*", ""]

    if summary:
        lines.append(f"«{summary}»")
        lines.append("")

    if post:
        engagement_line = build_engagement_line(post)
        if engagement_line:
            lines.append(engagement_line)
            lines.append("")

    lines.append(f"${token.ticker} — {token.name}")

    return "\n".join(lines)


def build_no_post_message(token: TokenInfo, reason: str) -> str:
    """Used when we have token info but no usable X post (no account, no
    posts found, or the X provider failed) - never invent a post."""
    lines = [
        "🧠 *X ANALYZER*",
        "",
        f"${token.ticker} — {token.name}",
        "",
        f"_{reason}_",
    ]
    return "\n".join(lines)


def build_link_button(token: TokenInfo, post: XPost | None = None) -> tuple[str, str] | None:
    """Returns (label, url) for the single link button attached to a reply,
    or None if there's nothing to link to. Prefers the original X post when
    we have one; falls back to the DexScreener pair page otherwise."""
    if post and post.url:
        return "🔗 View Original Post", post.url
    if token.dexscreener_url:
        return "🔗 View on DexScreener", token.dexscreener_url
    return None
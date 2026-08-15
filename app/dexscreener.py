"""
DexScreener integration.

Only responsible for: given a Solana contract (token) address, return the
token name, ticker and whatever social links DexScreener has on file.
It does NOT know anything about X/Twitter post content - that's x_provider.py.
"""
import logging
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{address}"


@dataclass
class TokenInfo:
    address: str
    name: str
    ticker: str
    price_usd: str | None = None
    dexscreener_url: str | None = None
    twitter_url: str | None = None
    website_url: str | None = None
    telegram_url: str | None = None
    socials: dict = field(default_factory=dict)


class DexScreenerError(Exception):
    pass


class TokenNotFoundError(DexScreenerError):
    pass


def get_token_info(contract_address: str, timeout: int = 10) -> TokenInfo:
    """
    Fetch token name/ticker/socials for a Solana contract address.
    Raises TokenNotFoundError if DexScreener has no pairs for this address,
    or DexScreenerError on any other request failure.
    """
    url = DEXSCREENER_TOKEN_URL.format(address=contract_address)
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        log.warning("DexScreener request failed for %s: %s", contract_address, exc)
        raise DexScreenerError(str(exc)) from exc

    pairs = data.get("pairs") or []
    if not pairs:
        raise TokenNotFoundError(f"No DexScreener pairs found for {contract_address}")

    # Pick the pair with the highest liquidity as the "primary" one.
    def liquidity(pair: dict) -> float:
        try:
            return float(pair.get("liquidity", {}).get("usd") or 0)
        except (TypeError, ValueError):
            return 0.0

    best_pair = max(pairs, key=liquidity)
    base_token = best_pair.get("baseToken", {})

    twitter_url = None
    website_url = None
    telegram_url = None
    socials_map = {}

    # DexScreener's social entries come in one of two shapes depending on
    # endpoint/response version:
    #   {"type": "twitter", "url": "https://x.com/handle"}   (older shape)
    #   {"platform": "twitter", "handle": "handle"}          (current shape)
    # Handle both so a social link is never missed just because of naming.
    def _social_platform_and_url(social: dict) -> tuple[str, str | None]:
        platform = (social.get("type") or social.get("platform") or "").lower()
        url = social.get("url")
        if not url:
            handle = social.get("handle")
            if handle:
                handle = handle.lstrip("@")
                if platform in ("twitter", "x"):
                    url = f"https://x.com/{handle}"
                elif platform == "telegram":
                    url = f"https://t.me/{handle}"
                elif handle.startswith("http"):
                    url = handle
        return platform, url

    info = best_pair.get("info") or {}
    for social in info.get("socials", []) or []:
        s_type, s_url = _social_platform_and_url(social)
        if not s_url:
            continue
        socials_map[s_type] = s_url
        if s_type in ("twitter", "x"):
            twitter_url = s_url
        elif s_type == "telegram":
            telegram_url = s_url

    for site in info.get("websites", []) or []:
        if site.get("url"):
            website_url = site["url"]
            break

    return TokenInfo(
        address=contract_address,
        name=base_token.get("name") or "Unknown",
        ticker=base_token.get("symbol") or "?",
        price_usd=best_pair.get("priceUsd"),
        dexscreener_url=best_pair.get("url"),
        twitter_url=twitter_url,
        website_url=website_url,
        telegram_url=telegram_url,
        socials=socials_map,
    )

"""
X (Twitter) data provider.

DexScreener only gives us a profile URL like https://x.com/someproject -
it never gives us the actual post content, media or engagement numbers.
This module is the ONLY place that talks to an external X data API, so
swapping providers later (RapidAPI, apidance, official X API, etc.) means
editing this file only - nothing else in the bot needs to change.

Concrete implementation here uses twitterapi.io (https://twitterapi.io),
a third-party read-only X data API that doesn't require OAuth. If you use
a different provider, just rewrite TwitterAPIIOProvider.get_latest_post()
to return an XPost with the same fields.

IMPORTANT: this module never invents data. If a field isn't returned by
the provider, it stays None and the formatter must skip it rather than
fake a number.
"""
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

from app.config import X_API_BASE_URL, X_API_KEY

log = logging.getLogger(__name__)

# Matches x.com/twitter.com profile or status URLs and captures the handle
# and (optionally) a tweet id.
_HANDLE_RE = re.compile(
    r"(?:x\.com|twitter\.com)/(?!home|search|i/)([A-Za-z0-9_]{1,15})(?:/status/(\d+))?",
    re.IGNORECASE,
)


@dataclass
class XPost:
    text: str
    url: str
    image_url: str | None = None
    likes: int | None = None
    comments: int | None = None
    views: int | None = None


class XProviderError(Exception):
    pass


class XAccountNotFoundError(XProviderError):
    pass


class NoRecentPostError(XProviderError):
    pass


def extract_handle_and_tweet_id(twitter_url: str) -> tuple[str | None, str | None]:
    """Pull the @handle (and tweet id, if the URL points at a specific post)
    out of a DexScreener-supplied X/Twitter URL."""
    match = _HANDLE_RE.search(twitter_url)
    if not match:
        return None, None
    return match.group(1), match.group(2)


class XProvider(ABC):
    """Swap in a different provider by implementing this interface."""

    @abstractmethod
    def get_latest_post(self, twitter_url: str) -> XPost:
        """Return the most relevant recent post for the given profile/post URL.
        Raise XAccountNotFoundError / NoRecentPostError / XProviderError as
        appropriate. Never fabricate engagement numbers."""
        raise NotImplementedError


class TwitterAPIIOProvider(XProvider):
    """Implementation backed by twitterapi.io's /twitter/user/last_tweets endpoint."""

    def __init__(self, api_key: str = X_API_KEY, base_url: str = X_API_BASE_URL, timeout: int = 10):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_latest_post(self, twitter_url: str) -> XPost:
        handle, tweet_id = extract_handle_and_tweet_id(twitter_url)
        if not handle:
            raise XAccountNotFoundError(f"Could not parse an X handle from {twitter_url}")

        # Many pump.fun/meme-coin listings link a specific status URL rather
        # than a profile page - often on some other account (a promoter's
        # tweet), not the project's own. In that case go straight for that
        # exact tweet by ID instead of relying on it showing up in the
        # linked account's "last tweets" list, which can come back empty
        # even though the specific tweet itself is fetchable (quiet account,
        # tweet has scrolled out of the recent window, etc).
        if tweet_id:
            tweet = self._fetch_tweet_by_id(tweet_id)
            if tweet:
                return self._to_xpost(tweet)

        tweets = self._fetch_last_tweets(handle)
        if not tweets:
            raise NoRecentPostError(f"No tweets found for @{handle}")

        tweet = self._pick_tweet(tweets, tweet_id)
        if not tweet:
            raise NoRecentPostError(f"No relevant tweet found for @{handle}")

        return self._to_xpost(tweet)

    def _fetch_tweet_by_id(self, tweet_id: str) -> dict | None:
        """Fetch a single tweet directly via /twitter/tweets. Returns None
        (rather than raising) on any failure so callers can fall back to
        the last-tweets flow - a miss here isn't fatal since there's a
        fallback path."""
        url = f"{self.base_url}/twitter/tweets"
        headers = {"X-API-Key": self.api_key}
        params = {"tweet_ids": tweet_id}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.warning("X API tweet-by-id request failed for %s: %s", tweet_id, exc)
            return None

        tweets = data.get("tweets") or []
        return tweets[0] if tweets else None

    def _fetch_last_tweets(self, handle: str) -> list[dict]:
        url = f"{self.base_url}/twitter/user/last_tweets"
        headers = {"X-API-Key": self.api_key}
        params = {"userName": handle}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            log.warning("X API request failed for @%s: %s", handle, exc)
            raise XProviderError(str(exc)) from exc

        if resp.status_code == 404:
            raise XAccountNotFoundError(f"X account @{handle} not found")
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise XProviderError(f"X API error {resp.status_code}: {resp.text[:200]}") from exc

        data = resp.json()
        return data.get("tweets") or []

    @staticmethod
    def _pick_tweet(tweets: list[dict], tweet_id: str | None) -> dict | None:
        # If DexScreener linked a specific post, prefer that exact tweet.
        if tweet_id:
            for t in tweets:
                if str(t.get("id")) == str(tweet_id):
                    return t
        # Otherwise, latest non-reply, non-retweet post is "the relevant post".
        for t in tweets:
            if t.get("isReply"):
                continue
            if (t.get("text") or "").startswith("RT @"):
                continue
            return t
        # Fall back to the very latest tweet if everything looked like a reply/RT.
        return tweets[0] if tweets else None

    @staticmethod
    def _to_xpost(tweet: dict) -> XPost:
        image_url = None
        media_list = (
            (tweet.get("extendedEntities") or {}).get("media")
            or (tweet.get("entities") or {}).get("media")
            or []
        )
        for media in media_list:
            if media.get("type") in (None, "photo"):
                image_url = media.get("media_url_https") or media.get("media_url") or media.get("url")
                if image_url:
                    break

        def as_int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        return XPost(
            text=tweet.get("text") or "",
            url=tweet.get("url") or (f"https://x.com/i/status/{tweet.get('id')}" if tweet.get("id") else ""),
            image_url=image_url,
            likes=as_int(tweet.get("likeCount")),
            comments=as_int(tweet.get("replyCount")),
            views=as_int(tweet.get("viewCount")),
        )


def get_default_provider() -> XProvider:
    return TwitterAPIIOProvider()
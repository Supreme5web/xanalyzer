"""
Minimal in-memory TTL cache + per-chat rate limiter.

Deliberately not a database: the bot is single-process on a single Render
instance, so a plain dict is enough to avoid duplicate DexScreener/X/AI
calls for the same contract address in a short window, and to stop a chat
from spamming the bot.
"""
import time
from threading import Lock


class TTLCache:
    def __init__(self, ttl_seconds: int):
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, object]] = {}
        self._lock = Lock()

    def get(self, key: str):
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if time.time() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: object):
        with self._lock:
            self._store[key] = (time.time() + self.ttl, value)

    def cleanup(self):
        """Optional periodic sweep to keep memory bounded."""
        now = time.time()
        with self._lock:
            expired = [k for k, (exp, _) in self._store.items() if now > exp]
            for k in expired:
                del self._store[k]


class RateLimiter:
    """Simple per-key cooldown, e.g. one request per chat every N seconds."""

    def __init__(self, cooldown_seconds: int):
        self.cooldown = cooldown_seconds
        self._last_seen: dict[str, float] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            last = self._last_seen.get(key, 0)
            if now - last < self.cooldown:
                return False
            self._last_seen[key] = now
            return True

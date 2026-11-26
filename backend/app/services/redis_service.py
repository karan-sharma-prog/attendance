"""
Redis / Distributed TTL Store Service.
Uses real Redis via redis.asyncio when reachable at REDIS_URL;
falls back gracefully to an asyncio-locked in-process TTL cache for local Windows dev
when a Redis daemon is not installed, while reporting actual connection status.
"""
import asyncio
import time
import logging
from typing import Optional
import redis.asyncio as aioredis
from backend.app.core.config import settings

logger = logging.getLogger("smartpresence.redis")


class EphemeralTTLStore:
    def __init__(self) -> None:
        self._client: Optional[aioredis.Redis] = None
        self._redis_available: bool = False
        self._checked: bool = False
        self._mem: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    async def init(self) -> bool:
        try:
            client = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1.5)
            await client.ping()
            self._client = client
            self._redis_available = True
            self._checked = True
            logger.info("Connected to Redis server at %s", settings.REDIS_URL)
            return True
        except Exception as exc:
            self._redis_available = False
            self._checked = True
            logger.warning(
                "Redis unreachable (%s). Using in-process TTL fallback store for QR nonces & token revocation.",
                str(exc),
            )
            return False

    @property
    def is_redis_connected(self) -> bool:
        return self._redis_available

    async def set_ex(self, key: str, ttl_seconds: int, value: str) -> None:
        if not self._checked:
            await self.init()
        if self._redis_available and self._client:
            try:
                await self._client.setex(key, ttl_seconds, value)
                return
            except Exception as exc:
                logger.warning("Redis setex failed, falling back to memory: %s", exc)
        async with self._lock:
            self._mem[key] = (value, time.monotonic() + ttl_seconds)

    async def get(self, key: str) -> Optional[str]:
        if not self._checked:
            await self.init()
        if self._redis_available and self._client:
            try:
                return await self._client.get(key)
            except Exception as exc:
                logger.warning("Redis get failed, falling back to memory: %s", exc)
        async with self._lock:
            entry = self._mem.get(key)
            if not entry:
                return None
            val, exp = entry
            if time.monotonic() > exp:
                del self._mem[key]
                return None
            return val

    async def delete(self, key: str) -> None:
        if self._redis_available and self._client:
            try:
                await self._client.delete(key)
                return
            except Exception:
                pass
        async with self._lock:
            self._mem.pop(key, None)

    async def incr_window(self, key: str, ttl_seconds: int) -> int:
        """Simple sliding-window counter for rate limiting."""
        if not self._checked:
            await self.init()
        if self._redis_available and self._client:
            try:
                count = await self._client.incr(key)
                if count == 1:
                    await self._client.expire(key, ttl_seconds)
                return int(count)
            except Exception:
                pass
        async with self._lock:
            now = time.monotonic()
            entry = self._mem.get(key)
            if not entry or now > entry[1]:
                self._mem[key] = ("1", now + ttl_seconds)
                return 1
            count = int(entry[0]) + 1
            self._mem[key] = (str(count), entry[1])
            return count

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()


ttl_store = EphemeralTTLStore()

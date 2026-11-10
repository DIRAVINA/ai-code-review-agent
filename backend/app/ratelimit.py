"""Fixed-window rate limiter shared by all workers through Redis.

Keeps the fleet of workers under the LLM provider's requests-per-minute quota.
"""

import asyncio
import time

from redis.asyncio import Redis


class RateLimiter:
    def __init__(self, redis: Redis | None, key: str, per_minute: int):
        self.redis = redis
        self.key = key
        self.per_minute = per_minute

    async def acquire(self) -> None:
        if self.redis is None or self.per_minute <= 0:
            return
        while True:
            window = int(time.time() // 60)
            key = f"ratelimit:{self.key}:{window}"
            count = await self.redis.incr(key)
            if count == 1:
                await self.redis.expire(key, 70)
            if count <= self.per_minute:
                return
            await asyncio.sleep(60 - time.time() % 60 + 0.1)

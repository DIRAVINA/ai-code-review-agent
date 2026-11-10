"""Redis job queue (arq). The API enqueues; app.worker consumes."""

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

from app.config import get_settings

_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def enqueue_review(review_id: int) -> None:
    pool = await get_pool()
    # A fixed job id makes enqueueing idempotent if GitHub redelivers a webhook.
    await pool.enqueue_job("review_pull_request", review_id, _job_id=f"review:{review_id}")


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None

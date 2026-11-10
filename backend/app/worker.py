"""arq worker. Run with:  arq app.worker.WorkerSettings"""

import logging

import httpx
from arq import Retry

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.github.auth import GitHubAppAuth
from app.github.client import GitHubClient, GitHubError
from app.queue import redis_settings
from app.ratelimit import RateLimiter
from app.review.llm import build_provider
from app.review.service import ReviewDeps, mark_failed, run_review

log = logging.getLogger(__name__)
MAX_TRIES = 4


def is_transient(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError | TimeoutError):
        return True
    if isinstance(exc, GitHubError):
        return exc.status >= 500 or exc.status in (403, 429)
    # LLM SDK errors (rate limits, overloads, connection drops)
    name = type(exc).__name__
    return name in {
        "RateLimitError",
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "OverloadedError",
    }


async def startup(ctx: dict) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    await init_db()
    http = httpx.AsyncClient(timeout=30)
    auth = GitHubAppAuth(settings, http)

    async def github_for(installation_id: int) -> GitHubClient:
        token = await auth.installation_token(installation_id)
        return GitHubClient(token, settings.github_api_url)

    ctx["http"] = http
    ctx["deps"] = ReviewDeps(
        settings=settings,
        session_factory=SessionLocal,
        github_for=github_for,
        token_for=auth.installation_token,
        provider=build_provider(settings),
        limiter=RateLimiter(ctx["redis"], "llm", settings.llm_requests_per_minute),
    )


async def shutdown(ctx: dict) -> None:
    await ctx["http"].aclose()


async def review_pull_request(ctx: dict, review_id: int) -> str:
    deps: ReviewDeps = ctx["deps"]
    try:
        return await run_review(review_id, deps)
    except Exception as exc:
        attempt = ctx.get("job_try", 1)
        if is_transient(exc) and attempt < MAX_TRIES:
            delay = 30 * 2 ** (attempt - 1)
            log.warning(
                "Review %s attempt %d failed (%s); retrying in %ds", review_id, attempt, exc, delay
            )
            raise Retry(defer=delay) from exc
        log.exception("Review %s failed permanently", review_id)
        await mark_failed(deps, review_id, f"{type(exc).__name__}: {exc}")
        return "failed"


class WorkerSettings:
    functions = [review_pull_request]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    max_tries = MAX_TRIES
    max_jobs = 5
    job_timeout = 900

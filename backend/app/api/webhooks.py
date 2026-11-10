import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import queue
from app.config import get_settings
from app.db import get_session
from app.github.security import verify_signature
from app.models import Review, ReviewStatus

log = logging.getLogger(__name__)
router = APIRouter()

REVIEW_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


@router.post("/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    body = await request.body()
    if not verify_signature(get_settings().github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = json.loads(body)
    if x_github_event == "ping":
        return {"ok": True, "message": "pong"}
    if x_github_event != "pull_request":
        return {"ok": True, "ignored": f"event {x_github_event}"}

    action = payload.get("action")
    pr = payload["pull_request"]
    if action not in REVIEW_ACTIONS:
        return {"ok": True, "ignored": f"action {action}"}
    if pr.get("draft"):
        return {"ok": True, "ignored": "draft pull request"}

    repo = payload["repository"]["full_name"]
    head_sha = pr["head"]["sha"]

    # GitHub may redeliver the same event: one review per (repo, PR, commit).
    existing = await session.scalar(
        select(Review).where(
            Review.repo_full_name == repo,
            Review.pr_number == pr["number"],
            Review.head_sha == head_sha,
        )
    )
    if existing:
        return {"ok": True, "review_id": existing.id, "duplicate": True}

    review = Review(
        repo_full_name=repo,
        installation_id=payload["installation"]["id"],
        pr_number=pr["number"],
        pr_title=pr.get("title", "")[:500],
        pr_author=pr.get("user", {}).get("login", ""),
        pr_url=pr.get("html_url", ""),
        head_sha=head_sha,
        status=ReviewStatus.QUEUED,
    )
    session.add(review)
    await session.commit()
    await queue.enqueue_review(review.id)
    log.info("Queued review %s for %s#%s @ %s", review.id, repo, pr["number"], head_sha[:7])
    return {"ok": True, "review_id": review.id}

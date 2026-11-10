from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import queue
from app.db import get_session
from app.models import Review, ReviewComment, ReviewStatus
from app.review.service import load_review
from app.schemas import DayCount, ReviewDetail, ReviewOut, ReviewPage, Stats

router = APIRouter(prefix="/api")


@router.get("/reviews", response_model=ReviewPage)
async def list_reviews(
    repo: str | None = None,
    status: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ReviewPage:
    filters = []
    if repo:
        filters.append(Review.repo_full_name == repo)
    if status:
        filters.append(Review.status == status)

    total = await session.scalar(select(func.count(Review.id)).where(*filters)) or 0
    counts = (
        select(ReviewComment.review_id, func.count(ReviewComment.id).label("n"))
        .group_by(ReviewComment.review_id)
        .subquery()
    )
    rows = await session.execute(
        select(Review, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.review_id == Review.id)
        .where(*filters)
        .order_by(Review.created_at.desc(), Review.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = []
    for review, n in rows.all():
        out = ReviewOut.model_validate(review)
        out.comment_count = n
        items.append(out)
    return ReviewPage(items=items, total=total)


@router.get("/reviews/{review_id}", response_model=ReviewDetail)
async def get_review(review_id: int, session: AsyncSession = Depends(get_session)) -> ReviewDetail:
    review = await load_review(session, review_id)
    if review is None:
        raise HTTPException(404, "review not found")
    detail = ReviewDetail.model_validate(review)
    detail.comment_count = len(review.comments)
    return detail


@router.post("/reviews/{review_id}/retry", status_code=202)
async def retry_review(review_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    review = await session.get(Review, review_id)
    if review is None:
        raise HTTPException(404, "review not found")
    if review.status in (ReviewStatus.QUEUED, ReviewStatus.RUNNING):
        raise HTTPException(409, "review is already in progress")
    await session.execute(delete(ReviewComment).where(ReviewComment.review_id == review_id))
    review.status = ReviewStatus.QUEUED
    review.error = None
    review.summary = None
    review.verdict = None
    review.completed_at = None
    await session.commit()
    await queue.enqueue_review(review_id, attempt=review.attempts + 1)
    return {"ok": True}


@router.get("/repos", response_model=list[str])
async def list_repos(session: AsyncSession = Depends(get_session)) -> list[str]:
    rows = await session.scalars(
        select(Review.repo_full_name).distinct().order_by(Review.repo_full_name)
    )
    return list(rows)


async def _group_count(session: AsyncSession, column, *where) -> dict[str, int]:
    rows = await session.execute(select(column, func.count()).where(*where).group_by(column))
    return {str(k): v for k, v in rows.all() if k is not None}


@router.get("/stats", response_model=Stats)
async def stats(days: int = Query(14, ge=1, le=90), session: AsyncSession = Depends(get_session)):
    total_reviews = await session.scalar(select(func.count(Review.id))) or 0
    total_issues = await session.scalar(select(func.count(ReviewComment.id))) or 0
    avg_duration = await session.scalar(
        select(func.avg(Review.duration_ms)).where(Review.duration_ms.is_not(None))
    )
    total_tokens = await session.scalar(
        select(func.coalesce(func.sum(Review.tokens_in + Review.tokens_out), 0))
    )

    since = datetime.now(UTC) - timedelta(days=days - 1)
    since = since.replace(hour=0, minute=0, second=0, microsecond=0)
    recent = await session.execute(
        select(Review.id, Review.created_at).where(Review.created_at >= since)
    )
    review_day = {rid: created.date().isoformat() for rid, created in recent.all()}
    issue_rows = await session.execute(
        select(ReviewComment.review_id, func.count())
        .where(ReviewComment.review_id.in_(review_day.keys()))
        .group_by(ReviewComment.review_id)
    )
    issues_by_review = dict(issue_rows.all())

    per_day = {}
    for i in range(days):
        day = (since + timedelta(days=i)).date().isoformat()
        per_day[day] = DayCount(day=day, reviews=0, issues=0)
    for rid, day in review_day.items():
        if day in per_day:
            per_day[day].reviews += 1
            per_day[day].issues += issues_by_review.get(rid, 0)

    top = await session.execute(
        select(Review.repo_full_name, func.count(Review.id).label("n"))
        .group_by(Review.repo_full_name)
        .order_by(func.count(Review.id).desc())
        .limit(5)
    )

    return Stats(
        total_reviews=total_reviews,
        total_issues=total_issues,
        avg_duration_ms=float(avg_duration) if avg_duration is not None else None,
        total_tokens=int(total_tokens or 0),
        by_status=await _group_count(session, Review.status),
        by_severity=await _group_count(session, ReviewComment.severity),
        by_category=await _group_count(session, ReviewComment.category),
        by_verdict=await _group_count(session, Review.verdict),
        per_day=list(per_day.values()),
        top_repos=[{"repo": r, "reviews": n} for r, n in top.all()],
    )

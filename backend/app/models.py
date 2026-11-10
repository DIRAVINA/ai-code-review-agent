from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ReviewStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("repo_full_name", "pr_number", "head_sha"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), index=True)
    installation_id: Mapped[int] = mapped_column(Integer)
    pr_number: Mapped[int] = mapped_column(Integer)
    pr_title: Mapped[str] = mapped_column(String(500), default="")
    pr_author: Mapped[str] = mapped_column(String(255), default="")
    pr_url: Mapped[str] = mapped_column(String(500), default="")
    head_sha: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default=ReviewStatus.QUEUED, index=True)
    verdict: Mapped[str | None] = mapped_column(String(30), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    files_reviewed: Mapped[int] = mapped_column(Integer, default=0)
    lint_issue_count: Mapped[int] = mapped_column(Integer, default=0)
    tests_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    comments: Mapped[list["ReviewComment"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", order_by="ReviewComment.id"
    )


class ReviewComment(Base):
    __tablename__ = "review_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(500))
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="warning")  # info|warning|error
    category: Mapped[str] = mapped_column(String(30), default="maintainability")
    source: Mapped[str] = mapped_column(String(20), default="llm")  # llm|lint
    body: Mapped[str] = mapped_column(Text)
    posted_inline: Mapped[bool] = mapped_column(default=False)

    review: Mapped[Review] = relationship(back_populates="comments")

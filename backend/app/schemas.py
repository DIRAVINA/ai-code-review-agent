from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    path: str
    line: int | None
    severity: str
    category: str
    source: str
    body: str
    posted_inline: bool


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_full_name: str
    pr_number: int
    pr_title: str
    pr_author: str
    pr_url: str
    head_sha: str
    status: str
    verdict: str | None
    model: str | None
    files_reviewed: int
    lint_issue_count: int
    tests_status: str | None
    tokens_in: int
    tokens_out: int
    attempts: int
    duration_ms: int | None
    created_at: datetime
    completed_at: datetime | None
    comment_count: int = 0


class ReviewDetail(ReviewOut):
    summary: str | None
    error: str | None
    comments: list[CommentOut]


class ReviewPage(BaseModel):
    items: list[ReviewOut]
    total: int


class DayCount(BaseModel):
    day: str
    reviews: int
    issues: int


class Stats(BaseModel):
    total_reviews: int
    total_issues: int
    avg_duration_ms: float | None
    total_tokens: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    by_category: dict[str, int]
    by_verdict: dict[str, int]
    per_day: list[DayCount]
    top_repos: list[dict]

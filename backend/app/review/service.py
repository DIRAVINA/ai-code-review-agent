"""Orchestrates one review: fetch PR -> lint/test -> agent -> post to GitHub -> persist."""

import asyncio
import fnmatch
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.github.client import GitHubClient, GitHubError
from app.models import Review, ReviewComment, ReviewStatus, utcnow
from app.ratelimit import RateLimiter
from app.review import linters, tests_runner
from app.review.agent import ReviewAgent, ReviewResult
from app.review.context import ChangedFile, Finding, ReviewContext
from app.review.llm import LLMProvider

log = logging.getLogger(__name__)

SKIP_PATTERNS = [
    "*.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "Cargo.lock",
    "*.min.js", "*.min.css", "*.map", "*.svg", "*.png", "*.jpg", "*.gif", "*.ico", "*.pdf",
    "dist/*", "build/*", "vendor/*", "node_modules/*", "*.generated.*", "*_pb2.py",
]  # fmt: skip

SEVERITY_ICON = {"error": "🔴", "warning": "🟠", "info": "🔵"}
VERDICT_LABEL = {
    "approve": "✅ Looks good",
    "comment": "💬 Comments",
    "request_changes": "⚠️ Changes suggested",
}


@dataclass
class ReviewDeps:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    github_for: Callable[[int], Awaitable[GitHubClient]]  # installation_id -> client
    provider: LLMProvider
    token_for: Callable[[int], Awaitable[str]] | None = None  # needed only for running tests
    limiter: RateLimiter | None = None


def should_skip(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(name, p) for p in SKIP_PATTERNS)


async def collect_files(
    gh: GitHubClient, repo: str, pr_number: int, head_sha: str, settings: Settings
) -> list[ChangedFile]:
    raw = await gh.list_pr_files(repo, pr_number)
    candidates = [
        f
        for f in raw
        if f.get("patch") and f["status"] != "removed" and not should_skip(f["filename"])
    ][: settings.max_files_per_review]

    sem = asyncio.Semaphore(5)

    async def load(f: dict) -> ChangedFile:
        async with sem:
            content = await gh.get_file_content(repo, f["filename"], head_sha)
        if content is not None and len(content.encode()) > settings.max_file_bytes:
            content = None
        return ChangedFile(
            path=f["filename"],
            patch=f["patch"],
            status=f["status"],
            content=content,
            additions=f.get("additions", 0),
            deletions=f.get("deletions", 0),
        )

    return list(await asyncio.gather(*(load(f) for f in candidates)))


def format_comment(c: Finding) -> str:
    rule = f"\n\n<sub>{c.source}: {c.rule}</sub>" if c.rule else ""
    return f"{SEVERITY_ICON[c.severity]} **{c.severity} · {c.category}**\n\n{c.body}{rule}"


def format_summary(
    result: ReviewResult, ctx: ReviewContext, file_notes: list[Finding], elapsed: float
) -> str:
    counts = {
        s: sum(c.severity == s for c in result.comments) for s in ("error", "warning", "info")
    }
    lines = [
        "## 🤖 AI Code Review",
        f"**Verdict:** {VERDICT_LABEL[result.verdict]}",
        "",
        result.summary or "_No summary provided._",
        "",
        f"**Findings:** {counts['error']} error · {counts['warning']} warning · "
        f"{counts['info']} info  |  **Lint:** {len(ctx.lint_findings)}  |  "
        f"**Tests:** {ctx.test_result.status}",
    ]
    if file_notes:
        lines += ["", "### Notes outside the diff"]
        lines += [f"- `{n.path}`: {SEVERITY_ICON[n.severity]} {n.body}" for n in file_notes]
    if ctx.test_result.status == "failed":
        lines += ["", "<details><summary>Test output</summary>", "", "```",
                  ctx.test_result.output[-3000:], "```", "</details>"]  # fmt: skip
    lines += [
        "",
        f"<sub>Model: {result.model} · {len(ctx.files)} file(s) · {elapsed:.1f}s · "
        "comments are suggestions, use your judgment.</sub>",
    ]
    return "\n".join(lines)


async def post_review(
    gh: GitHubClient, review: Review, result: ReviewResult, ctx: ReviewContext, elapsed: float
) -> set[int]:
    """Post the review. Returns the ids (indexes) of comments posted inline."""
    inline = [c for c in result.comments if c.line is not None]
    notes = [c for c in result.comments if c.line is None]
    payload = [
        {"path": c.path, "line": c.line, "side": "RIGHT", "body": format_comment(c)} for c in inline
    ]
    body = format_summary(result, ctx, notes, elapsed)
    try:
        await gh.create_review(
            review.repo_full_name, review.pr_number, review.head_sha, body, payload
        )
        return {id(c) for c in inline}
    except GitHubError as exc:
        if exc.status != 422:
            raise
        # GitHub rejected a line position (e.g. the PR moved on). Fall back to one comment.
        log.warning("Inline comments rejected (%s); posting summary only", exc)
        body = format_summary(result, ctx, result.comments, elapsed)
        await gh.create_issue_comment(review.repo_full_name, review.pr_number, body)
        return set()


async def run_review(review_id: int, deps: ReviewDeps) -> str:
    settings = deps.settings
    started = time.monotonic()

    async with deps.session_factory() as session:
        review = await session.get(Review, review_id)
        if review is None:
            return "missing"
        if review.status in (ReviewStatus.COMPLETED, ReviewStatus.SKIPPED):
            return review.status
        review.status = ReviewStatus.RUNNING
        review.attempts += 1
        review.error = None
        await session.commit()

    gh = await deps.github_for(review.installation_id)
    try:
        pr = await gh.get_pull_request(review.repo_full_name, review.pr_number)
        if pr.get("head", {}).get("sha", review.head_sha) != review.head_sha:
            return await _finish(
                deps, review_id, ReviewStatus.SKIPPED, "Superseded by a newer commit."
            )

        files = await collect_files(
            gh, review.repo_full_name, review.pr_number, review.head_sha, settings
        )
        if not files:
            return await _finish(deps, review_id, ReviewStatus.SKIPPED, "No reviewable files.")

        lint_findings = await linters.run_all(files)
        test_result = await tests_runner.run_tests(
            settings,
            review.repo_full_name,
            review.head_sha,
            await deps.token_for(review.installation_id)
            if deps.token_for and settings.run_tests
            else "",
        )
        ctx = ReviewContext(
            repo=review.repo_full_name,
            pr_number=review.pr_number,
            title=pr.get("title", review.pr_title),
            description=pr.get("body") or "",
            files=files,
            lint_findings=lint_findings,
            test_result=test_result,
        )
        agent = ReviewAgent(
            deps.provider,
            max_steps=settings.llm_max_steps,
            max_tokens=settings.llm_max_tokens,
            max_comments=settings.max_comments_per_review,
            max_patch_lines=settings.max_patch_lines,
            limiter=deps.limiter,
        )
        result = await agent.run(ctx)
        posted = await post_review(gh, review, result, ctx, time.monotonic() - started)
    finally:
        await gh.aclose()

    async with deps.session_factory() as session:
        review = await session.get(Review, review_id)
        review.status = ReviewStatus.COMPLETED
        review.verdict = result.verdict
        review.summary = result.summary
        review.model = result.model
        review.files_reviewed = len(files)
        review.lint_issue_count = len(lint_findings)
        review.tests_status = test_result.status
        review.tokens_in = result.tokens_in
        review.tokens_out = result.tokens_out
        review.duration_ms = int((time.monotonic() - started) * 1000)
        review.completed_at = utcnow()
        session.add_all(
            ReviewComment(
                review_id=review_id,
                path=c.path,
                line=c.line,
                severity=c.severity,
                category=c.category,
                source=c.source,
                body=c.body,
                posted_inline=id(c) in posted,
            )
            for c in result.comments
        )
        await session.commit()
    log.info(
        "Review %s completed: %s, %d comments", review_id, result.verdict, len(result.comments)
    )
    return ReviewStatus.COMPLETED


async def _finish(deps: ReviewDeps, review_id: int, status: str, note: str) -> str:
    async with deps.session_factory() as session:
        review = await session.get(Review, review_id)
        review.status = status
        review.summary = note
        review.completed_at = utcnow()
        await session.commit()
    return status


async def mark_failed(deps: ReviewDeps, review_id: int, error: str) -> None:
    async with deps.session_factory() as session:
        review = await session.get(Review, review_id)
        if review:
            review.status = ReviewStatus.FAILED
            review.error = error[:2000]
            review.completed_at = utcnow()
            await session.commit()


async def load_review(session: AsyncSession, review_id: int) -> Review | None:
    return await session.scalar(
        select(Review).options(selectinload(Review.comments)).where(Review.id == review_id)
    )

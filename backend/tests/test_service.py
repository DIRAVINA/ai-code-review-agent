"""End-to-end review job against a mocked GitHub API."""

import base64
import json

import httpx
import respx

from app.config import Settings
from app.db import SessionLocal
from app.github.client import GitHubClient
from app.models import Review, ReviewStatus
from app.review.llm import FakeProvider
from app.review.service import ReviewDeps, load_review, run_review, should_skip

API = "https://api.github.com"
REPO = "octo/demo"
SHA = "deadbeef"
CONTENT = "import os\n\n\ndef run(cmd):\n    return eval(cmd)\n"
PATCH = "@@ -0,0 +1,5 @@\n" + "\n".join("+" + line for line in CONTENT.splitlines())


async def make_review() -> int:
    async with SessionLocal() as s:
        r = Review(repo_full_name=REPO, installation_id=1, pr_number=3, head_sha=SHA, pr_title="t")
        s.add(r)
        await s.commit()
        return r.id


def deps() -> ReviewDeps:
    async def github_for(_installation_id: int) -> GitHubClient:
        return GitHubClient("token")

    return ReviewDeps(Settings(), SessionLocal, github_for, FakeProvider())


def mock_pr(router: respx.MockRouter, head_sha: str = SHA) -> None:
    router.get(f"{API}/repos/{REPO}/pulls/3").mock(
        return_value=httpx.Response(
            200, json={"title": "Add runner", "body": "", "head": {"sha": head_sha}}
        )
    )
    router.get(f"{API}/repos/{REPO}/pulls/3/files").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"filename": "runner.py", "status": "added", "patch": PATCH, "additions": 5},
                {"filename": "package-lock.json", "status": "modified", "patch": "@@ -1 +1 @@\n+x"},
            ],
        )
    )
    router.get(f"{API}/repos/{REPO}/contents/runner.py").mock(
        return_value=httpx.Response(
            200, json={"encoding": "base64", "content": base64.b64encode(CONTENT.encode()).decode()}
        )
    )


@respx.mock
async def test_full_review_posts_inline_comments(reset_db):
    mock_pr(respx.mock)
    posted = respx.post(f"{API}/repos/{REPO}/pulls/3/reviews").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    review_id = await make_review()

    assert await run_review(review_id, deps()) == ReviewStatus.COMPLETED

    body = json.loads(posted.calls.last.request.content)
    assert body["commit_id"] == SHA and body["event"] == "COMMENT"
    assert "AI Code Review" in body["body"]
    assert {c["path"] for c in body["comments"]} == {"runner.py"}  # lockfile skipped
    assert any(c["line"] == 5 for c in body["comments"])  # eval

    async with SessionLocal() as s:
        review = await load_review(s, review_id)
    assert review.status == "completed" and review.verdict == "request_changes"
    assert review.files_reviewed == 1 and review.lint_issue_count >= 2  # F401 os, S307 eval
    assert all(c.posted_inline for c in review.comments)


@respx.mock
async def test_falls_back_to_issue_comment_on_422(reset_db):
    mock_pr(respx.mock)
    respx.post(f"{API}/repos/{REPO}/pulls/3/reviews").mock(return_value=httpx.Response(422))
    fallback = respx.post(f"{API}/repos/{REPO}/issues/3/comments").mock(
        return_value=httpx.Response(201, json={"id": 2})
    )
    review_id = await make_review()
    await run_review(review_id, deps())
    assert fallback.called
    async with SessionLocal() as s:
        review = await load_review(s, review_id)
    assert review.status == "completed"
    assert not any(c.posted_inline for c in review.comments)


@respx.mock
async def test_superseded_commit_is_skipped(reset_db):
    mock_pr(respx.mock, head_sha="newer")
    review_id = await make_review()
    assert await run_review(review_id, deps()) == ReviewStatus.SKIPPED


def test_skip_patterns():
    assert should_skip("frontend/package-lock.json")
    assert should_skip("dist/app.min.js")
    assert not should_skip("src/app.py")

import argparse

from app.cli import cmd_seed
from app.db import SessionLocal
from app.models import Review, ReviewComment


async def add_review(status="completed", n_comments=2, repo="o/a") -> int:
    async with SessionLocal() as s:
        r = Review(
            repo_full_name=repo, installation_id=1, pr_number=1, head_sha=f"sha{status}{repo}",
            status=status, duration_ms=1000, tokens_in=10, tokens_out=5,
        )  # fmt: skip
        r.comments = [
            ReviewComment(path="a.py", line=i, severity="error", category="bug", body="x")
            for i in range(n_comments)
        ]
        s.add(r)
        await s.commit()
        return r.id


async def test_list_and_detail(client):
    rid = await add_review()
    await add_review(status="failed", n_comments=0, repo="o/b")

    page = client.get("/api/reviews").json()
    assert page["total"] == 2
    first = next(i for i in page["items"] if i["id"] == rid)
    assert first["comment_count"] == 2

    assert client.get("/api/reviews?status=failed").json()["total"] == 1
    assert client.get("/api/reviews?repo=o/a").json()["total"] == 1
    assert client.get("/api/repos").json() == ["o/a", "o/b"]

    detail = client.get(f"/api/reviews/{rid}").json()
    assert len(detail["comments"]) == 2
    assert client.get("/api/reviews/999").status_code == 404


async def test_retry(client, enqueued):
    rid = await add_review(status="failed")
    assert client.post(f"/api/reviews/{rid}/retry").status_code == 202
    assert enqueued == [rid]
    detail = client.get(f"/api/reviews/{rid}").json()
    assert detail["status"] == "queued" and detail["comments"] == []
    assert client.post(f"/api/reviews/{rid}/retry").status_code == 409


async def test_stats_with_seed_data(client):
    await cmd_seed(argparse.Namespace(count=30))
    stats = client.get("/api/stats").json()
    assert stats["total_reviews"] == 30
    assert len(stats["per_day"]) == 14
    assert sum(d["reviews"] for d in stats["per_day"]) == 30
    assert sum(d["issues"] for d in stats["per_day"]) == stats["total_issues"]
    assert sum(stats["by_severity"].values()) == stats["total_issues"]
    assert stats["top_repos"][0]["reviews"] >= stats["top_repos"][-1]["reviews"]

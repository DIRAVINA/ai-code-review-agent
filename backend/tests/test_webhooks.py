import hashlib
import hmac
import json

from app.github.security import verify_signature


def sign(body: bytes, secret: str = "test-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def pr_event(action: str = "opened", sha: str = "abc123", draft: bool = False) -> dict:
    return {
        "action": action,
        "installation": {"id": 42},
        "repository": {"full_name": "octo/demo"},
        "pull_request": {
            "number": 7,
            "title": "Add feature",
            "draft": draft,
            "html_url": "https://github.com/octo/demo/pull/7",
            "user": {"login": "harshan"},
            "head": {"sha": sha},
        },
    }


def post(client, payload: dict, event: str = "pull_request", signature: str | None = None):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-Hub-Signature-256": signature or sign(body),
            "Content-Type": "application/json",
        },
    )


def test_verify_signature():
    assert verify_signature("s", b"x", sign(b"x", "s"))
    assert not verify_signature("s", b"x", sign(b"y", "s"))
    assert not verify_signature("s", b"x", None)
    assert not verify_signature("", b"x", sign(b"x", ""))


def test_rejects_bad_signature(client):
    assert post(client, pr_event(), signature="sha256=bad").status_code == 401


def test_ping(client):
    assert post(client, {"zen": "hi"}, event="ping").json()["message"] == "pong"


def test_opened_pr_is_queued(client, enqueued):
    resp = post(client, pr_event())
    assert resp.status_code == 202
    assert enqueued == [resp.json()["review_id"]]


def test_redelivery_is_deduplicated(client, enqueued):
    first = post(client, pr_event()).json()
    second = post(client, pr_event()).json()
    assert second["duplicate"] is True
    assert second["review_id"] == first["review_id"]
    assert len(enqueued) == 1


def test_new_commit_gets_new_review(client, enqueued):
    post(client, pr_event(sha="aaa"))
    post(client, pr_event(action="synchronize", sha="bbb"))
    assert len(enqueued) == 2


def test_ignores_drafts_and_other_actions(client, enqueued):
    assert "ignored" in post(client, pr_event(draft=True)).json()
    assert "ignored" in post(client, pr_event(action="closed")).json()
    assert enqueued == []

"""End-to-end smoke test with a fake GitHub.

Starts a mock GitHub API, the real FastAPI app and the real arq worker, sends a
signed `pull_request` webhook, and waits until the review is posted back.

Needs Redis and a database. From backend/:
    python scripts/e2e_smoke.py
(uses DATABASE_URL / REDIS_URL from the environment, defaulting to SQLite + local Redis)
"""

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request

MOCK_PORT, API_PORT = 9100, 8100
SECRET = "e2e-secret"
REPO, PR, SHA = "octo/shop", 12, "c0ffee" * 6 + "abcd"
CONTENT = (
    "import os\nimport subprocess\n\n\ndef run(cmd):\n"
    '    password = "hunter2hunter2"\n'
    "    try:\n        return subprocess.call(cmd, shell=True)\n"
    "    except:\n        print('failed')\n"
)
PATCH = "@@ -0,0 +1,10 @@\n" + "\n".join("+" + line for line in CONTENT.splitlines())

posted: list[dict] = []
mock = FastAPI()


@mock.post("/app/installations/{installation_id}/access_tokens")
async def token(installation_id: int, request: Request):
    assert request.headers["authorization"].startswith("Bearer ey"), "app JWT expected"
    return {"token": "ghs_mock", "expires_at": "2099-01-01T00:00:00Z"}


@mock.get(f"/repos/{REPO}/pulls/{PR}")
async def pull():
    return {"title": "Add command runner", "body": "Runs shell commands.", "head": {"sha": SHA}}


@mock.get(f"/repos/{REPO}/pulls/{PR}/files")
async def files():
    return [{"filename": "runner.py", "status": "added", "patch": PATCH, "additions": 10}]


@mock.get(f"/repos/{REPO}/contents/runner.py")
async def contents():
    return {"encoding": "base64", "content": base64.b64encode(CONTENT.encode()).decode()}


@mock.post(f"/repos/{REPO}/pulls/{PR}/reviews")
async def review(request: Request):
    posted.append(await request.json())
    return {"id": 1}


def main() -> int:
    backend = Path(__file__).resolve().parent.parent
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with tempfile.NamedTemporaryFile("wb", suffix=".pem", delete=False) as key_file:
        key_file.write(pem)

    env = {
        **os.environ,
        "GITHUB_API_URL": f"http://127.0.0.1:{MOCK_PORT}",
        "GITHUB_APP_ID": "1",
        "GITHUB_PRIVATE_KEY_PATH": key_file.name,
        "GITHUB_WEBHOOK_SECRET": SECRET,
        "LLM_PROVIDER": os.environ.get("LLM_PROVIDER", "fake"),
        "DATABASE_URL": os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./e2e.db"),
        "REDIS_URL": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    }

    server = uvicorn.Server(uvicorn.Config(mock, port=MOCK_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(API_PORT)],
        cwd=backend, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )  # fmt: skip
    worker = subprocess.Popen(
        [sys.executable, "-m", "arq", "app.worker.WorkerSettings"],
        cwd=backend, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )  # fmt: skip
    try:
        base = f"http://127.0.0.1:{API_PORT}"
        for _ in range(50):
            try:
                if httpx.get(f"{base}/health").status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.2)

        event = {
            "action": "opened",
            "installation": {"id": 99},
            "repository": {"full_name": REPO},
            "pull_request": {
                "number": PR, "title": "Add command runner", "draft": False,
                "html_url": f"https://github.com/{REPO}/pull/{PR}",
                "user": {"login": "harshan"}, "head": {"sha": SHA},
            },
        }  # fmt: skip
        body = json.dumps(event).encode()
        sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        resp = httpx.post(
            f"{base}/webhooks/github",
            content=body,
            headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sig},
        )
        print("webhook ->", resp.status_code, resp.json())
        review_id = resp.json()["review_id"]

        for _ in range(60):
            review = httpx.get(f"{base}/api/reviews/{review_id}").json()
            if review["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)
        print(
            "review  ->", review["status"], review["verdict"], f"{len(review['comments'])} issues"
        )
        for c in review["comments"]:
            print(
                f"   {c['severity']:<8} {c['source']:<5} {c['path']}:{c['line']}  {c['body'][:70]}"
            )
        print("github  ->", f"{len(posted)} review(s) posted,",
              f"{len(posted[0]['comments']) if posted else 0} inline comments")  # fmt: skip

        ok = review["status"] == "completed" and len(posted) == 1 and posted[0]["comments"]
        print("\nE2E PASSED" if ok else "\nE2E FAILED")
        if not ok:
            worker.terminate()
            print(worker.communicate(timeout=5)[0][-3000:])
        return 0 if ok else 1
    finally:
        api.terminate()
        worker.terminate()
        os.unlink(key_file.name)


if __name__ == "__main__":
    sys.exit(main())

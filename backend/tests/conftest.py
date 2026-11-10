import os

# Configure before any app module is imported.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("LLM_PROVIDER", "fake")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import queue  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
async def reset_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
def enqueued(monkeypatch):
    jobs: list[int] = []

    async def fake_enqueue(review_id: int) -> None:
        jobs.append(review_id)

    monkeypatch.setattr(queue, "enqueue_review", fake_enqueue)
    return jobs


@pytest.fixture
def client(reset_db, enqueued):
    with TestClient(app) as c:
        yield c


def pytest_sessionfinish(session, exitstatus):
    if os.path.exists("test.db"):
        os.remove("test.db")

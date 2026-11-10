"""Thin async GitHub REST client with retries and rate-limit handling."""

import asyncio
import base64
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub API {status}: {message}")
        self.status = status


class GitHubClient:
    def __init__(
        self,
        token: str,
        base_url: str = "https://api.github.com",
        http: httpx.AsyncClient | None = None,
        max_retries: int = 4,
    ):
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=30)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    @staticmethod
    def _retry_delay(resp: httpx.Response, attempt: int) -> float | None:
        """Seconds to wait before retrying, or None if the response is final."""
        if resp.status_code >= 500:
            return min(2**attempt, 30)
        if resp.status_code in (403, 429):
            if "retry-after" in resp.headers:
                return float(resp.headers["retry-after"])
            if resp.headers.get("x-ratelimit-remaining") == "0":
                reset = float(resp.headers.get("x-ratelimit-reset", time.time() + 60))
                return max(reset - time.time(), 1)
            if resp.status_code == 429:
                return min(2**attempt * 5, 60)
        return None

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._http.request(method, url, headers=self._headers, **kwargs)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise
                log.warning("GitHub transport error %s, retrying", exc)
                await asyncio.sleep(min(2**attempt, 30))
                continue

            if resp.is_success:
                return resp
            delay = self._retry_delay(resp, attempt)
            if delay is None or attempt == self.max_retries or delay > 300:
                raise GitHubError(resp.status_code, resp.text[:500])
            log.warning("GitHub %s on %s, retrying in %.0fs", resp.status_code, path, delay)
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def get_pull_request(self, repo: str, number: int) -> dict:
        return (await self.request("GET", f"/repos/{repo}/pulls/{number}")).json()

    async def list_pr_files(self, repo: str, number: int, limit: int = 300) -> list[dict]:
        files: list[dict] = []
        page = 1
        while len(files) < limit:
            resp = await self.request(
                "GET", f"/repos/{repo}/pulls/{number}/files", params={"per_page": 100, "page": page}
            )
            batch = resp.json()
            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return files[:limit]

    async def get_file_content(self, repo: str, path: str, ref: str) -> str | None:
        try:
            resp = await self.request("GET", f"/repos/{repo}/contents/{path}", params={"ref": ref})
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise
        data = resp.json()
        if isinstance(data, list) or data.get("encoding") != "base64":
            return None
        try:
            return base64.b64decode(data["content"]).decode("utf-8")
        except UnicodeDecodeError:
            return None  # binary file

    async def create_review(
        self, repo: str, number: int, commit_id: str, body: str, comments: list[dict]
    ) -> dict:
        payload = {"commit_id": commit_id, "body": body, "event": "COMMENT", "comments": comments}
        resp = await self.request("POST", f"/repos/{repo}/pulls/{number}/reviews", json=payload)
        return resp.json()

    async def create_issue_comment(self, repo: str, number: int, body: str) -> dict:
        resp = await self.request(
            "POST", f"/repos/{repo}/issues/{number}/comments", json={"body": body}
        )
        return resp.json()

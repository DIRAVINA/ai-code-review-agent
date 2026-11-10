"""GitHub App authentication: app JWT -> short-lived installation access token."""

import time
from dataclasses import dataclass

import httpx
import jwt

from app.config import Settings


@dataclass
class _CachedToken:
    token: str
    expires_at: float


class GitHubAppAuth:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        self.settings = settings
        self._http = http
        self._cache: dict[int, _CachedToken] = {}

    def app_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": self.settings.github_app_id}
        return jwt.encode(payload, self.settings.private_key, algorithm="RS256")

    async def installation_token(self, installation_id: int) -> str:
        cached = self._cache.get(installation_id)
        if cached and cached.expires_at - time.time() > 120:
            return cached.token

        url = f"{self.settings.github_api_url}/app/installations/{installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {self.app_jwt()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        http = self._http or httpx.AsyncClient(timeout=30)
        try:
            resp = await http.post(url, headers=headers)
            resp.raise_for_status()
        finally:
            if self._http is None:
                await http.aclose()

        data = resp.json()
        # Tokens last one hour; cache for 55 minutes to stay clear of expiry.
        self._cache[installation_id] = _CachedToken(data["token"], time.time() + 55 * 60)
        return data["token"]

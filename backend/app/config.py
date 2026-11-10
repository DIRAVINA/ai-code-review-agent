from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infrastructure
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5173"

    # GitHub App
    github_app_id: str = ""
    github_private_key: str = ""  # PEM contents (\n escapes allowed)
    github_private_key_path: str = ""  # or a path to the .pem file
    github_webhook_secret: str = ""
    github_api_url: str = "https://api.github.com"

    # LLM
    llm_provider: Literal["anthropic", "openai", "fake"] = "fake"
    llm_model: str = ""  # empty = provider default
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    llm_max_steps: int = 12
    llm_max_tokens: int = 4096
    llm_requests_per_minute: int = 30

    # Review limits
    max_files_per_review: int = 30
    max_patch_lines: int = 2000
    max_file_bytes: int = 200_000
    max_comments_per_review: int = 25

    # Running the PR's own tests executes untrusted code: off by default,
    # and only ever inside a resource-limited Docker container.
    run_tests: bool = False
    test_command: str = "pip install -q -r requirements.txt && pytest -q"
    test_image: str = "python:3.12-slim"
    test_timeout_seconds: int = 300

    @property
    def private_key(self) -> str:
        if self.github_private_key:
            return self.github_private_key.replace("\\n", "\n")
        if self.github_private_key_path:
            return Path(self.github_private_key_path).read_text()
        return ""

    @property
    def model_name(self) -> str:
        if self.llm_model:
            return self.llm_model
        return {
            "anthropic": "claude-sonnet-5-5",
            "openai": "gpt-5-mini",
            "fake": "fake-reviewer",
        }[self.llm_provider]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

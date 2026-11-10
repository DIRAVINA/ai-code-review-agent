"""Optionally run the PR's test suite in a throwaway Docker container.

This executes code from the pull request, so it is disabled unless
RUN_TESTS=true, and always runs with CPU/memory/process limits and a timeout.
"""

import asyncio
import shutil
import tempfile

from app.config import Settings
from app.review.context import TestResult

MAX_OUTPUT = 6000


async def _run(*cmd: str, cwd: str | None = None, timeout: int = 300) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        return 124, f"Timed out after {timeout}s"
    return proc.returncode or 0, out.decode(errors="replace")


async def run_tests(settings: Settings, repo: str, sha: str, token: str) -> TestResult:
    if not settings.run_tests:
        return TestResult("skipped", "Test execution is disabled (RUN_TESTS=false).")
    if not shutil.which("docker"):
        return TestResult("skipped", "Docker is not available on the worker.")

    with tempfile.TemporaryDirectory() as tmp:
        url = f"https://x-access-token:{token}@github.com/{repo}.git"
        code, out = await _run("git", "init", "-q", tmp)
        code, out = await _run("git", "-C", tmp, "fetch", "-q", "--depth", "1", url, sha)
        if code != 0:
            return TestResult("error", "Could not fetch the PR commit.")
        await _run("git", "-C", tmp, "checkout", "-q", "FETCH_HEAD")

        code, out = await _run(
            "docker", "run", "--rm", "--memory", "1g", "--cpus", "1", "--pids-limit", "256",
            "-v", f"{tmp}:/src", "-w", "/src", settings.test_image,
            "sh", "-c", settings.test_command,
            timeout=settings.test_timeout_seconds,
        )  # fmt: skip

    tail = out[-MAX_OUTPUT:]
    if code == 124:
        return TestResult("error", tail)
    return TestResult("passed" if code == 0 else "failed", tail)

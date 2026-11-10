"""Static checks run before the LLM sees the PR.

Only findings on lines the PR actually adds are kept, so reviews stay about
the change rather than pre-existing code.
"""

import asyncio
import json
import logging
import re
import sys
import tempfile
from pathlib import Path

from app.review.context import ChangedFile, Finding

log = logging.getLogger(__name__)

RUFF_RULES = "F,E9,B,S"  # pyflakes, syntax errors, bugbear, bandit (security)
RUFF_IGNORE = "S101"  # `assert` is fine, especially in tests


def _ruff_severity(code: str) -> tuple[str, str]:
    if code.startswith("S"):
        return "warning", "security"
    if code.startswith(("E9", "F82", "F63")):
        return "error", "bug"
    if code.startswith("B"):
        return "warning", "bug"
    return "info", "maintainability"


async def run_ruff(files: list[ChangedFile]) -> list[Finding]:
    targets = [f for f in files if f.path.endswith(".py") and f.content is not None]
    if not targets:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for f in targets:
            dest = root / f.path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(f.content or "")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "ruff", "check", "--isolated", "--no-cache",
            "--output-format", "json", "--select", RUFF_RULES, "--ignore", RUFF_IGNORE, ".",
            cwd=root, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        stdout, stderr = await proc.communicate()
    try:
        results = json.loads(stdout or b"[]")
    except json.JSONDecodeError:
        log.warning("ruff produced unparseable output: %s", stderr[:300])
        return []

    by_path = {f.path: f for f in targets}
    findings = []
    for item in results:
        rel = Path(item["filename"]).resolve().relative_to(root.resolve()).as_posix()
        line = item["location"]["row"]
        changed = by_path.get(rel)
        if changed is None or line not in changed.added_lines:
            continue
        code = item.get("code") or "ruff"
        severity, category = _ruff_severity(code)
        findings.append(
            Finding(rel, line, f"`{code}` {item['message']}", severity, category, "lint", code)
        )
    return findings


SECRET_PATTERNS = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("API key", re.compile(r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}")),
    (
        "Hard-coded credential",
        re.compile(
            r"(?i)(password|passwd|secret|api_key|apikey|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"
        ),
    ),
]


def scan_secrets(files: list[ChangedFile]) -> list[Finding]:
    """Language-agnostic check for credentials committed in added lines."""
    from app.review.diff import parse_patch

    findings = []
    for f in files:
        for ln in parse_patch(f.patch):
            if ln.kind != "+":
                continue
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(ln.text):
                    findings.append(
                        Finding(
                            f.path,
                            ln.new_no,
                            f"Possible secret committed ({label}). Move it to an environment "
                            "variable or secret manager and rotate the exposed value.",
                            "error",
                            "security",
                            "lint",
                            "secret-scan",
                        )
                    )
                    break
    return findings


async def run_all(files: list[ChangedFile]) -> list[Finding]:
    ruff = await run_ruff(files)
    return ruff + scan_secrets(files)

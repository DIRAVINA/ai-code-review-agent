"""Review a raw unified diff without GitHub (used by the CLI and the MCP server)."""

from pathlib import Path

from app.config import Settings
from app.review import diff, linters
from app.review.agent import ReviewAgent, ReviewResult
from app.review.context import ChangedFile, ReviewContext
from app.review.llm import build_provider
from app.review.service import format_comment, should_skip


def files_from_diff(diff_text: str, root: str | None = None) -> list[ChangedFile]:
    files = []
    for entry in diff.split_unified_diff(diff_text):
        if entry["status"] == "removed" or should_skip(entry["path"]) or not entry["patch"]:
            continue
        content = None
        if root:
            path = Path(root, entry["path"])
            if path.is_file() and path.stat().st_size < 200_000:
                content = path.read_text(errors="replace")
        added = diff.added_lines(entry["patch"])
        removed = sum(1 for ln in diff.parse_patch(entry["patch"]) if ln.kind == "-")
        files.append(
            ChangedFile(
                entry["path"], entry["patch"], entry["status"], content, len(added), removed
            )
        )
    return files


async def review_diff(
    diff_text: str,
    settings: Settings,
    title: str = "Local changes",
    description: str = "",
    root: str | None = None,
) -> tuple[ReviewResult, ReviewContext]:
    files = files_from_diff(diff_text, root)
    ctx = ReviewContext("local", 0, title, description, files)
    ctx.lint_findings = await linters.run_all(files)
    agent = ReviewAgent(
        build_provider(settings),
        max_steps=settings.llm_max_steps,
        max_tokens=settings.llm_max_tokens,
        max_comments=settings.max_comments_per_review,
        max_patch_lines=settings.max_patch_lines,
    )
    return await agent.run(ctx), ctx


def to_markdown(result: ReviewResult) -> str:
    out = [f"## Review ({result.verdict})", "", result.summary or "_No summary._", ""]
    for c in result.comments:
        where = f"{c.path}:{c.line}" if c.line else c.path
        out += [f"### `{where}`", format_comment(c), ""]
    if not result.comments:
        out.append("No issues found.")
    return "\n".join(out)

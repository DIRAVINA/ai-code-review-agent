"""Expose the reviewer's tools over the Model Context Protocol.

Any MCP client (Claude Desktop, Claude Code, Cursor, ...) can then review a local
diff or query review history:

  python -m app.mcp_server           # stdio transport (for desktop clients)
  python -m app.mcp_server --http    # streamable HTTP on port 8765
"""

import argparse
import json

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import Review, ReviewComment
from app.review import linters
from app.review.local import files_from_diff, review_diff, to_markdown
from app.review.service import load_review

from mcp.server.mcpserver import MCPServer  # isort: skip

mcp = MCPServer(
    "ai-code-review-agent",
    instructions=(
        "Code review tools. Use review_code_diff on the output of `git diff` to get an AI "
        "review with inline findings; lint_code_diff for fast static checks only; "
        "list_reviews / get_review / review_stats to inspect pull requests the GitHub "
        "app has already reviewed."
    ),
)


@mcp.tool()
async def review_code_diff(diff: str, title: str = "Local changes", repo_root: str = "") -> str:
    """Review a unified diff (e.g. `git diff main`) with the LLM agent.

    Args:
        diff: Unified diff text.
        title: Short description of the change, used as the PR title.
        repo_root: Optional absolute path of the repository so full files can be read.
    """
    result, ctx = await review_diff(diff, get_settings(), title=title, root=repo_root or None)
    if not ctx.files:
        return "No reviewable files found in the diff."
    return to_markdown(result)


@mcp.tool()
async def lint_code_diff(diff: str, repo_root: str = "") -> str:
    """Run static checks on the lines added in a diff. Returns JSON.

    Secret scanning always runs; ruff (Python) needs repo_root to read the full files.
    """
    files = files_from_diff(diff, repo_root or None)
    findings = await linters.run_all(files)
    return json.dumps(
        [
            {
                "path": f.path,
                "line": f.line,
                "severity": f.severity,
                "rule": f.rule,
                "message": f.body,
            }
            for f in findings
        ],
        indent=1,
    )


@mcp.tool()
async def list_reviews(repo: str = "", status: str = "", limit: int = 10) -> str:
    """List recent pull request reviews. Optional filters: repo (owner/name) and status."""
    await init_db()
    async with SessionLocal() as s:
        q = select(Review).order_by(Review.created_at.desc()).limit(min(limit, 50))
        if repo:
            q = q.where(Review.repo_full_name == repo)
        if status:
            q = q.where(Review.status == status)
        rows = (await s.scalars(q)).all()
    return json.dumps(
        [
            {
                "id": r.id,
                "pr": f"{r.repo_full_name}#{r.pr_number}",
                "title": r.pr_title,
                "status": r.status,
                "verdict": r.verdict,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        indent=1,
    )


@mcp.tool()
async def get_review(review_id: int) -> str:
    """Get one review with its summary and every issue found."""
    await init_db()
    async with SessionLocal() as s:
        r = await load_review(s, review_id)
    if r is None:
        return f"Review {review_id} not found."
    lines = [
        f"# {r.repo_full_name}#{r.pr_number}: {r.pr_title}",
        f"status: {r.status} | verdict: {r.verdict} | model: {r.model}",
        "",
        r.summary or "(no summary)",
        "",
    ]
    lines += [
        f"- [{c.severity}/{c.category}] {c.path}:{c.line or '-'} {c.body}" for c in r.comments
    ]
    return "\n".join(lines)


@mcp.tool()
async def review_stats() -> str:
    """Totals of reviews and issues, broken down by severity and category."""
    await init_db()
    async with SessionLocal() as s:
        total = await s.scalar(select(func.count(Review.id)))
        sev = dict((await s.execute(
            select(ReviewComment.severity, func.count()).group_by(ReviewComment.severity)
        )).all())  # fmt: skip
        cat = dict((await s.execute(
            select(ReviewComment.category, func.count()).group_by(ReviewComment.category)
        )).all())  # fmt: skip
    return json.dumps({"reviews": total, "by_severity": sev, "by_category": cat}, indent=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.http:
        mcp.run("streamable-http", port=args.port)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()

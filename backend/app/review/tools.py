"""Tools the review agent can call. Shared by the LLM loop and the MCP server."""

import json
import re
from typing import Any

from app.review import diff
from app.review.context import CATEGORIES, SEVERITIES, ReviewContext

MAX_READ_LINES = 400

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_changed_files",
        "description": "List files changed in the pull request with status and line counts.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_file_diff",
        "description": "Get the diff of one file. Each line is prefixed with its new-file line "
        "number (blank for removed lines) and +, - or space.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a changed file as it is at the PR head, with line numbers. "
        f"Use to see surrounding context. Returns at most {MAX_READ_LINES} lines per call.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_code",
        "description": "Regex search across the changed files (full contents). Use it to find "
        "where a function or variable is defined or used.",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
    },
    {
        "name": "get_lint_results",
        "description": "Get static-analysis findings (ruff, secret scanning) on the added lines. "
        "These will be posted automatically; do not repeat them unless you add insight.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
    {
        "name": "get_test_results",
        "description": "Get the result and output tail of the project's test run, if it ran.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "submit_review",
        "description": "Submit the final review. Call exactly once, when done. Each comment's "
        "line must be a new-file line number that appears in that file's diff.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Markdown overview: what the PR does, risks, verdict reason.",
                },
                "verdict": {"type": "string", "enum": ["approve", "comment", "request_changes"]},
                "comments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "line": {"type": "integer"},
                            "severity": {"type": "string", "enum": list(SEVERITIES)},
                            "category": {"type": "string", "enum": list(CATEGORIES)},
                            "body": {"type": "string"},
                        },
                        "required": ["path", "line", "severity", "category", "body"],
                    },
                },
            },
            "required": ["summary", "verdict", "comments"],
        },
    },
]

TOOL_NAMES = {t["name"] for t in TOOL_SPECS}


class ReviewTools:
    def __init__(self, ctx: ReviewContext):
        self.ctx = ctx
        self.submission: dict | None = None

    def execute(self, name: str, args: dict[str, Any]) -> str:
        if name not in TOOL_NAMES:
            return f"Error: unknown tool {name!r}."
        try:
            return getattr(self, name)(**args)
        except TypeError as exc:
            return f"Error: bad arguments for {name}: {exc}"

    def list_changed_files(self) -> str:
        rows = [
            {
                "path": f.path,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
                "full_content_available": f.content is not None,
            }
            for f in self.ctx.files
        ]
        return json.dumps(rows, indent=1)

    def get_file_diff(self, path: str) -> str:
        f = self.ctx.file(path)
        if f is None:
            return f"Error: {path} is not a changed file."
        return diff.annotate_patch(f.patch) or "(no textual diff)"

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        f = self.ctx.file(path)
        if f is None:
            return f"Error: {path} is not a changed file."
        if f.content is None:
            return f"Error: full content of {path} is unavailable; use get_file_diff."
        lines = f.content.splitlines()
        start = max(start_line, 1)
        end = min(end_line or len(lines), len(lines), start + MAX_READ_LINES - 1)
        body = "\n".join(f"{i:>5} | {lines[i - 1]}" for i in range(start, end + 1))
        return f"{path} lines {start}-{end} of {len(lines)}\n{body}"

    def search_code(self, pattern: str) -> str:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Error: invalid regex: {exc}"
        hits = []
        for f in self.ctx.files:
            for i, line in enumerate((f.content or "").splitlines(), 1):
                if regex.search(line):
                    hits.append(f"{f.path}:{i}: {line.strip()[:200]}")
                    if len(hits) >= 50:
                        return "\n".join(hits) + "\n(truncated at 50 matches)"
        return "\n".join(hits) or "No matches."

    def get_lint_results(self, path: str | None = None) -> str:
        findings = [x for x in self.ctx.lint_findings if path is None or x.path == path]
        if not findings:
            return "No lint findings on the added lines."
        return "\n".join(f"{x.path}:{x.line} [{x.severity}] {x.body}" for x in findings)

    def get_test_results(self) -> str:
        t = self.ctx.test_result
        return f"status: {t.status}\n{t.output}".strip()

    def submit_review(self, summary: str, verdict: str, comments: list[dict]) -> str:
        self.submission = {"summary": summary, "verdict": verdict, "comments": comments}
        return "Review submitted."

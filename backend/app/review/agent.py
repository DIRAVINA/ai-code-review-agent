"""The review agent: an LLM tool-calling loop that ends in submit_review."""

import json
import logging
from dataclasses import dataclass, field

from app.ratelimit import RateLimiter
from app.review.context import CATEGORIES, SEVERITIES, Finding, ReviewContext
from app.review.llm import LLMProvider
from app.review.prompts import SYSTEM_PROMPT, initial_message
from app.review.tools import TOOL_SPECS, ReviewTools

log = logging.getLogger(__name__)
MAX_TOOL_OUTPUT = 12_000


@dataclass
class ReviewResult:
    summary: str
    verdict: str
    comments: list[Finding] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    steps: int = 0
    model: str = ""


class ReviewAgent:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_steps: int = 12,
        max_tokens: int = 4096,
        max_comments: int = 25,
        max_patch_lines: int = 2000,
        limiter: RateLimiter | None = None,
    ):
        self.provider = provider
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.max_comments = max_comments
        self.max_patch_lines = max_patch_lines
        self.limiter = limiter

    async def run(self, ctx: ReviewContext) -> ReviewResult:
        tools = ReviewTools(ctx)
        messages: list[dict] = [
            {"role": "user", "content": initial_message(ctx, self.max_patch_lines)}
        ]
        tokens_in = tokens_out = 0
        last_text = ""
        nudged = False

        for step in range(1, self.max_steps + 1):
            if self.limiter:
                await self.limiter.acquire()
            resp = await self.provider.complete(
                SYSTEM_PROMPT, messages, TOOL_SPECS, self.max_tokens
            )
            tokens_in += resp.tokens_in
            tokens_out += resp.tokens_out
            last_text = resp.text or last_text
            messages.append({"role": "assistant", "text": resp.text, "tool_calls": resp.tool_calls})

            if not resp.tool_calls:
                if nudged:
                    break
                nudged = True
                messages.append(
                    {"role": "user", "content": "Please finish by calling submit_review now."}
                )
                continue

            results = []
            for call in resp.tool_calls:
                output = tools.execute(call.name, call.args)
                log.debug("tool %s(%s) -> %d chars", call.name, json.dumps(call.args), len(output))
                results.append(
                    {"id": call.id, "name": call.name, "content": output[:MAX_TOOL_OUTPUT]}
                )
            messages.append({"role": "tool", "results": results})

            if tools.submission is not None:
                return self._finalize(ctx, tools.submission, tokens_in, tokens_out, step)

        log.warning("Agent stopped after %d steps without submit_review", self.max_steps)
        fallback = {
            "summary": last_text or "The reviewer did not produce a summary.",
            "verdict": "comment",
            "comments": [],
        }
        return self._finalize(ctx, fallback, tokens_in, tokens_out, self.max_steps)

    def _finalize(
        self, ctx: ReviewContext, sub: dict, tokens_in: int, tokens_out: int, steps: int
    ) -> ReviewResult:
        comments = self.validate_comments(ctx, sub.get("comments") or [])
        llm_lines = {(c.path, c.line) for c in comments}
        # Lint findings are added unless the model already commented on that line.
        for f in ctx.lint_findings:
            if (f.path, f.line) not in llm_lines:
                comments.append(f)
        comments.sort(key=lambda c: ({"error": 0, "warning": 1, "info": 2}[c.severity], c.path))
        verdict = sub.get("verdict")
        if verdict not in ("approve", "comment", "request_changes"):
            verdict = "comment"
        return ReviewResult(
            summary=str(sub.get("summary") or "").strip(),
            verdict=verdict,
            comments=comments[: self.max_comments],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            steps=steps,
            model=self.provider.model,
        )

    @staticmethod
    def validate_comments(ctx: ReviewContext, raw: list) -> list[Finding]:
        """Keep comments on real files; drop the line number if GitHub would reject it."""
        out: list[Finding] = []
        seen = set()
        for c in raw:
            if not isinstance(c, dict) or not c.get("body") or not c.get("path"):
                continue
            changed = ctx.file(str(c["path"]))
            if changed is None:
                continue
            try:
                line = int(c.get("line"))
            except (TypeError, ValueError):
                line = None
            if line not in changed.commentable_lines:
                line = None  # becomes a file-level note in the summary
            key = (changed.path, line, str(c["body"])[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                Finding(
                    path=changed.path,
                    line=line,
                    body=str(c["body"]).strip(),
                    severity=c.get("severity") if c.get("severity") in SEVERITIES else "warning",
                    category=c.get("category")
                    if c.get("category") in CATEGORIES
                    else "maintainability",
                    source="llm",
                )
            )
        return out

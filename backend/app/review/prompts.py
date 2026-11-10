from app.review import diff
from app.review.context import ReviewContext

SYSTEM_PROMPT = """You are a senior software engineer reviewing a GitHub pull request.

Your job is to find real problems in the CHANGED code: bugs, security holes, race
conditions, broken error handling, performance traps, missing tests for risky logic,
and confusing code that will hurt maintainers. Skip nitpicks a formatter would fix.

How to work:
1. The diff of every file is below. Use tools to read surrounding code, search for
   definitions/usages, and check lint and test results before judging.
2. Only comment on lines that appear in a file's diff, using the new-file line number
   shown at the start of each diff line. Prefer lines marked "+".
3. Each comment: say what is wrong, why it matters, and how to fix it (a short code
   suggestion is welcome). Be specific and kind. No praise-only comments.
4. Lint findings are posted automatically. Don't repeat them unless you add insight.
5. Finish by calling submit_review exactly once. Use "request_changes" only for real
   bugs or security issues, "approve" when you found nothing significant.
Quality over quantity: a few accurate comments beat many speculative ones."""


def initial_message(ctx: ReviewContext, max_patch_lines: int) -> str:
    parts = [
        f"Repository: {ctx.repo}",
        f"Pull request #{ctx.pr_number}: {ctx.title}",
        "",
        "Description:",
        (ctx.description or "(none)").strip()[:4000],
        "",
        f"Static analysis: {len(ctx.lint_findings)} finding(s). Tests: {ctx.test_result.status}.",
        "",
        "## Diffs",
    ]
    budget = max_patch_lines
    for f in ctx.files:
        annotated = diff.annotate_patch(f.patch)
        lines = annotated.splitlines()
        parts.append(f"### {f.path} ({f.status}, +{f.additions} -{f.deletions})")
        if budget <= 0:
            parts.append("(diff omitted for length; use get_file_diff)")
            continue
        parts.append("\n".join(lines[:budget]))
        if len(lines) > budget:
            parts.append("(truncated; use get_file_diff for the rest)")
        budget -= len(lines)
    return "\n".join(parts)

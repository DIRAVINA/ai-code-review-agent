from dataclasses import dataclass, field
from functools import cached_property

from app.review import diff

SEVERITIES = ("info", "warning", "error")
CATEGORIES = ("bug", "security", "performance", "style", "maintainability", "testing", "docs")


@dataclass
class ChangedFile:
    path: str
    patch: str
    status: str = "modified"  # added|modified|renamed|removed
    content: str | None = None  # full file at the PR head, when available
    additions: int = 0
    deletions: int = 0

    @cached_property
    def commentable_lines(self) -> set[int]:
        return diff.commentable_lines(self.patch)

    @cached_property
    def added_lines(self) -> set[int]:
        return diff.added_lines(self.patch)


@dataclass
class Finding:
    path: str
    line: int | None
    body: str
    severity: str = "warning"
    category: str = "maintainability"
    source: str = "llm"  # llm|lint
    rule: str | None = None


@dataclass
class TestResult:
    status: str  # passed|failed|skipped|error
    output: str = ""


@dataclass
class ReviewContext:
    repo: str
    pr_number: int
    title: str
    description: str
    files: list[ChangedFile]
    lint_findings: list[Finding] = field(default_factory=list)
    test_result: TestResult = field(default_factory=lambda: TestResult("skipped"))

    def file(self, path: str) -> ChangedFile | None:
        return next((f for f in self.files if f.path == path), None)

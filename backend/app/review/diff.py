"""Unified-diff helpers.

GitHub only accepts inline review comments on lines that appear in the diff,
so we track which new-file line numbers are commentable.
"""

import re
from dataclasses import dataclass

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffLine:
    kind: str  # "+", "-", " "
    old_no: int | None
    new_no: int | None
    text: str


def parse_patch(patch: str) -> list[DiffLine]:
    lines: list[DiffLine] = []
    old_no = new_no = 0
    in_hunk = False
    for raw in patch.splitlines():
        m = HUNK_RE.match(raw)
        if m:
            old_no, new_no = int(m.group(1)), int(m.group(3))
            in_hunk = True
            continue
        if not in_hunk or raw.startswith("\\"):  # "\ No newline at end of file"
            continue
        kind, text = (raw[:1] or " "), raw[1:]
        if kind == "+":
            lines.append(DiffLine("+", None, new_no, text))
            new_no += 1
        elif kind == "-":
            lines.append(DiffLine("-", old_no, None, text))
            old_no += 1
        else:
            lines.append(DiffLine(" ", old_no, new_no, text))
            old_no += 1
            new_no += 1
    return lines


def commentable_lines(patch: str) -> set[int]:
    return {ln.new_no for ln in parse_patch(patch) if ln.new_no is not None}


def added_lines(patch: str) -> set[int]:
    return {ln.new_no for ln in parse_patch(patch) if ln.kind == "+" and ln.new_no is not None}


def annotate_patch(patch: str) -> str:
    """Render a patch with new-file line numbers so an LLM can cite exact lines."""
    out = []
    for ln in parse_patch(patch):
        num = f"{ln.new_no:>5}" if ln.new_no is not None else "     "
        out.append(f"{num} {ln.kind} {ln.text}")
    return "\n".join(out)


def split_unified_diff(diff_text: str) -> list[dict]:
    """Split a multi-file `git diff` into [{path, status, patch}] entries."""
    files: list[dict] = []
    current: dict | None = None
    old_left = new_left = 0
    pending_old: str | None = None

    for raw in diff_text.splitlines():
        in_hunk = old_left > 0 or new_left > 0
        if in_hunk and current is not None:
            current["patch"].append(raw)
            if raw.startswith("+"):
                new_left -= 1
            elif raw.startswith("-"):
                old_left -= 1
            elif not raw.startswith("\\"):
                old_left -= 1
                new_left -= 1
            continue

        if raw.startswith("diff --git "):
            current = None
            pending_old = None
        elif raw.startswith("--- "):
            pending_old = raw[4:].strip()
        elif raw.startswith("+++ "):
            new_path = raw[4:].strip()
            if new_path == "/dev/null":
                path, status = _strip_prefix(pending_old or ""), "removed"
            else:
                path = _strip_prefix(new_path)
                status = "added" if pending_old == "/dev/null" else "modified"
            current = {"path": path, "status": status, "patch": []}
            files.append(current)
        elif (m := HUNK_RE.match(raw)) and current is not None:
            current["patch"].append(raw)
            old_left = int(m.group(2)) if m.group(2) is not None else 1
            new_left = int(m.group(4)) if m.group(4) is not None else 1

    for f in files:
        f["patch"] = "\n".join(f["patch"])
    return files


def _strip_prefix(path: str) -> str:
    path = path.split("\t")[0]
    return path[2:] if path[:2] in ("a/", "b/") else path

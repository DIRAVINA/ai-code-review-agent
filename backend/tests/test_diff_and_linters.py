from app.review import diff, linters
from app.review.context import ChangedFile

PATCH = """@@ -1,4 +1,5 @@
 import os
-x = 1
+x = 2
+y = 3
 def f():
     return x
\\ No newline at end of file"""


def test_parse_patch_line_numbers():
    assert diff.added_lines(PATCH) == {2, 3}
    assert diff.commentable_lines(PATCH) == {1, 2, 3, 4, 5}


def test_annotate_patch_shows_new_line_numbers():
    out = diff.annotate_patch(PATCH).splitlines()
    assert out[0].split() == ["1", "import", "os"]
    assert out[1].startswith("      - x = 1")
    assert out[2].split()[:2] == ["2", "+"]


GIT_DIFF = """diff --git a/app.py b/app.py
index 1..2 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 a = 1
--- this removed line starts with dashes
+b = 2
diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+hello
"""


def test_split_unified_diff():
    files = diff.split_unified_diff(GIT_DIFF)
    summary = [(f["path"], f["status"]) for f in files]
    assert summary == [("app.py", "modified"), ("new.txt", "added")]
    assert "this removed line" in files[0]["patch"]
    assert diff.added_lines(files[1]["patch"]) == {1}


async def test_ruff_reports_only_added_lines():
    content = "import os\nimport sys\n\n\ndef f():\n    return eval('1')\n"
    patch = "@@ -0,0 +1,6 @@\n" + "".join(f"+{line}\n" for line in content.splitlines()).replace(
        "+import os\n", " import os\n", 1
    ).replace("@@ -0,0", "@@ -1,1")
    f = ChangedFile("pkg/mod.py", patch, content=content)
    findings = await linters.run_ruff([f])
    rules = {(x.rule, x.line) for x in findings}
    assert ("F401", 2) in rules  # unused `sys` on an added line
    assert ("F401", 1) not in rules  # `os` was a context line, not added
    assert any(x.category == "security" for x in findings)  # eval -> S307


def test_secret_scan():
    patch = '@@ -0,0 +1,2 @@\n+API_KEY = "sk-ant-abcdefghijklmnopqrstuvwxyz"\n+name = "ok"'
    findings = linters.scan_secrets([ChangedFile("cfg.py", patch)])
    assert len(findings) == 1 and findings[0].line == 1 and findings[0].severity == "error"

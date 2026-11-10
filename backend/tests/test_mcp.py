from app.mcp_server import mcp

DIFF = """diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,6 @@
 def add(a, b):
     return a + b
+
+
+def run(expr):
+    return eval(expr)
"""


def text(result) -> str:
    return result.content[0].text


async def test_lists_tools():
    names = {t.name for t in await mcp.list_tools()}
    assert names == {
        "review_code_diff",
        "lint_code_diff",
        "list_reviews",
        "get_review",
        "review_stats",
    }


async def test_review_and_lint_diff(reset_db, tmp_path):
    review = text(await mcp.call_tool("review_code_diff", {"diff": DIFF}))
    assert "request_changes" in review and "calc.py:6" in review

    # ruff needs the full file, which the tool reads from repo_root
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef run(expr):\n    return eval(expr)\n"
    )
    lint = text(await mcp.call_tool("lint_code_diff", {"diff": DIFF, "repo_root": str(tmp_path)}))
    assert "S307" in lint
    assert text(await mcp.call_tool("lint_code_diff", {"diff": DIFF})) == "[]"


async def test_history_tools(reset_db):
    assert text(await mcp.call_tool("list_reviews", {})) == "[]"
    assert "not found" in text(await mcp.call_tool("get_review", {"review_id": 1}))
    assert '"reviews": 0' in text(await mcp.call_tool("review_stats", {}))

from app.review.agent import ReviewAgent
from app.review.context import ChangedFile, Finding, ReviewContext
from app.review.llm import AnthropicProvider, FakeProvider, LLMResponse, OpenAIProvider, ToolCall
from app.review.tools import ReviewTools

CONTENT = (
    "def load(path):\n    try:\n        return open(path).read()\n"
    "    except:\n        print('oops')\n"
)
PATCH = "@@ -0,0 +1,5 @@\n" + "\n".join("+" + line for line in CONTENT.splitlines())


def make_ctx(**kw) -> ReviewContext:
    return ReviewContext(
        repo="o/r",
        pr_number=1,
        title="Add loader",
        description="",
        files=[ChangedFile("app/io.py", PATCH, "added", CONTENT, 5, 0)],
        **kw,
    )


class ScriptedProvider:
    """Replays a fixed list of responses, recording what it was sent."""

    model = "scripted"

    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.calls: list[list[dict]] = []

    async def complete(self, system, messages, tools, max_tokens):
        self.calls.append(list(messages))
        return self.responses.pop(0)


async def test_fake_provider_finds_bare_except_and_print():
    ctx = make_ctx(
        lint_findings=[Finding("app/io.py", 4, "`E722`", "warning", "bug", "lint", "E722")]
    )
    result = await ReviewAgent(FakeProvider()).run(ctx)
    assert result.verdict == "request_changes"
    by_line = {(c.line, c.source) for c in result.comments}
    assert (5, "llm") in by_line  # print
    assert (4, "llm") in by_line  # bare except, LLM comment wins over lint on same line
    assert (4, "lint") not in by_line
    assert result.steps == 2


async def test_agent_tool_loop_and_validation():
    provider = ScriptedProvider(
        [
            LLMResponse(
                tool_calls=[ToolCall("1", "read_file", {"path": "app/io.py", "end_line": 2})]
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        "2",
                        "submit_review",
                        {
                            "summary": "Looks risky",
                            "verdict": "comment",
                            "comments": [
                                {"path": "app/io.py", "line": 3, "severity": "warning",
                                 "category": "bug", "body": "File handle never closed."},
                                {"path": "app/io.py", "line": 99, "severity": "info",
                                 "category": "style", "body": "Not in the diff."},
                                {"path": "nope.py", "line": 1, "severity": "error",
                                 "category": "bug", "body": "Unknown file."},
                            ],
                        },
                    )
                ]
            ),
        ]
    )  # fmt: skip
    result = await ReviewAgent(provider).run(make_ctx())
    tool_msg = provider.calls[1][-1]
    assert tool_msg["role"] == "tool" and "1 | def load(path):" in tool_msg["results"][0]["content"]
    assert [(c.line, c.body[:4]) for c in result.comments] == [(3, "File"), (None, "Not ")]


async def test_agent_nudges_then_falls_back():
    provider = ScriptedProvider([LLMResponse(text="I think it's fine."), LLMResponse(text="Done.")])
    result = await ReviewAgent(provider).run(make_ctx())
    assert result.verdict == "comment"
    assert result.summary == "Done."
    assert "submit_review" in provider.calls[1][-1]["content"]


def test_tools_search_and_errors():
    tools = ReviewTools(make_ctx())
    assert "app/io.py:4" in tools.execute("search_code", {"pattern": r"except"})
    assert tools.execute("read_file", {"path": "x.py"}).startswith("Error")
    assert tools.execute("bogus", {}).startswith("Error")
    assert tools.execute("read_file", {"wrong": 1}).startswith("Error")


HISTORY = [
    {"role": "user", "content": "review"},
    {"role": "assistant", "text": "hmm", "tool_calls": [ToolCall("t1", "get_lint_results", {})]},
    {"role": "tool", "results": [{"id": "t1", "name": "get_lint_results", "content": "none"}]},
]


def test_anthropic_message_conversion():
    out = AnthropicProvider._convert(HISTORY)
    assert out[1]["content"][1] == {
        "type": "tool_use",
        "id": "t1",
        "name": "get_lint_results",
        "input": {},
    }
    assert out[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "none"}],
    }


def test_openai_message_conversion():
    out = OpenAIProvider._convert("sys", HISTORY)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[2]["tool_calls"][0]["function"] == {"name": "get_lint_results", "arguments": "{}"}
    assert out[3] == {"role": "tool", "tool_call_id": "t1", "content": "none"}

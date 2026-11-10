"""Provider-neutral LLM interface with tool calling.

Conversation history uses a small neutral format so the agent loop doesn't
care which vendor is behind it:
  {"role": "user", "content": str}
  {"role": "assistant", "text": str, "tool_calls": [ToolCall, ...]}
  {"role": "tool", "results": [{"id": str, "name": str, "content": str}, ...]}
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import Settings


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


class LLMProvider(Protocol):
    model: str

    async def complete(
        self, system: str, messages: list[dict], tools: list[dict], max_tokens: int
    ) -> LLMResponse: ...


class AnthropicProvider:
    def __init__(self, api_key: str, model: str):
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=api_key, max_retries=4)
        self.model = model

    @staticmethod
    def _convert(messages: list[dict]) -> list[dict]:
        out = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                blocks: list[dict] = []
                if m.get("text"):
                    blocks.append({"type": "text", "text": m["text"]})
                for tc in m.get("tool_calls", []):
                    blocks.append(
                        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.args}
                    )
                # The API rejects empty assistant turns.
                out.append({"role": "assistant", "content": blocks or "(no response)"})
            else:
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"]}
                            for r in m["results"]
                        ],
                    }
                )
        return out

    async def complete(self, system, messages, tools, max_tokens) -> LLMResponse:
        resp = await self.client.messages.create(
            model=self.model,
            system=system,
            messages=self._convert(messages),
            tools=tools,
            max_tokens=max_tokens,
        )
        result = LLMResponse(tokens_in=resp.usage.input_tokens, tokens_out=resp.usage.output_tokens)
        for block in resp.content:
            if block.type == "text":
                result.text += block.text
            elif block.type == "tool_use":
                result.tool_calls.append(ToolCall(block.id, block.name, dict(block.input)))
        return result


class OpenAIProvider:
    def __init__(self, api_key: str, model: str):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key, max_retries=4)
        self.model = model

    @staticmethod
    def _convert(system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.get("text") or None}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                        }
                        for tc in m["tool_calls"]
                    ]
                out.append(msg)
            else:
                out.extend(
                    {"role": "tool", "tool_call_id": r["id"], "content": r["content"]}
                    for r in m["results"]
                )
        return out

    async def complete(self, system, messages, tools, max_tokens) -> LLMResponse:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=self._convert(system, messages),
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ],
            max_completion_tokens=max_tokens,
        )
        msg = resp.choices[0].message
        result = LLMResponse(
            text=msg.content or "",
            tokens_in=resp.usage.prompt_tokens if resp.usage else 0,
            tokens_out=resp.usage.completion_tokens if resp.usage else 0,
        )
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result.tool_calls.append(ToolCall(tc.id, tc.function.name, args))
        return result


class FakeProvider:
    """Offline, deterministic reviewer for demos and tests (no API key needed).

    It drives the same tool loop as a real model: first it asks for lint
    results, then submits a review built from simple heuristics on added lines.
    """

    model = "fake-reviewer"
    HEURISTICS = [
        (re.compile(r"^\s*except\s*:"), "error", "bug",
         "Bare `except:` also catches KeyboardInterrupt/SystemExit. Catch a specific exception."),
        (re.compile(r"\bprint\("), "info", "style",
         "Leftover `print()`? Prefer the `logging` module in application code."),
        (re.compile(r"\b(TODO|FIXME|HACK)\b"), "info", "maintainability",
         "Unresolved TODO/FIXME. Consider opening an issue so it isn't forgotten."),
        (re.compile(r"\b(eval|exec)\("), "error", "security",
         "`eval`/`exec` on dynamic input allows arbitrary code execution."),
        (re.compile(r"console\.log\("), "info", "style",
         "Remove debugging `console.log` before merging."),
        (re.compile(r"(?i)select .* from .*['\"]\s*\+|f['\"]select .*\{"), "error", "security",
         "SQL built with string formatting is injectable. Use parameterized queries."),
    ]  # fmt: skip

    async def complete(self, system, messages, tools, max_tokens) -> LLMResponse:
        step = sum(1 for m in messages if m["role"] == "assistant")
        if step == 0:
            return LLMResponse(
                text="Checking static analysis first.",
                tool_calls=[ToolCall("call_lint", "get_lint_results", {})],
            )
        comments = []
        path = None
        for line in messages[0]["content"].splitlines():
            if line.startswith("### "):
                path = line[4:].split(" (")[0].strip()
                continue
            m = re.match(r"^\s*(\d+) \+ (.*)$", line)
            if not (m and path):
                continue
            for pattern, severity, category, body in self.HEURISTICS:
                if pattern.search(m.group(2)):
                    comments.append(
                        {
                            "path": path,
                            "line": int(m.group(1)),
                            "severity": severity,
                            "category": category,
                            "body": body,
                        }
                    )
                    break
        verdict = (
            "request_changes"
            if any(c["severity"] == "error" for c in comments)
            else ("comment" if comments else "approve")
        )
        summary = (
            f"Automated heuristic review (offline mode). Found {len(comments)} potential "
            "issue(s) in the added lines. Configure `LLM_PROVIDER=anthropic` or `openai` "
            "for a full LLM review."
        )
        return LLMResponse(
            tool_calls=[
                ToolCall(
                    "call_submit",
                    "submit_review",
                    {"summary": summary, "verdict": verdict, "comments": comments},
                )
            ]
        )


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        return AnthropicProvider(settings.anthropic_api_key, settings.model_name)
    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        return OpenAIProvider(settings.openai_api_key, settings.model_name)
    return FakeProvider()

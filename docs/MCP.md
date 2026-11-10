# Using the reviewer as an MCP server

The same tools the agent uses are available to any [Model Context Protocol](https://modelcontextprotocol.io) client. Your assistant can review your uncommitted changes before you even open a PR.

| Tool | What it does |
|---|---|
| `review_code_diff(diff, title?, repo_root?)` | Full agent review of a unified diff. Returns Markdown. |
| `lint_code_diff(diff, repo_root?)` | Ruff + secret scan on added lines. Returns JSON. Ruff needs `repo_root`. |
| `list_reviews(repo?, status?, limit?)` | Recent PR reviews from the database |
| `get_review(review_id)` | One review with all of its issues |
| `review_stats()` | Totals by severity and category |

In the examples below, replace `/path/to/ai-code-review-agent` with where you cloned the repo, and make sure `backend/.venv` exists (`pip install -e ".[dev]"`).

## Claude Desktop

Add this to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "code-review": {
      "command": "/path/to/ai-code-review-agent/backend/.venv/bin/python",
      "args": ["-m", "app.mcp_server"],
      "env": {
        "PYTHONPATH": "/path/to/ai-code-review-agent/backend",
        "DATABASE_URL": "sqlite+aiosqlite:////path/to/ai-code-review-agent/backend/dev.db",
        "LLM_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

On Windows, the Python path is `...\\backend\\.venv\\Scripts\\python.exe`.

## Claude Code

```bash
claude mcp add code-review \
  -e PYTHONPATH=/path/to/ai-code-review-agent/backend \
  -e LLM_PROVIDER=anthropic -e ANTHROPIC_API_KEY=sk-ant-... \
  -- /path/to/ai-code-review-agent/backend/.venv/bin/python -m app.mcp_server
```

Then ask: *"Run `git diff` and review it with the code-review tools."*

## HTTP transport

```bash
cd backend && python -m app.mcp_server --http --port 8765
```

The server listens at `http://127.0.0.1:8765/mcp`.

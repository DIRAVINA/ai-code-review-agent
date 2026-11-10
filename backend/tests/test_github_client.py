import base64

import httpx
import pytest
import respx

from app.github.client import GitHubClient, GitHubError

API = "https://api.github.com"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr("app.github.client.asyncio.sleep", instant)


@respx.mock
async def test_retries_server_errors_then_succeeds():
    route = respx.get(f"{API}/repos/o/r/pulls/1").mock(
        side_effect=[httpx.Response(502), httpx.Response(200, json={"number": 1})]
    )
    async with GitHubClient("t") as gh:
        assert (await gh.get_pull_request("o/r", 1))["number"] == 1
    assert route.call_count == 2


@respx.mock
async def test_respects_rate_limit_then_succeeds():
    route = respx.get(f"{API}/repos/o/r/pulls/1").mock(
        side_effect=[
            httpx.Response(403, headers={"retry-after": "1"}),
            httpx.Response(200, json={"number": 1}),
        ]
    )
    async with GitHubClient("t") as gh:
        await gh.get_pull_request("o/r", 1)
    assert route.call_count == 2


@respx.mock
async def test_client_errors_are_not_retried():
    route = respx.get(f"{API}/repos/o/r/pulls/1").mock(return_value=httpx.Response(422))
    async with GitHubClient("t") as gh:
        with pytest.raises(GitHubError):
            await gh.get_pull_request("o/r", 1)
    assert route.call_count == 1


@respx.mock
async def test_lists_files_across_pages():
    page1 = [{"filename": f"f{i}.py"} for i in range(100)]
    respx.get(f"{API}/repos/o/r/pulls/1/files", params={"page": "1"}).mock(
        return_value=httpx.Response(200, json=page1)
    )
    respx.get(f"{API}/repos/o/r/pulls/1/files", params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[{"filename": "last.py"}])
    )
    async with GitHubClient("t") as gh:
        files = await gh.list_pr_files("o/r", 1)
    assert len(files) == 101


@respx.mock
async def test_file_content_decodes_and_handles_missing():
    content = base64.b64encode(b"print('hi')\n").decode()
    respx.get(f"{API}/repos/o/r/contents/a.py").mock(
        return_value=httpx.Response(200, json={"encoding": "base64", "content": content})
    )
    respx.get(f"{API}/repos/o/r/contents/gone.py").mock(return_value=httpx.Response(404))
    async with GitHubClient("t") as gh:
        assert await gh.get_file_content("o/r", "a.py", "sha") == "print('hi')\n"
        assert await gh.get_file_content("o/r", "gone.py", "sha") is None

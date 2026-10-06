import asyncio

import httpx
import pytest
from mcp.types import CallToolResult, TextContent

from vv.errors import Code, VVError
from vv.mcp_provider import discover_public, require_schema, transport_error, unpack_result


def test_sdk_timeout_is_sanitized():
    from mcp.shared.exceptions import McpError
    from mcp.types import ErrorData

    error = McpError(ErrorData(code=408, message="SECRET_SENTINEL"))
    assert transport_error(error).code == Code.NETWORK_ERROR
    assert transport_error(error, side_effect=True).code == Code.OUTCOME_UNKNOWN
    assert "SECRET_SENTINEL" not in transport_error(error).message


@pytest.mark.parametrize("status", [401, 403])
def test_auth_required_without_secret_echo(status):
    response = httpx.Response(status, request=httpx.Request("GET", "https://example.invalid"))
    error = httpx.HTTPStatusError(
        "secret-access-token", request=response.request, response=response
    )
    mapped = transport_error(error)
    assert mapped.code == Code.AUTH_REQUIRED
    assert "secret" not in mapped.message
    assert not mapped.retryable


def test_schema_changed():
    with pytest.raises(VVError) as caught:
        require_schema({"required": ["new_field"]}, {"required": []})
    assert caught.value.code == Code.SCHEMA_CHANGED


def test_same_schema():
    require_schema({"type": "object"}, {"type": "object"})


def test_tool_error_beats_structured_content():
    with pytest.raises(VVError) as caught:
        unpack_result(CallToolResult(isError=True, content=[], structuredContent={"price": 100}))
    assert caught.value.code == Code.PROVIDER_ERROR


def test_structured_and_json_text_results():
    assert unpack_result(CallToolResult(content=[], structuredContent={"test": 1})) == {"test": 1}
    assert unpack_result(
        CallToolResult(content=[TextContent(type="text", text='{"test": 1}')])
    ) == {"test": 1}


@pytest.mark.parametrize("text", ["[]", "not JSON", "__import__('os').system('false')"])
def test_invalid_response_is_schema_changed(text):
    with pytest.raises(VVError) as caught:
        unpack_result(CallToolResult(content=[TextContent(type="text", text=text)]))
    assert caught.value.code == Code.SCHEMA_CHANGED


def test_link_timeout_is_not_retryable():
    error = transport_error(httpx.ReadTimeout("secret"), side_effect=True)
    assert error.code == Code.OUTCOME_UNKNOWN
    assert not error.retryable
    assert transport_error(httpx.ReadTimeout("secret")).code == Code.NETWORK_ERROR


def test_discovery_uses_sdk_sessions_and_pagination(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    calls = []

    @asynccontextmanager
    async def transport(url, **kwargs):
        calls.append(url)
        yield ("reader", "writer", None)

    class Session:
        def __init__(self, reader, writer):
            assert (reader, writer) == ("reader", "writer")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            calls.append("initialize")

        async def list_tools(self, cursor=None):
            calls.append(cursor)
            return SimpleNamespace(tools=[], nextCursor="second" if cursor is None else None)

    monkeypatch.setattr("vv.mcp_provider.streamable_http_client", transport)
    monkeypatch.setattr("vv.mcp_provider.ClientSession", Session)
    assert asyncio.run(discover_public()) == []
    assert calls == ["https://mcp.vkusvill.ru/mcp", "initialize", None, "second"]

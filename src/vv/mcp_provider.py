import json

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

from vv.errors import Code, VVError
from vv.models import CartPayload, Request

ENDPOINT = "https://mcp.vkusvill.ru/mcp"
TOOLS = {
    "search": "vkusvill_products_search",
    "get": "vkusvill_product_details",
    "analogs": "vkusvill_product_analogs",
    "link": "vkusvill_cart_link_create",
}


def transport_error(error: Exception, *, side_effect: bool = False) -> VVError:
    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code in (401, 403):
            return VVError(
                Code.AUTH_REQUIRED, "Trusted OAuth onboarding is required; not implemented."
            )
        return VVError(Code.PROVIDER_ERROR, "Provider rejected the request.")
    if isinstance(error, (httpx.TransportError, TimeoutError)):
        if side_effect:
            return VVError(Code.OUTCOME_UNKNOWN, "Link outcome is unknown; do not retry blindly.")
        return VVError(Code.NETWORK_ERROR, "Provider connection failed.", retryable=True)
    return VVError(Code.PROVIDER_ERROR, "Provider request failed.")


def unpack_result(result: CallToolResult) -> dict:
    if result.isError:
        raise VVError(Code.PROVIDER_ERROR, "MCP tool returned an error.")
    if result.structuredContent is not None:
        return result.structuredContent
    if len(result.content) != 1 or result.content[0].type != "text":
        raise VVError(Code.SCHEMA_CHANGED, "Expected one JSON text block or structured content.")
    try:
        data = json.loads(result.content[0].text)
    except (ValueError, TypeError):
        raise VVError(Code.SCHEMA_CHANGED, "MCP response is not expected JSON.") from None
    if not isinstance(data, dict):
        raise VVError(Code.SCHEMA_CHANGED, "MCP response must be an object.")
    return data


def require_schema(actual: dict, reviewed: dict) -> None:
    if actual != reviewed:
        raise VVError(Code.SCHEMA_CHANGED, "MCP schema differs from the reviewed snapshot.")


async def discover_public() -> list[dict]:
    """Developer-only read-only discovery; no tool execution or authentication."""
    async with httpx.AsyncClient(timeout=20) as client:
        async with streamable_http_client(ENDPOINT, http_client=client) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                discovered = []
                cursor = None
                while True:
                    result = await session.list_tools(cursor=cursor)
                    discovered.extend(tool.model_dump(mode="json") for tool in result.tools)
                    cursor = result.nextCursor
                    if cursor is None:
                        return discovered


class MCPProvider:
    """Fail-closed adapters: no fabricated catalog data and no live tool calls."""

    def unavailable(self):
        raise VVError(
            Code.NOT_IMPLEMENTED,
            "TODO: live MCP discovery, reviewed schemas, OAuth and response normalization.",
        )

    def search(self, query: str, limit: int) -> dict:
        self.unavailable()

    def get(self, product_id: int) -> dict:
        self.unavailable()

    def analogs(self, product_id: int) -> dict:
        self.unavailable()

    def refresh(self, request: Request) -> dict:
        self.unavailable()

    def create_link(self, payload: CartPayload) -> str:
        self.unavailable()

import asyncio
import json
import logging
import os
import re
from datetime import timedelta
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

import httpx
from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult

from vv.errors import Code, VVError
from vv.models import CartPayload, ProductSnapshot, Request
from vv.normalize import normalize_product

ENDPOINT = "https://mcp.vkusvill.ru/mcp"
TOOLS = {
    "search": "vkusvill_products_search",
    "get": "vkusvill_product_details",
    "analogs": "vkusvill_product_analogs",
    "link": "vkusvill_cart_link_create",
    "barcode": "vkusvill_product_barcode",
    "discount": "vkusvill_products_discount",
    "recipes": "vkusvill_recipes",
    "shops": "vkusvill_shops",
    "orders": "vkusvill_orders_history",
    "favorite": "vkusvill_product_lp",
}


def configured_endpoint() -> str:
    value = os.environ.get("VV_MCP_TEST_URL")
    if value is None:
        return ENDPOINT
    parsed = urlsplit(value)
    if (
        os.environ.get("VV_TEST_MODE") != "1"
        or parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "::1")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/mcp"
        or parsed.query
        or parsed.fragment
    ):
        raise VVError(Code.INVALID_INPUT, "Test MCP requires explicit test mode and loopback /mcp.")
    return value


def transport_error(error: Exception, *, side_effect: bool = False) -> VVError:
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in (401, 403):
        return VVError(Code.AUTH_REQUIRED, "This operation requires trusted OAuth onboarding.")
    if side_effect:
        return VVError(Code.OUTCOME_UNKNOWN, "Link outcome is unknown; do not retry blindly.")
    if isinstance(error, (httpx.TransportError, TimeoutError)) or (
        isinstance(error, McpError) and error.error.code == httpx.codes.REQUEST_TIMEOUT
    ):
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


def provider_data(result: CallToolResult) -> dict:
    envelope = unpack_result(result)
    if envelope.get("ok") is False:
        error = envelope.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        code = code.upper() if isinstance(code, str) else None
        status = error.get("http_status") if isinstance(error, dict) else None
        if code in ("AUTH_REQUIRED", "UNAUTHORIZED") or status in (401, 403):
            raise VVError(Code.AUTH_REQUIRED, "Provider requires authentication.")
        if status == 404 or code == "NOT_FOUND":
            raise VVError(Code.NOT_FOUND, "Provider could not find the requested resource.")
        if code == "INVALID_INPUT":
            raise VVError(Code.INVALID_INPUT, "Provider rejected the supplied arguments.")
        raise VVError(Code.PROVIDER_ERROR, "Provider reported an unsuccessful result.")
    if envelope.get("ok") is not True or not isinstance(envelope.get("data"), dict):
        raise VVError(Code.SCHEMA_CHANGED, "Provider envelope changed.")
    return envelope["data"]


def structural_schema(value):
    if isinstance(value, dict):
        return {
            key: structural_schema(item)
            for key, item in value.items()
            if key not in ("description", "title")
        }
    if isinstance(value, list):
        return [structural_schema(item) for item in value]
    return value


def require_schema(actual: dict, reviewed: dict) -> None:
    if structural_schema(actual) != structural_schema(reviewed):
        raise VVError(Code.SCHEMA_CHANGED, "MCP schema differs from the reviewed snapshot.")


def valid_link(value) -> str:
    if not isinstance(value, str):
        raise VVError(Code.SCHEMA_CHANGED, "Provider did not return a cart link.")
    parsed = urlsplit(value)
    identifiers = parse_qs(parsed.query).get("share_basket", [])
    if (
        parsed.scheme != "https"
        or parsed.netloc not in ("vkusvill.ru", "www.vkusvill.ru")
        or parsed.path not in ("", "/")
        or parsed.fragment
        or len(identifiers) != 1
        or not identifiers[0].isdigit()
        or len(parse_qs(parsed.query)) != 1
    ):
        raise VVError(Code.SCHEMA_CHANGED, "Provider cart URL has an unexpected origin or format.")
    return value


def leaves(error: Exception) -> list[Exception]:
    if isinstance(error, ExceptionGroup):
        return [leaf for child in error.exceptions for leaf in leaves(child)]
    return [error]


async def discover_public() -> list[dict]:
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
    def __init__(self):
        self.endpoint = configured_endpoint()
        self.schemas = json.loads(files("vv").joinpath("schemas.json").read_text())
        for logger_name in ("mcp", "httpx", "httpcore"):
            logging.getLogger(logger_name).setLevel(logging.CRITICAL)

    async def _batch(self, calls: list[tuple[str, dict]]) -> list[dict]:
        sent_mutation = False
        try:
            async with asyncio.timeout(90):
                async with httpx.AsyncClient(timeout=30) as client:
                    async with streamable_http_client(self.endpoint, http_client=client) as streams:
                        async with ClientSession(
                            streams[0], streams[1], read_timeout_seconds=timedelta(seconds=30)
                        ) as session:
                            await session.initialize()
                            discovered = {}
                            cursor = None
                            cursors = set()
                            while True:
                                listed = await session.list_tools(cursor=cursor)
                                discovered.update(
                                    {tool.name: tool.inputSchema for tool in listed.tools}
                                )
                                cursor = listed.nextCursor
                                if cursor is None:
                                    break
                                if cursor in cursors or len(cursors) >= 100:
                                    raise VVError(Code.SCHEMA_CHANGED, "Invalid MCP pagination.")
                                cursors.add(cursor)
                            for name, _ in calls:
                                if name not in self.schemas or name not in discovered:
                                    raise VVError(
                                        Code.SCHEMA_CHANGED, "Required MCP tool is missing."
                                    )
                                require_schema(discovered[name], self.schemas[name])
                            results = []
                            for name, arguments in calls:
                                sent_mutation = name == TOOLS["link"]
                                result = await session.call_tool(name, arguments)
                                results.append(provider_data(result))
                            return results
        except Exception as error:
            nested = leaves(error)
            for leaf in nested:
                if isinstance(leaf, VVError):
                    if sent_mutation and leaf.code == Code.PROVIDER_ERROR:
                        raise VVError(
                            Code.OUTCOME_UNKNOWN, "Link outcome is unknown; do not retry blindly."
                        ) from None
                    raise leaf from None
            raise transport_error(nested[0], side_effect=sent_mutation) from None

    def batch(self, calls: list[tuple[str, dict]]) -> list[dict]:
        return asyncio.run(self._batch(calls))

    def health(self) -> dict:
        self.search("молоко", 1)
        return {"public_mcp": "ok", "auth": "not_configured", "catalog_scope": "public_unverified"}

    def read_tool(self, operation: str, arguments: dict, *, paginated: bool = False) -> dict:
        name = TOOLS[operation]
        schema = {**self.schemas[name], "additionalProperties": False}
        if not Draft202012Validator(schema).is_valid(arguments):
            raise VVError(Code.INVALID_INPUT, "Arguments do not match the reviewed tool schema.")
        data = self.batch([(name, arguments)])[0]
        if not isinstance(data, dict):
            raise VVError(Code.SCHEMA_CHANGED, "Expected a provider data object.")
        if paginated and (
            not isinstance(data.get("items"), list)
            or not all(isinstance(item, dict) for item in data["items"])
            or not isinstance(data.get("meta"), dict)
        ):
            raise VVError(Code.SCHEMA_CHANGED, "Expected provider items and pagination metadata.")
        return data

    def barcode(self, barcode: str) -> dict:
        if not isinstance(barcode, str) or re.fullmatch(r"[0-9]{13}", barcode) is None:
            raise VVError(Code.INVALID_INPUT, "Barcode must contain exactly 13 ASCII digits.")
        data = self.read_tool("barcode", {"barcode": barcode})
        return normalize_product(data).model_dump(mode="json")

    def discounts(
        self, page: int = 1, sort: str = "popularity", kind: str = "card", vvonly: int = 1
    ) -> dict:
        return self.read_tool(
            "discount", {"page": page, "sort": sort, "type": kind, "vvonly": vvonly}, paginated=True
        )

    def recipes(self, query: str = "", page: int = 1, sort: str = "popularity", **filters) -> dict:
        arguments = {
            "q": query,
            "page": page,
            "sort": sort,
            "id_feature_filter": 0,
            "id_cooking_time_filter": 0,
            "id_cooking_method_filter": 0,
            "id_complexity_filter": 0,
            "id_category_filter": 0,
            "id_exclude_allergens_filter": [],
            **filters,
        }
        return self.read_tool("recipes", arguments, paginated=True)

    def shops(self, page: int = 1, **filters) -> dict:
        return self.read_tool("shops", {"page": page, **filters}, paginated=True)

    def orders(self, page: int = 1) -> dict:
        return self.read_tool("orders", {"page": page}, paginated=True)

    def favorite(self) -> dict:
        return self.read_tool("favorite", {})

    def search(self, query: str, limit: int, page: int = 1) -> dict:
        if not 1 <= len(query) <= 255 or not 1 <= limit <= 10 or not 1 <= page <= 99999:
            raise VVError(
                Code.INVALID_INPUT, "Search needs 1–255 characters, limit 1–10 and valid page."
            )
        data = self.batch(
            [(TOOLS["search"], {"q": query, "limit": limit, "mode": "full", "page": page})]
        )[0]
        if not isinstance(data.get("items"), list) or not isinstance(data.get("meta"), dict):
            raise VVError(Code.SCHEMA_CHANGED, "Search response shape changed.")
        return {
            "items": [normalize_product(item).model_dump(mode="json") for item in data["items"]],
            "meta": data["meta"],
        }

    def get(self, product_id: int) -> dict:
        return self.products([product_id])[0].model_dump(mode="json")

    def products(self, identifiers: list[int]) -> list[ProductSnapshot]:
        data = self.batch([(TOOLS["get"], {"id": identifier}) for identifier in identifiers])
        snapshots = [normalize_product(item) for item in data]
        if [item.product_id for item in snapshots] != identifiers:
            raise VVError(Code.SCHEMA_CHANGED, "Provider returned an unexpected product id.")
        return snapshots

    def analogs(self, product_id: int) -> dict:
        data = self.batch([(TOOLS["analogs"], {"id": product_id})])[0]
        if data.get("product_id") != product_id or not isinstance(data.get("products"), list):
            raise VVError(Code.SCHEMA_CHANGED, "Analogs response shape changed.")
        return {
            "product_id": product_id,
            "items": [normalize_product(item).model_dump(mode="json") for item in data["products"]],
        }

    def refresh(self, request: Request) -> list[ProductSnapshot]:
        return self.products([item.product_id for item in request.items])

    def create_link(self, payload: CartPayload) -> str:
        arguments = {
            "products": [{"xml_id": item.xml_id, "q": float(item.q)} for item in payload.products]
        }
        data = self.batch([(TOOLS["link"], arguments)])[0]
        return valid_link(data.get("link"))

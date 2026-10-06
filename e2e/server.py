"""Real Streamable HTTP protocol, explicitly synthetic catalog and links."""

import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path

import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import CallToolResult, ListToolsRequest, ListToolsResult, TextContent, Tool
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route


def create_app(control: Path, journal: Path):
    server = Server("synthetic-vkusvill-e2e")
    schemas = json.loads(files("vv").joinpath("schemas.json").read_text())
    details_count = 0

    def settings():
        return json.loads(control.read_text())

    @server.list_tools()
    async def list_tools(request: ListToolsRequest):
        configured = settings()
        tools = []
        for name, schema in schemas.items():
            if name == configured.get("missing_tool"):
                continue
            schema = dict(schema)
            if configured.get("schema_changed"):
                schema["additionalProperties"] = True
            tools.append(Tool(name=name, inputSchema=schema))
        if configured.get("pagination"):
            offset = int(request.params.cursor) if request.params and request.params.cursor else 0
            return ListToolsResult(
                tools=tools[offset : offset + 1],
                nextCursor=(
                    "1"
                    if configured.get("cursor_loop")
                    else str(offset + 1)
                    if offset + 1 < len(tools)
                    else None
                ),
            )
        return ListToolsResult(tools=tools)

    @server.call_tool()
    async def call_tool(name, arguments):
        nonlocal details_count
        configured = settings()
        with journal.open("a") as destination:
            destination.write(json.dumps({"name": name, "arguments": arguments}) + "\n")
        if configured.get("malformed_result"):
            return [TextContent(type="text", text="not JSON: SECRET_SENTINEL")]
        if name == "vkusvill_cart_link_create" and configured.get("tool_error_after_mutation"):
            return CallToolResult(
                isError=True, content=[TextContent(type="text", text="SECRET_SENTINEL")]
            )
        if configured.get("auth_required"):
            envelope = {"ok": False, "error": {"code": "AUTH_REQUIRED"}}
        else:
            product = {
                "id": 101,
                "xml_id": 901,
                "name": "SYNTHETIC TEST milk",
                "description": configured.get("description", "Not a real catalog product"),
                "unit": "шт",
                "price": {"current": configured.get("price", 100), "currency": "RUB"},
                "properties": [],
            }
            if name in ("vkusvill_products_search", "vkusvill_products_discount"):
                data = {"items": [product], "meta": {"total": 1}}
            elif name == "vkusvill_product_barcode":
                data = product
            elif name == "vkusvill_product_lp":
                data = {"product": product}
            elif name in ("vkusvill_shops", "vkusvill_recipes", "vkusvill_orders_history"):
                data = {
                    "items": [{"id": 1, "name": "SYNTHETIC TEST record"}],
                    "meta": {"page": arguments.get("page", 1), "filters": []},
                }
            elif name == "vkusvill_product_details":
                details_count += 1
                if configured.get("price_after_first_detail") and details_count > 1:
                    product["price"]["current"] = configured["price_after_first_detail"]
                data = product
            elif name == "vkusvill_product_analogs":
                data = {"product_id": 101, "products": [product]}
            elif name == "vkusvill_cart_link_create":
                data = {"link": "https://vkusvill.ru/?share_basket=0000000000"}
                if configured.get("uncertain_link"):
                    data = {"link": "invalid synthetic response after mutation"}
            else:
                raise ValueError("Unexpected tool")
            envelope = {"ok": True, "data": data}
        return [TextContent(type="text", text=json.dumps(envelope))]

    manager = StreamableHTTPSessionManager(server, json_response=True, stateless=True)

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    async def health(request):
        return JSONResponse({"synthetic": True})

    class MCPRoute:
        async def __call__(self, scope, receive, send):
            configured = settings()
            if configured.get("http_status"):
                await JSONResponse(
                    {"error": "SECRET_SENTINEL"}, status_code=configured["http_status"]
                )(scope, receive, send)
                return
            chunks = []
            while True:
                message = await receive()
                chunks.append(message.get("body", b""))
                if not message.get("more_body"):
                    break
            body = b"".join(chunks)
            try:
                payload = json.loads(body)
            except ValueError:
                payload = {}
            mutation = payload.get("params", {}).get("name") == "vkusvill_cart_link_create"
            if mutation and configured.get("drop_after_mutation"):
                with journal.open("a") as destination:
                    destination.write(
                        json.dumps(
                            {
                                "name": "vkusvill_cart_link_create",
                                "arguments": payload["params"]["arguments"],
                            }
                        )
                        + "\n"
                    )
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", b"1000"),
                        ],
                    }
                )
                raise ConnectionResetError("Synthetic disconnect after accepted mutation")
            if configured.get("delay_seconds"):
                await asyncio.sleep(configured["delay_seconds"])
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await manager.handle_request(scope, replay, send)

    return Starlette(
        routes=[Route("/health", health), Route("/mcp", MCPRoute())],
        lifespan=lifespan,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args()
    uvicorn.run(
        create_app(args.control, args.journal), host="127.0.0.1", port=args.port, log_level="error"
    )


if __name__ == "__main__":
    main()

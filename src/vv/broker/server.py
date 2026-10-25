import argparse
import asyncio
import json
import logging
import secrets
import time
from collections import deque
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from vv.auth import private_read
from vv.broker.service import Broker, Settings
from vv.errors import Code, VVError

COOKIE = "__Host-vv-session"


class Admission:
    def __init__(self):
        self.events = {
            name: deque() for name in ("session", "callback", "browser", "bridge", "page")
        }
        self.limits = {"session": 12, "callback": 20, "browser": 60, "bridge": 120, "page": 120}
        self.active = 0

    def accept(self, path):
        group = (
            "session"
            if path == "/api/session"
            else "callback"
            if path == "/oauth/callback"
            else "bridge"
            if path.startswith("/bridge/")
            else "browser"
            if path.startswith("/api/")
            else "page"
        )
        events = self.events[group]
        now = time.monotonic()
        while events and events[0] <= now - 60:
            events.popleft()
        if len(events) >= self.limits[group] or self.active >= 8:
            raise VVError(Code.RATE_LIMITED, "Service busy; wait before retrying.", retryable=True)
        events.append(now)


def envelope(data=None, error=None):
    return {
        "schema_version": 1,
        "ok": error is None,
        "data": data if error is None else None,
        "error": {"code": error.code.value, "message": error.message, "retryable": error.retryable}
        if error
        else None,
        "warnings": [],
        "meta": {},
    }


class Boundary(BaseHTTPMiddleware):
    def __init__(self, app, origin, admission):
        super().__init__(app)
        self.origin = origin
        self.admission = admission

    async def dispatch(self, request, call_next):
        try:
            expected_host = urlsplit(self.origin).netloc
            allowed = {expected_host}
            if request.url.path.startswith("/bridge/") or request.url.path in ("/health", "/ready"):
                allowed.update(("vv-auth:8080", "127.0.0.1:8080"))
            if len(request.headers.getlist("host")) != 1 or request.headers["host"] not in allowed:
                raise VVError(Code.INVALID_INPUT, "Invalid request host.")
            if len(request.scope.get("query_string", b"")) > 8192:
                raise VVError(Code.INVALID_INPUT, "Request too large.")
            if request.url.path not in ("/health", "/ready"):
                self.admission.accept(request.url.path)
            if request.method == "POST" and not request.url.path.startswith("/bridge/"):
                if request.headers.get("origin") != self.origin:
                    raise VVError(Code.AUTH_REQUIRED, "Invalid request origin.")
            self.admission.active += 1
            try:
                response = await call_next(request)
            finally:
                self.admission.active -= 1
        except VVError as error:
            status = (
                429
                if error.code == Code.RATE_LIMITED
                else 401
                if error.code == Code.AUTH_REQUIRED
                else 400
            )
            response = JSONResponse(envelope(error=error), status_code=status)
        except (ValueError, ValidationError, TypeError, KeyError):
            response = JSONResponse(
                envelope(
                    error=VVError(Code.INVALID_INPUT, "Invalid request; input details suppressed.")
                ),
                status_code=400,
            )
        except Exception:
            response = JSONResponse(
                envelope(
                    error=VVError(Code.INTERNAL_ERROR, "Service unavailable; details suppressed.")
                ),
                status_code=503,
            )
        bootstrap = request.url.path == "/"
        if request.url.path == "/oauth/callback" and response.status_code != 303:
            response = RedirectResponse("/oauth/problem", status_code=303)
        scripts = "'self' https://telegram.org" if bootstrap else "'self'"
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": (
                    f"default-src 'none'; script-src {scripts}; connect-src 'self'; "
                    "style-src 'self'; base-uri 'none'; form-action 'none'; "
                    "frame-ancestors 'self' https://web.telegram.org"
                ),
                "Strict-Transport-Security": "max-age=31536000",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "X-Request-ID": secrets.token_hex(12),
            }
        )
        if response.status_code == 429:
            response.headers["Retry-After"] = "60"
        return response


async def json_body(request):
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise VVError(Code.INVALID_INPUT, "JSON required.")
    body = bytearray()
    async with asyncio.timeout(5):
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 32768:
                raise VVError(Code.INVALID_INPUT, "Request too large.")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise VVError(Code.INVALID_INPUT, "Expected an object.")
    return value


def create_app(broker: Broker):
    async def page(request):
        name = "bootstrap.html" if request.url.path == "/" else "connect.html"
        if name == "connect.html":
            try:
                await run_in_threadpool(broker.browser_status, request.cookies.get(COOKIE))
            except VVError as error:
                if error.code != Code.AUTH_REQUIRED:
                    raise
                return HTMLResponse(
                    files("vv.broker").joinpath("static", "expired.html").read_text(),
                    status_code=401,
                )
        return HTMLResponse(files("vv.broker").joinpath("static", name).read_text())

    async def asset(request):
        name = request.path_params["name"]
        if name not in ("bootstrap.js", "connect.js", "style.css"):
            return Response(status_code=404)
        media = "text/css" if name.endswith(".css") else "text/javascript"
        return Response(files("vv.broker").joinpath("static", name).read_text(), media_type=media)

    async def problem(request):
        return HTMLResponse(files("vv.broker").joinpath("static", "problem.html").read_text())

    async def authenticate(request):
        body = await json_body(request)
        if set(body) != {"init_data"} or not isinstance(body["init_data"], str):
            raise VVError(Code.INVALID_INPUT, "Telegram authentication required.")
        session = await run_in_threadpool(broker.authenticate, body["init_data"])
        response = JSONResponse(envelope({"next": "/connect"}))
        response.set_cookie(
            COOKIE, session, secure=True, httponly=True, samesite="lax", max_age=600, path="/"
        )
        return response

    async def status(request):
        return JSONResponse(
            envelope(await run_in_threadpool(broker.browser_status, request.cookies.get(COOKIE)))
        )

    async def begin(request):
        body = await json_body(request)
        if "redirect_uri" in body:
            raise VVError(Code.INVALID_INPUT, "Callback cannot be overridden.")
        url = await run_in_threadpool(broker.begin, request.cookies.get(COOKIE), body)
        return JSONResponse(envelope({"authorize_url": url}))

    async def callback(request):
        await run_in_threadpool(
            broker.callback, request.cookies.get(COOKIE), list(request.query_params.multi_items())
        )
        return RedirectResponse("/connect", status_code=303)

    async def disconnect(request):
        if await json_body(request) != {}:
            raise VVError(Code.INVALID_INPUT, "Unexpected disconnect parameters.")
        return JSONResponse(
            envelope(await run_in_threadpool(broker.disconnect, request.cookies.get(COOKIE)))
        )

    async def bridge(request):
        broker.bridge_auth(request.headers.get("authorization", ""))
        if request.method == "GET":
            result = await run_in_threadpool(broker.bridge_status)
        else:
            body = await json_body(request)
            if set(body) != {"calls", "context", "confirmed"}:
                raise VVError(Code.INVALID_INPUT, "Unexpected bridge parameters.")
            result = await run_in_threadpool(
                broker.call, body["calls"], body["context"], body["confirmed"]
            )
        return JSONResponse(envelope(result))

    async def connect_button(request):
        broker.bridge_auth(request.headers.get("authorization", ""))
        if await json_body(request) != {}:
            raise VVError(Code.INVALID_INPUT, "Button recipient and URL cannot be overridden.")
        return JSONResponse(envelope(await run_in_threadpool(broker.send_connect_button)))

    async def health(request):
        return JSONResponse({"ok": True})

    async def ready(request):
        return JSONResponse(await run_in_threadpool(broker.ready))

    app = Starlette(
        routes=[
            Route("/", page),
            Route("/connect", page),
            Route("/assets/{name}", asset),
            Route("/api/session", authenticate, methods=["POST"]),
            Route("/api/status", status),
            Route("/api/connect", begin, methods=["POST"]),
            Route("/api/disconnect", disconnect, methods=["POST"]),
            Route("/oauth/callback", callback),
            Route("/oauth/problem", problem),
            Route("/bridge/status", bridge),
            Route("/bridge/connect", connect_button, methods=["POST"]),
            Route("/bridge/call", bridge, methods=["POST"]),
            Route("/health", health),
            Route("/ready", ready),
        ]
    )
    app.state.admission = Admission()
    app.add_middleware(
        Boundary, origin=broker.settings.public_origin, admission=app.state.admission
    )
    return app


def main():
    parser = argparse.ArgumentParser(description="Single-owner isolated VkusVill auth service")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--send-connect-button",
        action="store_true",
        help="Send an owner-only connection button without replacing the command menu",
    )
    parser.add_argument(
        "--set-menu",
        action="store_true",
        help="Set the Mini App menu only for the configured owner's private chat",
    )
    args = parser.parse_args()
    for name in ("httpx", "httpcore", "mcp", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    try:
        broker = Broker(Settings.model_validate(private_read(args.config)))
    except Exception:
        parser.exit(1, "Invalid private broker configuration; details suppressed.\n")
    if args.set_menu or args.send_connect_button:
        try:
            from vv.broker.menu import configure

            configure(args.config, "send" if args.send_connect_button else "enable")
        except Exception:
            parser.exit(1, "Could not configure owner menu; details suppressed.\n")
        print("Owner Mini App entry configured; no polling or webhook changes.")
        return
    import uvicorn

    uvicorn.run(
        create_app(broker),
        host=args.host,
        port=args.port,
        access_log=False,
        log_level="critical",
        proxy_headers=False,
        server_header=False,
        limit_concurrency=32,
        backlog=32,
        timeout_keep_alive=5,
    )


if __name__ == "__main__":
    main()

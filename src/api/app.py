import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
import json
from fastapi.staticfiles import StaticFiles
from mangum import Mangum
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.routers import account, admin, chat, embeddings, messages, model, responses
from api.safe_errors import client_safe_detail, scrub_log_error
from api.setting import (
    ADMIN_IP_ALLOWLIST,
    ADMIN_ROUTE_PREFIX,
    ADMIN_UI_SLUG,
    API_ROUTE_PREFIX,
    DEBUG,
    DESCRIPTION,
    DISABLE_OPENAPI,
    SUMMARY,
    TITLE,
    VERSION,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
STATIC_DIR = WEB_DIR / "static"

config = {
    "title": TITLE,
    "description": DESCRIPTION,
    "summary": SUMMARY,
    "version": VERSION,
}
if DISABLE_OPENAPI and not DEBUG:
    config.update({"docs_url": None, "redoc_url": None, "openapi_url": None})

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
app = FastAPI(**config)

allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*")
origins_list = [origin.strip() for origin in allowed_origins.split(",")] if allowed_origins != "*" else ["*"]

# Warn if CORS allows all origins
if origins_list == ["*"]:
    logging.warning("CORS is configured to allow all origins (*). Set ALLOWED_ORIGINS environment variable to restrict access.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins_list,  # nosec - configurable via ALLOWED_ORIGINS env var
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def _client_ip_from_scope(scope: Scope) -> str:
    headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
    if headers.get("cf-connecting-ip"):
        return headers["cf-connecting-ip"].strip()
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    client = scope.get("client")
    return client[0] if client else ""


def _should_log_request(path: str, method: str, status_code: int) -> bool:
    if method == "OPTIONS":
        return False
    if path in ("/health", "/favicon.ico"):
        return False
    if path.startswith("/static/"):
        return False
    if path.rstrip("/").endswith("/request-logs") or "/request-logs/" in path:
        return False
    if (
        path.startswith(API_ROUTE_PREFIX)
        or path.startswith(ADMIN_ROUTE_PREFIX)
        or path.startswith("/v1/")
        or path == "/v1"
    ):
        return True
    return status_code >= 400


class AdminIpAllowlistMiddleware:
    """If ADMIN_IP_ALLOWLIST is set, only listed IPs may hit /admin APIs (stealth 404)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if not ADMIN_IP_ALLOWLIST:
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or "/"
        if not path.startswith(ADMIN_ROUTE_PREFIX):
            await self.app(scope, receive, send)
            return
        client_ip = _client_ip_from_scope(scope)
        if _ip_allowlisted(client_ip):
            await self.app(scope, receive, send)
            return
        body = b'{"detail":"Not found"}'
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _ip_allowlisted(ip: str) -> bool:
    if not ip or not ADMIN_IP_ALLOWLIST:
        return not ADMIN_IP_ALLOWLIST
    for rule in ADMIN_IP_ALLOWLIST:
        if rule.endswith("*"):
            if ip.startswith(rule[:-1]):
                return True
        elif ip == rule:
            return True
    return False


class IpBanMiddleware:
    """Reject banned client IPs before routing / logging (stops admin spam)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or "/"
        if path in ("/health", "/favicon.ico") or path.startswith("/static/"):
            await self.app(scope, receive, send)
            return

        from api.security import is_ip_banned

        client_ip = _client_ip_from_scope(scope)
        if client_ip and is_ip_banned(client_ip):
            body = b'{"detail":"IP banned"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Pure ASGI — avoids BaseHTTPMiddleware buffering/streaming deadlocks."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or "/"

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                extras = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                ]
                if path.startswith(API_ROUTE_PREFIX) or path.startswith(ADMIN_ROUTE_PREFIX):
                    extras.append((b"cache-control", b"no-store"))
                existing = {k.lower() for k, _ in headers}
                for key, value in extras:
                    if key not in existing:
                        headers.append((key, value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RequestLoggingMiddleware:
    """Queue access logs without buffering response bodies (safe for SSE streams)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or "/"
        method = (scope.get("method") or "GET").upper()
        started = time.perf_counter()
        status_code = 500
        error = ""
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        user_agent = (headers.get("user-agent") or "")[:256]
        client_ip = _client_ip_from_scope(scope)

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status") or 200)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:  # noqa: BLE001
            error = scrub_log_error(str(exc), max_len=200)
            raise
        finally:
            if _should_log_request(path, method, status_code):
                latency_ms = int((time.perf_counter() - started) * 1000)
                if status_code >= 400 and not error:
                    error = f"HTTP {status_code}"
                from api.db import enqueue_request_log

                enqueue_request_log(
                    method=method,
                    path=path[:512],
                    status_code=status_code,
                    client_ip=client_ip,
                    latency_ms=latency_ms,
                    error=scrub_log_error(error),
                    user_agent=user_agent,
                )


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(AdminIpAllowlistMiddleware)
# Outermost: drop banned IPs before access logging floods Check Log.
app.add_middleware(IpBanMiddleware)


@app.on_event("startup")
async def _startup_tune() -> None:
    """Widen default executor so Bedrock + DB threads do not starve UI routes."""
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=64, thread_name_prefix="bag"))
    try:
        from api.db import auth_db
        from api.security import refresh_banned_ips_cache

        from api.setting import ADMIN_REVOKE_SESSIONS_ON_STARTUP

        if ADMIN_REVOKE_SESSIONS_ON_STARTUP:
            n = await asyncio.to_thread(auth_db.revoke_all_admin_sessions)
            if n:
                logging.info("Revoked %s admin session(s) on startup", n)
        banned = await asyncio.to_thread(refresh_banned_ips_cache)
        if banned:
            logging.info("Loaded %s banned IP(s)", len(banned))
        migrated = await asyncio.to_thread(auth_db.migrate_legacy_allowlists_to_tiers)
        if migrated.get("keys") or migrated.get("cdks"):
            logging.info(
                "Migrated allowlists to tiers: %s key(s), %s CDK(s)",
                migrated.get("keys", 0),
                migrated.get("cdks", 0),
            )
    except Exception as exc:  # noqa: BLE001 — never block boot on session maintenance
        logging.warning("Admin startup maintenance failed: %s", exc)

    # Prefetch model list in background — never block accepting traffic.
    try:
        from api.models.bedrock import _schedule_model_list_refresh

        _schedule_model_list_refresh()
    except Exception as exc:  # noqa: BLE001
        logging.warning("Could not schedule model list refresh: %s", exc)


app.include_router(model.router, prefix=API_ROUTE_PREFIX)
app.include_router(chat.router, prefix=API_ROUTE_PREFIX)
app.include_router(embeddings.router, prefix=API_ROUTE_PREFIX)
app.include_router(account.router, prefix=API_ROUTE_PREFIX)
# OpenAI Responses API shim (Sub2API OpenAI API-key accounts default to /responses).
app.include_router(responses.router, prefix=API_ROUTE_PREFIX)
# Anthropic Messages API shim (Claude Code / Anthropic SDK → /v1/messages).
app.include_router(messages.router, prefix=API_ROUTE_PREFIX)
# Extra OpenAI / Anthropic aliases at /v1 for clients that do not use /api/v1.
app.include_router(model.router, prefix="/v1")
app.include_router(chat.router, prefix="/v1")
app.include_router(responses.router, prefix="/v1")
app.include_router(messages.router, prefix="/v1")
app.include_router(admin.router, prefix=ADMIN_ROUTE_PREFIX)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
async def health():
    """For health check if needed"""
    return {"status": "OK"}


def _index_html() -> HTMLResponse | PlainTextResponse:
    index = WEB_DIR / "index.html"
    if not index.is_file():
        return PlainTextResponse("Web UI not found", status_code=404)
    html = index.read_text(encoding="utf-8")
    cfg = json.dumps({"adminUiSlug": ADMIN_UI_SLUG}, separators=(",", ":"))
    inject = f"<script>window.__MRDEV_CFG__={cfg};</script>"
    if "<!--MRDEV_CFG-->" in html:
        html = html.replace("<!--MRDEV_CFG-->", inject, 1)
    else:
        html = html.replace("</head>", inject + "\n</head>", 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/")
async def web_index():
    return _index_html()


@app.get("/docs")
@app.get("/v/docs")
@app.get("/user")
@app.get("/chat")
@app.get("/usage")
@app.get("/admin")
@app.get("/admin/login")
async def spa_pretty_paths():
    """Pretty paths that redirect into the hash router via index bootstrap."""
    return _index_html()


# Secret admin SPA entry (path alone does not grant access — still needs login).
@app.get(f"/{ADMIN_UI_SLUG}")
@app.get(f"/{ADMIN_UI_SLUG}/{{rest:path}}")
async def spa_admin_secret_path(rest: str = ""):
    return _index_html()


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Never forward provider/raw upstream text in JSON error bodies."""
    status = int(exc.status_code or 500)
    detail = client_safe_detail(exc.detail, status=status)
    return JSONResponse(status_code=status, content={"detail": detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.getLogger(__name__).error(
        "Unhandled error on %s %s: %s", request.method, request.url.path, exc
    )
    return JSONResponse(
        status_code=500,
        content={"detail": client_safe_detail(None, status=500)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger = logging.getLogger(__name__)

    # Log essential info only - avoid sensitive data and performance overhead
    logger.warning(
        "Request validation failed: %s %s - %s",
        request.method,
        request.url.path,
        str(exc).split("\n")[0][:200],  # First line only
    )

    return JSONResponse(
        status_code=400,
        content={"detail": "Invalid request"},
    )


handler = Mangum(app)

if __name__ == "__main__":
    # Local public proxy: bind localhost only. Containers/cloud may override via CMD.
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app:app", host=host, port=port, reload=False)

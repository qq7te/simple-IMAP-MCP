from __future__ import annotations

import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

from .config import ImapConfig
from .imap import (
    envelope_to_dict,
    extract_bodies,
    imap_connect,
    list_attachments,
    parse_rfc822,
    parse_yyyy_mm_dd,
)

load_dotenv()  # loads .env if present; no-op otherwise

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Enable uvicorn access logging
uvicorn_logger = logging.getLogger("uvicorn.access")
uvicorn_logger.setLevel(logging.DEBUG)
uvicorn_error_logger = logging.getLogger("uvicorn.error")
uvicorn_error_logger.setLevel(logging.DEBUG)


def _getenv_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


# Transport defaults are chosen for "standalone server on another machine" usage.
# If you want the old local stdio behavior, run with MCP_TRANSPORT=stdio.
_MCP_HOST = (os.getenv("MCP_HOST") or "127.0.0.1").strip()
_MCP_PORT = _getenv_int("MCP_PORT", 8993)

logger.info(f"Initializing FastMCP server with host={_MCP_HOST}, port={_MCP_PORT}")

# Disable DNS rebinding protection for non-localhost addresses
# For production, you should configure proper allowed_hosts/origins
from mcp.server.transport_security import TransportSecuritySettings
transport_security = None
if _MCP_HOST not in ("127.0.0.1", "localhost", "::1"):
    logger.info(f"Disabling DNS rebinding protection for non-localhost address {_MCP_HOST}")
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

# Enable stateless mode for streamable-http to avoid session ID issues
mcp = FastMCP(
    "IMAP Email",
    host=_MCP_HOST,
    port=_MCP_PORT,
    transport_security=transport_security,
    stateless_http=True  # This makes each request independent
)
logger.info("FastMCP server initialized successfully")


# Add a health check endpoint
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: StarletteRequest) -> StarletteResponse:
    from starlette.responses import JSONResponse
    logger.info("Health check endpoint called")
    return JSONResponse({"status": "ok", "server": "IMAP Email"})


# Add logging middleware
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        logger.info(f"Incoming request: {request.method} {request.url.path}")
        logger.debug(f"Headers: {dict(request.headers)}")
        logger.debug(f"Query params: {dict(request.query_params)}")
        
        response = await call_next(request)
        
        logger.info(f"Response status: {response.status_code}")
        return response

_CONFIG: Optional[ImapConfig] = None


def get_config() -> ImapConfig:
    global _CONFIG
    if _CONFIG is None:
        logger.debug("Loading IMAP configuration from environment")
        _CONFIG = ImapConfig.from_env()
        logger.info(f"IMAP configuration loaded: host={_CONFIG.host}, port={_CONFIG.port}, username={_CONFIG.username}")
    return _CONFIG


def _normalize_fetch_item(item: dict[str, Any], key: str) -> Any:
    # IMAPClient sometimes returns byte keys depending on server; handle both.
    if key in item:
        return item[key]
    bkey = key.encode("ascii")
    return item.get(bkey)


@mcp.tool()
def list_mailboxes() -> list[dict[str, Any]]:
    """List available mailboxes/folders."""
    logger.info("list_mailboxes tool called")
    cfg = get_config()
    logger.debug(f"Connecting to IMAP server at {cfg.host}:{cfg.port}")
    with imap_connect(cfg) as client:
        logger.debug("Successfully connected to IMAP server")
        folders = client.list_folders()
        logger.debug(f"Retrieved {len(folders)} folders")

    out: list[dict[str, Any]] = []
    for flags, delimiter, name in folders:
        out.append(
            {
                "name": name,
                "delimiter": delimiter,
                "flags": [f.decode() if isinstance(f, (bytes, bytearray)) else str(f) for f in flags],
            }
        )
    logger.info(f"Returning {len(out)} mailboxes")
    return out


@mcp.tool()
def search_messages(
    mailbox: str = "INBOX",
    from_: str | None = None,
    to: str | None = None,
    subject: str | None = None,
    text: str | None = None,
    unseen: bool | None = None,
    since: str | None = None,
    before: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search messages and return a summary list (UID, subject, from, date, flags, size)."""
    cfg = get_config()

    criteria: list[Any] = []
    if from_:
        criteria += ["FROM", from_]
    if to:
        criteria += ["TO", to]
    if subject:
        criteria += ["SUBJECT", subject]
    if text:
        criteria += ["TEXT", text]
    if unseen is True:
        criteria.append("UNSEEN")
    elif unseen is False:
        criteria.append("SEEN")
    if since:
        criteria += ["SINCE", parse_yyyy_mm_dd(since)]
    if before:
        criteria += ["BEFORE", parse_yyyy_mm_dd(before)]
    if not criteria:
        criteria = ["ALL"]

    with imap_connect(cfg) as client:
        client.select_folder(mailbox, readonly=True)
        uids = client.search(criteria)

        if not uids:
            return []

        # Search results are typically ascending; pick most recent by taking the last N.
        if limit and limit > 0:
            uids = uids[-limit:]

        fetched = client.fetch(uids, ["ENVELOPE", "FLAGS", "RFC822.SIZE", "INTERNALDATE"])

    out: list[dict[str, Any]] = []
    for uid in uids:
        item = fetched.get(uid, {})
        env = _normalize_fetch_item(item, "ENVELOPE")
        flags = _normalize_fetch_item(item, "FLAGS") or []
        size = _normalize_fetch_item(item, "RFC822.SIZE")
        internaldate = _normalize_fetch_item(item, "INTERNALDATE")

        out.append(
            {
                "uid": int(uid),
                "mailbox": mailbox,
                "envelope": envelope_to_dict(env),
                "flags": [
                    f.decode() if isinstance(f, (bytes, bytearray)) else str(f)
                    for f in (flags or [])
                ],
                "size_bytes": int(size) if size is not None else None,
                "internaldate": internaldate.isoformat() if hasattr(internaldate, "isoformat") else None,
            }
        )

    return out


@mcp.tool()
def get_message(
    uid: int,
    mailbox: str = "INBOX",
    include_body: bool = True,
    include_html: bool = False,
    max_body_chars: int = 20000,
) -> dict[str, Any]:
    """Fetch a message by UID. Returns headers and (optionally) the body."""
    cfg = get_config()

    with imap_connect(cfg) as client:
        client.select_folder(mailbox, readonly=True)
        fetched = client.fetch([uid], ["RFC822", "FLAGS", "RFC822.SIZE", "INTERNALDATE"])

    item = fetched.get(uid)
    if not item:
        raise ValueError(f"No message found for UID {uid} in {mailbox}")

    raw_msg = _normalize_fetch_item(item, "RFC822")
    if not isinstance(raw_msg, (bytes, bytearray)):
        raise ValueError("Server did not return RFC822 bytes for message")

    msg = parse_rfc822(bytes(raw_msg))

    headers = {
        "subject": str(msg.get("subject", "")),
        "from": str(msg.get("from", "")),
        "to": str(msg.get("to", "")),
        "cc": str(msg.get("cc", "")),
        "date": str(msg.get("date", "")),
        "message_id": str(msg.get("message-id", "")),
    }

    flags = _normalize_fetch_item(item, "FLAGS") or []
    size = _normalize_fetch_item(item, "RFC822.SIZE")
    internaldate = _normalize_fetch_item(item, "INTERNALDATE")

    body: dict[str, str] = {"text": "", "html": ""}
    if include_body:
        body = extract_bodies(msg, max_chars=max_body_chars)

    result: dict[str, Any] = {
        "uid": int(uid),
        "mailbox": mailbox,
        "headers": headers,
        "flags": [
            f.decode() if isinstance(f, (bytes, bytearray)) else str(f)
            for f in (flags or [])
        ],
        "size_bytes": int(size) if size is not None else None,
        "internaldate": internaldate.isoformat() if hasattr(internaldate, "isoformat") else None,
        "attachments": list_attachments(msg),
    }

    if include_body:
        result["text"] = body.get("text", "")
        if include_html:
            result["html"] = body.get("html", "")

    return result


@mcp.tool()
def set_seen(uid: int, mailbox: str = "INBOX", seen: bool = True) -> dict[str, Any]:
    """Mark a message as seen/unseen."""
    cfg = get_config()

    with imap_connect(cfg) as client:
        client.select_folder(mailbox, readonly=False)
        if seen:
            client.add_flags([uid], ["\\Seen"])
        else:
            client.remove_flags([uid], ["\\Seen"])
        fetched = client.fetch([uid], ["FLAGS"])

    item = fetched.get(uid, {})
    flags = _normalize_fetch_item(item, "FLAGS") or []

    return {
        "uid": int(uid),
        "mailbox": mailbox,
        "flags": [
            f.decode() if isinstance(f, (bytes, bytearray)) else str(f)
            for f in (flags or [])
        ],
    }


def main() -> None:
    logger.info("Starting MCP IMAP server...")
    
    # Patch the streamable HTTP app to add detailed logging
    if (os.getenv("MCP_TRANSPORT") or "streamable-http").strip().lower() in ("streamable-http", "streamable_http"):
        original_streamable_http_app = mcp.streamable_http_app
        
        def logged_streamable_http_app():
            app = original_streamable_http_app()
            
            # Wrap the ASGI app to log requests
            original_call = app.__call__
            
            async def logged_call(scope, receive, send):
                if scope["type"] == "http":
                    logger.info(f"ASGI HTTP request: {scope['method']} {scope['path']}")
                    logger.debug(f"ASGI scope: {scope}")
                    
                    # Read and log the body
                    body_parts = []
                    async def logged_receive():
                        message = await receive()
                        if message["type"] == "http.request":
                            body = message.get("body", b"")
                            if body:
                                body_parts.append(body)
                                try:
                                    logger.debug(f"Request body: {body.decode('utf-8')[:500]}")
                                except:
                                    logger.debug(f"Request body (binary): {len(body)} bytes")
                        return message
                    
                    return await original_call(scope, logged_receive, send)
                return await original_call(scope, receive, send)
            
            app.__call__ = logged_call
            return app
        
        mcp.streamable_http_app = logged_streamable_http_app
    
    transport = (os.getenv("MCP_TRANSPORT") or "streamable-http").strip().lower()
    if transport == "streamable_http":
        transport = "streamable-http"
    
    logger.info(f"Using transport: {transport}")

    if transport not in {"stdio", "sse", "streamable-http"}:
        raise ValueError(
            "MCP_TRANSPORT must be one of: stdio, sse, streamable-http (got %r)" % transport
        )

    # mount_path is only relevant for the SSE transport; safe to pass None otherwise.
    mount_path = (os.getenv("MCP_MOUNT_PATH") or "").strip() or None
    logger.info(f"Mount path: {mount_path}")
    logger.info(f"Server will listen on {_MCP_HOST}:{_MCP_PORT}")
    
    logger.info("Calling mcp.run()...")
    mcp.run(transport=transport, mount_path=mount_path)
    logger.info("mcp.run() returned")

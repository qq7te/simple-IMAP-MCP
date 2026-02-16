from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime
from email import policy
from email.header import decode_header
from email.message import Message
from email.parser import BytesParser
from typing import Any, Iterator

from imapclient import IMAPClient

from .config import ImapConfig

logger = logging.getLogger(__name__)


@contextmanager
def imap_connect(config: ImapConfig) -> Iterator[IMAPClient]:
    # IMAPClient uses socket default timeout unless passed; this sets a per-connection timeout.
    logger.debug(f"Creating IMAPClient connection to {config.host}:{config.port} (ssl={config.ssl})")
    try:
        client = IMAPClient(
            config.host,
            port=config.port,
            ssl=config.ssl,
            timeout=config.timeout_seconds,
            use_uid=True,
        )
        logger.debug("IMAPClient instance created")
    except Exception as e:
        logger.error(f"Failed to create IMAPClient: {e}", exc_info=True)
        raise
    
    try:
        if (not config.ssl) and config.starttls:
            logger.debug("Starting TLS...")
            client.starttls()
            logger.debug("TLS started successfully")
        
        logger.debug(f"Logging in as {config.username}...")
        client.login(config.username, config.password)
        logger.info(f"Successfully logged in to IMAP server as {config.username}")
        
        yield client
    except Exception as e:
        logger.error(f"Error during IMAP operation: {e}", exc_info=True)
        raise
    finally:
        try:
            logger.debug("Logging out from IMAP server...")
            client.logout()
            logger.debug("Logged out successfully")
        except Exception as e:
            logger.warning(f"Error during logout: {e}")


def parse_yyyy_mm_dd(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _decode_mime_words(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        # Could be raw encoded-word bytes
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:
            value = repr(value)

    parts: list[str] = []
    for chunk, encoding in decode_header(value):
        if isinstance(chunk, bytes):
            enc = encoding or "utf-8"
            parts.append(chunk.decode(enc, errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


def _format_address(addr: Any) -> str:
    # IMAPClient returns EnvelopeAddress objects which have .name and .mailbox/.host
    if addr is None:
        return ""
    name = getattr(addr, "name", None)
    mailbox = getattr(addr, "mailbox", None)
    host = getattr(addr, "host", None)

    email_addr = ""
    if mailbox and host:
        mb = mailbox.decode() if isinstance(mailbox, (bytes, bytearray)) else str(mailbox)
        hs = host.decode() if isinstance(host, (bytes, bytearray)) else str(host)
        email_addr = f"{mb}@{hs}"

    display = ""
    if name:
        display = name.decode(errors="replace") if isinstance(name, (bytes, bytearray)) else str(name)

    if display and email_addr:
        return f"{display} <{email_addr}>"
    return email_addr or display


def envelope_to_dict(envelope: Any) -> dict[str, Any]:
    if envelope is None:
        return {}

    # Fields: date, subject, from_, sender, reply_to, to, cc, bcc, in_reply_to, message_id
    def _addr_list(value: Any) -> list[str]:
        if not value:
            return []
        return [_format_address(a) for a in value]

    d: dict[str, Any] = {}
    d["date"] = envelope.date.isoformat() if getattr(envelope, "date", None) else None
    d["subject"] = _decode_mime_words(getattr(envelope, "subject", None))
    d["from"] = _addr_list(getattr(envelope, "from_", None))
    d["to"] = _addr_list(getattr(envelope, "to", None))
    d["cc"] = _addr_list(getattr(envelope, "cc", None))
    d["message_id"] = _decode_mime_words(getattr(envelope, "message_id", None))
    return d


def parse_rfc822(message_bytes: bytes) -> Message:
    return BytesParser(policy=policy.default).parsebytes(message_bytes)


def iter_attachment_parts(msg: Message) -> Iterator[Message]:
    """Yield attachment parts in a stable order (walk order).

    A part is considered an attachment if it has a filename.
    """

    for part in msg.walk():
        filename = part.get_filename()
        if filename:
            yield part


def get_attachment_bytes(
    msg: Message,
    *,
    attachment_index: int = 0,
    filename: str | None = None,
    offset_bytes: int = 0,
    max_bytes: int = 10_000_000,
) -> dict[str, Any]:
    """Extract an attachment payload from an already-parsed RFC822 message.

    Returns metadata plus a raw bytes payload (possibly truncated).

    Notes:
    - Attachment selection is either by exact filename match (preferred) or by index.
    - offset_bytes selects where to start in the attachment payload.
    - If max_bytes > 0 and the remaining bytes are larger, the returned payload is truncated.

    This is intended to support chunked downloads over JSON transports.
    """

    parts = list(iter_attachment_parts(msg))
    if not parts:
        raise ValueError("Message has no attachments")

    selected_part: Message | None = None
    selected_index: int | None = None

    if filename is not None:
        for i, part in enumerate(parts):
            if part.get_filename() == filename:
                selected_part = part
                selected_index = i
                break
        if selected_part is None:
            raise ValueError(f"No attachment found with filename {filename!r}")
    else:
        if attachment_index < 0 or attachment_index >= len(parts):
            raise ValueError(
                f"attachment_index out of range: {attachment_index} (have {len(parts)} attachments)"
            )
        selected_index = attachment_index
        selected_part = parts[attachment_index]

    payload_all = selected_part.get_payload(decode=True) or b""
    original_size = len(payload_all)

    if offset_bytes < 0:
        raise ValueError("offset_bytes must be >= 0")
    if offset_bytes > original_size:
        raise ValueError(
            f"offset_bytes out of range: {offset_bytes} (attachment size is {original_size})"
        )

    payload = payload_all[offset_bytes:]

    truncated = False
    if max_bytes and max_bytes > 0 and len(payload) > max_bytes:
        payload = payload[:max_bytes]
        truncated = True

    next_offset = offset_bytes + len(payload)

    return {
        "index": int(selected_index or 0),
        "filename": selected_part.get_filename(),
        "content_type": selected_part.get_content_type(),
        "size_bytes": int(original_size),
        "offset_bytes": int(offset_bytes),
        "returned_bytes": int(len(payload)),
        "truncated": truncated,
        "next_offset_bytes": int(next_offset),
        "done": bool(next_offset >= original_size),
        "content_bytes": payload,
    }


def extract_bodies(msg: Message, max_chars: int = 20000) -> dict[str, str]:
    text = ""
    html = ""

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get_content_disposition() or "").lower()
            if disp in {"attachment", "inline"} and part.get_filename():
                continue
            if ctype == "text/plain" and not text:
                try:
                    text = part.get_content() or ""
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    text = payload.decode("utf-8", errors="replace")
            if ctype == "text/html" and not html:
                try:
                    html = part.get_content() or ""
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    html = payload.decode("utf-8", errors="replace")
            if text and html:
                break
    else:
        ctype = msg.get_content_type()
        if ctype == "text/plain":
            try:
                text = msg.get_content() or ""
            except Exception:
                payload = msg.get_payload(decode=True) or b""
                text = payload.decode("utf-8", errors="replace")
        elif ctype == "text/html":
            try:
                html = msg.get_content() or ""
            except Exception:
                payload = msg.get_payload(decode=True) or b""
                html = payload.decode("utf-8", errors="replace")

    if max_chars > 0:
        if text and len(text) > max_chars:
            text = text[:max_chars] + "\n\n[truncated]"
        if html and len(html) > max_chars:
            html = html[:max_chars] + "\n\n[truncated]"

    return {"text": text, "html": html}


def list_attachments(msg: Message) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for part in iter_attachment_parts(msg):
        ctype = part.get_content_type()
        payload = part.get_payload(decode=True) or b""
        out.append(
            {
                "filename": part.get_filename(),
                "content_type": ctype,
                "size_bytes": len(payload),
            }
        )

    return out

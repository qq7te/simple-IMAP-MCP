from __future__ import annotations

from dataclasses import dataclass
import logging
import os

logger = logging.getLogger(__name__)


def _getenv_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int = 993
    username: str = ""
    password: str = ""
    ssl: bool = True
    starttls: bool = False
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "ImapConfig":
        logger.debug("Reading IMAP configuration from environment variables")
        host = (os.getenv("IMAP_HOST") or "").strip()
        username = (os.getenv("IMAP_USERNAME") or "").strip()
        password = os.getenv("IMAP_PASSWORD") or ""
        logger.debug(f"IMAP_HOST={host}, IMAP_USERNAME={username}")

        port_raw = (os.getenv("IMAP_PORT") or "993").strip()
        try:
            port = int(port_raw)
        except ValueError:
            port = 993

        ssl = _getenv_bool("IMAP_SSL", True)
        starttls = _getenv_bool("IMAP_STARTTLS", False)

        timeout_raw = (os.getenv("IMAP_TIMEOUT_SECONDS") or "30").strip()
        try:
            timeout_seconds = int(timeout_raw)
        except ValueError:
            timeout_seconds = 30

        if not host:
            logger.error("IMAP_HOST is not set or empty")
            raise ValueError("IMAP_HOST is required")
        if not username:
            logger.error("IMAP_USERNAME is not set or empty")
            raise ValueError("IMAP_USERNAME is required")
        if not password:
            logger.error("IMAP_PASSWORD is not set or empty")
            raise ValueError("IMAP_PASSWORD is required")

        config = cls(
            host=host,
            port=port,
            username=username,
            password=password,
            ssl=ssl,
            starttls=starttls,
            timeout_seconds=timeout_seconds,
        )
        logger.debug(f"Config created: host={host}, port={port}, ssl={ssl}, starttls={starttls}")
        return config

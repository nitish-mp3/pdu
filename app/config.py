from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

OPTIONS_PATH = Path(os.getenv("PDU_GUARD_OPTIONS_PATH", "/data/options.json"))


def _load_options() -> dict:
    try:
        if OPTIONS_PATH.is_file():
            data = json.loads(OPTIONS_PATH.read_text())
            safe_keys = {k: ("***" if "password" in k.lower() or "key" in k.lower() else v) for k, v in data.items()}
            logger.info("Loaded options from %s: %s", OPTIONS_PATH, safe_keys)
            return data
    except Exception:
        logger.warning("Could not read %s, falling back to env vars", OPTIONS_PATH)
    logger.info("No options file found at %s — using env vars / defaults", OPTIONS_PATH)
    return {}


_opts = _load_options()


def _opt_str(key: str, env_key: str, default: str = "") -> str:
    value = _opts.get(key)
    if value is not None and str(value).strip():
        return str(value).strip()
    return os.getenv(env_key, default)


def _opt_int(key: str, env_key: str, default: int) -> int:
    value = _opts.get(key)
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    raw = os.getenv(env_key)
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return default


def _opt_hosts() -> tuple[str, ...]:
    raw = _opts.get("pdu_hosts")
    if isinstance(raw, list):
        return tuple(h.strip() for h in raw if isinstance(h, str) and h.strip())
    return ()


@dataclass(frozen=True)
class Settings:
    database_path: str = _opt_str("database_path", "PDU_GUARD_DB_PATH", "/data/pdu_guard.sqlite3")
    poll_interval_seconds: int = _opt_int("poll_interval", "PDU_GUARD_POLL_INTERVAL_SECONDS", 15)
    discovery_interval_seconds: int = _opt_int("discovery_interval", "PDU_GUARD_DISCOVERY_INTERVAL_SECONDS", 300)
    discovery_timeout_seconds: int = _opt_int("discovery_timeout", "PDU_GUARD_DISCOVERY_TIMEOUT_SECONDS", 2)
    discovery_retries: int = _opt_int("discovery_retries", "PDU_GUARD_DISCOVERY_RETRIES", 0)
    snmp_port: int = _opt_int("snmp_port", "PDU_GUARD_SNMP_PORT", 161)
    max_outlets_per_device: int = _opt_int("max_outlets", "PDU_GUARD_MAX_OUTLETS", 48)
    max_history_rows: int = _opt_int("max_history", "PDU_GUARD_MAX_HISTORY_ROWS", 2000)
    max_hosts_per_network: int = 254
    scan_workers: int = 32
    snmp_username: str = _opt_str("snmp_username", "PDU_GUARD_SNMP_USERNAME")
    snmp_auth_password: str = _opt_str("snmp_auth_password", "PDU_GUARD_SNMP_AUTH_PASSWORD")
    snmp_priv_password: str = _opt_str("snmp_priv_password", "PDU_GUARD_SNMP_PRIV_PASSWORD")
    pdu_hosts: tuple[str, ...] = field(default_factory=_opt_hosts)


settings = Settings()

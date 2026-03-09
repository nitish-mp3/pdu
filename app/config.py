from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    database_path: str = os.getenv("PDU_GUARD_DB_PATH", "/data/pdu_guard.sqlite3")
    poll_interval_seconds: int = _int_env("PDU_GUARD_POLL_INTERVAL_SECONDS", 15)
    discovery_interval_seconds: int = _int_env("PDU_GUARD_DISCOVERY_INTERVAL_SECONDS", 300)
    discovery_timeout_seconds: int = _int_env("PDU_GUARD_DISCOVERY_TIMEOUT_SECONDS", 2)
    discovery_retries: int = _int_env("PDU_GUARD_DISCOVERY_RETRIES", 0)
    snmp_port: int = _int_env("PDU_GUARD_SNMP_PORT", 161)
    max_outlets_per_device: int = _int_env("PDU_GUARD_MAX_OUTLETS", 48)
    max_history_rows: int = _int_env("PDU_GUARD_MAX_HISTORY_ROWS", 2000)
    max_hosts_per_network: int = _int_env("PDU_GUARD_MAX_HOSTS_PER_NETWORK", 254)
    scan_workers: int = _int_env("PDU_GUARD_SCAN_WORKERS", 32)
    snmp_username: str = os.getenv("PDU_GUARD_SNMP_USERNAME", "")
    snmp_auth_password: str = os.getenv("PDU_GUARD_SNMP_AUTH_PASSWORD", "")
    snmp_priv_password: str = os.getenv("PDU_GUARD_SNMP_PRIV_PASSWORD", "")


settings = Settings()

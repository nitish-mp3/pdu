from __future__ import annotations

import logging
from dataclasses import dataclass

from pysnmp.hlapi import (
    ContextData,
    Integer,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    getCmd,
    setCmd,
    usmAesCfb128Protocol,
    usmHMACSHAAuthProtocol,
)

from config import Settings

logger = logging.getLogger(__name__)

SYS_DESCR_OID = "1.3.6.1.2.1.1.1.0"
SYS_NAME_OID = "1.3.6.1.2.1.1.5.0"
OUTLET_STATE_BASE_OID = "1.3.6.1.4.1.318.1.1.26.9.2.2.1.3"
OUTLET_NAME_BASE_OID = "1.3.6.1.4.1.318.1.1.26.9.2.3.1.3"
OUTLET_CONTROL_BASE_OID = "1.3.6.1.4.1.318.1.1.26.9.2.4.1.5"

CONTROL_VALUES = {
    "on": 1,
    "off": 2,
    "reboot": 3,
}

STATE_VALUES = {
    1: "on",
    2: "off",
    3: "rebooting",
}


@dataclass(frozen=True)
class ProbeResult:
    host: str
    system_name: str
    system_description: str


class SNMPClient:
    def __init__(self, settings: Settings, host: str, is_configured: bool = False):
        self._settings = settings
        self._host = host
        self._is_configured = is_configured
        # Configured hosts (from pdu_hosts list) produce WARNING-level SNMP errors so
        # they appear in the add-on log. Scanned hosts use DEBUG to avoid flooding logs.
        self._log_level = logging.WARNING if is_configured else logging.DEBUG
        # Reuse one engine per client so SNMPv3 engine-discovery (extra round trip)
        # only happens once instead of on every get_value / set_int call.
        self._engine = SnmpEngine()

    def _auth(self) -> UsmUserData:
        return UsmUserData(
            self._settings.snmp_username,
            self._settings.snmp_auth_password,
            self._settings.snmp_priv_password,
            authProtocol=usmHMACSHAAuthProtocol,
            privProtocol=usmAesCfb128Protocol,
        )

    def _target(self) -> UdpTransportTarget:
        if self._is_configured:
            # Explicitly configured hosts get generous timeouts so a single
            # dropped UDP packet doesn't produce a false negative.
            return UdpTransportTarget(
                (self._host, self._settings.snmp_port),
                timeout=5,
                retries=2,
            )
        return UdpTransportTarget(
            (self._host, self._settings.snmp_port),
            timeout=self._settings.discovery_timeout_seconds,
            retries=self._settings.discovery_retries,
        )

    def get_value(self, oid: str):
        try:
            iterator = getCmd(
                self._engine,
                self._auth(),
                self._target(),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )

            error_indication, error_status, error_index, var_binds = next(iterator)
            if error_indication:
                logger.log(
                    self._log_level,
                    "SNMP error_indication for %s on %s: %s",
                    oid, self._host, error_indication,
                )
                return None
            if error_status:
                logger.log(
                    self._log_level,
                    "SNMP error_status for %s on %s: %s at index %s",
                    oid, self._host, error_status.prettyPrint(), error_index,
                )
                return None
            return var_binds[0][1]
        except Exception:
            logger.log(self._log_level, "SNMP GET failed for %s on %s", oid, self._host, exc_info=True)
            return None

    def get_int(self, oid: str) -> int | None:
        value = self.get_value(oid)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def get_string(self, oid: str) -> str | None:
        value = self.get_value(oid)
        if value is None:
            return None
        return str(value)

    def set_int(self, oid: str, value: int) -> bool:
        try:
            iterator = setCmd(
                self._engine,
                self._auth(),
                self._target(),
                ContextData(),
                ObjectType(ObjectIdentity(oid), Integer(value)),
            )
            error_indication, error_status, _error_index, _var_binds = next(iterator)
            return not error_indication and not error_status
        except Exception:
            logger.warning("SNMP SET failed for %s on %s", oid, self._host, exc_info=True)
            return False

    def probe_device(self) -> ProbeResult | None:
        try:
            return self._probe_device_inner()
        except Exception:
            logger.log(self._log_level, "Probe failed for %s", self._host, exc_info=True)
            return None

    def _probe_device_inner(self) -> ProbeResult | None:
        outlet_one_state = self.get_int(f"{OUTLET_CONTROL_BASE_OID}.1")
        if outlet_one_state is None:
            return None

        system_name = self.get_string(SYS_NAME_OID) or f"PDU {self._host}"
        system_description = self.get_string(SYS_DESCR_OID) or f"APC PDU at {self._host}"
        return ProbeResult(
            host=self._host,
            system_name=system_name,
            system_description=system_description,
        )

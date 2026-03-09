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
    def __init__(self, settings: Settings, host: str):
        self._settings = settings
        self._host = host

    def _auth(self) -> UsmUserData:
        return UsmUserData(
            self._settings.snmp_username,
            self._settings.snmp_auth_password,
            self._settings.snmp_priv_password,
            authProtocol=usmHMACSHAAuthProtocol,
            privProtocol=usmAesCfb128Protocol,
        )

    def _target(self) -> UdpTransportTarget:
        return UdpTransportTarget(
            (self._host, self._settings.snmp_port),
            timeout=self._settings.discovery_timeout_seconds,
            retries=self._settings.discovery_retries,
        )

    def get_value(self, oid: str):
        try:
            iterator = getCmd(
                SnmpEngine(),
                self._auth(),
                self._target(),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )

            error_indication, error_status, _error_index, var_binds = next(iterator)
            if error_indication or error_status:
                return None
            return var_binds[0][1]
        except Exception:
            logger.debug("SNMP GET failed for %s on %s", oid, self._host, exc_info=True)
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
                SnmpEngine(),
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
            logger.debug("Probe failed for %s", self._host, exc_info=True)
            return None

    def _probe_device_inner(self) -> ProbeResult | None:
        system_description = self.get_string(SYS_DESCR_OID)
        if not system_description:
            return None

        outlet_one_state = self.get_int(f"{OUTLET_STATE_BASE_OID}.1")
        is_apc_like = "apc" in system_description.lower() or outlet_one_state is not None
        if not is_apc_like:
            return None

        system_name = self.get_string(SYS_NAME_OID) or f"PDU {self._host}"
        return ProbeResult(
            host=self._host,
            system_name=system_name,
            system_description=system_description,
        )

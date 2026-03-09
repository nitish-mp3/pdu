from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from config import Settings, settings
from database import Base, engine, session_scope
from models import Device, Outlet, OutletEvent
from snmp import (
    CONTROL_VALUES,
    OUTLET_CONTROL_BASE_OID,
    OUTLET_NAME_BASE_OID,
    STATE_VALUES,
    ProbeResult,
    SNMPClient,
)

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CommandResult:
    accepted: bool
    message: str


class PDUService:
    def __init__(self, app_settings: Settings):
        self.settings = app_settings
        self._stop_event = asyncio.Event()
        self._last_discovery_at = datetime.min.replace(tzinfo=timezone.utc)

    def initialize(self) -> None:
        data_dir = Path(self.settings.database_path).parent
        data_dir.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized at %s", self.settings.database_path)
        logger.info(
            "Config: snmp_user=%s, pdu_hosts=%s, snmp_port=%d, credentials_set=%s",
            self.settings.snmp_username or "(empty)",
            list(self.settings.pdu_hosts) or "(none)",
            self.settings.snmp_port,
            self._credentials_ready,
        )

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self.sync_once)
            except Exception:
                logger.exception("Background sync cycle failed — will retry next interval")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.settings.poll_interval_seconds)
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._stop_event.set()

    def sync_once(self) -> None:
        if not self._credentials_ready:
            logger.warning("SNMP credentials not configured — skipping sync. Set them in the add-on Configuration tab.")
            return

        now = utcnow()
        should_discover = now - self._last_discovery_at >= timedelta(seconds=self.settings.discovery_interval_seconds)
        if should_discover:
            try:
                self.discover_devices()
            except Exception:
                logger.exception("Discovery cycle failed")
            self._last_discovery_at = now

        try:
            self.poll_devices()
        except Exception:
            logger.exception("Poll cycle failed")

        try:
            self.trim_history()
        except Exception:
            logger.exception("History trim failed")

    @property
    def _credentials_ready(self) -> bool:
        return all(
            [
                self.settings.snmp_username,
                self.settings.snmp_auth_password,
                self.settings.snmp_priv_password,
            ]
        )

    def discover_devices(self) -> None:
        if not self._credentials_ready:
            logger.warning("Discovery skipped — SNMP credentials not configured.")
            return
        candidates = self._candidate_hosts()
        logger.info("Discovery starting — %d candidate host(s) to probe", len(candidates))
        if not candidates:
            return

        configured_set = set(self.settings.pdu_hosts)
        found = 0

        # ── Phase 1: Probe explicitly configured hosts sequentially ──────
        # They run alone (no thread pool contention) with generous timeouts
        # so a single dropped UDP packet can't cause a false negative.
        for host in self.settings.pdu_hosts:
            if not host:
                continue
            logger.info("Probing configured host %s …", host)
            result = self._probe_host(host, is_configured=True)
            if result is not None:
                found += 1
                self._register_device(result)
            else:
                logger.warning(
                    "Configured host %s did not respond — check SNMP credentials, "
                    "network path, and that SNMPv3 is enabled on the device.",
                    host,
                )

        # ── Phase 2: Scan remaining subnet hosts in a thread pool ────────
        remaining = [h for h in candidates if h not in configured_set]
        if remaining:
            with ThreadPoolExecutor(max_workers=self.settings.scan_workers) as executor:
                futures = {
                    executor.submit(self._probe_host, host, False): host
                    for host in remaining
                }
                for future in as_completed(futures):
                    try:
                        result = future.result()
                    except Exception:
                        logger.debug("Probe future raised", exc_info=True)
                        continue
                    if result is None:
                        continue
                    found += 1
                    self._register_device(result)
        logger.info("Discovery complete — %d device(s) found out of %d probed", found, len(candidates))

    def _register_device(self, result: ProbeResult) -> None:
        """Upsert a discovered device and its outlets into the database."""
        logger.info("Found PDU: %s (%s)", result.system_name, result.host)
        with session_scope() as session:
            device = session.scalar(select(Device).where(Device.host == result.host))
            if device is None:
                device = Device(host=result.host)
                session.add(device)
            device.name = result.system_name
            device.model = result.system_description
            device.status = "online"
            device.last_seen_at = utcnow()
            self._ensure_outlets(session, device)

    def _probe_host(self, host: str, is_configured: bool = False):
        return SNMPClient(self.settings, host, is_configured=is_configured).probe_device()

    def _candidate_hosts(self) -> list[str]:
        hosts: list[str] = []
        seen: set[str] = set()

        for host in self.settings.pdu_hosts:
            if host and host not in seen:
                hosts.append(host)
                seen.add(host)

        for interface_addresses in psutil.net_if_addrs().values():
            for address in interface_addresses:
                if address.family != socket.AF_INET or not address.netmask:
                    continue
                if address.address.startswith("127."):
                    continue
                network = ipaddress.ip_network(f"{address.address}/{address.netmask}", strict=False)
                if not network.is_private:
                    continue
                count = 0
                for host in network.hosts():
                    host_str = str(host)
                    if host_str == address.address or host_str in seen:
                        continue
                    hosts.append(host_str)
                    seen.add(host_str)
                    count += 1
                    if count >= self.settings.max_hosts_per_network:
                        break
        return hosts

    def poll_devices(self) -> None:
        with session_scope() as session:
            devices = session.scalars(
                select(Device)
                .options(selectinload(Device.outlets))
                .order_by(Device.name.asc())
            ).all()
            for device in devices:
                try:
                    self._poll_device(session, device)
                except Exception:
                    logger.warning("Failed to poll device %s (%s)", device.name, device.host, exc_info=True)

    def _ensure_outlets(self, session: Session, device: Device) -> None:
        known = {outlet.outlet_index: outlet for outlet in device.outlets}
        client = SNMPClient(self.settings, device.host)
        for outlet_index in range(1, self.settings.max_outlets_per_device + 1):
            raw_state = client.get_int(f"{OUTLET_CONTROL_BASE_OID}.{outlet_index}")
            if raw_state is None:
                continue

            snmp_name = client.get_string(f"{OUTLET_NAME_BASE_OID}.{outlet_index}")
            display_name = snmp_name.strip() if snmp_name and snmp_name.strip() else f"Outlet {outlet_index}"

            outlet = known.get(outlet_index)
            state = self._decode_state(raw_state)
            if outlet is None:
                outlet = Outlet(
                    device=device,
                    outlet_index=outlet_index,
                    name=display_name,
                    current_state=state,
                    raw_state=raw_state,
                    last_changed_at=utcnow(),
                )
                session.add(outlet)
                self._log_event(
                    session,
                    outlet,
                    action="discovered",
                    source="system",
                    previous_state=None,
                    next_state=state,
                    message="Outlet discovered during device onboarding.",
                )
            else:
                outlet.name = display_name
                outlet.current_state = state
                outlet.raw_state = raw_state

    def _poll_device(self, session: Session, device: Device) -> None:
        client = SNMPClient(self.settings, device.host)
        any_reachable = False
        for outlet in device.outlets:
            raw_state = client.get_int(f"{OUTLET_CONTROL_BASE_OID}.{outlet.outlet_index}")
            if raw_state is None:
                continue

            any_reachable = True
            previous_state = outlet.current_state
            next_state = self._decode_state(raw_state)
            outlet.raw_state = raw_state
            outlet.current_state = next_state
            if previous_state != next_state:
                outlet.last_changed_at = utcnow()
                self._log_event(
                    session,
                    outlet,
                    action="state_change",
                    source="poller",
                    previous_state=previous_state,
                    next_state=next_state,
                    message="State changed outside the add-on or after a delayed device response.",
                )

        device.last_polled_at = utcnow()
        if any_reachable:
            device.status = "online"
            device.last_seen_at = utcnow()
        else:
            device.status = "offline"

    def set_lock(self, outlet_id: int, locked: bool) -> CommandResult:
        with session_scope() as session:
            outlet = session.get(Outlet, outlet_id)
            if outlet is None:
                return CommandResult(False, "Outlet not found.")
            if outlet.is_locked == locked:
                return CommandResult(True, "Lock already in the requested state.")

            outlet.is_locked = locked
            self._log_event(
                session,
                outlet,
                action="lock" if locked else "unlock",
                source="ui",
                previous_state=outlet.current_state,
                next_state=outlet.current_state,
                message="Remote-off protection enabled." if locked else "Remote-off protection disabled.",
            )
            return CommandResult(True, "Lock updated.")

    def issue_command(self, outlet_id: int, action: str) -> CommandResult:
        if action not in CONTROL_VALUES:
            return CommandResult(False, "Unsupported action.")

        with session_scope() as session:
            outlet = session.scalar(
                select(Outlet)
                .options(selectinload(Outlet.device))
                .where(Outlet.id == outlet_id)
            )
            if outlet is None:
                return CommandResult(False, "Outlet not found.")

            if outlet.is_locked and action in {"off", "reboot"}:
                return CommandResult(False, "Outlet is locked against remote off and reboot actions.")

            client = SNMPClient(self.settings, outlet.device.host)
            success = client.set_int(
                f"{OUTLET_CONTROL_BASE_OID}.{outlet.outlet_index}",
                CONTROL_VALUES[action],
            )
            if not success:
                return CommandResult(False, "SNMP command was rejected or timed out.")

            previous_state = outlet.current_state
            refreshed_raw = client.get_int(f"{OUTLET_CONTROL_BASE_OID}.{outlet.outlet_index}")
            if refreshed_raw is not None:
                outlet.raw_state = refreshed_raw
                outlet.current_state = self._decode_state(refreshed_raw)
                if outlet.current_state != previous_state:
                    outlet.last_changed_at = utcnow()

            self._log_event(
                session,
                outlet,
                action=action,
                source="ui",
                previous_state=previous_state,
                next_state=outlet.current_state,
                message=f"Operator sent '{action}' command.",
            )
            return CommandResult(True, f"Command '{action}' accepted.")

    def trim_history(self) -> None:
        with session_scope() as session:
            event_ids = session.scalars(
                select(OutletEvent.id)
                .order_by(desc(OutletEvent.created_at))
                .offset(self.settings.max_history_rows)
            ).all()
            if event_ids:
                session.query(OutletEvent).filter(OutletEvent.id.in_(event_ids)).delete(synchronize_session=False)

    def overview(self) -> dict:
        with session_scope() as session:
            devices = session.scalars(
                select(Device)
                .options(selectinload(Device.outlets))
                .order_by(Device.name.asc())
            ).all()
            history = session.scalars(
                select(OutletEvent)
                .options(selectinload(OutletEvent.outlet).selectinload(Outlet.device))
                .order_by(desc(OutletEvent.created_at))
                .limit(60)
            ).all()

            devices_payload = []
            online_devices = 0
            outlet_total = 0
            locked_total = 0
            powered_on_total = 0
            for device in devices:
                if device.status == "online":
                    online_devices += 1
                outlet_total += len(device.outlets)
                device_outlets = []
                for outlet in sorted(device.outlets, key=lambda entry: entry.outlet_index):
                    locked_total += int(outlet.is_locked)
                    powered_on_total += int(outlet.current_state == "on")
                    device_outlets.append(
                        {
                            "id": outlet.id,
                            "outlet_index": outlet.outlet_index,
                            "name": outlet.name,
                            "current_state": outlet.current_state,
                            "raw_state": outlet.raw_state,
                            "is_locked": outlet.is_locked,
                            "last_changed_at": outlet.last_changed_at,
                        }
                    )
                devices_payload.append(
                    {
                        "id": device.id,
                        "name": device.name,
                        "host": device.host,
                        "model": device.model,
                        "status": device.status,
                        "last_seen_at": device.last_seen_at,
                        "last_polled_at": device.last_polled_at,
                        "outlets": device_outlets,
                    }
                )

            history_payload = []
            for item in history:
                history_payload.append(
                    {
                        "id": item.id,
                        "outlet_id": item.outlet_id,
                        "outlet_name": item.outlet.name,
                        "device_name": item.outlet.device.name,
                        "action": item.action,
                        "source": item.source,
                        "previous_state": item.previous_state,
                        "next_state": item.next_state,
                        "message": item.message,
                        "created_at": item.created_at,
                    }
                )

            return {
                "devices": devices_payload,
                "history": history_payload,
                "summary": {
                    "devices_total": len(devices_payload),
                    "devices_online": online_devices,
                    "outlets_total": outlet_total,
                    "outlets_on": powered_on_total,
                    "outlets_locked": locked_total,
                },
            }

    def _decode_state(self, raw_state: int | None) -> str:
        if raw_state is None:
            return "unknown"
        return STATE_VALUES.get(raw_state, f"unknown({raw_state})")

    def _log_event(
        self,
        session: Session,
        outlet: Outlet,
        action: str,
        source: str,
        previous_state: str | None,
        next_state: str | None,
        message: str | None,
    ) -> None:
        session.add(
            OutletEvent(
                outlet=outlet,
                action=action,
                source=source,
                previous_state=previous_state,
                next_state=next_state,
                message=message,
            )
        )


service = PDUService(settings)

# PDU Outlet Guard

PDU Outlet Guard is a Home Assistant OS add-on for APC-style SNMP-managed PDUs. It provides an operator UI with live outlet state, per-port history, and a lock that prevents remote off or reboot operations until the lock is revoked.

## What this build does

- Auto-discovers candidate PDUs on the local HA host networks instead of asking the end user to enter IP addresses.
- Polls outlet state on a schedule and records detected changes into a local SQLite event log.
- Allows outlet on, off, and reboot actions through a simple ingress UI.
- Enforces a per-outlet lock so remote off and reboot commands are rejected while the lock is active.
- Stores history and lock state under `/data`, so the add-on survives restart and upgrade cycles.

## Architecture

- Backend: FastAPI service with a background sync loop.
- Persistence: SQLite via SQLAlchemy.
- Discovery: subnet scan of private interfaces visible to the HA host network namespace.
- Protocol: SNMPv3 using the APC-style OIDs from your test script.
- UI: static ingress frontend served by the add-on.

## Current assumptions

- The PDU family is APC-like and responds to these OIDs:
  - Outlet state: `1.3.6.1.4.1.318.1.1.26.9.2.2.1.3.<port>`
  - Outlet control: `1.3.6.1.4.1.318.1.1.26.9.2.4.1.5.<port>`
- The environment already has valid SNMPv3 credentials.
- End users should not type device IPs into the UI.

## Important product note

Your requirement of "no technical setup" is realistic for IP discovery, but SNMPv3 credentials still need a provisioning strategy. For commercial deployment, the right approach is usually one of these:

1. Ship a managed appliance profile where all supported PDUs are provisioned with the same org-level SNMPv3 credentials.
2. Pair this add-on with an onboarding service that writes credentials into the add-on environment from a secure admin flow.
3. Replace direct SNMP credential handling with a vendor gateway or API bridge if the PDU fleet supports it.

This code keeps the operator UI non-technical. Credential sourcing still needs a product decision before production release.

## Files

- `config.yaml`: Home Assistant add-on manifest.
- `Dockerfile`: add-on container image.
- `app/main.py`: FastAPI app and endpoints.
- `app/service.py`: discovery, polling, lock enforcement, and history logic.
- `app/snmp.py`: SNMPv3 client for APC-style PDU OIDs.
- `app/static/`: ingress UI.

## Next production hardening steps

1. Move SNMP secrets into Home Assistant-managed secrets or an external secret source.
2. Add vendor-specific device fingerprints and richer outlet metadata.
3. Add authentication and audit enrichment if multiple operator roles will use this add-on.
4. Add integration tests with an SNMP simulator before commercial rollout.
# pdu

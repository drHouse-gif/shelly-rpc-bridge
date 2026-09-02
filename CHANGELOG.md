# Changelog

## 0.4.0 - 2026-09-02

- Renamed and refactored the project into one `shelly_toolkit` HACS integration.
- Added unified HTTP/WebSocket/remote/official-integration RPC transports.
- Added device inventory, capability discovery, admin-only responsive panel,
  Remote Pair credential lifecycle, Doctor/Repairs, diagnostics downloads,
  backup/restore, exact/smart migration, RPC Explorer, Script Studio, bounded
  events, automation event forwarding, and response-enabled actions.
- Added simulated HTTP/WebSocket Shelly RPC tests, Home Assistant config-entry
  lifecycle tests, frontend security checks, lint/type checks, HACS validation,
  and hassfest CI.
- Breaking: removed the `shelly_rpc_bridge` integration domain, dynamic entity
  generation, and recoverable plaintext token model.

Physical Shelly hardware validation is not included in this release.

## 0.3.0

- Added multiple named bridge tokens and a Home Assistant options flow.

## 0.2.0

- Moved the outbound WebSocket receiver into the Home Assistant integration.

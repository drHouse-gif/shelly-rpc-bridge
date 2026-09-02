# Changelog

## 0.4.1 - 2026-09-02

- Fixed Shelly WebSocket digest authentication to use the device-provided
  integer nonce count and a standards-compatible base64 client nonce.
- Serialized authenticated WebSocket calls and stopped replaying timed-out or
  mutating RPC calls after ambiguous transport failures.
- Hardened Remote Pair so credentials bind only after a matching, valid
  `Shelly.GetDeviceInfo` Gen2+ response.
- Fixed recursive backup and diagnostics redaction, local-target duplicate
  detection, full-snapshot notification handling, and stale entities after a
  local target is removed.
- Added post-upload Shelly Script verification and positive script-ID schemas.
- Repaired the Home Assistant test environment and expanded protocol/security
  regression coverage.
- Corrected documentation about Toolkit-owned entities and the sensitivity of
  backups containing script source.

Physical Shelly hardware validation is not included in this release.

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
- Breaking: removed the `shelly_rpc_bridge` integration domain and recoverable
  plaintext token model.

Physical Shelly hardware validation is not included in this release.

## 0.3.0

- Added multiple named bridge tokens and a Home Assistant options flow.

## 0.2.0

- Moved the outbound WebSocket receiver into the Home Assistant integration.

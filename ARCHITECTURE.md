# Shelly Toolkit architecture

Shelly Toolkit is one HACS custom integration. It is an independent community
project and is not affiliated with or endorsed by Shelly Group.

## Boundaries

- Home Assistant remains the only server-side runtime. There is no relay or
  project-owned cloud backend.
- Official Home Assistant Shelly config entries are exposed as read/write
  developer targets through their loaded RPC coordinator. Toolkit does not
  create duplicate entities for them.
- Toolkit-managed local targets use direct HTTP or WebSocket RPC.
- Remote targets initiate an outbound WebSocket to Home Assistant and are
  authenticated with per-device, revocable credentials.
- All panel WebSocket commands and all powerful actions are administrator-only.

## Modules

- `rpc/`: transport-independent RPC client plus HTTP, client WebSocket and
  official-integration adapters.
- `remote.py`: inbound outbound-WebSocket receiver and credential validation.
- `device_manager.py`: unified target inventory and Home Assistant device
  registry synchronization.
- `capabilities.py`: runtime component and RPC method discovery.
- `doctor.py`: evidence-based health checks and repair issue synchronization.
- `backup.py`: versioned, secret-scrubbed capture and persistent backup store.
- `restore.py`: compatibility preview and confirmed restore execution.
- `migration.py`: exact clone and capability-based smart migration planning.
- `scripts.py`: safe Shelly Script lifecycle with pre-overwrite backup.
- `events.py`: bounded event history and Home Assistant event forwarding.
- `websocket_api.py`: admin-only backend API for the sidebar panel.
- `frontend/`: dependency-free responsive Home Assistant custom panel.

`DataUpdateCoordinator` schedules periodic refreshes for Toolkit-managed local
targets. Push-connected remote devices update state and events immediately.

## Backup safety

Backups are JSON objects with a schema version. Secret-like keys are removed at
capture time, and network/auth configuration is never restored automatically.
Backups are stored through Home Assistant's `.storage` abstraction and can be
downloaded explicitly from the panel.

## Remote credential model

Generated bearer secrets are displayed once. Only a SHA-256 digest is stored.
A credential is bound to the first valid Shelly device identity that uses it,
and only one live socket may use a bound credential. Regeneration revokes the
old secret and disconnects its socket. TLS is required across untrusted
networks; no application protocol can protect a bearer token after it is
stolen from an endpoint or reverse-proxy log.

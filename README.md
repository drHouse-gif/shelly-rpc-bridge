# Shelly Toolkit for Home Assistant

One HACS installation for Shelly Gen2+ RPC diagnostics, maintenance, backup,
migration, scripting, and remote connectivity.

> **Independent community project. Not affiliated with or endorsed by Shelly
> Group.** “Shelly” and “Home Assistant” are used only to describe
> compatibility. The project is maintained by **Dr. House** (`drHouse-gif`).

Version **0.4.1** is an experimental pre-release intended for careful testing
on non-critical devices. It has extensive automated simulation coverage and a
successful smoke test on physical Shelly Gen2+ hardware.

## What is Shelly Toolkit?

Shelly Toolkit is an administrator-only developer and maintenance layer that
runs entirely inside Home Assistant. It is not a replacement for normal Home
Assistant entities, not a Fleet Manager, and not a project-operated cloud
service.

The toolkit can reuse loaded devices from Home Assistant's official Shelly
integration without registering conflicting entities. It can also manage
explicit local RPC targets and accept a Shelly-initiated outbound WebSocket for
a device outside the Home Assistant LAN.

## Features

- Unified HTTP, WebSocket, official-integration, and remote RPC transports.
- Runtime component and method discovery instead of a model allowlist.
- Central inventory with model, ID/MAC, firmware, connection, online state,
  last seen, uptime, RSSI, temperature, and RPC availability when reported.
- Revocable, one-device-bound Remote Pair credentials.
- Evidence-based Shelly Doctor with Home Assistant Repairs for error findings.
- Versioned, secret-redacted backups and compatibility-aware restore previews.
- Exact Clone and capability-based Smart Migration.
- Admin-only RPC Explorer with local method history and JSON responses.
- Script list, code download/upload, start/stop/restart/status, and automatic
  pre-overwrite code backup.
- Bounded RPC event history, filtering, and the `shelly_toolkit_event` Home
  Assistant event for automations.
- Responsive, dependency-free Home Assistant sidebar panel.
- Response-enabled Home Assistant actions for automation and developer use.

Unsupported methods or components are reported as `UNSUPPORTED`; the toolkit
does not claim support for every Shelly model or firmware.

## Requirements

- Home Assistant **2026.8 or newer**.
- A Home Assistant administrator account.
- Shelly Gen2+ for direct Toolkit RPC targets.
- HTTPS/WSS for Remote Pair across an untrusted network.

## Installation through HACS

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/drHouse-gif/shelly-rpc-bridge` with category
   **Integration**.
3. Open **Shelly Toolkit for Home Assistant** and choose **Download**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration** and select
   **Shelly Toolkit for Home Assistant**.
6. Open **Shelly Toolkit** in the sidebar.

This repository has not been submitted to the HACS default repository list.
Install it as a custom repository.

## Adding the integration

The config flow creates one Toolkit hub. Device targets and credentials are
managed from the admin-only sidebar panel, keeping the normal Home Assistant
device pages focused on entities.

The options flow intentionally links users back to the panel rather than
duplicating the maintenance interface in many config-flow forms.

## Local devices

Loaded Gen2+ devices from the official Shelly integration appear automatically
as `official` targets and retain their existing device-registry ownership.

To add a Toolkit-managed target, open **Devices → Add local RPC target** and
enter its LAN hostname/IP, port, transport, and optional device password. The
target must resolve only to private, non-loopback addresses and must answer
`Shelly.GetDeviceInfo` with generation 2 or later. This limits SSRF exposure
and prevents arbitrary endpoints from being persisted.

If its MAC matches an official-integration target, Toolkit discards the local
duplicate and uses the official target. Toolkit creates capability-based
switch, light, cover, sensor, and binary-sensor entities only for its own local
and Remote Pair targets; it does not duplicate entities owned by the official
Shelly integration.

## Remote Pair

Remote Pair does not require Docker, a VPS, or an external relay:

1. Ensure Home Assistant has a reachable external HTTPS URL.
2. Open **Shelly Toolkit → Remote Pair**.
3. Name the credential and choose **Generate pairing URL**.
4. Copy the WSS URL immediately; the secret is shown only once.
5. In the Shelly web interface, enable **Outbound WebSocket** and paste the URL.
   Exact labels vary by firmware.

The device initiates the connection to Home Assistant. Toolkit stores only the
SHA-256 verifier, binds the credential to the first valid device identity, and
allows only one device identity per credential. Regeneration or revocation
immediately invalidates the credential and closes its socket.

The URL itself is a bearer secret. TLS prevents network observers from reading
it, but cannot protect a token copied from the device, browser history, or
reverse-proxy access logs. See [SECURITY.md](SECURITY.md).

## Shelly Doctor

Doctor uses values actually returned by the target and does not invent missing
telemetry. Current checks include:

- connectivity, timeouts, unstable RPC, and authentication errors;
- Wi-Fi warning at `≤ -70 dBm` and error at `≤ -85 dBm`;
- temperature warning at `≥ 70 °C` and error at `≥ 85 °C`;
- free memory/filesystem warning below 20% and error below 10%;
- firmware information and `restart_required` when exposed;
- component and Shelly Script errors returned by RPC.

The health score is a compact summary, not a hardware safety certification.
Current error findings are mirrored to Home Assistant Repairs.

## Backup / Restore

Backups use a stable outer schema:

```json
{
  "toolkit_backup_version": 1,
  "id": "…",
  "created_at": "…",
  "device": {},
  "capabilities": {},
  "configuration": {},
  "redacted_paths": []
}
```

Toolkit captures `Shelly.GetConfig`, component config/status, scripts,
schedules, and webhooks when the target advertises them. Future component types
remain visible through capability discovery even before a migration mapping is
added.

Password, passphrase, token, secret, private-key, HA1, and similar fields are
removed recursively before persistence or download. A redacted secret cannot
be restored and must be configured separately. Shelly Script source is
preserved so it can be restored; because scripts can contain hard-coded
credentials, every stored or downloaded backup must still be treated as
sensitive.

Restore always creates a preview with `READY`, `SKIPPED`, `UNSUPPORTED`, or
`FAILED` operations. Network, authentication, system, and connectivity config
is skipped automatically. Apply requires explicit confirmation, captures a
safety backup of the target, and never runs a factory reset.

## Clone / Migration

- **Exact Clone** requires the same advertised model and preserves compatible
  component/script IDs.
- **Smart Migration** maps logical component keys and advertised methods, for
  example `switch:0 → switch:0`, rather than sending the source JSON blindly.

Every migration captures a sanitized source backup first. The target preview
lists incompatible components and unsupported resources. Target mutation is
impossible without explicit confirmation.

## RPC Explorer and Capability Explorer

The Devices page exposes discovered components, namespaces, and RPC methods.
RPC Explorer accepts a method and JSON parameters and displays the exact JSON
result or Home Assistant error. Its autocomplete history is browser-local and
stores method names only—never parameters or credentials.

RPC Explorer is deliberately powerful. Every backend command requires an HA
administrator, known destructive methods require a confirmation checkbox, and
the call can only target an already validated Toolkit device.

## Script Studio

Script Studio implements `Script.List`, `Script.GetCode`, chunk-safe
`Script.PutCode`, start, stop, restart, and status. The current code is stored
as a Toolkit backup immediately before overwrite. Script-reported errors are
also included in Doctor.

Shelly does not expose a universal historical script-log RPC, so Toolkit shows
only status and errors the device actually provides. The editor is intentionally
small and is not presented as an IDE.

## Events and automation triggers

WebSocket notifications are normalized to timestamp, device, component, event,
and payload. History is memory-only and capped at 500 events.

Automations can use an ordinary Home Assistant event trigger:

```yaml
triggers:
  - trigger: event
    event_type: shelly_toolkit_event
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.device_id == 'remote:my-shelly' }}"
actions: []
```

HTTP-only targets do not provide push events. Events owned by the official
Shelly integration are not intercepted or duplicated by Toolkit.

## Actions

All actions are registered with schemas, require a Home Assistant
administrator, and return response data:

- `shelly_toolkit.rpc_call`
- `shelly_toolkit.run_diagnostics`
- `shelly_toolkit.backup_device`
- `shelly_toolkit.restore_device`
- `shelly_toolkit.clone_device`
- `shelly_toolkit.restart_script`

Restore and clone require `confirm: true`; known destructive RPC calls do too.

## Security considerations

- Treat Remote Pair URLs and local device passwords as secrets.
- Use WSS with a valid certificate outside a trusted network.
- Prevent reverse proxies from recording the Remote Pair query string.
- Keep Home Assistant administrator accounts protected with MFA.
- Review every restore/migration preview before confirming it.
- Downloaded backups are redacted, but can still reveal network names,
  schedules, topology, script logic, and device identifiers.
- Script upload executes code on the Shelly device. Review code before upload.

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Troubleshooting

- **No sidebar item:** verify the config entry is loaded, then hard-refresh the
  browser after restarting Home Assistant.
- **Remote device never connects:** use the externally reachable WSS URL,
  verify reverse-proxy WebSocket support, and confirm the Shelly clock/TLS
  trust. Generate a new credential if the old one may be logged.
- **Local target rejected:** Toolkit accepts LAN/private addresses only. Use
  Remote Pair for a device outside the LAN.
- **Authentication failed:** update the device credential by removing and
  re-adding the local target; secrets are never printed in logs.
- **Unsupported:** update device firmware if appropriate, then refresh
  capabilities. The firmware may genuinely omit that RPC method.
- **Restore skips Wi-Fi/MQTT:** this is an intentional connectivity safeguard.

## Upgrade from Shelly RPC Bridge 0.3.x

Version 0.4.0 changes the integration domain from `shelly_rpc_bridge` to
`shelly_toolkit` and is intentionally breaking. Remove the legacy config entry,
remove a leftover `custom_components/shelly_rpc_bridge` directory if HACS did
not clean it up, restart, and add Shelly Toolkit. Legacy plaintext remote
tokens are not exposed by the new UI; create new one-device credentials.

## Development

The architecture is documented in [ARCHITECTURE.md](ARCHITECTURE.md). Tests use
a controllable fake Shelly server with real local HTTP/WebSocket sockets.

```bash
python -m pip install -r requirements-test.txt
ruff check .
ruff format --check custom_components tests
mypy custom_components/shelly_toolkit
pytest -q
node --check custom_components/shelly_toolkit/frontend/shelly-toolkit-panel.js
node --test tests/frontend.test.mjs
```

GitHub Actions also run hassfest and HACS validation on every push and pull
request. No test claims physical-hardware validation.

## Disclaimer

Independent community project. Not affiliated with or endorsed by Shelly
Group. This software is provided without warranty under the MIT License. Use
maintenance, restore, migration, arbitrary RPC, and script functions only when
you understand their effect on the target device.

## License

Project code is MIT licensed. No third-party source is vendored. Runtime and
test dependency licenses are summarized in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

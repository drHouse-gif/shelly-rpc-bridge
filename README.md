# Shelly RPC Bridge

Direct Shelly Gen2+ outbound WebSocket integration for Home Assistant.

## Version 0.2.0 — no external relay

The bridge now runs inside Home Assistant. You do **not** need Docker, a VPS, Caddy, a separate relay service, port forwarding, or manually generated credentials.

Flow:

```text
Shelly Gen2+  ── outbound WebSocket ──>  Home Assistant / Shelly RPC Bridge
```

The Shelly can use the best URL Home Assistant exposes. When Home Assistant has a secure external or Home Assistant Cloud URL, the generated address is `wss://...`. For same-LAN testing, Home Assistant can also generate a local `ws://...` address.

## Install with HACS

1. In HACS open **Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/drHouse-gif/shelly-rpc-bridge` as category **Integration**.
3. Open **Shelly RPC Bridge** and download the latest version.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration → Shelly RPC Bridge**.
6. Press **Submit** to generate the private Shelly WebSocket URL.
7. Copy the generated URL and press **Submit** again to finish the Home Assistant setup.
8. Open the Shelly web UI → **Settings → Connectivity → Outbound WebSocket**.
9. Enable Outbound WebSocket, paste the generated URL as the server URL, save, and connect.

The device should then appear in Home Assistant automatically. Supported component families include switches, CB outputs, lights/RGB/RGBW, covers, numeric sensors, and binary sensors exposed by the existing integration platforms.

## Security

Each installation generates a random private device token. Connections without the token are rejected. Destructive or connectivity-changing RPC calls such as factory reset, firmware update, Wi-Fi/Ethernet/MQTT/WebSocket reconfiguration, authentication changes, scripts, schedules, and webhooks are blocked by the bridge.

Treat the generated WebSocket URL as a secret because it contains the device token.

## Development status

`0.2.0` is the first direct-connection test release. Test it on non-critical devices before production use.

## License

MIT

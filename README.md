# Shelly RPC Bridge

Direct Shelly Gen2+ outbound WebSocket integration for Home Assistant.

## Version 0.3.0 — multi-token direct bridge

No Docker, VPS, Caddy or external relay is required. The bridge runs inside Home Assistant.

### Multi-token management

Open **Settings → Devices & services → Shelly RPC Bridge → Configure**. You can:

- **Generate token** — create a named token and a ready-to-paste WebSocket URL.
- **View tokens and URLs** — recover any generated URL later.
- **Revoke token** — immediately invalidate one token without affecting the others.

Use one token per device or per site. For larger installations, one-token-per-device gives the best isolation because a leaked or retired token can be revoked without touching every other Shelly.

Existing 0.2.x single-token installations are migrated automatically to a token named **Primary**.

### Install with HACS

1. Add `https://github.com/drHouse-gif/shelly-rpc-bridge` to HACS as a custom **Integration** repository.
2. Download/update Shelly RPC Bridge and restart Home Assistant.
3. Add **Shelly RPC Bridge** from Settings → Devices & services if it is not already configured.
4. Open **Configure → Generate token** whenever you need another device URL.
5. Paste the generated URL into Shelly → Settings → Connectivity → Outbound WebSocket.

### Security

Generated URLs contain private bearer-like device tokens. Treat them as secrets. Destructive and connectivity-changing RPC methods remain blocked. Revoking a token disconnects active devices using that token.

### Development status

`0.3.0` is a test release. Use non-critical devices while validating behavior.

## License

MIT

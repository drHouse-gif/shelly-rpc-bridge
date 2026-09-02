# Security policy

## Reporting a vulnerability

Do not publish vulnerabilities, pairing URLs, device passwords, backups, or
tokens in a public issue. Use the repository's private GitHub security-advisory
flow. Include the affected version, impact, reproduction steps, and a minimal
redacted log if relevant.

## Supported versions

Security fixes are applied to the latest `0.x` pre-release. Earlier Shelly RPC
Bridge versions are not supported after the 0.4.0 domain and credential-model
change.

## Security model

- Every panel WebSocket command and every Home Assistant action is restricted
  to administrators.
- A Remote Pair secret contains 384 bits of randomness, is shown once, and is
  stored only as a SHA-256 verifier.
- A remote credential binds to the first Shelly device identity, permits one
  identity at a time, and is disconnected on revoke/regenerate.
- Remote Pair is an unauthenticated Home Assistant HTTP view by design because
  a Shelly device cannot use an HA user session. The high-entropy credential is
  the authentication factor.
- Local target input accepts only a host and port, resolves only to private,
  non-loopback/non-link-local addresses, always uses the fixed `/rpc` path, and
  verifies Shelly Gen2+ device information before persistence.
- RPC request and backup sizes are bounded. Event history and stored backup
  count are bounded.
- Backups recursively remove password, passphrase, token, secret, key, private
  key, HA1, and related fields. Diagnostics redact stored credential verifiers.
- Known destructive RPC methods, restore, migration, backup deletion, token
  revoke/regenerate, and script overwrite require explicit confirmation.
- Factory reset and automatic network/auth restore are not implemented.
- Secrets are never intentionally logged.

## Operator responsibilities

Use HTTPS/WSS across untrusted networks, keep Home Assistant patched, protect
administrator accounts, and disable query-string logging for the Remote Pair
endpoint (`/api/shelly_toolkit/remote`). A bearer token copied from the device,
browser, or proxy can be replayed until it is revoked; device binding limits
the impact but cannot make a stolen bearer token safe.

Local Shelly passwords are stored in the Home Assistant config-entry store so
the integration can reconnect after restart. Protect Home Assistant backups
and `.storage` files accordingly.

Downloaded Toolkit backups are secret-redacted but remain sensitive because
they can contain network names, schedules, script source, device IDs, and
topology.

## Recovery

If a Remote Pair URL is exposed:

1. Revoke or regenerate the named credential in Shelly Toolkit.
2. Remove the old URL from the Shelly device.
3. Review Home Assistant and reverse-proxy logs for unexpected connections.
4. Configure the new URL over a trusted administrative path.

If a local device password or backup is exposed, rotate the device credential,
remove and re-add the local target, and treat any disclosed topology/script
information as compromised.

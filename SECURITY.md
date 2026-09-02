# Security policy

Please don't publish vulnerabilities or tokens in a public issue. Contact the
maintainer through a private GitHub security advisory.

The relay intentionally blocks device reset, firmware update, network
reconfiguration and code-execution RPC namespaces unless
`BRIDGE_ALLOW_DANGEROUS_RPC=true` is explicitly configured.

If a device or HA token is exposed:

1. Generate a new random token of at least 32 characters.
2. Replace it in the relay environment.
3. Restart the relay.
4. Replace the affected URL or HA integration credential.

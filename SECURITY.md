# Security Policy

## Reporting a vulnerability

If you believe you have found a security issue in `geolabel-mcp`, please
**do not open a public GitHub issue**. Instead, email the maintainer at
**security@geolabel.dev** with:

- A description of the issue and its impact.
- Steps to reproduce, ideally with a minimal example.
- Any relevant logs or proof-of-concept code.

You can expect:

- An acknowledgement within **3 business days**.
- An assessment and fix plan within **10 business days**.
- A coordinated disclosure once a patched release is available.

## Scope

In scope:

- The `geolabel_mcp` package (this repository).
- The default request path and configuration handling.

Out of scope:

- The upstream `api.geolabel.dev` service. Report those at
  https://geolabel.dev/security.
- Third-party MCP clients (Claude Desktop, OpenClaw, Hermes, etc.) that
  embed this server.

## Privacy invariants

These hold by design and have automated tests guarding them. A
contribution that breaks any of them must include a corresponding
update to `SECURITY.md` and the privacy section of `README.md`.

- **No coordinates leave the machine for clearly-invalid inputs.**
  Bounds checks (`-90 ≤ lat ≤ 90`, `-180 ≤ lng ≤ 180`, `10 ≤ radius ≤ 500`)
  short-circuit before any network call.
- **No coordinates traverse plaintext HTTP.** A non-`https://` base URL
  (other than `localhost` / `127.0.0.1`) is rejected at request time.
- **No request inputs are logged.** Tests assert that the
  `geolabel_mcp` logger emits no records on success or error.
- **No personal data is written to disk.** The in-memory cache is
  bounded (64 entries, 3-minute TTL) and never persists.
- **The API key never appears in error messages or query parameters.**
  It is sent only as the `X-API-Key` header.
- **Coordinates are rounded to ~1 m precision** (5 decimal places)
  before transmission.

## Supported versions

Only the latest published release receives security fixes.

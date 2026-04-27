# Contributing to geolabel-mcp

Thanks for your interest! This is a small, focused MCP server with a
deliberate runtime contract — please read the invariants below before
submitting changes.

## Setup

```bash
git clone https://github.com/TylerCoxDruin/geolabel.git
cd geolabel
python -m pip install -e ".[test,dev]"
pre-commit install   # optional but recommended
```

## Local quality gate

A change is ready to push when all of these pass:

```bash
ruff check .
ruff format --check .
python -m mypy
coverage run -m pytest && coverage report
```

The coverage gate is **90%** (line + branch). The current suite holds
100% — please don't ship a regression.

## Invariants you must not break

These are enforced by tests; if a test fails because of a change you
made here, fix the change, not the test.

1. **No request inputs are logged.** Adding `print(lat, lng, ...)` or
   `logger.info(...)` with coordinates will fail the no-logging tests
   (see `tests/test_security.py`).
2. **No personal data on disk.** The request path must not open files
   in writable mode (see `tests/test_cache.py`).
3. **`https://` only**, except `localhost` / `127.0.0.1` for dev.
4. **Coordinates are rounded to 5 decimals before transmission.**
5. **The API key only travels as the `X-API-Key` header.** Never as a
   query parameter, never in error messages.
6. **Aggregate metrics only.** `geolabel_stats` returns counters and
   percentiles — no inputs, no keys, no per-request detail.

## Architecture

- `geolabel_mcp/_client.py` — shared `httpx.AsyncClient`, retry policy,
  status-code → message map. New tools should call `_client.get(path,
  params)` rather than instantiating their own client.
- `geolabel_mcp/_metrics.py` — process-local counters and the latency
  window. Add new metric kinds here, don't sprinkle counters across
  modules.
- `geolabel_mcp/server.py` — `FastMCP` instance, tool registration,
  per-tool input validation, and the location-specific cache.

## Adding a new tool

1. Implement an `async def my_tool(...)` decorated with `@mcp.tool()`
   in `server.py`.
2. Validate inputs at the top — fail fast before any network call.
3. Call `_client.get("/path", params=...)` and check for the `error`
   key on the result.
4. If the tool deserves caching, add an LRU keyed on the post-validation
   input tuple. Bound it (size cap + TTL).
5. Record metrics: `_metrics.record_request()` at entry and any
   tool-specific cache or error counters.
6. Add tests covering: happy path, the full error matrix, validation
   bounds, cache behavior (if applicable), no-logging, no-API-key-leak.

## Pull requests

- Keep PRs focused; prefer many small PRs to one large one.
- Update `CHANGELOG`-style notes in the PR body, not in tracked files.
- The CI runs lint, mypy, the test matrix on Python 3.10–3.13, and
  `pip-audit`. All four must be green.

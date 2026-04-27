"""Internal HTTP client for the GeoLabel API.

This module owns:
  * Configuration parsing (env vars, captured at import time).
  * The shared `httpx.AsyncClient` — one connection pool per process,
    HTTP/2 enabled, so each tool call avoids a fresh TCP/TLS handshake.
  * The status-code → user-facing error message map. Adding new tools
    means adding a new path here, not duplicating this matrix.

Privacy invariant: this module MUST NOT log request inputs (lat/lng,
API keys, paths) anywhere. Coordinates are processed in-memory and
discarded with the response. If you add logging here, scrub coordinates
first or skip them entirely.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

# Pydantic (used by FastMCP to introspect tool signatures) requires
# typing_extensions.TypedDict on Python < 3.12.
from typing_extensions import TypedDict

from . import _metrics

# ---------------------------------------------------------------------------
# Configuration (captured at import time)
# ---------------------------------------------------------------------------

_API_KEY: str = os.getenv("GEOLABEL_API_KEY", "").strip()
_BASE_URL: str = os.getenv("GEOLABEL_BASE_URL", "https://api.geolabel.dev").rstrip("/")

# Local URLs are allowed for tests / self-hosted dev servers; everything
# else must be https:// so coordinates and the API key never traverse
# the network in clear text.
_INSECURE_LOCAL_PREFIXES = ("http://localhost", "http://127.0.0.1")


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


class LocationLabel(TypedDict, total=False):
    """Successful payload from GET /label."""

    place: str | None
    label: str
    category: str | None
    distance_meters: float | None
    is_open: bool | None
    opens_at: str | None
    closes_at: str | None
    opening_hours: str | None
    cached: bool


class ErrorEnvelope(TypedDict):
    """Uniform error shape returned to MCP clients.

    Always a single key, `error`, holding a human-readable message safe
    to surface to an end user. Never contains the API key or raw
    exception messages.
    """

    error: str


# ---------------------------------------------------------------------------
# Status → message map. New endpoints reuse this; specialise per call only
# when the message needs request-specific context (e.g. echoing parameters
# back on a 422).
# ---------------------------------------------------------------------------

STATUS_MESSAGES: dict[int, str] = {
    401: (
        "Invalid API key. Verify GEOLABEL_API_KEY or generate a new key at https://geolabel.dev."
    ),
    429: ("Rate limit reached. Upgrade your plan at https://geolabel.dev for higher limits."),
    502: ("OpenStreetMap data is temporarily unavailable. Try again in a moment."),
}


# ---------------------------------------------------------------------------
# Shared AsyncClient
# ---------------------------------------------------------------------------

# Latency budget: connect must be quick (DNS + TLS); read can take longer
# because the upstream may be aggregating Overpass results.
_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=5.0)
_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
# Retry on connect-level errors only (pre-request); explicit retry-on-502
# / retry-on-timeout is handled in `get()` so we control the cap.
_TRANSPORT_RETRIES = 1
# Retry once on transient upstream conditions. `/label` is an idempotent
# read so it's safe to repeat. The tiny backoff keeps p99 latency bounded.
_RETRY_STATUSES = frozenset({502})
_RETRY_BACKOFF_SECONDS = 0.2

_client: httpx.AsyncClient | None = None


def _build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=_BASE_URL,
        headers={"X-API-Key": _API_KEY},
        timeout=_TIMEOUT,
        limits=_LIMITS,
        http2=True,
        transport=httpx.AsyncHTTPTransport(retries=_TRANSPORT_RETRIES),
    )


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = _build_client()
    return _client


async def aclose() -> None:
    """Close the shared client. Safe to call from a lifespan hook or atexit."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def _config_error() -> ErrorEnvelope | None:
    """Return an error envelope if the module is misconfigured, else None.

    Both checks run before any network call, so an invalid setup never
    causes coordinates or API keys to leave the machine.
    """
    if not _API_KEY:
        return {
            "error": (
                "GEOLABEL_API_KEY is not configured. "
                "Get a free API key at https://geolabel.dev and add it to your "
                "MCP server environment as GEOLABEL_API_KEY."
            )
        }

    if not _BASE_URL.startswith("https://") and not _BASE_URL.startswith(_INSECURE_LOCAL_PREFIXES):
        return {
            "error": (
                "GEOLABEL_BASE_URL must use https:// to protect coordinates and "
                "the API key in transit. Remove the override to use the default."
            )
        }

    return None


# ---------------------------------------------------------------------------
# Request helper
# ---------------------------------------------------------------------------


async def get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET `path` on the shared client and translate any failure into an
    `ErrorEnvelope`. Returns the raw JSON dict on success.

    Records latency (network only) and error counts in `_metrics`.

    `path` is a path on the configured base URL (e.g. "/label"). Callers
    handle endpoint-specific 422 messaging by inspecting the returned
    envelope and replacing it if needed.
    """
    config_err = _config_error()
    if config_err is not None:
        _metrics.record_client_error("config")
        return dict(config_err)

    client = _get_client()
    started = time.monotonic()

    try:
        response = await _request_with_retry(client, path, params)
        response.raise_for_status()
        _metrics.record_latency_ms((time.monotonic() - started) * 1000)
        return response.json()  # type: ignore[no-any-return]

    except httpx.HTTPStatusError as exc:
        _metrics.record_latency_ms((time.monotonic() - started) * 1000)
        status = exc.response.status_code
        _metrics.record_http_error(status)
        message = STATUS_MESSAGES.get(status, f"GeoLabel API returned HTTP {status}.")
        return {"error": message, "_status": status}

    except httpx.TimeoutException:
        _metrics.record_client_error("timeout")
        return {"error": "Request timed out. The service may be briefly slow - try again."}

    except httpx.HTTPError as exc:
        # Network / transport errors. Include only the exception class so
        # we never leak partial response bodies, header values, or the API
        # key (httpx normally redacts auth, but defence in depth).
        _metrics.record_client_error("network")
        return {"error": f"Network error ({type(exc).__name__})."}

    except Exception as exc:
        # Final safety net: never let an unexpected exception bubble up
        # to the MCP transport. The class name is enough for debugging
        # without leaking the (potentially sensitive) message text.
        _metrics.record_client_error("unexpected")
        return {"error": f"Unexpected error ({type(exc).__name__})."}


async def _request_with_retry(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any],
) -> httpx.Response:
    """One attempt + at most one retry on 502 or TimeoutException.

    Anything else (4xx other than the retry set, network failure that's
    already exhausted transport retries) bubbles up unchanged.
    """
    try:
        response = await client.get(path, params=params)
    except httpx.TimeoutException:
        await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
        return await client.get(path, params=params)

    if response.status_code in _RETRY_STATUSES:
        await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
        return await client.get(path, params=params)

    return response

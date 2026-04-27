"""
GeoLabel MCP Server
===================
Turn GPS coordinates into AI-ready location context for Claude and any
MCP-compatible assistant. Wraps the GeoLabel API (geolabel.dev).

Configuration (environment variables):
    GEOLABEL_API_KEY   Your GeoLabel API key (required). Get one free at geolabel.dev.
    GEOLABEL_BASE_URL  Override the API base URL (optional, must be https://).

Privacy: no coordinates are logged or persisted by this server. Inputs
are rounded to ~1 m precision before transmission, held in process
memory only for the lifetime of one request (or one cache entry, max
3 minutes), and then discarded. Nothing touches disk.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import _client, _metrics
from ._client import ErrorEnvelope, LocationLabel

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="GeoLabel",
    instructions=(
        "GeoLabel converts GPS coordinates into a human-friendly place name, "
        "a stable category (gym, supermarket, restaurant, gas_station, pharmacy ...), "
        "and real-time opening-hours status. "
        "Call get_location_label whenever the user shares coordinates or asks "
        "what is at a specific location. "
        "Use 'category' for decisions, 'label' for display, and the hours "
        "fields (is_open, closes_at, opens_at) to answer time-sensitive questions. "
        "If is_open is null the place has no hours data in OpenStreetMap - "
        "do not guess; tell the user hours are unavailable for that location. "
        "Call geolabel_stats only when an operator asks for server health or latency."
    ),
)

# ---------------------------------------------------------------------------
# Coordinate rounding
# ---------------------------------------------------------------------------

# 5 decimal places ≈ 1.1 m at the equator. The /label endpoint matches
# venues by `radius` so anything finer is wasted bandwidth and a small
# privacy leak. Rounding also makes the cache key stable for repeat
# lookups in the same neighbourhood.
_COORD_DECIMALS = 5


def _round_coords(lat: float, lng: float) -> tuple[float, float]:
    return (round(lat, _COORD_DECIMALS), round(lng, _COORD_DECIMALS))


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _validate_inputs(lat: float, lng: float, radius: int) -> ErrorEnvelope | None:
    """Fail-fast input bounds checks.

    These run before any network call so clearly-invalid coordinates
    never leave the machine and we save a round-trip to the server.
    """
    if not -90.0 <= lat <= 90.0:
        return {"error": "Latitude must be between -90 and 90."}
    if not -180.0 <= lng <= 180.0:
        return {"error": "Longitude must be between -180 and 180."}
    if not 10 <= radius <= 500:
        return {"error": "Radius must be between 10 and 500 metres."}
    return None


# ---------------------------------------------------------------------------
# In-memory LRU + TTL cache
#
# Repeat calls within ~3 minutes (e.g. the assistant asking the same
# question twice in a session) bypass the network entirely. Bounded
# size keeps the memory footprint constant. No disk writes, ever.
# ---------------------------------------------------------------------------

_CACHE_MAX_ENTRIES = 64
_CACHE_TTL_SECONDS = 180.0
_CacheKey = tuple[float, float, int]
_cache: OrderedDict[_CacheKey, tuple[float, dict[str, Any]]] = OrderedDict()


def _cache_get(key: _CacheKey) -> dict[str, Any] | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    timestamp, value = entry
    if time.monotonic() - timestamp > _CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    # Defensive copy so the caller can't mutate the cached value.
    return dict(value)


def _cache_set(key: _CacheKey, value: dict[str, Any]) -> None:
    _cache[key] = (time.monotonic(), dict(value))
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_location_label(
    lat: float, lng: float, radius: int = 100
) -> LocationLabel | ErrorEnvelope:
    """
    Identify a place from GPS coordinates and return its label, category,
    and live opening-hours status.

    Use this whenever the user provides coordinates or asks what is at a
    location. The response gives Claude everything needed to answer
    location-aware questions - place name, type, whether it is open right
    now, and when it closes or next opens.

    Args:
        lat:    Latitude in decimal degrees (-90 to 90).
        lng:    Longitude in decimal degrees (-180 to 180).
        radius: Search radius in metres (10-500). Smaller values pin to
                the nearest place precisely; larger values cast a wider
                net. Default 100 m.

    Returns a dict with:
        place           Raw venue name from OpenStreetMap.
        label           Clean, user-friendly name - "Walmart", "Planet Fitness", etc.
        category        Stable place type for logic: "gym", "supermarket", etc.
        distance_meters Distance from your coordinates to the matched place.
        is_open         true / false / null (no hours data in OSM).
        opens_at        Next opening time "HH:MM" (when closed). null otherwise.
        closes_at       Today's closing time "HH:MM" (when open). null otherwise.
        opening_hours   Raw OSM opening_hours string, or null.
        cached          true if the upstream served from its 10-min cache.
                        Hours fields are always recomputed live.

    On error returns {"error": "<message>"}. Errors are safe to surface
    to the end user and never contain the API key or raw exception text.
    Coordinates are rounded to ~1 m precision before transmission.
    """
    _metrics.record_request()

    validation_error = _validate_inputs(lat, lng, radius)
    if validation_error is not None:
        _metrics.record_client_error("validation")
        return validation_error

    lat_r, lng_r = _round_coords(lat, lng)
    key: _CacheKey = (lat_r, lng_r, radius)

    cached = _cache_get(key)
    if cached is not None:
        _metrics.record_cache_hit()
        return cached  # type: ignore[return-value]
    _metrics.record_cache_miss()

    result = await _client.get("/label", params={"lat": lat_r, "lng": lng_r, "radius": radius})

    if result.get("_status") == 422:
        return {
            "error": (
                f"Invalid parameters: lat={lat_r}, lng={lng_r}, radius={radius}. "
                "Latitude must be -90 to 90, longitude -180 to 180, radius 10 to 500."
            )
        }

    result.pop("_status", None)

    # Only cache successful responses. Caching errors would lock users
    # out for the TTL window after a transient failure.
    if "error" not in result:
        _cache_set(key, result)

    return result  # type: ignore[return-value]


@mcp.tool()
async def geolabel_stats() -> dict[str, Any]:
    """
    Return aggregate health/performance counters for this MCP server.

    Useful for an operator (or the assistant, if asked) to verify the
    server is responsive and see whether any errors are accumulating.

    The snapshot contains only aggregate numbers - no coordinates, no
    request inputs, no API keys. Counters reset whenever the server
    process restarts.

    Returns:
        total_requests:    Tool invocations seen since startup.
        cache:             {hits, misses, hit_rate} for the local LRU cache.
        errors_by_status:  Map of upstream HTTP status -> count.
        client_errors:     Map of failure category (validation / config /
                           network / timeout / unexpected) -> count.
        latency_ms:        {count, p50, p95, p99} over the last 128
                           network calls (cache hits excluded).
        uptime_seconds:    Time since the server module loaded.
    """
    return _metrics.snapshot()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

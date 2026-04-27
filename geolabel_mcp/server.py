"""
GeoLabel MCP Server
===================
Turn GPS coordinates into AI-ready location context for Claude and any
MCP-compatible assistant. Wraps the GeoLabel API (geolabel.dev).

Configuration (environment variables):
    GEOLABEL_API_KEY   Your GeoLabel API key (required). Get one free at geolabel.dev.
    GEOLABEL_BASE_URL  Override the API base URL (optional, must be https://).

Privacy: no coordinates are logged or persisted by this server. They live
in process memory for the duration of one request and are then discarded.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import _client
from ._client import ErrorEnvelope, LocationLabel

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="GeoLabel",
    instructions=(
        "GeoLabel converts GPS coordinates into a human-friendly place name, "
        "a stable category (gym, supermarket, restaurant, gas_station, pharmacy …), "
        "and real-time opening-hours status. "
        "Call get_location_label whenever the user shares coordinates or asks "
        "what is at a specific location. "
        "Use 'category' for decisions, 'label' for display, and the hours "
        "fields (is_open, closes_at, opens_at) to answer time-sensitive questions. "
        "If is_open is null the place has no hours data in OpenStreetMap — "
        "do not guess; tell the user hours are unavailable for that location."
    ),
)

# ---------------------------------------------------------------------------
# Tools
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


@mcp.tool()
async def get_location_label(
    lat: float, lng: float, radius: int = 100
) -> LocationLabel | ErrorEnvelope:
    """
    Identify a place from GPS coordinates and return its label, category,
    and live opening-hours status.

    Use this whenever the user provides coordinates or asks what is at a
    location. The response gives Claude everything needed to answer
    location-aware questions — place name, type, whether it is open right
    now, and when it closes or next opens.

    Args:
        lat:    Latitude in decimal degrees (-90 to 90).
        lng:    Longitude in decimal degrees (-180 to 180).
        radius: Search radius in metres (10-500). Smaller values pin to
                the nearest place precisely; larger values cast a wider
                net. Default 100 m.

    Returns a dict with:
        place           Raw venue name from OpenStreetMap (may include branch
                        numbers or location suffixes). Prefer 'label' for display.
        label           Clean, user-friendly name — e.g. "Walmart", "Planet Fitness",
                        "Starbucks". Use this for display and speech.
        category        Stable place type for logic: "gym", "supermarket",
                        "restaurant", "fast_food", "gas_station", "pharmacy",
                        "hospital", "cafe", "retail", etc.
        distance_meters Distance in metres from the supplied coordinates to the
                        matched place centroid.
        is_open         true  → currently open.
                        false → currently closed.
                        null  → OpenStreetMap has no hours data for this place.
        opens_at        Next opening time as "HH:MM" (24-hour). Populated when
                        is_open is false so you know when it reopens.
                        null when open, or when hours are unknown.
        closes_at       Today's closing time as "HH:MM" (24-hour). Populated when
                        is_open is true — subtract current time to get minutes
                        remaining. null when closed or hours unknown.
        opening_hours   Raw OpenStreetMap opening_hours string, e.g.
                        "Mo-Fr 09:00-18:00; Sa 10:00-17:00". null if not set in OSM.
        cached          true if place data was served from the 10-minute in-memory
                        cache. Hours fields are always recalculated live against
                        the current time, even on cache hits.

    On error returns {"error": "<message>"}. Errors are safe to surface to
    the end user and never contain the API key or raw exception details.
    """
    validation_error = _validate_inputs(lat, lng, radius)
    if validation_error is not None:
        return validation_error

    result = await _client.get("/label", params={"lat": lat, "lng": lng, "radius": radius})

    # Endpoint-specific 422 message — generic STATUS_MESSAGES doesn't have
    # the input context the user needs to fix their call.
    if result.get("_status") == 422:
        return {
            "error": (
                f"Invalid parameters: lat={lat}, lng={lng}, radius={radius}. "
                "Latitude must be -90-90, longitude -180-180, radius 10-500."
            )
        }
    result.pop("_status", None)
    return result  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

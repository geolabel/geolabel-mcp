"""Client-side input bounds tests.

These guard the privacy and latency promise: clearly-invalid coordinates
never leave the machine. Bounds violations short-circuit before the
shared AsyncClient is even consulted.
"""

from __future__ import annotations

import pytest
import respx


@pytest.mark.parametrize(
    "lat, lng, radius, fragment",
    [
        (91.0, 0.0, 100, "Latitude must be between -90 and 90"),
        (-91.0, 0.0, 100, "Latitude must be between -90 and 90"),
        (float("nan"), 0.0, 100, "Latitude must be between -90 and 90"),
        (float("inf"), 0.0, 100, "Latitude must be between -90 and 90"),
        (0.0, 181.0, 100, "Longitude must be between -180 and 180"),
        (0.0, -181.0, 100, "Longitude must be between -180 and 180"),
        (0.0, 0.0, 9, "Radius must be between 10 and 500"),
        (0.0, 0.0, 501, "Radius must be between 10 and 500"),
        (0.0, 0.0, 0, "Radius must be between 10 and 500"),
        (0.0, 0.0, -1, "Radius must be between 10 and 500"),
    ],
)
async def test_invalid_input_short_circuits_before_network(server, lat, lng, radius, fragment):
    with respx.mock(assert_all_called=False) as router:
        route = router.get("https://api.geolabel.dev/label")
        result = await server.get_location_label(lat=lat, lng=lng, radius=radius)

    assert fragment in result["error"]
    assert not route.called, "request must not be sent for invalid inputs"


@pytest.mark.parametrize(
    "lat, lng, radius",
    [
        (90.0, 180.0, 500),
        (-90.0, -180.0, 10),
        (0.0, 0.0, 100),
    ],
)
async def test_boundary_values_are_accepted(server, lat, lng, radius):
    """Inclusive bounds — exactly 90/-90/180/-180/10/500 must be allowed."""
    import httpx

    with respx.mock() as router:
        route = router.get("https://api.geolabel.dev/label").mock(
            return_value=httpx.Response(200, json={"label": "x"})
        )
        result = await server.get_location_label(lat=lat, lng=lng, radius=radius)

    assert result == {"label": "x"}
    assert route.called

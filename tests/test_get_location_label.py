"""HTTP error branch matrix and happy-path tests for get_location_label."""

from __future__ import annotations

import httpx
import pytest
import respx


SUCCESS_PAYLOAD = {
    "place": "Walmart Supercenter #1234",
    "label": "Walmart",
    "category": "supermarket",
    "distance_meters": 12.4,
    "is_open": True,
    "opens_at": None,
    "closes_at": "23:00",
    "opening_hours": "Mo-Su 06:00-23:00",
    "cached": False,
}


@respx.mock
async def test_happy_path_returns_parsed_payload(server):
    route = respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json=SUCCESS_PAYLOAD)
    )

    result = await server.get_location_label(lat=41.8827, lng=-87.6233)

    assert result == SUCCESS_PAYLOAD
    assert route.called
    request = route.calls.last.request
    assert request.headers["X-API-Key"] == "test-api-key"
    assert request.url.params["lat"] == "41.8827"
    assert request.url.params["lng"] == "-87.6233"
    assert request.url.params["radius"] == "100"  # default


@respx.mock
async def test_radius_override_is_forwarded(server):
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json=SUCCESS_PAYLOAD)
    )

    await server.get_location_label(lat=0.0, lng=0.0, radius=350)

    request = respx.calls.last.request
    assert request.url.params["radius"] == "350"


async def test_missing_api_key_short_circuits(server_factory):
    """No env var set → no HTTP call, helpful error returned."""
    module = server_factory(api_key=None)

    with respx.mock(assert_all_called=False) as router:
        route = router.get("https://api.geolabel.dev/label")
        result = await module.get_location_label(lat=1.0, lng=2.0)

    assert "GEOLABEL_API_KEY is not configured" in result["error"]
    assert "geolabel.dev" in result["error"]
    assert not route.called


@pytest.mark.parametrize(
    "status, expected_fragment",
    [
        (401, "Invalid API key"),
        (429, "Rate limit reached"),
        (502, "OpenStreetMap data is temporarily unavailable"),
        (500, "HTTP 500"),
        (503, "HTTP 503"),
    ],
)
@respx.mock
async def test_http_error_branches(server, status, expected_fragment):
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(status, json={"detail": "nope"})
    )

    result = await server.get_location_label(lat=1.0, lng=2.0)

    assert "error" in result
    assert expected_fragment in result["error"]


@respx.mock
async def test_http_422_echoes_input_parameters(server):
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(422, json={"detail": "bad"})
    )

    result = await server.get_location_label(lat=999.0, lng=-555.0, radius=10000)

    assert "Invalid parameters" in result["error"]
    assert "lat=999.0" in result["error"]
    assert "lng=-555.0" in result["error"]
    assert "radius=10000" in result["error"]


@respx.mock
async def test_timeout_returns_friendly_message(server):
    respx.get("https://api.geolabel.dev/label").mock(
        side_effect=httpx.TimeoutException("slow")
    )

    result = await server.get_location_label(lat=1.0, lng=2.0)

    assert "timed out" in result["error"].lower()


@respx.mock
async def test_unexpected_exception_is_caught(server):
    respx.get("https://api.geolabel.dev/label").mock(
        side_effect=RuntimeError("boom")
    )

    result = await server.get_location_label(lat=1.0, lng=2.0)

    assert result["error"].startswith("Unexpected error:")
    assert "boom" in result["error"]

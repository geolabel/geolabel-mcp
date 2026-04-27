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
async def test_http_502_retries_then_returns_friendly_error(server):
    """502 is transient (OSM upstream); we retry once before giving up."""
    route = respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(502, json={"detail": "osm down"})
    )

    result = await server.get_location_label(lat=1.0, lng=2.0)

    assert "OpenStreetMap data is temporarily unavailable" in result["error"]
    assert route.call_count == 2  # original + 1 retry


@respx.mock
async def test_http_502_retry_succeeds(server):
    """If the retry succeeds the user sees a normal payload."""
    route = respx.get("https://api.geolabel.dev/label").mock(
        side_effect=[
            httpx.Response(502, json={"detail": "osm down"}),
            httpx.Response(200, json=SUCCESS_PAYLOAD),
        ]
    )

    result = await server.get_location_label(lat=1.0, lng=2.0)

    assert result == SUCCESS_PAYLOAD
    assert route.call_count == 2


@respx.mock
async def test_http_422_echoes_input_parameters(server):
    """A 422 from the server (in-bounds inputs the server still rejects)
    surfaces the values back so the user can fix the call."""
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(422, json={"detail": "bad"})
    )

    # Inputs are within client-side bounds so the request is sent;
    # the server returns 422 anyway (e.g. weird precision).
    result = await server.get_location_label(lat=45.0, lng=-90.0, radius=100)

    assert "Invalid parameters" in result["error"]
    assert "lat=45.0" in result["error"]
    assert "lng=-90.0" in result["error"]
    assert "radius=100" in result["error"]


@respx.mock
async def test_timeout_retries_then_returns_friendly_message(server):
    route = respx.get("https://api.geolabel.dev/label").mock(
        side_effect=httpx.TimeoutException("slow")
    )

    result = await server.get_location_label(lat=1.0, lng=2.0)

    assert "timed out" in result["error"].lower()
    assert route.call_count == 2  # original + 1 retry


@respx.mock
async def test_timeout_retry_succeeds(server):
    route = respx.get("https://api.geolabel.dev/label").mock(
        side_effect=[
            httpx.TimeoutException("slow"),
            httpx.Response(200, json=SUCCESS_PAYLOAD),
        ]
    )

    result = await server.get_location_label(lat=1.0, lng=2.0)

    assert result == SUCCESS_PAYLOAD
    assert route.call_count == 2


@respx.mock
async def test_network_error_returns_generic_message(server):
    """Network errors must not leak the underlying exception message."""
    respx.get("https://api.geolabel.dev/label").mock(
        side_effect=httpx.ConnectError("dns failure for api.geolabel.dev")
    )

    result = await server.get_location_label(lat=1.0, lng=2.0)

    assert "Network error" in result["error"]
    assert "ConnectError" in result["error"]
    # The exception's free-text message must not be echoed.
    assert "dns failure" not in result["error"]


@respx.mock
async def test_unexpected_exception_is_caught_without_leak(server):
    respx.get("https://api.geolabel.dev/label").mock(
        side_effect=RuntimeError("internal token=secret123")
    )

    result = await server.get_location_label(lat=1.0, lng=2.0)

    assert result["error"].startswith("Unexpected error")
    assert "RuntimeError" in result["error"]
    # The exception's free-text message must not be echoed.
    assert "secret123" not in result["error"]
    assert "internal token" not in result["error"]


@respx.mock
async def test_status_field_not_leaked_to_caller(server):
    """The internal _status field used to route 422 messaging must not
    appear in the response returned to the MCP client."""
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json=SUCCESS_PAYLOAD)
    )

    result = await server.get_location_label(lat=1.0, lng=2.0)

    assert "_status" not in result

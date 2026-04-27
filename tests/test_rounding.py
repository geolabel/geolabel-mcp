"""Coordinate rounding tests.

Inputs are rounded to ~1 m precision before transmission so the
upstream service never sees sub-metre detail (a privacy nudge) and
so the cache key is stable for repeat lookups in the same area.
"""

from __future__ import annotations

import httpx
import respx


@respx.mock
async def test_lat_lng_rounded_to_5_decimals(server):
    route = respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "x"})
    )

    await server.get_location_label(lat=41.882702345678, lng=-87.62331111111)

    request = route.calls.last.request
    assert request.url.params["lat"] == "41.8827"
    assert request.url.params["lng"] == "-87.62331"


@respx.mock
async def test_already_rounded_inputs_pass_through(server):
    route = respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "x"})
    )

    await server.get_location_label(lat=41.8827, lng=-87.6233)

    request = route.calls.last.request
    assert request.url.params["lat"] == "41.8827"
    assert request.url.params["lng"] == "-87.6233"


@respx.mock
async def test_two_calls_within_rounding_window_share_cache(server):
    """Two coordinates that round to the same 5-decimal value should
    produce a single network call thanks to the cache."""
    route = respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "x"})
    )

    await server.get_location_label(lat=41.882700123, lng=-87.62330456)
    await server.get_location_label(lat=41.882699987, lng=-87.62330111)

    assert route.call_count == 1

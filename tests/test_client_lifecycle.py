"""Tests for the shared AsyncClient lifecycle.

The client is constructed lazily on first request and cached for the
process lifetime so subsequent calls reuse the same TLS + HTTP/2
connection pool. `aclose()` lets a lifespan hook tear it down cleanly.
"""

from __future__ import annotations

import httpx
import respx


@respx.mock
async def test_async_client_is_reused_across_calls(server, handle):
    """Two consecutive calls must hit the same client instance — that's
    the whole point of the connection-pool reuse."""
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "a"})
    )

    assert handle.client._client is None

    await server.get_location_label(lat=1.0, lng=2.0)
    first = handle.client._client
    assert first is not None

    await server.get_location_label(lat=3.0, lng=4.0)
    second = handle.client._client
    assert second is first


async def test_aclose_resets_cached_client(server, handle):
    import httpx as _httpx

    with respx.mock() as router:
        router.get("https://api.geolabel.dev/label").mock(
            return_value=_httpx.Response(200, json={"label": "ok"})
        )
        await server.get_location_label(lat=1.0, lng=2.0)

    assert handle.client._client is not None

    await handle.client.aclose()

    assert handle.client._client is None


async def test_aclose_is_noop_when_no_client(handle):
    assert handle.client._client is None
    await handle.client.aclose()  # must not raise
    assert handle.client._client is None

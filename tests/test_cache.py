"""Tests for the in-memory LRU + TTL cache.

The cache trades a small amount of in-RAM coordinate retention for
zero-network repeat lookups. It must:
  * Hit on identical post-rounding coordinate triples within the TTL.
  * Miss after the TTL expires.
  * Evict the least-recently-used entry when the size cap is reached.
  * Never cache error responses.
  * Never write to disk.
"""

from __future__ import annotations

import builtins

import httpx
import respx


@respx.mock
async def test_cache_hits_avoid_network(server):
    route = respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "x"})
    )

    a = await server.get_location_label(lat=1.0, lng=2.0)
    b = await server.get_location_label(lat=1.0, lng=2.0)

    assert a == b == {"label": "x"}
    assert route.call_count == 1


@respx.mock
async def test_cache_distinguishes_radius(server):
    route = respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "x"})
    )

    await server.get_location_label(lat=1.0, lng=2.0, radius=100)
    await server.get_location_label(lat=1.0, lng=2.0, radius=200)

    assert route.call_count == 2


@respx.mock
async def test_cache_ttl_expires(server, monkeypatch):
    """After the TTL window, a repeat lookup must hit the network again."""
    route = respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "x"})
    )

    fake_time = [1000.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: fake_time[0])

    await server.get_location_label(lat=1.0, lng=2.0)
    fake_time[0] += server._CACHE_TTL_SECONDS + 1
    await server.get_location_label(lat=1.0, lng=2.0)

    assert route.call_count == 2


@respx.mock
async def test_cache_evicts_when_full(server):
    """Filling beyond _CACHE_MAX_ENTRIES should evict the oldest entry,
    so a re-lookup of the first key hits the network again."""
    route = respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "x"})
    )

    cap = server._CACHE_MAX_ENTRIES

    # First entry — will be evicted as we fill past the cap.
    await server.get_location_label(lat=0.0, lng=0.0)
    # Fill up to the cap with distinct keys (cap entries total after this).
    for i in range(1, cap):
        await server.get_location_label(lat=float(i) * 0.001, lng=0.0)
    # One more distinct entry → forces eviction of the first.
    await server.get_location_label(lat=89.0, lng=0.0)

    calls_before = route.call_count
    # Re-lookup the first key — it should be a miss now.
    await server.get_location_label(lat=0.0, lng=0.0)
    assert route.call_count == calls_before + 1


@respx.mock
async def test_errors_are_not_cached(server):
    """A transient 500 must not poison the cache for the TTL window."""
    route = respx.get("https://api.geolabel.dev/label").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json={"label": "ok"}),
        ]
    )

    first = await server.get_location_label(lat=1.0, lng=2.0)
    second = await server.get_location_label(lat=1.0, lng=2.0)

    assert "error" in first
    assert second == {"label": "ok"}
    assert route.call_count == 2


@respx.mock
async def test_validation_errors_do_not_pollute_cache(server):
    """Out-of-range inputs short-circuit; the next valid call must miss."""
    route = respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "ok"})
    )

    await server.get_location_label(lat=999.0, lng=0.0)  # validation error
    result = await server.get_location_label(lat=1.0, lng=2.0)

    assert result == {"label": "ok"}
    assert route.call_count == 1


@respx.mock
async def test_cached_response_is_independent_of_caller_mutation(server):
    """Mutating a returned dict must not corrupt the cache entry."""
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "ok", "category": "gym"})
    )

    first = await server.get_location_label(lat=1.0, lng=2.0)
    first["category"] = "MUTATED"

    second = await server.get_location_label(lat=1.0, lng=2.0)
    assert second["category"] == "gym"


@respx.mock
async def test_no_disk_writes_on_request_path(server, monkeypatch):
    """The request path must not open any file in a writable mode.

    This is the automated guardrail behind the "no personal data on disk"
    promise. Read-only opens (e.g. mimetype tables, certs) are allowed.
    """
    real_open = builtins.open
    writable_modes = {"w", "a", "x", "w+", "a+", "r+", "wb", "ab", "xb", "wb+", "ab+", "rb+"}
    bad_paths: list[str] = []

    def guarded_open(file, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        if any(m in writable_modes for m in [mode]):
            bad_paths.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)

    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "ok"})
    )

    await server.get_location_label(lat=1.0, lng=2.0)
    await server.get_location_label(lat=1.0, lng=2.0)  # cache hit

    assert bad_paths == [], f"writable file opened on request path: {bad_paths}"

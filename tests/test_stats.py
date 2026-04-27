"""Tests for the geolabel_stats MCP tool and the metrics it exposes.

The metrics surface is part of the public contract — the assistant
will call this tool and read the keys back, so changes here are
breaking changes.
"""

from __future__ import annotations

import httpx
import respx

# ---------------------------------------------------------------------------
# Snapshot shape
# ---------------------------------------------------------------------------


async def test_initial_snapshot_has_zero_counters(server):
    snap = await server.geolabel_stats()

    assert snap["total_requests"] == 0
    assert snap["cache"] == {"hits": 0, "misses": 0, "hit_rate": 0.0}
    assert snap["errors_by_status"] == {}
    assert snap["client_errors"] == {
        "validation": 0,
        "config": 0,
        "network": 0,
        "timeout": 0,
        "unexpected": 0,
    }
    assert snap["latency_ms"] == {"count": 0, "p50": None, "p95": None, "p99": None}
    assert snap["uptime_seconds"] >= 0.0


def _walk_keys_and_strs(value):
    """Yield every dict key and every string value found in `value`."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _walk_keys_and_strs(v)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys_and_strs(item)
    elif isinstance(value, str):
        yield value


async def test_snapshot_contains_no_personal_data(server):
    """Belt-and-braces: the snapshot keys and string values must not
    name any user input. Inspecting structure (not raw repr) avoids
    false positives from words like 'latency_ms'."""
    snap = await server.geolabel_stats()

    forbidden = {
        "latitude",
        "longitude",
        "lng",
        "coords",
        "coordinates",
        "api_key",
        "apikey",
        "token",
        "secret",
    }
    for token in _walk_keys_and_strs(snap):
        lowered = token.lower()
        assert lowered not in forbidden, f"snapshot leaks {token!r}: {snap}"


# ---------------------------------------------------------------------------
# Counter behaviour
# ---------------------------------------------------------------------------


@respx.mock
async def test_total_requests_counts_every_invocation(server):
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "x"})
    )

    await server.get_location_label(lat=1.0, lng=2.0)
    await server.get_location_label(lat=1.0, lng=2.0)  # cache hit
    await server.get_location_label(lat=999.0, lng=2.0)  # validation error

    snap = await server.geolabel_stats()
    assert snap["total_requests"] == 3


@respx.mock
async def test_cache_hit_rate_counts_correctly(server):
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "x"})
    )

    # 1 miss + 2 hits → hit_rate 2/3.
    await server.get_location_label(lat=1.0, lng=2.0)
    await server.get_location_label(lat=1.0, lng=2.0)
    await server.get_location_label(lat=1.0, lng=2.0)

    snap = await server.geolabel_stats()
    assert snap["cache"]["hits"] == 2
    assert snap["cache"]["misses"] == 1
    assert snap["cache"]["hit_rate"] == round(2 / 3, 3)


@respx.mock
async def test_validation_errors_counted_separately(server):
    await server.get_location_label(lat=999.0, lng=0.0)
    await server.get_location_label(lat=0.0, lng=999.0)

    snap = await server.geolabel_stats()
    assert snap["client_errors"]["validation"] == 2
    # No network call happened, so no latency samples either.
    assert snap["latency_ms"]["count"] == 0


@respx.mock
async def test_http_status_errors_counted(server):
    respx.get("https://api.geolabel.dev/label").mock(return_value=httpx.Response(429))

    await server.get_location_label(lat=1.0, lng=2.0)

    snap = await server.geolabel_stats()
    assert snap["errors_by_status"] == {429: 1}


@respx.mock
async def test_502_retry_records_two_status_errors(server):
    """Each 502 (initial + retry) counts — operators see real upstream pain."""
    respx.get("https://api.geolabel.dev/label").mock(return_value=httpx.Response(502))

    await server.get_location_label(lat=1.0, lng=2.0)

    snap = await server.geolabel_stats()
    # Only the final HTTPStatusError is recorded (raise_for_status fires once).
    assert snap["errors_by_status"] == {502: 1}


@respx.mock
async def test_timeout_recorded_as_client_error(server):
    respx.get("https://api.geolabel.dev/label").mock(side_effect=httpx.TimeoutException("slow"))

    await server.get_location_label(lat=1.0, lng=2.0)

    snap = await server.geolabel_stats()
    assert snap["client_errors"]["timeout"] == 1


@respx.mock
async def test_network_error_recorded_as_client_error(server):
    respx.get("https://api.geolabel.dev/label").mock(side_effect=httpx.ConnectError("no route"))

    await server.get_location_label(lat=1.0, lng=2.0)

    snap = await server.geolabel_stats()
    assert snap["client_errors"]["network"] == 1


async def test_config_error_counted(server_factory):
    module = server_factory(api_key=None)
    await module.get_location_label(lat=1.0, lng=2.0)

    snap = await module.geolabel_stats()
    assert snap["client_errors"]["config"] == 1


@respx.mock
async def test_unexpected_error_recorded(server):
    respx.get("https://api.geolabel.dev/label").mock(side_effect=RuntimeError("kaboom"))

    await server.get_location_label(lat=1.0, lng=2.0)

    snap = await server.geolabel_stats()
    assert snap["client_errors"]["unexpected"] == 1


# ---------------------------------------------------------------------------
# Latency window
# ---------------------------------------------------------------------------


@respx.mock
async def test_latency_window_populates_after_network_calls(server):
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "x"})
    )

    for i in range(5):
        await server.get_location_label(lat=float(i), lng=0.0)

    snap = await server.geolabel_stats()
    assert snap["latency_ms"]["count"] == 5
    assert snap["latency_ms"]["p50"] is not None
    assert snap["latency_ms"]["p99"] is not None


@respx.mock
async def test_cache_hits_excluded_from_latency_window(server):
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "x"})
    )

    # 1 miss + 9 hits → only 1 latency sample.
    for _ in range(10):
        await server.get_location_label(lat=1.0, lng=2.0)

    snap = await server.geolabel_stats()
    assert snap["latency_ms"]["count"] == 1


@respx.mock
async def test_latency_window_is_bounded(server, handle):
    """Window size is fixed; long runs don't grow memory unbounded."""
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "x"})
    )

    cap = handle.metrics._LATENCY_WINDOW
    # Generate cap+10 distinct keys so each call is a network call.
    for i in range(cap + 10):
        await server.get_location_label(lat=float(i) * 0.001, lng=0.0)

    snap = await server.geolabel_stats()
    assert snap["latency_ms"]["count"] == cap


def test_unknown_client_error_kind_falls_back_to_unexpected(handle):
    handle.metrics.record_client_error("not-a-real-bucket")

    snap = handle.metrics.snapshot()
    assert snap["client_errors"]["unexpected"] == 1

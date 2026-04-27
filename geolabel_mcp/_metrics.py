"""Process-local metrics for the GeoLabel MCP server.

Tracks aggregate counters and a small sliding window of latencies so the
assistant (or an operator) can ask `geolabel_stats` and see whether the
server is healthy and fast. By design this module:

  * Stores **only aggregate numbers** — no coordinates, no API keys, no
    request bodies. The privacy invariant that holds for the request
    path also holds here.
  * Keeps everything in process memory, capped to a fixed footprint
    (the latency deque is bounded). No disk, no network.

Tests reset the module between cases by reloading it.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

# Total number of `get_location_label` invocations seen (including
# validation failures and cache hits).
_total_requests: int = 0

_cache_hits: int = 0
_cache_misses: int = 0

# HTTP status codes returned by the upstream API, e.g. {429: 3, 502: 1}.
_errors_by_status: dict[int, int] = {}

# Failures that never reached or never received a response from the API.
_client_errors: dict[str, int] = {
    "validation": 0,  # bounds check failed before any network call
    "config": 0,  # missing/empty key, non-https base URL
    "network": 0,  # connection error, dns failure, etc.
    "timeout": 0,
    "unexpected": 0,  # safety net: unforeseen exception class
}

# Latency window for network calls only (cache hits don't enter this
# distribution — they'd skew p50 toward zero and obscure real network
# pain). Bounded by maxlen so memory is constant.
_LATENCY_WINDOW = 128
_latency_ms: deque[float] = deque(maxlen=_LATENCY_WINDOW)


# ---------------------------------------------------------------------------
# Recording helpers
# ---------------------------------------------------------------------------


def record_request() -> None:
    global _total_requests
    _total_requests += 1


def record_cache_hit() -> None:
    global _cache_hits
    _cache_hits += 1


def record_cache_miss() -> None:
    global _cache_misses
    _cache_misses += 1


def record_http_error(status: int) -> None:
    _errors_by_status[status] = _errors_by_status.get(status, 0) + 1


def record_client_error(kind: str) -> None:
    """`kind` must be one of the keys in `_client_errors`."""
    if kind not in _client_errors:
        # Unknown bucket → file under "unexpected" so we never silently drop
        # data. Keeps the keyspace closed for callers reading the snapshot.
        _client_errors["unexpected"] += 1
        return
    _client_errors[kind] += 1


def record_latency_ms(ms: float) -> None:
    _latency_ms.append(ms)


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def _percentile(sorted_samples: list[float], p: float) -> float | None:
    n = len(sorted_samples)
    if n == 0:
        return None
    # Nearest-rank percentile, biased low — we'd rather under-claim p99
    # than over-claim it.
    idx = min(int(n * p), n - 1)
    return round(sorted_samples[idx], 2)


def snapshot() -> dict[str, Any]:
    """Read-only, point-in-time view of all counters.

    Safe to call concurrently with recorders — at worst a single
    increment is missed, which is fine for monitoring purposes.
    """
    sorted_samples = sorted(_latency_ms)
    total_cache = _cache_hits + _cache_misses
    return {
        "total_requests": _total_requests,
        "cache": {
            "hits": _cache_hits,
            "misses": _cache_misses,
            "hit_rate": round(_cache_hits / total_cache, 3) if total_cache else 0.0,
        },
        "errors_by_status": dict(_errors_by_status),
        "client_errors": dict(_client_errors),
        "latency_ms": {
            "count": len(sorted_samples),
            "p50": _percentile(sorted_samples, 0.50),
            "p95": _percentile(sorted_samples, 0.95),
            "p99": _percentile(sorted_samples, 0.99),
        },
        "uptime_seconds": round(time.monotonic() - _started_at, 1),
    }


# Captured at import time so reloading the module resets the clock.
_started_at: float = time.monotonic()

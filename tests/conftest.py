"""Shared fixtures for the geolabel_mcp test suite.

Configuration (`_API_KEY`, `_BASE_URL`) is captured at import time in
`geolabel_mcp._client`, so tests that need to vary those values must
reload that module after patching the environment. Reloading also
resets the cached `AsyncClient` reference to None, so each test starts
with a clean connection pool.
"""

from __future__ import annotations

import importlib
import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from types import ModuleType

import pytest

import geolabel_mcp._client as _client_module
import geolabel_mcp._metrics as _metrics_module
import geolabel_mcp.server as _server_module


@dataclass
class ServerHandle:
    server: ModuleType
    client: ModuleType
    metrics: ModuleType


def _reload(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_key: str | None,
    base_url: str | None,
) -> ServerHandle:
    if api_key is None:
        monkeypatch.delenv("GEOLABEL_API_KEY", raising=False)
    else:
        monkeypatch.setenv("GEOLABEL_API_KEY", api_key)

    if base_url is None:
        monkeypatch.delenv("GEOLABEL_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("GEOLABEL_BASE_URL", base_url)

    # Suppress the "unclosed client" ResourceWarning that httpx may emit
    # when the previous test's cached client is garbage-collected. The
    # transport sockets close on GC; we just don't await aclose() because
    # doing so requires the right event loop and is fragile across
    # pytest-asyncio versions.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        importlib.reload(_metrics_module)
        importlib.reload(_client_module)
        importlib.reload(_server_module)

    return ServerHandle(server=_server_module, client=_client_module, metrics=_metrics_module)


@pytest.fixture
def handle(monkeypatch: pytest.MonkeyPatch) -> ServerHandle:
    return _reload(monkeypatch, api_key="test-api-key", base_url="https://api.geolabel.dev")


@pytest.fixture
def server(handle: ServerHandle) -> ModuleType:
    return handle.server


@pytest.fixture
def server_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator:
    def _build(*, api_key: str | None = "test-api-key", base_url: str | None = None) -> ModuleType:
        return _reload(monkeypatch, api_key=api_key, base_url=base_url).server

    yield _build

"""Shared fixtures for the geolabel_mcp test suite.

The server module captures `GEOLABEL_API_KEY` and `GEOLABEL_BASE_URL` at import
time, so tests that need to vary those values must reload the module after
patching the environment.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest

import geolabel_mcp.server as _server_module


def _reload_server(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_key: str | None,
    base_url: str | None,
):
    if api_key is None:
        monkeypatch.delenv("GEOLABEL_API_KEY", raising=False)
    else:
        monkeypatch.setenv("GEOLABEL_API_KEY", api_key)

    if base_url is None:
        monkeypatch.delenv("GEOLABEL_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("GEOLABEL_BASE_URL", base_url)

    return importlib.reload(_server_module)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator:
    """Server module reloaded with a configured test API key."""
    module = _reload_server(
        monkeypatch,
        api_key="test-api-key",
        base_url="https://api.geolabel.dev",
    )
    yield module
    # Restore default state for any later importers in the session.
    importlib.reload(_server_module)


@pytest.fixture
def server_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator:
    """Build a server module with custom env vars per test."""

    def _build(*, api_key: str | None = "test-api-key", base_url: str | None = None):
        return _reload_server(monkeypatch, api_key=api_key, base_url=base_url)

    yield _build
    importlib.reload(_server_module)

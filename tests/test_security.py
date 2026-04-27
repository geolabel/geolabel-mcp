"""Security and privacy invariants.

* The API key must never appear in any user-facing error message.
* Coordinates must never be logged by this package.
* The shared client must send the API key as a header, never in the URL.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

SECRET_KEY = "glk_super_secret_token_DO_NOT_LEAK"


@pytest.fixture
def secret_server(server_factory):
    return server_factory(api_key=SECRET_KEY, base_url="https://api.geolabel.dev")


@respx.mock
async def test_api_key_sent_as_header_never_as_query_param(secret_server):
    route = respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "ok"})
    )

    await secret_server.get_location_label(lat=1.0, lng=2.0)

    request = route.calls.last.request
    assert request.headers["X-API-Key"] == SECRET_KEY
    assert SECRET_KEY not in str(request.url)
    assert "api_key" not in request.url.params
    assert "key" not in request.url.params


@respx.mock
async def test_api_key_not_in_http_error_messages(secret_server):
    """Even if the underlying API echoes the key (it shouldn't), we don't
    pass that text through to the model."""
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(500, text=f"Server error: rejected key {SECRET_KEY}")
    )

    result = await secret_server.get_location_label(lat=1.0, lng=2.0)

    assert SECRET_KEY not in result["error"]


@respx.mock
async def test_api_key_not_in_unexpected_exception_message(secret_server):
    """Exception messages frequently embed config — we must not pass
    them through."""
    respx.get("https://api.geolabel.dev/label").mock(
        side_effect=RuntimeError(f"auth failed for key={SECRET_KEY}")
    )

    result = await secret_server.get_location_label(lat=1.0, lng=2.0)

    assert SECRET_KEY not in result["error"]


@respx.mock
async def test_api_key_not_in_network_error_message(secret_server):
    respx.get("https://api.geolabel.dev/label").mock(
        side_effect=httpx.ConnectError(f"trying to reach host with {SECRET_KEY}")
    )

    result = await secret_server.get_location_label(lat=1.0, lng=2.0)

    assert SECRET_KEY not in result["error"]


@respx.mock
async def test_no_logs_emitted_on_success(secret_server, caplog):
    """No log records from this package on the happy path — we don't want
    coordinates or any request metadata sitting in log files. This is the
    automated guardrail behind the README's privacy promise."""
    respx.get("https://api.geolabel.dev/label").mock(
        return_value=httpx.Response(200, json={"label": "ok"})
    )

    with caplog.at_level(logging.DEBUG, logger="geolabel_mcp"):
        await secret_server.get_location_label(lat=41.8827, lng=-87.6233)

    package_records = [r for r in caplog.records if r.name.startswith("geolabel_mcp")]
    assert package_records == []


@respx.mock
async def test_no_logs_emitted_on_error(secret_server, caplog):
    respx.get("https://api.geolabel.dev/label").mock(return_value=httpx.Response(500))

    with caplog.at_level(logging.DEBUG, logger="geolabel_mcp"):
        await secret_server.get_location_label(lat=41.8827, lng=-87.6233)

    package_records = [r for r in caplog.records if r.name.startswith("geolabel_mcp")]
    assert package_records == []

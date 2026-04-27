"""Tests for module-level configuration: API key handling, base URL parsing,
and the HTTPS guard."""

from __future__ import annotations

import httpx
import respx

# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------


def test_unset_api_key_is_empty_string(server_factory):
    module = server_factory(api_key=None)
    assert module._client._API_KEY == ""


def test_empty_api_key_is_treated_as_missing(server_factory):
    module = server_factory(api_key="")
    assert module._client._API_KEY == ""


def test_api_key_whitespace_is_stripped(server_factory):
    """Common copy-paste mistake — leading/trailing whitespace must not
    break authentication or, worse, leak the key into headers oddly."""
    module = server_factory(api_key="  glk_real_key  \n")
    assert module._client._API_KEY == "glk_real_key"


async def test_empty_api_key_short_circuits_request(server_factory):
    module = server_factory(api_key="")

    with respx.mock(assert_all_called=False) as router:
        route = router.get("https://api.geolabel.dev/label")
        result = await module.get_location_label(lat=0.0, lng=0.0)

    assert "GEOLABEL_API_KEY is not configured" in result["error"]
    assert not route.called


async def test_whitespace_only_api_key_short_circuits(server_factory):
    module = server_factory(api_key="   ")

    with respx.mock(assert_all_called=False) as router:
        route = router.get("https://api.geolabel.dev/label")
        result = await module.get_location_label(lat=0.0, lng=0.0)

    assert "GEOLABEL_API_KEY is not configured" in result["error"]
    assert not route.called


# ---------------------------------------------------------------------------
# Base URL
# ---------------------------------------------------------------------------


def test_default_base_url(server_factory):
    module = server_factory(base_url=None)
    assert module._client._BASE_URL == "https://api.geolabel.dev"


def test_base_url_strips_single_trailing_slash(server_factory):
    module = server_factory(base_url="https://api.geolabel.dev/")
    assert module._client._BASE_URL == "https://api.geolabel.dev"


def test_base_url_strips_repeated_trailing_slashes(server_factory):
    module = server_factory(base_url="https://api.geolabel.dev///")
    assert module._client._BASE_URL == "https://api.geolabel.dev"


def test_base_url_preserves_path_prefix(server_factory):
    module = server_factory(base_url="https://example.com/v2/")
    assert module._client._BASE_URL == "https://example.com/v2"


async def test_base_url_override_is_used_for_requests(server_factory):
    module = server_factory(base_url="https://staging.geolabel.dev/")

    with respx.mock() as router:
        route = router.get("https://staging.geolabel.dev/label").mock(
            return_value=httpx.Response(200, json={"label": "X"})
        )
        result = await module.get_location_label(lat=1.0, lng=2.0)

    assert result == {"label": "X"}
    assert route.called


# ---------------------------------------------------------------------------
# HTTPS guard — coordinates and API key must never go over plaintext HTTP
# ---------------------------------------------------------------------------


async def test_http_base_url_is_rejected(server_factory):
    module = server_factory(base_url="http://api.geolabel.dev")

    with respx.mock(assert_all_called=False) as router:
        route = router.get("http://api.geolabel.dev/label")
        result = await module.get_location_label(lat=1.0, lng=2.0)

    assert "https://" in result["error"]
    assert not route.called


async def test_http_localhost_is_allowed_for_local_dev(server_factory):
    module = server_factory(base_url="http://localhost:8000")

    with respx.mock() as router:
        route = router.get("http://localhost:8000/label").mock(
            return_value=httpx.Response(200, json={"label": "ok"})
        )
        result = await module.get_location_label(lat=1.0, lng=2.0)

    assert result == {"label": "ok"}
    assert route.called


async def test_http_127_0_0_1_is_allowed_for_local_dev(server_factory):
    module = server_factory(base_url="http://127.0.0.1:9000")

    with respx.mock() as router:
        route = router.get("http://127.0.0.1:9000/label").mock(
            return_value=httpx.Response(200, json={"label": "ok"})
        )
        result = await module.get_location_label(lat=1.0, lng=2.0)

    assert result == {"label": "ok"}
    assert route.called

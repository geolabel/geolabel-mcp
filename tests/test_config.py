"""Tests for module-level configuration: API key handling and base URL parsing."""

from __future__ import annotations

import httpx
import respx


def test_unset_api_key_is_empty_string(server_factory):
    module = server_factory(api_key=None)
    assert module._API_KEY == ""


def test_empty_api_key_is_treated_as_missing(server_factory):
    """An explicitly empty GEOLABEL_API_KEY behaves the same as unset."""
    module = server_factory(api_key="")
    assert module._API_KEY == ""


async def test_empty_api_key_short_circuits_request(server_factory):
    module = server_factory(api_key="")

    with respx.mock(assert_all_called=False) as router:
        route = router.get("https://api.geolabel.dev/label")
        result = await module.get_location_label(lat=0.0, lng=0.0)

    assert "GEOLABEL_API_KEY is not configured" in result["error"]
    assert not route.called


def test_default_base_url(server_factory):
    module = server_factory(base_url=None)
    assert module._BASE_URL == "https://api.geolabel.dev"


def test_base_url_strips_single_trailing_slash(server_factory):
    module = server_factory(base_url="https://api.geolabel.dev/")
    assert module._BASE_URL == "https://api.geolabel.dev"


def test_base_url_strips_repeated_trailing_slashes(server_factory):
    module = server_factory(base_url="https://api.geolabel.dev///")
    assert module._BASE_URL == "https://api.geolabel.dev"


def test_base_url_preserves_path_prefix(server_factory):
    module = server_factory(base_url="https://example.com/v2/")
    assert module._BASE_URL == "https://example.com/v2"


async def test_base_url_override_is_used_for_requests(server_factory):
    module = server_factory(base_url="https://staging.geolabel.dev/")

    with respx.mock() as router:
        route = router.get("https://staging.geolabel.dev/label").mock(
            return_value=httpx.Response(200, json={"label": "X"})
        )
        result = await module.get_location_label(lat=1.0, lng=2.0)

    assert result == {"label": "X"}
    assert route.called

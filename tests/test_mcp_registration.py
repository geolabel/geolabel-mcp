"""Smoke tests for the FastMCP tool registration.

These guard the public contract: tool name, parameter schema, server name,
and that `main()` is wired to `mcp.run`. Drift in any of these would silently
break MCP clients.
"""

from __future__ import annotations

import geolabel_mcp


async def test_server_metadata(server):
    assert server.mcp.name == "GeoLabel"
    assert server.mcp.instructions
    assert "GeoLabel" in server.mcp.instructions


async def test_tools_are_registered(server):
    tools = await server.mcp.list_tools()
    names = sorted(t.name for t in tools)
    assert names == ["geolabel_stats", "get_location_label"]


async def test_get_location_label_input_schema(server):
    tools = {t.name: t for t in await server.mcp.list_tools()}
    schema = tools["get_location_label"].inputSchema

    assert schema["type"] == "object"
    assert set(schema["required"]) == {"lat", "lng"}

    props = schema["properties"]
    assert props["lat"]["type"] == "number"
    assert props["lng"]["type"] == "number"
    assert props["radius"]["type"] == "integer"
    assert props["radius"]["default"] == 100


async def test_geolabel_stats_input_schema(server):
    tools = {t.name: t for t in await server.mcp.list_tools()}
    schema = tools["geolabel_stats"].inputSchema

    # Stats takes no inputs.
    assert schema["type"] == "object"
    assert schema.get("required", []) == []
    assert schema.get("properties", {}) == {}


async def test_get_location_label_description_documents_response_fields(server):
    tools = {t.name: t for t in await server.mcp.list_tools()}
    description = tools["get_location_label"].description or ""
    # A few key response field names that clients rely on.
    for field in ("label", "category", "is_open", "opens_at", "closes_at", "cached"):
        assert field in description, f"missing {field!r} in tool description"


def test_main_invokes_mcp_run(server, monkeypatch):
    called = {}

    def fake_run(*args, **kwargs):
        called["ran"] = True

    monkeypatch.setattr(server.mcp, "run", fake_run)
    server.main()
    assert called == {"ran": True}


def test_package_exposes_version():
    assert isinstance(geolabel_mcp.__version__, str)
    assert geolabel_mcp.__version__

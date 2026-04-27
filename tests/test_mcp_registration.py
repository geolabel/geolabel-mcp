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


async def test_tool_is_registered(server):
    tools = await server.mcp.list_tools()
    names = [t.name for t in tools]
    assert names == ["get_location_label"]


async def test_tool_input_schema(server):
    [tool] = await server.mcp.list_tools()
    schema = tool.inputSchema

    assert schema["type"] == "object"
    assert set(schema["required"]) == {"lat", "lng"}

    props = schema["properties"]
    assert props["lat"]["type"] == "number"
    assert props["lng"]["type"] == "number"
    assert props["radius"]["type"] == "integer"
    assert props["radius"]["default"] == 100


async def test_tool_description_documents_response_fields(server):
    [tool] = await server.mcp.list_tools()
    description = tool.description or ""
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

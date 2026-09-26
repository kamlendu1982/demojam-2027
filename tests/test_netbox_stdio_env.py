"""Tests for the NetBox stdio-transport plumbing added for the embedded
(same-EE) NetBox MCP server: NETBOX_URL/NETBOX_TOKEN -> subprocess env.
"""

import asyncio

import pytest

from src.config import load_settings
from src.mcp.base_client import BaseMCPClient
from src.mcp.netbox_client import (
    NetBoxConfigError,
    NetBoxMCPClient,
    build_embedded_server_env,
)


def test_build_embedded_server_env_maps_real_netbox_credentials(monkeypatch):
    monkeypatch.setenv("NETBOX_URL", "https://netbox.example.com/")
    monkeypatch.setenv("NETBOX_TOKEN", "nbt_faketoken")
    monkeypatch.setenv("NETBOX_VERIFY_SSL", "false")
    settings = load_settings(refresh=True)

    env = build_embedded_server_env(settings)

    assert env["NETBOX_URL"] == "https://netbox.example.com/"
    assert env["NETBOX_TOKEN"] == "nbt_faketoken"
    assert env["TRANSPORT"] == "stdio"
    assert env["VERIFY_SSL"] == "false"


def test_netbox_client_fails_fast_when_stdio_missing_credentials(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("NETBOX_MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("NETBOX_URL", "")
    monkeypatch.setenv("NETBOX_TOKEN", "")
    load_settings(refresh=True)

    with pytest.raises(NetBoxConfigError):
        NetBoxMCPClient()

    # Restore demo mode for any tests that run after this one without the
    # autouse conftest fixture re-running (belt-and-suspenders).
    monkeypatch.setenv("DEMO_MODE", "true")
    load_settings(refresh=True)


def test_stdio_session_merges_parent_env_with_explicit_overrides(monkeypatch):
    """Reproduces the exact bug found while advising on the embedded MCP
    server: StdioServerParameters must receive BOTH the parent process's
    environment AND the explicit NETBOX_URL/NETBOX_TOKEN overrides, or the
    spawned server subprocess would never see the NetBox credentials.
    """
    import mcp
    import mcp.client.stdio as stdio_mod

    captured = {}

    class FakeStdioServerParameters:
        def __init__(self, command, args, env=None):
            captured["command"] = command
            captured["args"] = args
            captured["env"] = env

    def fake_stdio_client(params):
        return params  # never entered as a context manager in this test

    monkeypatch.setattr(mcp, "StdioServerParameters", FakeStdioServerParameters)
    monkeypatch.setattr(stdio_mod, "stdio_client", fake_stdio_client)
    monkeypatch.setenv("SOME_UNRELATED_PARENT_VAR", "should-still-be-present")

    client = BaseMCPClient(
        name="netbox",
        transport="stdio",
        command="fake-netbox-mcp-server --flag",
        env={
            "NETBOX_URL": "https://netbox.example.com/",
            "NETBOX_TOKEN": "nbt_faketoken",
        },
    )

    asyncio.run(client._stdio_session())

    assert captured["command"] == "fake-netbox-mcp-server"
    assert captured["args"] == ["--flag"]
    # Explicit overrides made it through.
    assert captured["env"]["NETBOX_URL"] == "https://netbox.example.com/"
    assert captured["env"]["NETBOX_TOKEN"] == "nbt_faketoken"
    # AND the parent process environment was still inherited (this is the
    # part that was previously missing — StdioServerParameters was called
    # with no `env=` at all, so the SDK fell back to a minimal default).
    assert captured["env"]["SOME_UNRELATED_PARENT_VAR"] == "should-still-be-present"

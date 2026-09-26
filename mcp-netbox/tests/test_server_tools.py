"""Tests for the two MCP tool functions themselves — calling them as
plain Python functions (verified empirically that @mcp.tool() leaves the
decorated function directly callable), so no MCP transport is needed
here. See tests/test_stdio_roundtrip.py for a full transport-level check.
"""

import httpx
import pytest
import respx

import server

BASE_URL = "https://netbox.example.com"


@pytest.fixture(autouse=True)
def _netbox_env(monkeypatch):
    monkeypatch.setenv("NETBOX_URL", BASE_URL)
    monkeypatch.setenv("NETBOX_TOKEN", "nbt_faketoken")


@respx.mock
def test_get_ntp_servers_success():
    respx.get(f"{BASE_URL}/api/dcim/devices/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "name": "rtr-core-01",
                        "site": {"name": "dc-east-1"},
                        "config_context": {"ntp_servers": ["10.10.0.123"]},
                    }
                ],
            },
        )
    )
    result = server.netbox_get_ntp_servers("rtr-core-01")
    assert result == {
        "device": "rtr-core-01",
        "ntp_servers": ["10.10.0.123"],
        "error": None,
    }


@respx.mock
def test_get_login_banner_success():
    respx.get(f"{BASE_URL}/api/dcim/devices/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "name": "rtr-core-01",
                        "site": {"name": "dc-east-1"},
                        "config_context": {"login_banner": "Authorized access only."},
                    }
                ],
            },
        )
    )
    result = server.netbox_get_login_banner("rtr-core-01")
    assert result == {
        "device": "rtr-core-01",
        "login_banner": "Authorized access only.",
        "error": None,
    }


@respx.mock
def test_get_ntp_servers_device_not_found_returns_structured_error():
    respx.get(f"{BASE_URL}/api/dcim/devices/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )
    result = server.netbox_get_ntp_servers("ghost-device")

    assert result["device"] == "ghost-device"
    assert result["ntp_servers"] is None
    assert "No device named" in result["error"]


@respx.mock
def test_get_login_banner_key_missing_from_config_context():
    respx.get(f"{BASE_URL}/api/dcim/devices/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "name": "rtr-core-01",
                        "site": {"name": "dc-east-1"},
                        # config_context present, but no login_banner key
                        "config_context": {"ntp_servers": ["10.10.0.123"]},
                    }
                ],
            },
        )
    )
    result = server.netbox_get_login_banner("rtr-core-01")

    assert result["device"] == "rtr-core-01"
    assert result["login_banner"] is None
    assert "no 'login_banner' key" in result["error"]


@respx.mock
def test_get_ntp_servers_network_error_returns_structured_error():
    respx.get(f"{BASE_URL}/api/dcim/devices/").mock(side_effect=httpx.ConnectError("refused"))
    result = server.netbox_get_ntp_servers("rtr-core-01")

    assert result["ntp_servers"] is None
    assert "Could not reach NetBox" in result["error"]


def test_missing_credentials_returns_structured_error(monkeypatch):
    monkeypatch.delenv("NETBOX_URL", raising=False)
    monkeypatch.delenv("NETBOX_TOKEN", raising=False)

    result = server.netbox_get_ntp_servers("rtr-core-01")

    assert result["ntp_servers"] is None
    assert "NETBOX_URL" in result["error"]


def test_both_tools_are_registered_with_descriptions():
    tool_names = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert tool_names == {"netbox_get_ntp_servers", "netbox_get_login_banner"}

    for tool in server.mcp._tool_manager.list_tools():
        assert tool.description, f"{tool.name} has no description"
        assert len(tool.description) > 50, f"{tool.name} description too thin"

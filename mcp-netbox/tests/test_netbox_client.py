import httpx
import pytest
import respx

from netbox_client import NetBoxClientError, NetBoxConfigContextClient

BASE_URL = "https://netbox.example.com"


def _client(**overrides):
    defaults = dict(base_url=BASE_URL, token="nbt_faketoken", verify_ssl=True)
    defaults.update(overrides)
    return NetBoxConfigContextClient(**defaults)


def test_missing_url_raises_immediately(monkeypatch):
    monkeypatch.delenv("NETBOX_URL", raising=False)
    with pytest.raises(NetBoxClientError, match="NETBOX_URL"):
        NetBoxConfigContextClient(base_url="", token="tok")


def test_missing_token_raises_immediately():
    with pytest.raises(NetBoxClientError, match="NETBOX_TOKEN"):
        NetBoxConfigContextClient(base_url=BASE_URL, token="")


@respx.mock
def test_success_returns_config_context():
    respx.get(f"{BASE_URL}/api/dcim/devices/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "name": "rtr-core-01",
                        "site": {"name": "dc-east-1"},
                        "config_context": {
                            "ntp_servers": ["10.10.0.123"],
                            "login_banner": "Authorized access only.",
                        },
                    }
                ],
            },
        )
    )
    client = _client()
    ctx = client.get_device_config_context("rtr-core-01")
    assert ctx["ntp_servers"] == ["10.10.0.123"]
    assert ctx["login_banner"] == "Authorized access only."


@respx.mock
def test_device_not_found():
    respx.get(f"{BASE_URL}/api/dcim/devices/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )
    client = _client()
    with pytest.raises(NetBoxClientError, match="No device named"):
        client.get_device_config_context("does-not-exist")


@respx.mock
def test_ambiguous_device_name_across_sites():
    respx.get(f"{BASE_URL}/api/dcim/devices/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {"name": "sw-1", "site": {"name": "dc-east"}, "config_context": {}},
                    {"name": "sw-1", "site": {"name": "dc-west"}, "config_context": {}},
                ],
            },
        )
    )
    client = _client()
    with pytest.raises(NetBoxClientError, match="Multiple devices"):
        client.get_device_config_context("sw-1")


@respx.mock
def test_device_with_no_config_context():
    respx.get(f"{BASE_URL}/api/dcim/devices/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "results": [{"name": "rtr-core-01", "site": {"name": "dc-east-1"}, "config_context": None}],
            },
        )
    )
    client = _client()
    with pytest.raises(NetBoxClientError, match="no Config Context data"):
        client.get_device_config_context("rtr-core-01")


@respx.mock
def test_unauthorized_token():
    respx.get(f"{BASE_URL}/api/dcim/devices/").mock(return_value=httpx.Response(403))
    client = _client()
    with pytest.raises(NetBoxClientError, match="403"):
        client.get_device_config_context("rtr-core-01")


@respx.mock
def test_server_error():
    respx.get(f"{BASE_URL}/api/dcim/devices/").mock(return_value=httpx.Response(500, text="boom"))
    client = _client()
    with pytest.raises(NetBoxClientError, match="500"):
        client.get_device_config_context("rtr-core-01")


@respx.mock
def test_network_unreachable():
    respx.get(f"{BASE_URL}/api/dcim/devices/").mock(side_effect=httpx.ConnectError("refused"))
    client = _client()
    with pytest.raises(NetBoxClientError, match="Could not reach NetBox"):
        client.get_device_config_context("rtr-core-01")

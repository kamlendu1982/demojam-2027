#!/usr/bin/env python3
"""NetBox Config Context MCP Server.

A minimal, read-only Model Context Protocol server exposing exactly two
tools, both backed by a single device's NetBox Config Context data
(Provisioning -> Config Contexts -> the "Data" panel on the device page):

  - netbox_get_ntp_servers   -> the device's 'ntp_servers' Config Context value
  - netbox_get_login_banner  -> the device's 'login_banner' Config Context value

Both tools take a single `device_name` argument and always return a JSON
object (never raise a raw exception up to the MCP transport), so a calling
agent can reliably branch on the presence of an "error" key:

    {"device": "<name>", "<field>": <value or null>, "error": <string or null>}

Environment variables (see README.md for the full list):
    NETBOX_URL     - base URL of the NetBox instance (required)
    NETBOX_TOKEN   - NetBox API token (required)
    VERIFY_SSL     - "true"/"false", default "true"
    TRANSPORT      - "stdio" (default) or "streamable-http"
    HOST / PORT    - only used when TRANSPORT=streamable-http
    LOG_LEVEL      - default "INFO"

Run standalone:
    NETBOX_URL=https://netbox.example.com/ NETBOX_TOKEN=<token> python server.py

Embed in the parent network-drift-manager project (stdio, same process
group / same Execution Environment):
    NETBOX_MCP_TRANSPORT=stdio
    NETBOX_MCP_COMMAND=python /path/to/mcp-netbox/server.py
"""

import logging
import os
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from netbox_client import NetBoxClientError, NetBoxConfigContextClient

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger("netbox-config-context-mcp")

mcp = FastMCP(name="netbox-config-context", log_level=LOG_LEVEL)


def _get_client() -> NetBoxConfigContextClient:
    # Constructed fresh per call (cheap) rather than cached at import time,
    # so a misconfigured environment always surfaces as a normal tool
    # error response instead of a crash at server startup.
    return NetBoxConfigContextClient()


def _error_response(device_name: str, field: str, message: str) -> Dict[str, Any]:
    logger.warning("%s lookup failed for device '%s': %s", field, device_name, message)
    return {"device": device_name, field: None, "error": message}


def _lookup_field(device_name: str, field: str) -> Dict[str, Any]:
    """Shared implementation for both tools: fetch Config Context, pull
    one field out of it, and always return the structured response shape.
    """
    try:
        client = _get_client()
        config_context = client.get_device_config_context(device_name)
    except NetBoxClientError as exc:
        return _error_response(device_name, field, str(exc))
    except Exception as exc:  # noqa: BLE001 - never let anything escape unstructured
        return _error_response(device_name, field, f"Unexpected error: {exc}")

    if field not in config_context:
        return _error_response(
            device_name,
            field,
            f"Device's Config Context data has no '{field}' key.",
        )

    logger.info("%s lookup succeeded for device '%s'", field, device_name)
    return {"device": device_name, field: config_context[field], "error": None}


@mcp.tool(
    name="netbox_get_ntp_servers",
    description=(
        "Fetch the NTP server list for a network device from its NetBox "
        "Config Context (Provisioning -> Config Contexts -> the 'Data' "
        "panel on the device's page in NetBox). Looks the device up by "
        "exact name, reads its rendered/merged Config Context, and "
        "returns the value of the 'ntp_servers' key within that data. "
        "Read-only: makes no changes in NetBox. "
        "Always returns a JSON object shaped "
        "{\"device\": <name>, \"ntp_servers\": <value or null>, "
        "\"error\": <string or null>} — never raises. Check 'error' "
        "first: if it is non-null, the lookup failed (device not found, "
        "device name ambiguous across sites, NetBox unreachable, "
        "NETBOX_TOKEN invalid/insufficient, or the device's Config "
        "Context has no 'ntp_servers' key) and 'ntp_servers' must be "
        "treated as unknown — NOT as an empty/absent NTP configuration."
    ),
)
def netbox_get_ntp_servers(device_name: str) -> Dict[str, Any]:
    """Look up the 'ntp_servers' key in a device's NetBox Config Context."""
    return _lookup_field(device_name, "ntp_servers")


@mcp.tool(
    name="netbox_get_login_banner",
    description=(
        "Fetch the login banner text for a network device from its "
        "NetBox Config Context (Provisioning -> Config Contexts -> the "
        "'Data' panel on the device's page in NetBox). Looks the device "
        "up by exact name, reads its rendered/merged Config Context, and "
        "returns the value of the 'login_banner' key within that data. "
        "Read-only: makes no changes in NetBox. "
        "Always returns a JSON object shaped "
        "{\"device\": <name>, \"login_banner\": <value or null>, "
        "\"error\": <string or null>} — never raises. Check 'error' "
        "first: if it is non-null, the lookup failed (device not found, "
        "device name ambiguous across sites, NetBox unreachable, "
        "NETBOX_TOKEN invalid/insufficient, or the device's Config "
        "Context has no 'login_banner' key) and 'login_banner' must be "
        "treated as unknown — NOT as an empty/absent banner."
    ),
)
def netbox_get_login_banner(device_name: str) -> Dict[str, Any]:
    """Look up the 'login_banner' key in a device's NetBox Config Context."""
    return _lookup_field(device_name, "login_banner")


def main() -> None:
    transport = os.environ.get("TRANSPORT", "stdio")
    logger.info("Starting netbox-config-context MCP server (transport=%s)", transport)
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()

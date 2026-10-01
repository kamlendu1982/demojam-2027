"""NetBox access over MCP — the source of truth for NETWORKING attributes.

Real (non-demo) mode calls into a NetBox MCP server (e.g. the NetBox Labs
`netbox-mcp-server`, which commonly exposes a generic
`netbox_get_objects(object_type, filters)` tool). Because exact tool names
vary by server/version, the device-lookup tool is resolved dynamically:

  1. Use NETBOX_MCP_DEVICE_TOOL from .env if set (explicit override).
  2. Otherwise try the well-known `netbox_get_objects` tool name.
  3. Otherwise search the server's tool catalogue for a tool whose name
     contains "device" and ("get" or "list").

Demo mode (DEMO_MODE=true) reads from demo_fixtures/netbox/devices.json
instead of calling out to any MCP server at all — this lets the whole
pipeline run end-to-end with zero live dependencies for a demo/hackathon.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.config import PROJECT_ROOT, get_settings
from src.mcp.base_client import BaseMCPClient, MCPClientError

logger = logging.getLogger(__name__)

DEMO_DEVICES_FILE = PROJECT_ROOT / "demo_fixtures" / "netbox" / "devices.json"


class NetBoxDeviceNotFound(RuntimeError):
    pass


def _resolve_path(obj: Dict[str, Any], path: str) -> Any:
    """Resolve a small dotted-path DSL against a NetBox device dict.

    Supports plain dotted keys ("site.name") and a `len(x)` wrapper for
    counting list attributes ("len(interfaces)").
    """
    if path.startswith("len(") and path.endswith(")"):
        inner = path[4:-1]
        value = _resolve_path(obj, inner)
        return len(value) if isinstance(value, (list, dict, str)) else None

    current: Any = obj
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


class NetBoxConfigError(RuntimeError):
    pass


def build_embedded_server_env(settings) -> Dict[str, str]:
    """Env vars to inject into a locally-spawned (stdio) NetBox MCP server.

    Matches the settings documented by netboxlabs/netbox-mcp-server:
    NETBOX_URL, NETBOX_TOKEN, TRANSPORT, VERIFY_SSL, LOG_LEVEL. Exposed as
    a standalone function (rather than inlined) so it's directly unit
    testable without spawning a real subprocess.
    """
    return {
        "NETBOX_URL": settings.netbox_url,
        "NETBOX_TOKEN": settings.netbox_token,
        "TRANSPORT": "stdio",
        "VERIFY_SSL": "true" if settings.netbox_verify_ssl else "false",
        "LOG_LEVEL": settings.log_level,
    }


class NetBoxMCPClient:
    """High-level NetBox client used by Agent 1 (and Agent 2's revert plan)."""

    def __init__(self):
        self.settings = get_settings()
        self._mcp: Optional[BaseMCPClient] = None
        if not self.settings.demo_mode:
            transport = self.settings.netbox_mcp_transport.lower()
            env = {}

            if transport == "stdio":
                if not self.settings.netbox_url or not self.settings.netbox_token:
                    raise NetBoxConfigError(
                        "NETBOX_MCP_TRANSPORT=stdio requires NETBOX_URL and "
                        "NETBOX_TOKEN to be set (these are the REAL NetBox "
                        "instance credentials passed into the embedded MCP "
                        "server's subprocess environment — not "
                        "NETBOX_MCP_URL/NETBOX_MCP_TOKEN, which are only "
                        "used for transport=http)."
                    )
                env = build_embedded_server_env(self.settings)

            self._mcp = BaseMCPClient(
                name="netbox",
                transport=self.settings.netbox_mcp_transport,
                url=self.settings.netbox_mcp_url,
                token=self.settings.netbox_mcp_token,
                command=self.settings.netbox_mcp_command,
                verify_ssl=self.settings.netbox_verify_ssl,
                env=env,
            )

    # ── device retrieval ─────────────────────────────────────────────────

    def _get_device_demo(self, device_name: str) -> Dict[str, Any]:
        if not DEMO_DEVICES_FILE.exists():
            raise NetBoxDeviceNotFound(
                f"Demo fixture file not found: {DEMO_DEVICES_FILE}"
            )
        data = json.loads(DEMO_DEVICES_FILE.read_text())
        device = data.get(device_name)
        if device is None:
            raise NetBoxDeviceNotFound(
                f"Device '{device_name}' not found in NetBox demo fixtures"
            )
        return device

    def _get_device_live(self, device_name: str) -> Dict[str, Any]:
        assert self._mcp is not None
        tool_name = self.settings.netbox_mcp_device_tool or self._mcp.find_tool(
            "get", "objects"
        ) or "netbox_get_objects"

        try:
            # object_type is NetBox's internal Django "app_label.model" name
            # (singular - dcim.device), NOT the REST API's plural URL path
            # segment (dcim.devices). Confirmed against a real
            # netbox-mcp-server v1.2.1 instance: passing the plural form
            # raises "Invalid object_type" with the full valid-type list,
            # which includes "dcim.device" but not "dcim.devices".
            result = self._mcp.call_tool(
                tool_name,
                {
                    "object_type": "dcim.device",
                    # include=config_context: NetBox omits the (expensive to
                    # compute) config_context field by default. Several
                    # networking_attributes entries in
                    # config/attribute_classification.yaml read from
                    # config_context.* (e.g. dns_servers, ntp_servers) -
                    # without this, those paths always resolve to None,
                    # making every such attribute look like NetBox has no
                    # opinion on it rather than comparing against the real
                    # value. Confirmed live: switch1's config_context holds
                    # the real dns_servers/ntp_servers values.
                    "filters": {"name": device_name, "include": "config_context"},
                },
            )
        except Exception as exc:  # noqa: BLE001
            raise MCPClientError(f"NetBox MCP call failed via '{tool_name}': {exc}") from exc

        objects = result.get("results", result) if isinstance(result, dict) else result
        if isinstance(objects, list):
            for obj in objects:
                if isinstance(obj, dict) and obj.get("name") == device_name:
                    return obj
            raise NetBoxDeviceNotFound(f"Device '{device_name}' not found in NetBox")
        if isinstance(objects, dict) and objects.get("name") == device_name:
            return objects

        raise NetBoxDeviceNotFound(f"Device '{device_name}' not found in NetBox")

    def get_device(self, device_name: str) -> Dict[str, Any]:
        if self.settings.demo_mode:
            return self._get_device_demo(device_name)
        return self._get_device_live(device_name)

    def get_attribute_values(
        self, device_name: str, netbox_paths: Dict[str, str]
    ) -> Dict[str, Any]:
        """Return {attribute_name: value_from_netbox} for the given path map."""
        device = self.get_device(device_name)
        return {attr: _resolve_path(device, path) for attr, path in netbox_paths.items()}

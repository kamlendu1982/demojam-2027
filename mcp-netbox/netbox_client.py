"""Thin, read-only NetBox REST API client used by the Config Context MCP
tools in server.py.

Only ever performs a single GET against /api/dcim/devices/ — no writes,
no other NetBox object types. Every failure mode (bad URL, bad token, no
network route, device not found, ambiguous device name, missing Config
Context data) is normalized into a single `NetBoxClientError` with a
clear, specific message, so the caller (server.py) never has to guess
what went wrong.
"""

import os
from typing import Any, Dict, List, Optional

import httpx


class NetBoxClientError(RuntimeError):
    """Raised for any NetBox connectivity / auth / data problem.

    Always caught by the MCP tool functions in server.py and converted
    into a structured `{"error": "..."}` response — this exception type
    itself should never escape to the MCP transport layer.
    """


class NetBoxConfigContextClient:
    """Looks up a single device's rendered NetBox Config Context data.

    Config Context is the NetBox feature under Provisioning -> Config
    Contexts: named JSON blobs assigned to devices (directly, or via
    site/role/platform/tag/tenant rules) and merged together per-device.
    The merged result is shown as the "Data" panel on a device's Config
    Context tab in the NetBox UI, and is exposed by the REST API as the
    device's `config_context` field — but ONLY when the request
    explicitly asks for it via `?include=config_context` (NetBox omits it
    by default since rendering it is relatively expensive).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        verify_ssl: Optional[bool] = None,
        timeout: float = 15.0,
    ):
        self.base_url = (base_url or os.environ.get("NETBOX_URL", "")).rstrip("/")
        self.token = token if token is not None else os.environ.get("NETBOX_TOKEN", "")

        if verify_ssl is None:
            # Matches the env var name used by the main agent project's
            # build_embedded_server_env() (VERIFY_SSL), with a
            # NETBOX_-prefixed fallback for convenience when running this
            # server standalone.
            raw = os.environ.get("VERIFY_SSL", os.environ.get("NETBOX_VERIFY_SSL", "true"))
            verify_ssl = raw.strip().lower() not in ("false", "0", "no")
        self.verify_ssl = verify_ssl
        self.timeout = timeout

        if not self.base_url:
            raise NetBoxClientError(
                "NETBOX_URL is not configured (set it in the environment "
                "passed to this server, e.g. via the embedding agent's "
                "NETBOX_URL setting)."
            )
        if not self.token:
            raise NetBoxClientError(
                "NETBOX_TOKEN is not configured (set it in the environment "
                "passed to this server)."
            )

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Token {self.token}",
                "Accept": "application/json",
            },
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

    def get_device_config_context(self, device_name: str) -> Dict[str, Any]:
        """Return the rendered Config Context 'data' dict for one device.

        Raises NetBoxClientError when: NetBox is unreachable, the token is
        rejected, the device does not exist, more than one device shares
        that name (NetBox allows duplicate names across sites), or the
        device has no Config Context data assigned at all.
        """
        try:
            with self._client() as client:
                resp = client.get(
                    "/api/dcim/devices/",
                    params={"name": device_name, "include": "config_context"},
                )
        except httpx.RequestError as exc:
            raise NetBoxClientError(
                f"Could not reach NetBox at {self.base_url}: {exc}"
            ) from exc

        if resp.status_code in (401, 403):
            raise NetBoxClientError(
                f"NetBox rejected the request ({resp.status_code} "
                f"{resp.reason_phrase}). Check that NETBOX_TOKEN is valid, "
                "includes any required 'nbt_' prefix (NetBox 4.5+ token "
                "peppers), and has read permission on dcim.device."
            )
        if resp.status_code >= 400:
            raise NetBoxClientError(
                f"NetBox returned HTTP {resp.status_code}: {resp.text[:300]}"
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise NetBoxClientError(
                f"NetBox returned a non-JSON response: {exc}"
            ) from exc

        results: List[Dict[str, Any]] = body.get("results", [])

        if not results:
            raise NetBoxClientError(
                f"No device named '{device_name}' found in NetBox."
            )

        if len(results) > 1:
            sites = [
                (r.get("site") or {}).get("name", "unknown") for r in results
            ]
            raise NetBoxClientError(
                f"Multiple devices named '{device_name}' found in NetBox "
                f"(sites: {', '.join(sites)}). Disambiguate by site — this "
                "server only accepts a device name."
            )

        device = results[0]
        config_context = device.get("config_context")
        if not config_context:
            raise NetBoxClientError(
                f"Device '{device_name}' has no Config Context data in "
                "NetBox (Provisioning -> Config Contexts is not assigned "
                "to this device, or its 'data' field is empty)."
            )
        return config_context

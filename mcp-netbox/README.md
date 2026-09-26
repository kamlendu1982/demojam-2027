# netbox-config-context-mcp

A minimal, purpose-built MCP server for NetBox — **exactly two read-only
tools**, both backed by a single device's **Config Context** data
(NetBox UI: *Provisioning → Config Contexts*, rendered per-device on the
device page's Config Context tab as a "Data" panel).

Built with the official MCP Python SDK's `FastMCP` framework, same as
`netboxlabs/netbox-mcp-server` — but scoped down to just the two fields
this project's agents actually need, rather than a general-purpose NetBox
object browser.

## Tools

| Tool | Input | Output |
|---|---|---|
| `netbox_get_ntp_servers` | `device_name: str` | `{"device": "...", "ntp_servers": <value or null>, "error": <string or null>}` |
| `netbox_get_login_banner` | `device_name: str` | `{"device": "...", "login_banner": <value or null>, "error": <string or null>}` |

Both tools:
- Look the device up **by exact name** via `GET /api/dcim/devices/?name=<name>&include=config_context`.
- Read the device's **rendered/merged** Config Context (NetBox merges all Config Contexts assigned via site/role/platform/tag/tenant rules into one dict — this is exactly the "Data" panel shown in the UI).
- Pull out one key (`ntp_servers` / `login_banner`) from that merged dict.
- **Never raise a raw exception.** Every failure — device not found, ambiguous device name (NetBox allows duplicate names across sites), NetBox unreachable, invalid/insufficient token, or the key simply not being present in that device's Config Context — is caught and returned as a clear `"error"` string in the same JSON shape, with the field value set to `null`. A calling agent should **always check `error` first**; a non-null `error` means the field value must be treated as *unknown*, not as an empty/absent configuration.

## Environment variables

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `NETBOX_URL` | Yes | — | Base URL of the NetBox instance, e.g. `https://netbox.example.com/` |
| `NETBOX_TOKEN` | Yes | — | NetBox API token. Must include the full `nbt_...` prefix if your NetBox uses token peppers (4.5+). |
| `VERIFY_SSL` | No | `true` | `false` to skip TLS verification (self-signed certs) |
| `TRANSPORT` | No | `stdio` | `stdio` or `streamable-http` |
| `HOST` / `PORT` | No | n/a | Only used when `TRANSPORT=streamable-http` |
| `LOG_LEVEL` | No | `INFO` | Standard Python logging level |

These names intentionally match what the parent `network-drift-manager`
project's `build_embedded_server_env()` already sends when spawning this
server via `NETBOX_MCP_TRANSPORT=stdio` (see `../src/mcp/netbox_client.py`).

## Running standalone

```bash
cd mcp-netbox
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

NETBOX_URL=https://netbox.example.com/ NETBOX_TOKEN=your_token python server.py
```

It will sit waiting on stdin/stdout for MCP protocol messages (this is
normal — it's meant to be spawned by an MCP client, not run interactively).

## Wiring into the parent project (embedded / same Execution Environment)

In the parent project's `.env`:

```bash
NETBOX_MCP_TRANSPORT=stdio
NETBOX_MCP_COMMAND=python /full/path/to/mcp-netbox/server.py
NETBOX_URL=https://netbox.example.com/
NETBOX_TOKEN=your_token
```

`src/mcp/netbox_client.py::build_embedded_server_env()` takes care of
passing `NETBOX_URL` / `NETBOX_TOKEN` / `TRANSPORT=stdio` / `VERIFY_SSL` /
`LOG_LEVEL` into this server's subprocess environment automatically —
no extra wiring needed there.

> Note: this server currently only exposes `ntp_servers` / `login_banner`
> lookups. It does **not** (yet) expose the generic
> `netbox_get_objects`-style tool that `src/mcp/netbox_client.py` also
> knows how to call for other networking attributes (`dns_servers`,
> `vlan`, `interfaces`, etc.) — that's a separate, later piece of work.

## NetBox-side setup required

For these tools to return real data, a Config Context must exist in
NetBox (*Provisioning → Config Contexts → Add*) whose **Data** field
includes the keys these tools read, e.g.:

```json
{
  "ntp_servers": ["10.10.0.123"],
  "login_banner": "Authorized access only. All activity is monitored."
}
```

...and that Config Context must be **assigned** to the relevant device(s)
— directly, or via a matching site / role / platform / tag / tenant rule.
If a device has no Config Context assigned, both tools will return a
clear `error` rather than silently returning `null`/empty values.

## Tests

```bash
cd mcp-netbox
source venv/bin/activate
python -m pytest -v
```

`tests/test_netbox_client.py` mocks NetBox's HTTP API (via `respx`) to
cover: success, device not found, ambiguous device name, missing Config
Context, 401/403, and network failure. `tests/test_server_tools.py`
calls the two tool functions directly and asserts the exact JSON shape
for both the success and every error case above.

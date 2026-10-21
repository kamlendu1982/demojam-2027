"""Generic MCP client used to reach NetBox and GitHub over the Model Context
Protocol (MCP).

Supports two transports, selected per-server via env vars:

  - "http"  : streamable-HTTP MCP server at a fixed URL (most SaaS/hosted
              MCP servers, e.g. NetBox Cloud MCP, GitHub's hosted MCP server)
  - "stdio" : spawn a local command that speaks MCP over stdio (e.g. a
              self-hosted `netbox-mcp-server` or the official
              `github-mcp-server` container run locally)

Tool discovery is dynamic: on first use we call `list_tools()` and cache the
result, then pick the best-matching tool name for the operation requested.
This mirrors the approach used for AAP's MCP domain servers elsewhere in
this environment, so behaviour keeps working even if a server renames a
tool between versions.
"""

import asyncio
import json
import logging
import shlex
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MCPClientError(RuntimeError):
    pass


class BaseMCPClient:
    """Thin synchronous wrapper around the official `mcp` Python SDK."""

    def __init__(
        self,
        name: str,
        transport: str,
        url: str = "",
        token: str = "",
        command: str = "",
        verify_ssl: bool = True,
        env: Optional[Dict[str, str]] = None,
    ):
        self.name = name
        self.transport = (transport or "http").lower()
        self.url = url
        self.token = token
        self.command = command
        self.verify_ssl = verify_ssl
        # Extra environment variables to inject into the spawned stdio
        # subprocess (e.g. NETBOX_URL / NETBOX_TOKEN for an embedded
        # netbox-mcp-server). Merged on top of the parent process's full
        # environment — see _stdio_session() for why that merge is
        # necessary in the first place.
        self.env = env or {}
        self._tool_names: Optional[List[str]] = None

    # ── low-level session helpers ───────────────────────────────────────

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def _http_session(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        if not self.url:
            raise MCPClientError(f"{self.name}: MCP URL is not configured")

        kwargs: Dict[str, Any] = {
            "url": self.url,
            "headers": self._auth_headers(),
        }

        # Only override httpx_client_factory when we actually need a
        # custom one (verify_ssl=False). streamablehttp_client's own
        # default (create_mcp_http_client) is a real, working callable -
        # explicitly passing httpx_client_factory=None here (the previous
        # bug) overrides that default with None, which the library then
        # tries to call directly (`httpx_client_factory(...)`), raising
        # "'NoneType' object is not callable". Confirmed live: this broke
        # every real (non-demo) GitHub MCP call, since GitHubMCPClient
        # always sets verify_ssl=True - NetBox never hit this because it
        # uses the stdio transport, not http.
        if not self.verify_ssl:
            import httpx

            def factory(headers, timeout, **kw):  # noqa: ANN001
                return httpx.AsyncClient(headers=headers, timeout=timeout, verify=False, **kw)

            kwargs["httpx_client_factory"] = factory

        return streamablehttp_client(**kwargs)

    async def _stdio_session(self):
        import os

        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        if not self.command:
            raise MCPClientError(f"{self.name}: MCP command is not configured")

        # IMPORTANT: the MCP SDK does NOT inherit the full parent process
        # environment by default when `env` is omitted from
        # StdioServerParameters — it falls back to a minimal safe subset
        # (PATH/HOME/etc). Without this explicit merge, credentials like
        # NETBOX_URL/NETBOX_TOKEN that are only present in *this*
        # process's environment (e.g. loaded from .env, or injected by an
        # AAP Custom Credential) would silently NOT reach the spawned
        # server subprocess.
        merged_env = {**os.environ, **self.env}

        parts = shlex.split(self.command)
        params = StdioServerParameters(command=parts[0], args=parts[1:], env=merged_env)
        return stdio_client(params)

    async def _session_cm(self):
        if self.transport == "stdio":
            return await self._stdio_session()
        return await self._http_session()

    async def _list_tools_async(self) -> List[str]:
        from mcp import ClientSession

        async with await self._session_cm() as (read, write, *_rest):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [t.name for t in tools.tools]

    async def _call_tool_async(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> Any:
        from mcp import ClientSession

        async with await self._session_cm() as (read, write, *_rest):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=args or {})
                if result.content:
                    # Prefer EmbeddedResource content. Confirmed live: GitHub's
                    # hosted get_file_contents tool returns TWO content items -
                    # a short TextContent status message first (e.g.
                    # "successfully downloaded text file (SHA: ...)"), followed
                    # by an EmbeddedResource whose `.resource.text` (or
                    # `.resource.blob`, base64, for binary files) holds the
                    # actual file body. The previous code returned on the
                    # FIRST item with a `.text` attribute, which matched the
                    # status message's TextContent.text and never reached the
                    # real file content.
                    for item in result.content:
                        resource = getattr(item, "resource", None)
                        if resource is None:
                            continue
                        resource_text = getattr(resource, "text", None)
                        if resource_text:
                            return self._maybe_json(resource_text)
                        resource_blob = getattr(resource, "blob", None)
                        if resource_blob:
                            import base64

                            decoded = base64.b64decode(resource_blob).decode(
                                "utf-8", errors="replace"
                            )
                            return self._maybe_json(decoded)

                    # Fall back to plain TextContent items (most tools only
                    # return these, e.g. JSON API responses with no
                    # embedded-resource wrapping).
                    for item in result.content:
                        text = getattr(item, "text", None)
                        if text:
                            return self._maybe_json(text)
                return {}

    @staticmethod
    def _maybe_json(text: str) -> Any:
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text

    # ── sync wrappers ───────────────────────────────────────────────────

    @staticmethod
    def _run_async(coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, coro).result()
        return asyncio.run(coro)

    def list_tools(self, refresh: bool = False) -> List[str]:
        if self._tool_names is None or refresh:
            self._tool_names = self._run_async(self._list_tools_async())
        return self._tool_names

    def call_tool(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> Any:
        return self._run_async(self._call_tool_async(tool_name, args))

    def find_tool(self, *keywords: str) -> Optional[str]:
        """Return the first discovered tool name containing ALL given keywords."""
        try:
            names = self.list_tools()
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: failed to list MCP tools: %s", self.name, exc)
            return None
        for candidate in names:
            lowered = candidate.lower()
            if all(kw.lower() in lowered for kw in keywords):
                return candidate
        return None

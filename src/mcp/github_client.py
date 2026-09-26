"""GitHub access over MCP — the source of truth for SECURITY policy.

Real (non-demo) mode calls the official GitHub MCP server's
`get_file_contents` tool (this exact tool name is exposed by GitHub's
hosted and self-hosted `github-mcp-server`) to fetch a per-device YAML
policy file from GITHUB_POLICY_REPO_OWNER/GITHUB_POLICY_REPO_NAME at
GITHUB_POLICY_BRANCH, using GITHUB_POLICY_PATH_TEMPLATE with `{device}`
substituted.

Demo mode (DEMO_MODE=true) reads the same YAML shape from
demo_fixtures/github/security-policies/<device>.yml instead.
"""

import base64
import binascii
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from src.config import PROJECT_ROOT, get_settings
from src.mcp.base_client import BaseMCPClient, MCPClientError

logger = logging.getLogger(__name__)

DEMO_POLICY_DIR = PROJECT_ROOT / "demo_fixtures" / "github" / "security-policies"


class GitHubPolicyNotFound(RuntimeError):
    pass


class GitHubMCPClient:
    """High-level GitHub client used by Agent 3 (and Agent 4's revert plan)."""

    def __init__(self):
        self.settings = get_settings()
        self._mcp: Optional[BaseMCPClient] = None
        if not self.settings.demo_mode:
            self._mcp = BaseMCPClient(
                name="github",
                transport=self.settings.github_mcp_transport,
                url=self.settings.github_mcp_url,
                token=self.settings.github_mcp_token,
                command=self.settings.github_mcp_command,
                verify_ssl=True,
            )

    def _policy_path(self, device_name: str) -> str:
        return self.settings.github_policy_path_template.format(device=device_name)

    def _get_policy_demo(self, device_name: str) -> Dict[str, Any]:
        file_path = DEMO_POLICY_DIR / f"{device_name}.yml"
        if not file_path.exists():
            raise GitHubPolicyNotFound(
                f"No demo security policy fixture found for '{device_name}' "
                f"(expected {file_path})"
            )
        return yaml.safe_load(file_path.read_text()) or {}

    def _get_policy_live(self, device_name: str) -> Dict[str, Any]:
        assert self._mcp is not None
        path = self._policy_path(device_name)
        tool_name = self._mcp.find_tool("get", "file", "contents") or "get_file_contents"

        try:
            result = self._mcp.call_tool(
                tool_name,
                {
                    "owner": self.settings.github_policy_repo_owner,
                    "repo": self.settings.github_policy_repo_name,
                    "path": path,
                    "ref": self.settings.github_policy_branch,
                },
            )
        except Exception as exc:  # noqa: BLE001
            raise MCPClientError(f"GitHub MCP call failed via '{tool_name}': {exc}") from exc

        content = self._extract_content(result)
        if content is None:
            raise GitHubPolicyNotFound(
                f"Security policy file not found for '{device_name}' at {path}"
            )
        return yaml.safe_load(content) or {}

    @staticmethod
    def _extract_content(result: Any) -> Optional[str]:
        """Handle the couple of shapes GitHub MCP servers commonly return."""
        if isinstance(result, str):
            text = result
        elif isinstance(result, dict):
            text = result.get("content") or result.get("text")
        else:
            text = None

        if text is None:
            return None

        # GitHub's contents API (and MCP wrappers around it) usually base64-encodes.
        try:
            decoded = base64.b64decode(text, validate=True)
            return decoded.decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return text

    def get_security_policy(self, device_name: str) -> Dict[str, Any]:
        if self.settings.demo_mode:
            return self._get_policy_demo(device_name)
        return self._get_policy_live(device_name)

    def policy_source_metadata(self, device_name: str) -> Dict[str, str]:
        if self.settings.demo_mode:
            return {
                "mode": "demo",
                "path": str(DEMO_POLICY_DIR / f"{device_name}.yml"),
            }
        return {
            "mode": "live",
            "repo": f"{self.settings.github_policy_repo_owner}/{self.settings.github_policy_repo_name}",
            "branch": self.settings.github_policy_branch,
            "path": self._policy_path(device_name),
        }

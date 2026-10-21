"""GitHub access over MCP — the source of truth for SECURITY policy.

Real (non-demo) mode calls the official GitHub MCP server's
`get_file_contents` tool (this exact tool name is exposed by GitHub's
hosted and self-hosted `github-mcp-server`) to fetch a security policy
YAML file from GITHUB_POLICY_REPO_OWNER/GITHUB_POLICY_REPO_NAME at
GITHUB_POLICY_BRANCH, using GITHUB_POLICY_PATH_TEMPLATE (`{device}` is
substituted if present, but the path is normally a single file SHARED
across all devices - e.g.
arista_virtual_devices/vars/all_policies.yml - rather than a separate
file per device).

Demo mode (DEMO_MODE=true) reads the same YAML shape from
demo_fixtures/github/security-policies/<device>.yml instead.
"""

import base64
import binascii
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

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
        policy = yaml.safe_load(file_path.read_text()) or {}
        return self._normalize_policy(policy)

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
        policy = yaml.safe_load(content) or {}
        return self._normalize_policy(policy)

    @classmethod
    def _normalize_policy(cls, policy: Dict[str, Any]) -> Dict[str, Any]:
        """Adapt the richer `security_acls` ACE schema (the native format
        used by arista_virtual_devices/vars/all_policies.yml /
        deploy_security_policies.yml) into the flat `acl_rules: [list of
        EOS CLI lines]` shape Agent 3 compares against - so the shared
        policy file can be used as-is for both device deployment AND drift
        detection, with no duplicated content.

        No-op (returns `policy` unchanged) if `security_acls` isn't
        present, so flat `acl_rules`-shaped policy files (e.g. existing
        demo fixtures) keep working untouched.
        """
        if "security_acls" not in policy:
            return policy

        lines: List[str] = []
        for acl in policy.get("security_acls") or []:
            aces = sorted(acl.get("aces") or [], key=lambda a: a.get("sequence", 0))
            lines.extend(cls._ace_to_cli_line(ace) for ace in aces)

        return {**policy, "acl_rules": lines}

    @staticmethod
    def _ace_to_cli_line(ace: Dict[str, Any]) -> str:
        """Render one ACE dict (all_policies.yml's schema) as the
        equivalent flat EOS CLI line, e.g.
        {"grant": "deny", "protocol": "tcp", "destination":
         {"any": True, "port_protocol": {"eq": "23"}}}
        -> "deny tcp any any eq 23"

        Only supports `any` source/destination today (the only form this
        project's ACLs currently use) - extend here if host/network
        matches are ever added to all_policies.yml.
        """
        grant = ace.get("grant", "permit")
        protocol = ace.get("protocol", "ip")
        source = "any" if (ace.get("source") or {}).get("any") else "any"
        destination = ace.get("destination") or {}
        dest_token = "any" if destination.get("any") else "any"

        line = f"{grant} {protocol} {source} {dest_token}"
        port = (destination.get("port_protocol") or {}).get("eq")
        if port:
            line += f" eq {port}"
        return line

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

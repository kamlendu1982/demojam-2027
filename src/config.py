"""Configuration management for the Network Drift Manager.

Loads every setting from environment variables / a local .env file (see
.env.example in the project root for the full list and documentation of
each variable).
"""

from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM (MaaS, OpenAI-compatible) ───────────────────────────────────
    maas_api_base: str = Field("", description="MaaS OpenAI-compatible base URL")
    maas_api_key: str = Field("", description="MaaS API key")
    maas_model: str = Field("", description="MaaS model name")

    # ── NetBox (MCP) ─────────────────────────────────────────────────────
    # There are TWO distinct sets of NetBox settings — don't confuse them:
    #
    #   netbox_url / netbox_token
    #       Credentials for the REAL NetBox instance. These are what the
    #       embedded NetBox MCP server itself needs (e.g. netboxlabs/
    #       netbox-mcp-server reads NETBOX_URL / NETBOX_TOKEN from its own
    #       process environment). When NETBOX_MCP_TRANSPORT=stdio, this
    #       project passes them into the spawned subprocess's environment
    #       (see BaseMCPClient / NetBoxMCPClient). Passed via AAP as an
    #       extra_var (netbox_url) + a Custom Credential env var
    #       (NETBOX_TOKEN) — see network-drift-manager.yaml.
    #
    #   netbox_mcp_url / netbox_mcp_token
    #       Only relevant for NETBOX_MCP_TRANSPORT=http: the URL of an
    #       ALREADY-RUNNING, separately-hosted NetBox MCP server, and a
    #       bearer token to authenticate to THAT server's HTTP endpoint
    #       (its own MCP_AUTH_TOKEN, not the NetBox API token).
    netbox_url: str = Field(
        "", description="Base URL of the real NetBox instance (for the embedded/stdio MCP server)"
    )
    netbox_token: str = Field(
        "", description="NetBox API token (for the embedded/stdio MCP server)"
    )

    netbox_mcp_transport: str = Field("http", description="'http' or 'stdio'")
    netbox_mcp_url: str = Field("", description="Streamable-HTTP MCP URL for an externally-hosted NetBox MCP server")
    netbox_mcp_token: str = Field("", description="Bearer token for an externally-hosted NetBox MCP server's HTTP endpoint")
    netbox_mcp_command: str = Field("", description="Shell command for stdio transport, e.g. 'uv run netbox-mcp-server'")
    netbox_verify_ssl: bool = Field(True, description="Verify TLS certs when talking to NetBox")
    netbox_mcp_device_tool: str = Field(
        "", description="Override auto-discovered NetBox MCP tool name"
    )

    # ── GitHub (MCP) ─────────────────────────────────────────────────────
    github_mcp_transport: str = Field("http", description="'http' or 'stdio'")
    github_mcp_url: str = Field("", description="Streamable-HTTP MCP URL for GitHub")
    github_mcp_token: str = Field("", description="PAT / bearer token for GitHub MCP server")
    github_mcp_command: str = Field("", description="Shell command for stdio transport")

    github_policy_repo_owner: str = Field("", description="Owner/org of the policy repo")
    github_policy_repo_name: str = Field("", description="Name of the policy repo")
    github_policy_branch: str = Field("main", description="Branch to read policy files from")
    github_policy_path_template: str = Field(
        "security-policies/{device}.yml",
        description="Path template for a device's security policy file",
    )

    # ── AAP Controller ───────────────────────────────────────────────────
    aap_url: str = Field("", description="AAP Controller base URL")
    aap_token: str = Field("", description="AAP API token")
    aap_verify_ssl: bool = Field(False, description="Verify TLS certs for AAP")
    aap_job_template_netbox_remediation: str = Field(
        "", description="AAP job template ID/name used to revert NetBox-governed drift"
    )
    aap_job_template_github_remediation: str = Field(
        "", description="AAP job template ID/name used to revert GitHub-governed drift"
    )
    aap_extra_vars_device_key: str = Field(
        "device_name", description="Extra-vars key used to pass the device name to AAP"
    )

    # ── Behaviour ────────────────────────────────────────────────────────
    dry_run: bool = Field(True, description="If true, never launch AAP jobs — plan only")
    demo_mode: bool = Field(True, description="If true, use local fixtures instead of live MCP/AAP")
    log_level: str = Field("INFO")

    @property
    def has_llm(self) -> bool:
        return bool(self.maas_api_base and self.maas_api_key and self.maas_model)


_settings: Optional[Settings] = None


def load_settings(refresh: bool = False) -> Settings:
    """Load (or reload) settings from the environment / .env file.

    override=False is intentional: a variable already present in the
    process environment (e.g. injected by an AAP Custom Credential, or set
    directly by a test/shell) must always win over whatever happens to be
    sitting in a checked-out .env file on disk. Only keys NOT already set
    get filled in from .env.
    """
    global _settings
    if _settings is None or refresh:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
        _settings = Settings()
    return _settings


def get_settings() -> Settings:
    return load_settings()

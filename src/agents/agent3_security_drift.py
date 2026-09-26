"""Agent 3 — SecurityPolicyDriftChecker.

Triggered when Agent 1 reports `security_review_attributes` (attributes
classified as security-related that NetBox does not model). This agent
fetches the security policy "source of truth" for the device from GitHub
(over MCP) and produces the REAL true/false drift verdict for each of
those attributes.
"""

import logging
from typing import Dict, List

from src.mcp.github_client import GitHubMCPClient, GitHubPolicyNotFound
from src.models import Agent1Response, Agent3Response, AttributeResult
from src import llm

logger = logging.getLogger(__name__)


class SecurityPolicyDriftChecker:
    """Agent 3: compare security attributes against the GitHub policy repo."""

    def __init__(self, github_client: GitHubMCPClient = None):
        self.github = github_client or GitHubMCPClient()

    def run(self, agent1_response: Agent1Response) -> Agent3Response:
        device = agent1_response.device
        attrs_to_check: List[str] = agent1_response.security_review_attributes

        results: Dict[str, AttributeResult] = {}
        remediation: List[str] = []
        policy_source = self.github.policy_source_metadata(device)

        try:
            policy = self.github.get_security_policy(device)
            policy_error = ""
        except GitHubPolicyNotFound as exc:
            policy = {}
            policy_error = str(exc)
        except Exception as exc:  # noqa: BLE001
            policy = {}
            policy_error = f"GitHub MCP lookup failed: {exc}"

        for attr_name in attrs_to_check:
            observed_value = agent1_response.attributes[attr_name].observed_value

            if policy_error:
                results[attr_name] = AttributeResult(
                    attribute=attr_name,
                    category="security",
                    drift=False,
                    source_of_truth="github",
                    observed_value=observed_value,
                    message=f"Could not verify against GitHub policy: {policy_error}",
                )
                continue

            if attr_name not in policy:
                results[attr_name] = AttributeResult(
                    attribute=attr_name,
                    category="security",
                    drift=False,
                    source_of_truth="github",
                    observed_value=observed_value,
                    message=(
                        "Attribute not defined in the GitHub security policy file "
                        "for this device; nothing to compare against."
                    ),
                )
                continue

            expected_value = policy[attr_name]
            has_drift = expected_value != observed_value
            results[attr_name] = AttributeResult(
                attribute=attr_name,
                category="security",
                drift=has_drift,
                source_of_truth="github",
                expected_value=expected_value,
                observed_value=observed_value,
                message=(
                    "Value differs from the GitHub security policy source of truth."
                    if has_drift
                    else "Matches GitHub security policy. No drift."
                ),
            )
            if has_drift:
                remediation.append(attr_name)

        summary_prompt = (
            f"Device '{device}' security policy check against GitHub. "
            f"Security drift found on: {remediation or 'none'}."
        )
        llm_summary = llm.summarize(summary_prompt)

        return Agent3Response(
            device=device,
            attributes=results,
            github_remediation_attributes=remediation,
            policy_source=policy_source,
            llm_summary=llm_summary,
        )

"""Agent 3 — SecurityPolicyDriftChecker.

Triggered when Agent 1 reports `security_review_attributes` (attributes
classified as security-related that NetBox does not model). This agent
fetches the security policy "source of truth" for the device from GitHub
(over MCP) and produces the REAL true/false drift verdict for each of
those attributes.
"""

import logging
import re
from typing import Dict, List, Optional

from src.mcp.github_client import GitHubMCPClient, GitHubPolicyNotFound
from src.models import Agent1Response, Agent3Response, AttributeResult
from src import llm

logger = logging.getLogger(__name__)

_ACL_PORT_RE = re.compile(r"\beq\s+(\S+)")


def _acl_rule_key(line: str) -> str:
    """Stable identity key for one flat ACL rule CLI line (e.g. "deny tcp
    any any eq 23"), used to match an observed rule to its corresponding
    policy rule WITHOUT needing an explicit sequence number.

    Uses the rule's destination port ("eq <port>") when present - every
    ACE in this project's ACLs has a unique port (22, 23, ...) - and falls
    back to the full line for port-less entries (e.g. the catch-all
    "permit ip any any").
    """
    match = _ACL_PORT_RE.search(line)
    return f"eq:{match.group(1)}" if match else line.strip()


def _diff_acl_rules(expected: List[str], observed: List[str]) -> List[str]:
    """Compare ACL rule lines by identity, not by list length/position.

    This is what makes a PARTIAL `observed` list work correctly - e.g. a
    real Splunk AAA accounting event only ever reports the single rule
    that was just changed ("cmd=20 permit tcp any any eq 23"), never the
    whole ACL. Comparing a 1-item observed list against the full 3-item
    policy list with plain `!=` would always report drift, even when that
    one rule already matches policy. Here, each observed rule is matched
    to its corresponding policy rule by identity (see _acl_rule_key) and
    only THAT pair is compared - rules not mentioned in `observed` are
    simply not checked (we only verify what was actually reported).

    Returns a list of human-readable mismatch descriptions - empty if
    every observed rule matches its corresponding expected rule.
    """
    expected_by_key = {_acl_rule_key(line): line for line in expected}
    mismatches: List[str] = []
    for obs_line in observed:
        key = _acl_rule_key(obs_line)
        exp_line = expected_by_key.get(key)
        if exp_line is None:
            mismatches.append(f"'{obs_line}' is not defined in the GitHub policy")
        elif exp_line != obs_line:
            mismatches.append(f"'{obs_line}' should be '{exp_line}'")
    return mismatches


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

            mismatches: Optional[List[str]] = None
            if (
                isinstance(expected_value, list)
                and isinstance(observed_value, list)
                and all(isinstance(x, str) for x in expected_value)
                and all(isinstance(x, str) for x in observed_value)
            ):
                # Flat list-of-CLI-line attributes (e.g. acl_rules): compare
                # rule-by-rule so a partial observed list (a single changed
                # line, as a real Splunk event would report) is checked
                # correctly instead of always mismatching on length/order.
                mismatches = _diff_acl_rules(expected_value, observed_value)
                has_drift = bool(mismatches)
            else:
                has_drift = expected_value != observed_value

            if has_drift and mismatches:
                message = "Value differs from the GitHub security policy source of truth: " + "; ".join(
                    mismatches
                )
            elif has_drift:
                message = "Value differs from the GitHub security policy source of truth."
            else:
                message = "Matches GitHub security policy. No drift."

            results[attr_name] = AttributeResult(
                attribute=attr_name,
                category="security",
                drift=has_drift,
                source_of_truth="github",
                expected_value=expected_value,
                observed_value=observed_value,
                message=message,
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

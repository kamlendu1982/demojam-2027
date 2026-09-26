"""Agent 1 — DeviceDriftDetector.

Given a device name and a dict of attribute_name -> observed_value:

  1. Classify each attribute as "security" or "networking" (deterministic
     config lookup, LLM fallback only for unknown names).
  2. "security"   -> NetBox does not govern this attribute. Emit
                     drift="security" and route it to Agent 3 for the real
                     GitHub-backed verdict. NO comparison is attempted here.
  3. "networking" -> fetch the source-of-truth value from NetBox (via MCP)
                     and compare it to the observed value.
                       - values differ -> drift=True,  expected_value=NetBox truth
                       - values match  -> drift=False

Output is always the strict `Agent1Response` JSON model — see src/models.py.
"""

import logging
from typing import Any, Dict

from src.classification import classify_from_config
from src.llm import classify_attribute
from src.mcp.netbox_client import NetBoxDeviceNotFound, NetBoxMCPClient
from src.models import Agent1Response, AttributeResult
from src import llm

logger = logging.getLogger(__name__)


class DeviceDriftDetector:
    """Agent 1: classify attributes and detect NetBox-governed drift."""

    def __init__(self, netbox_client: NetBoxMCPClient = None):
        self.netbox = netbox_client or NetBoxMCPClient()

    def _classify(self, attribute_name: str):
        category, netbox_path = classify_from_config(attribute_name)
        if category is not None:
            return category, netbox_path
        # Deterministic config had no entry -> bounded LLM fallback.
        category = classify_attribute(attribute_name)
        return category, None

    def run(self, device: str, observed_attributes: Dict[str, Any]) -> Agent1Response:
        results: Dict[str, AttributeResult] = {}
        netbox_remediation: list[str] = []
        security_review: list[str] = []

        # Separate networking attrs first so we can fetch NetBox truth in one call.
        networking_attrs: Dict[str, str] = {}
        categories: Dict[str, str] = {}
        for attr_name in observed_attributes:
            category, netbox_path = self._classify(attr_name)
            categories[attr_name] = category
            if category == "networking":
                networking_attrs[attr_name] = netbox_path or attr_name

        netbox_truth: Dict[str, Any] = {}
        netbox_error: str = ""
        if networking_attrs:
            try:
                netbox_truth = self.netbox.get_attribute_values(device, networking_attrs)
            except NetBoxDeviceNotFound as exc:
                netbox_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                netbox_error = f"NetBox MCP lookup failed: {exc}"

        for attr_name, observed_value in observed_attributes.items():
            category = categories[attr_name]

            if category == "security":
                results[attr_name] = AttributeResult(
                    attribute=attr_name,
                    category="security",
                    drift="security",
                    source_of_truth="github",
                    observed_value=observed_value,
                    message=(
                        "This is a security setting. Security settings are defined "
                        "and governed in GitHub, not NetBox. Routing to the "
                        "security policy drift agent for a GitHub-backed verdict."
                    ),
                )
                security_review.append(attr_name)
                continue

            # category == "networking"
            if netbox_error:
                results[attr_name] = AttributeResult(
                    attribute=attr_name,
                    category="networking",
                    drift=False,
                    source_of_truth="netbox",
                    observed_value=observed_value,
                    message=f"Could not verify against NetBox: {netbox_error}",
                )
                continue

            expected_value = netbox_truth.get(attr_name)
            has_drift = expected_value != observed_value
            results[attr_name] = AttributeResult(
                attribute=attr_name,
                category="networking",
                drift=has_drift,
                source_of_truth="netbox",
                expected_value=expected_value,
                observed_value=observed_value,
                message=(
                    "Value differs from NetBox source of truth."
                    if has_drift
                    else "Matches NetBox source of truth. No drift."
                ),
            )
            if has_drift:
                netbox_remediation.append(attr_name)

        summary_prompt = (
            f"Device '{device}' drift check. "
            f"Networking drift found on: {netbox_remediation or 'none'}. "
            f"Security attributes routed for policy review: {security_review or 'none'}."
        )
        llm_summary = llm.summarize(summary_prompt)

        return Agent1Response(
            device=device,
            attributes=results,
            netbox_remediation_attributes=netbox_remediation,
            security_review_attributes=security_review,
            llm_summary=llm_summary,
        )

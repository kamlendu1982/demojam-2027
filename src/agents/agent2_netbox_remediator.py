"""Agent 2 — NetBoxRemediator.

Triggered when Agent 1 reports `netbox_remediation_attributes` (networking
drift=True). Launches the AAP job template configured in
AAP_JOB_TEMPLATE_NETBOX_REMEDIATION, passing every drifted attribute's
NetBox (source-of-truth) value in as an extra_var, so the device gets
reverted to exactly what NetBox says it should be.
"""

import logging
from typing import Any, Dict, List

from src.aap.aap_client import AAPClient
from src.config import get_settings
from src.models import Agent1Response, RemediationResult

logger = logging.getLogger(__name__)


class NetBoxRemediator:
    """Agent 2: revert networking drift back to NetBox values via AAP."""

    def __init__(self, aap_client: AAPClient = None):
        self.aap = aap_client or AAPClient()

    def run(self, agent1_response: Agent1Response, dry_run: bool = None) -> RemediationResult:
        settings = get_settings()
        device = agent1_response.device
        attrs: List[str] = agent1_response.netbox_remediation_attributes

        extra_vars: Dict[str, Any] = {settings.aap_extra_vars_device_key: device}
        for attr_name in attrs:
            result = agent1_response.attributes[attr_name]
            extra_vars[attr_name] = result.expected_value

        if not attrs:
            return RemediationResult(
                agent="netbox_remediator",
                device=device,
                source_of_truth="netbox",
                attributes_remediated=[],
                extra_vars=extra_vars,
                job_template=settings.aap_job_template_netbox_remediation,
                launched=False,
                dry_run=True,
                error=None,
            )

        launch = self.aap.launch_job_template(
            settings.aap_job_template_netbox_remediation,
            extra_vars,
            dry_run=dry_run,
        )

        return RemediationResult(
            agent="netbox_remediator",
            device=device,
            source_of_truth="netbox",
            attributes_remediated=attrs,
            extra_vars=extra_vars,
            job_template=launch.job_template,
            launched=launch.launched,
            dry_run=launch.dry_run,
            job_id=launch.job_id,
            job_url=launch.job_url,
            error=launch.error,
        )

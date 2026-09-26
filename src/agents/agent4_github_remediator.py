"""Agent 4 — GitHubRemediator.

Triggered when Agent 3 reports `github_remediation_attributes` (security
drift=True against the GitHub policy). Launches the AAP job template
configured in AAP_JOB_TEMPLATE_GITHUB_REMEDIATION, passing every drifted
attribute's GitHub (source-of-truth) value in as an extra_var, so the
device gets reverted to exactly what the GitHub policy says it should be.
"""

import logging
from typing import Any, Dict, List

from src.aap.aap_client import AAPClient
from src.config import get_settings
from src.models import Agent3Response, RemediationResult

logger = logging.getLogger(__name__)


class GitHubRemediator:
    """Agent 4: revert security drift back to GitHub policy values via AAP."""

    def __init__(self, aap_client: AAPClient = None):
        self.aap = aap_client or AAPClient()

    def run(self, agent3_response: Agent3Response, dry_run: bool = None) -> RemediationResult:
        settings = get_settings()
        device = agent3_response.device
        attrs: List[str] = agent3_response.github_remediation_attributes

        extra_vars: Dict[str, Any] = {settings.aap_extra_vars_device_key: device}
        for attr_name in attrs:
            result = agent3_response.attributes[attr_name]
            extra_vars[attr_name] = result.expected_value

        if not attrs:
            return RemediationResult(
                agent="github_remediator",
                device=device,
                source_of_truth="github",
                attributes_remediated=[],
                extra_vars=extra_vars,
                job_template=settings.aap_job_template_github_remediation,
                launched=False,
                dry_run=True,
                error=None,
            )

        launch = self.aap.launch_job_template(
            settings.aap_job_template_github_remediation,
            extra_vars,
            dry_run=dry_run,
        )

        return RemediationResult(
            agent="github_remediator",
            device=device,
            source_of_truth="github",
            attributes_remediated=attrs,
            extra_vars=extra_vars,
            job_template=launch.job_template,
            launched=launch.launched,
            dry_run=launch.dry_run,
            job_id=launch.job_id,
            job_url=launch.job_url,
            error=launch.error,
        )

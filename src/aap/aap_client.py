"""AAP (Ansible Automation Platform) client — remediation via job templates.

Agents 2 and 4 use this client to launch an AAP job template that reverts a
drifted device attribute back to its source-of-truth value, passing the
correct values in as `extra_vars`.

Only two operations are needed for this workflow:
  - resolve a job template identifier (numeric ID or exact name) to an ID
  - launch that job template with a given `extra_vars` payload

In DRY_RUN mode (default) or DEMO_MODE, no real HTTP call is made — the
client returns a simulated result so the deterministic JSON contract still
gets populated with what *would* be launched.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class JobLaunchResult:
    launched: bool
    dry_run: bool
    job_template: str
    extra_vars: Dict[str, Any]
    job_id: Optional[int] = None
    job_url: Optional[str] = None
    error: Optional[str] = None


class AAPClient:
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.aap_url.rstrip("/")
        self._session: Optional[httpx.Client] = None

    @property
    def session(self) -> httpx.Client:
        if self._session is None:
            headers = {}
            if self.settings.aap_token:
                headers["Authorization"] = f"Bearer {self.settings.aap_token}"
            self._session = httpx.Client(
                headers=headers,
                verify=self.settings.aap_verify_ssl,
                timeout=30.0,
            )
        return self._session

    def _api(self, path: str) -> str:
        return f"{self.base_url}/api/controller/v2/{path.lstrip('/')}"

    def _resolve_job_template_id(self, identifier: str) -> int:
        if identifier.isdigit():
            return int(identifier)

        resp = self.session.get(
            self._api("job_templates/"), params={"name": identifier}
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            raise ValueError(f"AAP job template not found: '{identifier}'")
        return results[0]["id"]

    def launch_job_template(
        self,
        identifier: str,
        extra_vars: Dict[str, Any],
        dry_run: Optional[bool] = None,
    ) -> JobLaunchResult:
        """Launch `identifier` (ID or name) with `extra_vars`.

        Returns a JobLaunchResult regardless of mode; in dry-run/demo mode
        `launched` is False and job_id/job_url are None, but the plan
        (job_template + extra_vars) is always populated so callers can
        report exactly what *would* happen.
        """
        is_dry_run = self.settings.dry_run if dry_run is None else dry_run

        if is_dry_run or self.settings.demo_mode:
            logger.info(
                "[DRY-RUN/DEMO] Would launch AAP job template '%s' with extra_vars=%s",
                identifier,
                extra_vars,
            )
            return JobLaunchResult(
                launched=False,
                dry_run=True,
                job_template=identifier,
                extra_vars=extra_vars,
            )

        try:
            template_id = self._resolve_job_template_id(identifier)
            resp = self.session.post(
                self._api(f"job_templates/{template_id}/launch/"),
                json={"extra_vars": extra_vars},
            )
            resp.raise_for_status()
            body = resp.json()
            job_id = body.get("job") or body.get("id")
            job_url = f"{self.base_url}/#/jobs/playbook/{job_id}/output" if job_id else None
            return JobLaunchResult(
                launched=True,
                dry_run=False,
                job_template=identifier,
                extra_vars=extra_vars,
                job_id=job_id,
                job_url=job_url,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to launch AAP job template '%s': %s", identifier, exc)
            return JobLaunchResult(
                launched=False,
                dry_run=False,
                job_template=identifier,
                extra_vars=extra_vars,
                error=str(exc),
            )

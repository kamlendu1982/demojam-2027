"""Pydantic schemas — the strict JSON contract produced by every agent.

Every agent in this pipeline returns ONE of these models, and every model
serializes cleanly to JSON via `.model_dump(mode="json")`. Nothing in this
file depends on the LLM: these are the deterministic response shapes the
workflow specification requires.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

DriftValue = Union[bool, Literal["security"]]
SourceOfTruth = Literal["netbox", "github"]
Category = Literal["security", "networking"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AttributeResult(BaseModel):
    """Per-attribute outcome, as produced by Agent 1 or Agent 3."""

    attribute: str
    category: Category
    # true       -> networking/security drift confirmed vs source of truth
    # false      -> value matches source of truth, no drift
    # "security" -> (Agent 1 only) attribute is security-governed; NetBox does
    #               not hold it, so no drift verdict is made here — Agent 3
    #               will produce the real true/false verdict against GitHub.
    drift: DriftValue
    source_of_truth: SourceOfTruth
    expected_value: Optional[Any] = None
    observed_value: Optional[Any] = None
    message: Optional[str] = None


class Agent1Response(BaseModel):
    """Output of Agent 1 — DeviceDriftDetector (NetBox-facing)."""

    agent: Literal["device_drift_detector"] = "device_drift_detector"
    device: str
    generated_at: datetime = Field(default_factory=utcnow)
    attributes: Dict[str, AttributeResult]
    # networking attributes where drift == True -> feed straight to Agent 2
    netbox_remediation_attributes: List[str] = Field(default_factory=list)
    # attributes classified as "security" -> feed to Agent 3 for the real check
    security_review_attributes: List[str] = Field(default_factory=list)
    llm_summary: Optional[str] = None


class Agent3Response(BaseModel):
    """Output of Agent 3 — SecurityPolicyDriftChecker (GitHub-facing)."""

    agent: Literal["security_policy_drift_checker"] = "security_policy_drift_checker"
    device: str
    generated_at: datetime = Field(default_factory=utcnow)
    attributes: Dict[str, AttributeResult]
    github_remediation_attributes: List[str] = Field(default_factory=list)
    policy_source: Dict[str, str] = Field(default_factory=dict)
    llm_summary: Optional[str] = None


class RemediationResult(BaseModel):
    """Output of Agent 2 (NetBoxRemediator) or Agent 4 (GitHubRemediator)."""

    agent: Literal["netbox_remediator", "github_remediator"]
    device: str
    generated_at: datetime = Field(default_factory=utcnow)
    source_of_truth: SourceOfTruth
    attributes_remediated: List[str] = Field(default_factory=list)
    extra_vars: Dict[str, Any] = Field(default_factory=dict)
    job_template: str = ""
    launched: bool = False
    dry_run: bool = True
    job_id: Optional[int] = None
    job_url: Optional[str] = None
    error: Optional[str] = None


class PipelineResponse(BaseModel):
    """Top-level JSON object returned for a full end-to-end pipeline run."""

    device: str
    generated_at: datetime = Field(default_factory=utcnow)
    agent1_drift_detection: Agent1Response
    agent2_netbox_remediation: Optional[RemediationResult] = None
    agent3_security_drift: Optional[Agent3Response] = None
    agent4_github_remediation: Optional[RemediationResult] = None

    @property
    def any_drift(self) -> bool:
        a1_drift = any(
            r.drift is True for r in self.agent1_drift_detection.attributes.values()
        )
        a3_drift = bool(
            self.agent3_security_drift
            and any(r.drift is True for r in self.agent3_security_drift.attributes.values())
        )
        return a1_drift or a3_drift

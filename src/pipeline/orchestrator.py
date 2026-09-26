"""Deterministic orchestrator wiring the four agents together.

Control flow (100% deterministic Python — no LLM/agent autonomy involved):

    Agent 1 (DeviceDriftDetector, NetBox)
        │
        ├─ netbox_remediation_attributes non-empty ──▶ Agent 2 (NetBoxRemediator → AAP)
        │
        └─ security_review_attributes non-empty ─────▶ Agent 3 (SecurityPolicyDriftChecker, GitHub)
                                                             │
                                                             └─ github_remediation_attributes non-empty
                                                                    ──▶ Agent 4 (GitHubRemediator → AAP)

Every branch is a plain `if` on the deterministic JSON output of the
previous agent — nothing here is decided by an LLM.
"""

from typing import Any, Dict, Optional

from src.agents.agent1_drift_detector import DeviceDriftDetector
from src.agents.agent2_netbox_remediator import NetBoxRemediator
from src.agents.agent3_security_drift import SecurityPolicyDriftChecker
from src.agents.agent4_github_remediator import GitHubRemediator
from src.config import get_settings
from src.models import PipelineResponse


def run_pipeline(
    device: str,
    attributes: Dict[str, Any],
    dry_run: Optional[bool] = None,
) -> PipelineResponse:
    settings = get_settings()
    is_dry_run = settings.dry_run if dry_run is None else dry_run

    print("=" * 70)
    print("Network Drift Manager — Deterministic 4-Agent Pipeline")
    print(f"  Device  : {device}")
    print(f"  Mode    : {'DRY-RUN / PLAN ONLY' if is_dry_run else 'APPLY (will launch AAP jobs)'}")
    print(f"  Demo    : {settings.demo_mode}")
    print("=" * 70)

    # ── Agent 1: NetBox-facing drift detection + security classification ──
    print("\n[Agent 1] DeviceDriftDetector — checking NetBox …")
    agent1_response = DeviceDriftDetector().run(device, attributes)
    print(agent1_response.model_dump_json(indent=2))

    agent2_response = None
    agent3_response = None
    agent4_response = None

    # ── Agent 2: revert networking drift back to NetBox truth via AAP ─────
    if agent1_response.netbox_remediation_attributes:
        print(
            f"\n[Agent 2] NetBoxRemediator — drift found on "
            f"{agent1_response.netbox_remediation_attributes}; launching AAP remediation …"
        )
        agent2_response = NetBoxRemediator().run(agent1_response, dry_run=is_dry_run)
        print(agent2_response.model_dump_json(indent=2))
    else:
        print("\n[Agent 2] NetBoxRemediator — skipped (no networking drift found).")

    # ── Agent 3: security attributes -> check GitHub policy ───────────────
    if agent1_response.security_review_attributes:
        print(
            f"\n[Agent 3] SecurityPolicyDriftChecker — reviewing "
            f"{agent1_response.security_review_attributes} against GitHub policy …"
        )
        agent3_response = SecurityPolicyDriftChecker().run(agent1_response)
        print(agent3_response.model_dump_json(indent=2))

        # ── Agent 4: revert security drift back to GitHub truth via AAP ───
        if agent3_response.github_remediation_attributes:
            print(
                f"\n[Agent 4] GitHubRemediator — drift found on "
                f"{agent3_response.github_remediation_attributes}; launching AAP remediation …"
            )
            agent4_response = GitHubRemediator().run(agent3_response, dry_run=is_dry_run)
            print(agent4_response.model_dump_json(indent=2))
        else:
            print("\n[Agent 4] GitHubRemediator — skipped (no security policy drift found).")
    else:
        print("\n[Agent 3] SecurityPolicyDriftChecker — skipped (no security attributes to review).")

    return PipelineResponse(
        device=device,
        agent1_drift_detection=agent1_response,
        agent2_netbox_remediation=agent2_response,
        agent3_security_drift=agent3_response,
        agent4_github_remediation=agent4_response,
    )

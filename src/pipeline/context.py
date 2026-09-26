"""Mutable context threaded through the deterministic 4-agent pipeline."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.models import Agent1Response, Agent3Response, RemediationResult


@dataclass
class PipelineContext:
    device: str
    input_attributes: Dict[str, Any]
    dry_run: bool

    agent1: Optional[Agent1Response] = None
    agent2: Optional[RemediationResult] = None
    agent3: Optional[Agent3Response] = None
    agent4: Optional[RemediationResult] = None

    log: list = field(default_factory=list)

    def note(self, message: str) -> None:
        self.log.append(message)
        print(message)

"""MaaS (Model as a Service) LLM client — OpenAI-compatible.

This is the ONLY place in the codebase that talks to an LLM. It is invoked
from exactly two bounded call sites in the pipeline:

  1. `classify_attribute()` — fallback classification of an attribute name
     into "security" vs "networking" when it is not already present in
     config/attribute_classification.yaml. This NEVER decides drift, only
     the category used to route the deterministic branch.

  2. `summarize()` — produces a short, human-readable narrative that is
     attached to agent output as `llm_summary`. Purely cosmetic; removing
     it changes nothing about the deterministic drift/remediation logic.

If MAAS_API_BASE / MAAS_API_KEY / MAAS_MODEL are not configured (or
DEMO_MODE=true and no LLM is reachable), both functions fall back to a
deterministic default so the pipeline keeps working without an LLM.
"""

import json
import logging
from typing import Optional

from src.config import get_settings

logger = logging.getLogger(__name__)

_CLASSIFY_SYSTEM_PROMPT = """You are a strict network-configuration classifier.
Given a single device attribute name, respond with ONLY a JSON object of the
exact shape {"category": "security"} or {"category": "networking"}.

"security" means the attribute concerns access control, authentication,
authorization, accounting, encryption, credentials, ACLs/firewall rules,
banners, or logging/monitoring of access.

"networking" means the attribute concerns interfaces, addressing, routing,
VLANs, DNS/NTP, MTU, hardware/platform, site/location, or device status.

Respond with JSON only. No prose, no markdown fences."""


def _client():
    """Return an OpenAI-compatible client pointed at the MaaS endpoint, or None."""
    settings = get_settings()
    if not settings.has_llm:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed; LLM calls will be skipped.")
        return None

    return OpenAI(base_url=settings.maas_api_base, api_key=settings.maas_api_key)


def classify_attribute(attribute_name: str) -> str:
    """Classify an unknown attribute as 'security' or 'networking' via the MaaS LLM.

    Falls back to 'networking' (the safer, less-destructive default -- it
    routes to a read-only NetBox comparison rather than a security-policy
    remediation) when no LLM is configured or the call fails.
    """
    client = _client()
    if client is None:
        logger.info(
            "LLM not configured; defaulting unclassified attribute '%s' to 'networking'.",
            attribute_name,
        )
        return "networking"

    settings = get_settings()
    try:
        resp = client.chat.completions.create(
            model=settings.maas_model,
            messages=[
                {"role": "system", "content": _CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": f"attribute_name: {attribute_name}"},
            ],
            temperature=0,
            max_tokens=50,
        )
        content = resp.choices[0].message.content.strip()
        # Be defensive: strip accidental markdown fences.
        content = content.strip("`").strip()
        if content.lower().startswith("json"):
            content = content[4:].strip()
        parsed = json.loads(content)
        category = parsed.get("category", "networking")
        if category not in ("security", "networking"):
            category = "networking"
        return category
    except Exception as exc:  # noqa: BLE001 - defensive fallback by design
        logger.warning("LLM classification failed for '%s': %s", attribute_name, exc)
        return "networking"


def summarize(prompt: str) -> Optional[str]:
    """Produce a short natural-language summary via the MaaS LLM. Best-effort."""
    client = _client()
    if client is None:
        return None

    settings = get_settings()
    try:
        resp = client.chat.completions.create(
            model=settings.maas_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You summarize network configuration drift findings for a "
                        "network operations audience in 2-3 concise sentences. "
                        "Be factual; do not invent values not present in the input."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=200,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:  # noqa: BLE001 - summary is optional, never fatal
        logger.warning("LLM summarization failed: %s", exc)
        return None

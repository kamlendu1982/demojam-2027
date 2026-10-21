#!/usr/bin/env python3
"""Standalone EDA payload parser/extractor — demojam-2027.

STANDALONE BY DESIGN: this script does NOT import anything from src/ (the
existing, working network-drift-manager pipeline). It is a brand-new,
self-contained component, meant to be built and tested entirely in
isolation BEFORE any integration with network-drift-manager.yaml /
DemoJamNetworkDriftManageent. Nothing in src/ or network-drift-manager.yaml
is touched by this file.

PURPOSE
-------
An upstream EDA rulebook (owned by another team member — we don't control
its design) will trigger a new, separate AAP Job Template running this
script, passing WHATEVER extra_vars it builds from a Splunk webhook event.
The exact payload shape/key names aren't fully known yet, and the rulebook
may or may not already filter down to only genuinely relevant events —
this script is built to handle BOTH cases.

This script's job: turn that unknown-shape payload into the clean
contract DemoJamNetworkDriftManageent already expects:
    device_name        : str
    device_attributes   : dict   (e.g. {"acl_rules": ["permit tcp any any eq 23"]})
    pipeline_apply       : bool

Intended (once tested and confirmed working standalone) to be chained as
the FIRST node of an AAP Workflow Job Template, with
DemoJamNetworkDriftManageent as the second node (on success) — AAP
automatically merges this job's set_stats output into the extra_vars
available to the downstream node, the same way network-drift-manager.yaml
already exposes its own result via set_stats.

THREE-LAYER EXTRACTION (cheapest first, LLM only as a last resort)
--------------------------------------------------------------------
1. LOCATE  — find the raw AAA/Splunk message text somewhere in the
   incoming payload. Checks a few likely candidate keys first, then falls
   back to a recursive scan of every string value in the payload, so this
   keeps working even if the upstream rulebook's exact field names turn
   out to be different than guessed.

2. DETERMINISTIC PARSE — regex-extract the device hostname and the
   "cmd=<seq> <command text>" portion of a Splunk AAA accounting line,
   e.g.:
     Oct 15 18:05:15 ... switch1 Aaa: %ACCOUNTING-6-CMD: ... cmd=20 permit tcp any any eq 23 <cr>
   -> device_name="switch1", command_text="permit tcp any any eq 23"

   If command_text matches this project's known ACE grammar
   ("permit|deny ... any any [eq <port>]"), treat it as an ACL rule
   change -> device_attributes = {"acl_rules": [command_text]}. Zero LLM
   calls — this is the fast path when the upstream rulebook already
   filters down to clean, relevant events.

3. IGNORE-LIST — a short list of known-irrelevant AAA commands (show *,
   enable, configure terminal, write memory, login/logout, bare
   "no <seq>", entering ACL submode) that get silently skipped with no
   LLM call either. This is what lets the "rulebook does NOT filter"
   case work without an LLM call for the common/obvious noise.

4. LLM FALLBACK (MaaS, OpenAI-compatible) — only reached when the command
   text is neither a recognized ACE nor on the ignore-list, i.e. a
   genuinely ambiguous event. Sends the raw candidate text plus an
   instruction prompt (overridable via --llm-instruction, which the
   calling playbook can source from an extra var) to MAAS_MODEL and
   expects a strict JSON verdict. Any failure here (no credentials, no
   `openai` package, bad/unparseable response) falls back to a safe
   "not relevant" verdict — never crashes, never invents data.

Prints a single marker line, EDA_EXTRACTION_RESULT=<compact JSON>, so the
calling playbook can reliably locate it in stdout — mirrors the
PIPELINE_JSON_RESULT= convention already used by run_pipeline.py /
network-drift-manager.yaml.
"""

import argparse
import json
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("eda_payload_parser")

# ---------------------------------------------------------------------------
# Layer 1 — locate the raw message
# ---------------------------------------------------------------------------

# Candidate top-level keys to check FIRST, before falling back to a full
# recursive scan. Coordinate with whoever owns the EDA rulebook to use one
# of these names if possible — it avoids the (cheap, but not free) full
# payload scan entirely and is the most robust long-term contract.
CANDIDATE_KEYS = [
    "event_payload",
    "payload",
    "splunk_message",
    "message",
    "event",
    "raw_message",
]

# Signature identifying a string as a Splunk/syslog AAA accounting event
# at all (vs. some unrelated string elsewhere in the payload).
_AAA_SIGNATURE_RE = re.compile(r"%ACCOUNTING-\d-CMD|Aaa:\s*%ACCOUNTING")


def _iter_strings(value: Any):
    """Recursively yield every string leaf value in a nested dict/list."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_strings(v)


def find_raw_message(payload: Dict[str, Any]) -> Optional[str]:
    """Find the string in `payload` that looks like a raw AAA/Splunk line.

    Checks CANDIDATE_KEYS first (cheap, and the preferred contract to
    coordinate on with whoever owns the EDA rulebook), then falls back to
    scanning every string value anywhere in the payload — so this keeps
    working even if the field name turns out to be something else
    entirely, or the payload is deeply nested (e.g. a full Splunk webhook
    JSON body rather than one flat field).
    """
    for key in CANDIDATE_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and _AAA_SIGNATURE_RE.search(value):
            return value

    for text in _iter_strings(payload):
        if _AAA_SIGNATURE_RE.search(text):
            return text

    return None


# ---------------------------------------------------------------------------
# Layer 2 — deterministic parse
# ---------------------------------------------------------------------------

# Matches e.g.:
#   Oct 15 18:05:15 172.31.8.57 2026-10-15T18:05:15.189687+00:00 switch1 Aaa: %ACCOUNTING-6-CMD: admin vty12 172.20.20.1 stop task_id=24 start_time=1792087515.189287 timezone=UTC service=shell priv-lvl=15 cmd=20 permit tcp any any eq 23 <cr>
_HOSTNAME_RE = re.compile(
    r"^\S+\s+\d+\s+\S+\s+\S+\s+\S+\s+(?P<hostname>\S+)\s+Aaa:\s*%ACCOUNTING"
)
_CMD_RE = re.compile(r"\bcmd=\d+\s+(?P<cmd>.+?)\s*(?:<cr>)?\s*$")

# Flat ACE grammar this project's ACLs use, e.g.
#   "permit tcp any any eq 23"  /  "deny ip any any"
_ACE_GRAMMAR_RE = re.compile(
    r"^(permit|deny)\s+\S+\s+any\s+any(\s+eq\s+\S+)?\s*$", re.IGNORECASE
)

# Known-irrelevant AAA commands — silently skipped, no LLM call needed.
# This is what makes the "rulebook forwards everything, unfiltered" case
# cheap for the common/obvious noise.
_IGNORE_PATTERNS = [
    re.compile(r"^show\b", re.IGNORECASE),
    re.compile(r"^enable\s*$", re.IGNORECASE),
    re.compile(r"^configure(\s+terminal)?\s*$", re.IGNORECASE),
    re.compile(r"^write\s+memory\s*$", re.IGNORECASE),
    re.compile(r"^exit\s*$", re.IGNORECASE),
    re.compile(r"^end\s*$", re.IGNORECASE),
    re.compile(r"^no\s+\d+\s*$", re.IGNORECASE),  # bare "no <seq>" deletion
    re.compile(r"^ip access-list\s+\S+\s*$", re.IGNORECASE),  # entering ACL submode
]


def extract_hostname_and_command(raw_message: str) -> Tuple[Optional[str], Optional[str]]:
    hostname = None
    match = _HOSTNAME_RE.search(raw_message)
    if match:
        hostname = match.group("hostname")

    command = None
    match = _CMD_RE.search(raw_message)
    if match:
        command = match.group("cmd").strip()

    return hostname, command


def is_ignorable(command: str) -> bool:
    return any(p.search(command) for p in _IGNORE_PATTERNS)


def is_acl_rule(command: str) -> bool:
    return bool(_ACE_GRAMMAR_RE.match(command.strip()))


# ---------------------------------------------------------------------------
# Layer 3 — LLM fallback (MaaS, OpenAI-compatible)
#
# Deliberately standalone: this does NOT import src/llm.py, so this
# component has zero dependency on (and makes zero changes to) the
# existing pipeline while it's being built/tested in isolation.
# ---------------------------------------------------------------------------

DEFAULT_LLM_INSTRUCTION = (
    "You are analyzing ONE raw AAA accounting command line captured from a "
    "network switch. Decide whether it represents a SECURITY-relevant "
    "configuration change (e.g. an access-control-list rule, an "
    "authentication/authorization/accounting setting, a credential, a "
    "banner, or logging/monitoring-of-access configuration) that should be "
    "checked for drift against a GitHub-hosted policy.\n\n"
    "Respond with ONLY a JSON object of this exact shape:\n"
    '{"relevant": true|false, "device_name": "<hostname or null>", '
    '"attribute": "<attribute name, e.g. acl_rules, or null>", '
    '"value": "<the normalized command/value, or null>"}\n\n'
    "If not security-relevant, or you are not confident, respond with "
    '{"relevant": false, "device_name": null, "attribute": null, "value": null}. '
    "No prose, no markdown fences, JSON only."
)


def llm_fallback(
    raw_message: str,
    candidate_command: Optional[str],
    hostname: Optional[str],
    instruction: str,
) -> Dict[str, Any]:
    """Ask MAAS to classify/extract an ambiguous event.

    Best-effort: any failure (no client library, no credentials, bad
    response) returns a safe 'not relevant' verdict rather than raising —
    a missing/failed LLM call must never crash this extraction step or
    produce bad data for the downstream pipeline.
    """
    maas_api_base = os.environ.get("MAAS_API_BASE", "")
    maas_api_key = os.environ.get("MAAS_API_KEY", "")
    maas_model = os.environ.get("MAAS_MODEL", "")

    if not (maas_api_base and maas_api_key and maas_model):
        logger.info("MaaS not configured; skipping LLM fallback, treating as not relevant.")
        return {"relevant": False, "device_name": hostname, "attribute": None, "value": None}

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed; skipping LLM fallback.")
        return {"relevant": False, "device_name": hostname, "attribute": None, "value": None}

    user_content = (
        f"Raw event: {raw_message}\n"
        f"Candidate command text (may be empty if not parsed): {candidate_command or ''}\n"
        f"Hostname already parsed (may be empty): {hostname or ''}"
    )

    try:
        client = OpenAI(base_url=maas_api_base, api_key=maas_api_key)
        resp = client.chat.completions.create(
            model=maas_model,
            messages=[
                {"role": "system", "content": instruction},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
            # NOTE: 200 is too small for reasoning-style models (e.g.
            # gpt-oss-120b), which spend a large share of max_tokens on an
            # internal reasoning_content chain-of-thought BEFORE emitting
            # the final JSON answer. Confirmed live: with max_tokens=200,
            # gpt-oss-120b's reasoning alone used >200 tokens, truncating
            # the response before the final JSON, causing json.loads() to
            # fail and silently fall back to "not relevant" below - NOT a
            # model capability issue, a token-budget bug. 1000 comfortably
            # fits both reasoning and non-reasoning models.
            max_tokens=1000,
        )
        content = resp.choices[0].message.content.strip()
        content = content.strip("`").strip()
        if content.lower().startswith("json"):
            content = content[4:].strip()
        parsed = json.loads(content)
        return {
            "relevant": bool(parsed.get("relevant", False)),
            "device_name": parsed.get("device_name") or hostname,
            "attribute": parsed.get("attribute"),
            "value": parsed.get("value"),
        }
    except Exception as exc:  # noqa: BLE001 - defensive fallback by design
        logger.warning("LLM fallback call failed: %s", exc)
        return {"relevant": False, "device_name": hostname, "attribute": None, "value": None}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def parse_payload(payload: Dict[str, Any], llm_instruction: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "device_name": "",
        "device_attributes": {},
        "pipeline_apply": False,
        "extraction_method": "none",
        "extraction_notes": "",
    }

    raw_message = find_raw_message(payload)
    if raw_message is None:
        result["extraction_notes"] = "No AAA/Splunk-like message found anywhere in the payload."
        return result

    hostname, command = extract_hostname_and_command(raw_message)

    if command and is_ignorable(command):
        result["extraction_method"] = "ignored"
        result["extraction_notes"] = f"Command '{command}' is on the known-irrelevant ignore-list."
        result["device_name"] = hostname or ""
        return result

    if command and is_acl_rule(command):
        result["extraction_method"] = "deterministic"
        result["extraction_notes"] = f"Recognized ACE grammar: '{command}'."
        result["device_name"] = hostname or ""
        result["device_attributes"] = {"acl_rules": [command]}
        result["pipeline_apply"] = True
        return result

    # Ambiguous: either no cmd= found at all, or command text didn't match
    # known ACE grammar / ignore-list -> escalate to the LLM.
    verdict = llm_fallback(raw_message, command, hostname, llm_instruction)
    result["extraction_method"] = "llm"
    result["extraction_notes"] = (
        f"Deterministic parse inconclusive (command={command!r}); used LLM fallback."
    )
    if (
        verdict.get("relevant")
        and verdict.get("device_name")
        and verdict.get("attribute")
        and verdict.get("value")
    ):
        result["device_name"] = verdict["device_name"]
        result["device_attributes"] = {verdict["attribute"]: [verdict["value"]]}
        result["pipeline_apply"] = True
    else:
        result["device_name"] = verdict.get("device_name") or hostname or ""
        result["extraction_notes"] += " LLM verdict: not relevant / incomplete."

    return result


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a JSON file containing the full incoming extra_vars payload",
    )
    parser.add_argument(
        "--llm-instruction",
        default=DEFAULT_LLM_INSTRUCTION,
        help="Override the LLM fallback instruction prompt",
    )
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        payload = json.load(f)

    result = parse_payload(payload, args.llm_instruction)

    print(json.dumps(result, indent=2))
    print(f"EDA_EXTRACTION_RESULT={json.dumps(result, separators=(',', ':'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

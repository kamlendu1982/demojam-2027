#!/usr/bin/env python3
"""CLI entry point for the Network Drift Manager deterministic pipeline.

Usage:
    # Using an inline JSON string
    python run_pipeline.py --device rtr-core-01 \\
        --attributes '{"dns_servers": ["10.10.0.53"], "num_interfaces": 5}'

    # Using a JSON file (device + attributes)
    python run_pipeline.py --input examples/sample_request_security_drift.json

    # Apply mode (actually launch AAP jobs instead of just planning)
    python run_pipeline.py --input examples/sample_request_networking_drift.json --apply

The final, top-level JSON object (PipelineResponse) is always printed to
stdout as the LAST line of output, so scripts can pull it out with
`... | tail -n 1 | jq`. All intermediate agent output is logged above it.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.config import get_settings  # noqa: E402
from src.pipeline.orchestrator import run_pipeline  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deterministic NetBox/GitHub/AAP network drift manager"
    )
    parser.add_argument("--device", type=str, help="Device name")
    parser.add_argument(
        "--attributes",
        type=str,
        help="JSON object of observed attribute_name -> value",
    )
    parser.add_argument(
        "--input",
        type=str,
        help="Path to a JSON file with {'device': ..., 'attributes': {...}}",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually launch AAP remediation jobs (default: dry-run/plan only)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.input:
        payload = json.loads(Path(args.input).read_text())
        device = payload["device"]
        attributes = payload["attributes"]
    elif args.device and args.attributes:
        device = args.device
        attributes = json.loads(args.attributes)
    else:
        print(
            "ERROR: provide either --input <file.json> or both --device and --attributes",
            file=sys.stderr,
        )
        sys.exit(2)

    settings = get_settings()
    dry_run = settings.dry_run if not args.apply else False

    response = run_pipeline(device, attributes, dry_run=dry_run)

    print("\n" + "=" * 70)
    print("FINAL PIPELINE RESULT (JSON)")
    print("=" * 70)
    print(response.model_dump_json(indent=2))

    # Also emit a single-line, marker-prefixed, compact JSON as the very
    # last line of stdout. This is what callers (e.g. the
    # network-drift-manager.yaml Ansible playbook, or any shell wrapper)
    # should parse — trivially found with `grep '^PIPELINE_JSON_RESULT='`
    # or a Jinja2 `select('match', '^PIPELINE_JSON_RESULT=')` — instead of
    # trying to slice the multi-line pretty-printed JSON above.
    print(f"PIPELINE_JSON_RESULT={response.model_dump_json()}")


if __name__ == "__main__":
    main()

# Network Drift Manager

A **deterministic**, 4-agent workflow that detects and remediates network
device configuration drift using **NetBox** and **GitHub** as two separate
sources of truth, **AAP** (Ansible Automation Platform) for remediation,
and a **MaaS** (Model-as-a-Service) LLM for two narrowly-bounded reasoning
tasks only. Control flow between agents is plain Python `if` statements on
strict JSON — no agent autonomy, no LLM-driven branching.

---

## How It Works

```
                     ┌─────────────────────────────┐
  device name   ───▶ │  Agent 1                     │
  + attributes       │  DeviceDriftDetector         │
  (input)            │                              │
                     │  For each attribute:         │
                     │   1. classify: security or   │
                     │      networking (config file │
                     │      + LLM fallback)         │
                     │   2. security   -> no NetBox │
                     │      lookup; drift="security"│
                     │      route to Agent 3        │
                     │   3. networking -> fetch     │
                     │      NetBox truth (MCP),     │
                     │      compare -> drift T/F    │
                     └──────────────┬────────────────┘
                                    │  JSON (Agent1Response)
              ┌─────────────────────┼─────────────────────┐
              │ netbox_remediation_  │ security_review_
              │ attributes non-empty │ attributes non-empty
              ▼                     ▼
  ┌───────────────────────┐  ┌───────────────────────────────┐
  │ Agent 2                │  │ Agent 3                        │
  │ NetBoxRemediator        │  │ SecurityPolicyDriftChecker      │
  │                         │  │                                 │
  │ Launch AAP job template │  │ Fetch device security policy    │
  │ with extra_vars = the   │  │ from GitHub (MCP), compare to    │
  │ NetBox source-of-truth  │  │ observed values -> real drift    │
  │ value for each drifted  │  │ T/F verdict (source_of_truth=    │
  │ attribute.               │  │ github)                          │
  └───────────────────────┘  └───────────────┬─────────────────┘
                                              │ github_remediation_
                                              │ attributes non-empty
                                              ▼
                                ┌───────────────────────────────┐
                                │ Agent 4                        │
                                │ GitHubRemediator                │
                                │                                 │
                                │ Launch AAP job template with    │
                                │ extra_vars = the GitHub policy   │
                                │ source-of-truth value for each   │
                                │ drifted attribute.               │
                                └───────────────────────────────┘
```

Every agent returns **one strict JSON object** (Pydantic model, see
`src/models.py`). The orchestrator (`src/pipeline/orchestrator.py`) is the
only place that decides which agent runs next, and it does so purely by
checking whether the previous agent's JSON output listed any attributes
needing remediation — nothing here is an LLM decision.

### Where the LLM is (and isn't) used

The **only** two call sites that touch the MaaS LLM (`src/llm.py`):

1. `classify_attribute()` — fallback classification of an attribute name
   into `security` / `networking` **only if** it isn't already listed in
   `config/attribute_classification.yaml`. It never decides `drift`.
2. `summarize()` — an optional, cosmetic `llm_summary` string attached to
   Agent 1 / Agent 3 output. Never affects `drift`, `expected_value`, or
   which downstream agent runs.

If `MAAS_API_BASE` / `MAAS_API_KEY` / `MAAS_MODEL` are blank, both
functions fall back to deterministic defaults and the pipeline keeps
working — the LLM is strictly additive, not load-bearing.

### MCP-only communication with NetBox and GitHub

All communication with NetBox and GitHub happens over the **Model Context
Protocol (MCP)** — see `src/mcp/`:

- `src/mcp/base_client.py` — generic, transport-agnostic MCP client
  (streamable-HTTP or stdio), with dynamic tool discovery so it keeps
  working even if a server renames a tool between versions.
- `src/mcp/netbox_client.py` — resolves a device's networking attributes
  from a NetBox MCP server (dynamically discovers a `get`+`objects` tool,
  e.g. `netbox_get_objects`, called with `object_type=dcim.device` — the
  singular Django model name, not the plural REST path `dcim/devices/`;
  override the tool name with `NETBOX_MCP_DEVICE_TOOL`).
- `src/mcp/github_client.py` — resolves a device's security policy file
  from a GitHub MCP server via `get_file_contents` (the tool name exposed
  by GitHub's official `github-mcp-server`).

### AAP remediation

`src/aap/aap_client.py` launches a job template by numeric ID **or** exact
name via `POST /api/controller/v2/job_templates/{id}/launch/`, passing the
source-of-truth values as `extra_vars`. In `DRY_RUN=true` (default) or
`DEMO_MODE=true`, no HTTP call is made — the client returns the exact
`extra_vars` payload that *would* be sent, so you can review the plan
before flipping to `--apply`.

---

## Project Structure

```
demojam-2027/
├── .env.example                 # documented list of every setting
├── .env                         # your local copy (git-ignored)
├── requirements.txt / pyproject.toml
├── run_pipeline.py              # CLI entry point
├── network-drift-manager.yaml   # Ansible playbook to run this as an AAP Job Template
│
├── config/
│   └── attribute_classification.yaml   # security vs networking map (Agent 1)
│
├── demo_fixtures/               # used when DEMO_MODE=true (no live deps)
│   ├── netbox/devices.json
│   └── github/security-policies/<device>.yml
│
├── examples/                    # ready-to-run sample requests
│   ├── sample_request_networking_drift.json
│   ├── sample_request_security_drift.json
│   └── sample_request_no_drift.json
│
├── src/
│   ├── config.py                # Settings (pydantic-settings, loads .env)
│   ├── models.py                # strict JSON contract for every agent
│   ├── classification.py        # loads config/attribute_classification.yaml
│   ├── llm.py                   # the ONLY file that calls the MaaS LLM
│   │
│   ├── mcp/
│   │   ├── base_client.py       # generic MCP client (http/stdio, tool discovery)
│   │   ├── netbox_client.py     # NetBox source-of-truth lookups
│   │   └── github_client.py     # GitHub security-policy source-of-truth lookups
│   │
│   ├── aap/
│   │   └── aap_client.py        # AAPClient.launch_job_template()
│   │
│   ├── agents/
│   │   ├── agent1_drift_detector.py     # Agent 1
│   │   ├── agent2_netbox_remediator.py  # Agent 2
│   │   ├── agent3_security_drift.py     # Agent 3
│   │   └── agent4_github_remediator.py  # Agent 4
│   │
│   └── pipeline/
│       ├── context.py
│       └── orchestrator.py      # deterministic branching between agents
│
└── tests/                       # 11 tests, all run against DEMO_MODE fixtures
```

---

## Installation

```bash
cd /home/kashekha/labs/demo-jam/demojam-2027
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env   # already done for you with demo-safe defaults
```

Every variable is documented inline in `.env.example`. The three modes you
care about:

| Setting | Demo (default) | Live |
|---|---|---|
| `DEMO_MODE` | `true` — reads `demo_fixtures/` instead of calling MCP servers or AAP | `false` — real NetBox/GitHub MCP calls |
| `DRY_RUN` | `true` — computes drift + prints the AAP `extra_vars` plan, never launches a job | `false` — actually calls `job_templates/{id}/launch/` |
| LLM vars | blank — classification/summarization silently fall back to deterministic defaults | fill in `MAAS_API_BASE` / `MAAS_API_KEY` / `MAAS_MODEL` |

## Running

```bash
source venv/bin/activate

# 1) Networking drift -> Agent 1 finds it directly against NetBox, Agent 2 plans the AAP revert
python run_pipeline.py --input examples/sample_request_networking_drift.json

# 2) Security drift -> Agent 1 routes to Agent 3 (GitHub policy check), Agent 4 plans the AAP revert
python run_pipeline.py --input examples/sample_request_security_drift.json

# 3) No drift at all -> only Agent 1 runs, nothing to remediate
python run_pipeline.py --input examples/sample_request_no_drift.json

# Ad-hoc input instead of a file
python run_pipeline.py --device rtr-core-01 --attributes '{"vlan": 99}'

# Apply mode — actually launch the AAP job template(s) (requires DEMO_MODE=false
# and real AAP_URL / AAP_TOKEN / job template names in .env)
python run_pipeline.py --input examples/sample_request_networking_drift.json --apply
```

The final line of output is always the complete `PipelineResponse` JSON
object (device, Agent 1 result, and whichever of Agent 2/3/4 ran).

### Tests

```bash
python -m pytest -v
```

All 11 tests run entirely against the `demo_fixtures/` data — no network
access, MCP server, AAP instance, or LLM required.

---

## Running as an AAP Job Template

`network-drift-manager.yaml` runs this pipeline as an AAP Job Template
(same pattern as `aap-drift-manager.yaml` in the `aap-drift-manager`
project): it writes `.env` from an AAP Custom Credential + Extra
Variables, writes the per-run `device_name`/`device_attributes` to a JSON
input file, invokes `run_pipeline.py`, logs the full output, and — via
`ansible.builtin.set_stats` — exposes the final `PipelineResponse` JSON as
a **job artifact** so an EDA rulebook or a downstream Workflow Job
Template node can consume the structured drift result directly.

```bash
# Local test (same fixtures used by the demo, dry-run)
ansible-playbook network-drift-manager.yaml \
  -e drift_python="$(pwd)/venv/bin/python3" \
  -e device_name=rtr-core-01 \
  -e '{"device_attributes": {"dns_servers": ["10.10.0.53"]}}' \
  -e demo_mode=true -e pipeline_apply=false
```

Required per-run Extra Variables (typically set by an EDA rulebook or a
Survey): `device_name`, `device_attributes` (dict), `pipeline_apply`
(`true`/`false`). All other settings (LLM/NetBox/GitHub/AAP endpoints,
job template names) come from Job Template Extra Variables and a Custom
Credential injecting `MAAS_API_KEY`, `NETBOX_MCP_TOKEN`,
`GITHUB_MCP_TOKEN`, `AAP_TOKEN` — see the header comment in
`network-drift-manager.yaml` for the full list.

To actually run inside an Execution Environment such as
`aap-drift-manager-ee` (built from the `Containerfile` in the
`aap-drift-manager` project), that image's `requirements.txt` needs two
changes before rebuilding: add `openai` (for real MaaS LLM calls) and pin
`mcp<2.0.0` (the `mcp` 2.x line renamed
`streamablehttp_client`→`streamable_http_client`, which breaks any MCP
client code — including this project's — built against the 1.x API).

## Going from Demo to Live

1. **NetBox MCP** — set `NETBOX_MCP_TRANSPORT`, `NETBOX_MCP_URL` (or
   `NETBOX_MCP_COMMAND` for stdio), `NETBOX_MCP_TOKEN`. If your server
   exposes a device-lookup tool under a different name than
   `netbox_get_objects`, set `NETBOX_MCP_DEVICE_TOOL` explicitly, or add a
   new keyword pair to `BaseMCPClient.find_tool()` in
   `src/mcp/netbox_client.py`.

2. **GitHub MCP** — set `GITHUB_MCP_TRANSPORT`, `GITHUB_MCP_URL` (or
   `GITHUB_MCP_COMMAND`), `GITHUB_MCP_TOKEN`, and the
   `GITHUB_POLICY_REPO_OWNER` / `GITHUB_POLICY_REPO_NAME` /
   `GITHUB_POLICY_BRANCH` / `GITHUB_POLICY_PATH_TEMPLATE` that point at
   your actual security-policy-as-code repository. Each device needs one
   YAML file (see `demo_fixtures/github/security-policies/*.yml` for the
   expected shape: top-level keys are attribute names).

3. **AAP** — set `AAP_URL`, `AAP_TOKEN`, and the two job template
   identifiers (`AAP_JOB_TEMPLATE_NETBOX_REMEDIATION`,
   `AAP_JOB_TEMPLATE_GITHUB_REMEDIATION`) — either the numeric ID or the
   exact template name both work. Make sure each template's playbook
   accepts the attribute names used in `config/attribute_classification.yaml`
   / your security policy files as `extra_vars` (plus
   `AAP_EXTRA_VARS_DEVICE_KEY`, default `device_name`, to target the host).

4. **New attributes** — add them to
   `config/attribute_classification.yaml` under `security_attributes` or
   `networking_attributes` (with the NetBox dotted-path to read). Anything
   left out falls back to the MaaS LLM classifier automatically.

5. Set `DEMO_MODE=false` and `DRY_RUN=true` first, confirm the printed
   `extra_vars` plans look correct, then set `DRY_RUN=false` to apply.

---

## Design Notes / Guardrails

- **Deterministic control flow.** The orchestrator only ever branches on
  `if attribute_list:` checks against the previous agent's JSON. Swap the
  LLM provider, model, or remove it entirely, and the branching behavior
  is unchanged.
- **Strict JSON everywhere.** Every agent response is a Pydantic model
  (`src/models.py`) — `drift` is always `true`, `false`, or the literal
  string `"security"` (Agent 1 only, before Agent 3 resolves the real
  verdict). No free-text agent output is ever parsed to make a decision.
- **Dry-run by default.** No AAP job is ever launched unless
  `DRY_RUN=false` (or `--apply` on the CLI) **and** `DEMO_MODE=false`.
- **MCP read, REST write.** NetBox and GitHub are read exclusively via
  MCP; AAP remediation is a direct authenticated REST call to the
  Controller API (mirrors the read/write separation used by other drift
  tooling in this environment).

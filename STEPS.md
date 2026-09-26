# Local Test Workflow — Execution Environment → `.env` → `ansible-navigator`

This is the exact sequence to test the whole Network Drift Manager stack
on your local machine the same way it will eventually run in AAP:

```
Step 1: podman build   -> demojam-2027-ee:latest (Execution Environment)
Step 2: edit .env        -> credentials + settings the pipeline reads
Step 3: ansible-navigator run network-drift-manager.yaml -e device_name=... -e device_attributes='...'
                          -> runs INSIDE the EE container, launches run_pipeline.py
                             (the deterministic 4-agent workflow)
```

Everything below has been **verified working end-to-end** on this machine
(build → navigator → playbook → pipeline → `set_stats` artifact, `PLAY
RECAP failed=0`), using a stand-in image where noted, because this
sandbox isn't logged into `registry.redhat.io`. Step 1 itself you'll need
to run with your own Red Hat subscription credentials.

---

## Prerequisites

Already present on this machine:
- `podman` (or `docker`)
- `ansible-navigator` (`26.4.0` here)
- Access to `registry.redhat.io` (`podman login registry.redhat.io`) —
  needed only for the base image in Step 1

```bash
cd /home/kashekha/labs/demo-jam/demojam-2027
```

---

## Step 0 (optional, fast) — sanity-check the pipeline with plain Python first

Before involving containers/Ansible at all, confirm the agent code itself
works in isolation. This is the fastest feedback loop while iterating.

```bash
python3 -m venv venv        # already created
source venv/bin/activate
pip install -r requirements.txt

# Demo-safe defaults (DEMO_MODE=true, DRY_RUN=true) are already in .env
python run_pipeline.py --device rtr-core-01 --attributes '{"dns_servers": ["10.10.0.53"]}'

# Full test suite (14 tests, no network/MCP/AAP required)
python -m pytest -v
```

If this doesn't pass, fix it here first — Steps 1-3 below just wrap this
same script in an Execution Environment and Ansible.

---

## Step 1 — Build the Execution Environment

`Containerfile` (in this directory) mirrors the pattern already used by
`../aap-drift-manager/aap-drift-manager/Containerfile`, but installs
**this** project's own `requirements.txt` (which already includes the
`openai` + `mcp<2.0.0` pin that project's README flagged as needed).

```bash
podman login registry.redhat.io      # one-time, needs your RH subscription

podman build -t demojam-2027-ee:latest -f Containerfile .
```

Expect the last build line to be:
```
EE smoke test passed - all deps import OK
```

> **Verified in this session:** the pip-install layer and the smoke-test
> import line both work exactly as written (validated against a plain
> Python 3.12 image, since `registry.redhat.io` isn't authenticated in
> this sandbox). `mcp==1.30.0` resolves under the `<2.0.0` pin and still
> exposes `streamablehttp_client`, matching what `src/mcp/base_client.py`
> imports — no surprises there.
>
> **You still need to run this exact build yourself** with real
> `registry.redhat.io` credentials to get the real, RHEL9-based image —
> I could not do that from here.

If you don't have `registry.redhat.io` access on this machine yet and
just want to exercise the navigator/playbook wiring first, see
**Appendix A** for a throwaway substitute image.

---

## Step 2 — Configure `.env`

`.env` already exists (git-ignored) with demo-safe defaults. Edit the
values you want for this test run. Two ways to test:

### Option A — Demo mode (recommended first pass, no live systems needed)

Leave these as-is (already the default):
```bash
DEMO_MODE=true
DRY_RUN=true
```
`Agent 1` reads `demo_fixtures/netbox/devices.json` instead of calling a
real NetBox MCP server; no AAP job is ever launched. This proves the
whole EE → navigator → playbook → pipeline chain works before you touch
any real credentials.

### Option B — Live-ish mode (real NetBox, embedded `mcp-netbox` server)

```bash
DEMO_MODE=false
DRY_RUN=true                 # keep true until you've reviewed the plan

MAAS_API_BASE=https://your-maas-endpoint/v1
MAAS_API_KEY=...
MAAS_MODEL=...

NETBOX_URL=https://your-netbox/
NETBOX_TOKEN=your_real_netbox_token
NETBOX_MCP_TRANSPORT=stdio
# Path as seen INSIDE the container - the project root is mounted at
# /runner/project by ansible-navigator (confirmed below):
NETBOX_MCP_COMMAND=python3.12 /runner/project/mcp-netbox/server.py

AAP_URL=https://your-aap-controller/
AAP_TOKEN=your_real_aap_token
AAP_JOB_TEMPLATE_NETBOX_REMEDIATION=revert-network-config-from-netbox
AAP_JOB_TEMPLATE_GITHUB_REMEDIATION=revert-security-config-from-github
```

Because `network-drift-manager.yaml` only regenerates `.env` when it
detects AAP-Custom-Credential env vars injected into its own process
(`_aap_run`), for a **local** run it just uses this `.env` file exactly
as you've edited it — no extra wiring needed.

> Note: `mcp-netbox`'s two tools (`netbox_get_ntp_servers`,
> `netbox_get_login_banner`) aren't wired into
> `config/attribute_classification.yaml` yet, so a normal pipeline run
> won't call them automatically today — that's tracked as a separate,
> not-yet-requested step. To test `mcp-netbox` itself right now, see
> **Appendix B**.

---

## Step 3 — Run via `ansible-navigator`

`ansible-navigator.yml` (in this directory) is already configured to use
the image from Step 1, mount `/tmp` (so the run's input/log files
persist on the host), and run as `--user=0` to avoid uid/gid friction.

```bash
ansible-navigator run network-drift-manager.yaml \
  -e device_name=rtr-core-01 \
  -e device_attributes='{"dns_servers": ["10.10.0.53"]}' \
  -e pipeline_apply=false
```

- `device_name` / `device_attributes` are the **per-run extra-vars** —
  exactly the inputs your deterministic agentic workflow receives.
- `pipeline_apply=false` (default) = plan only, never launches an AAP job.
  Set `pipeline_apply=true` once you're ready to actually remediate.
- `demo_mode` / other settings come from `.env` unless you override them
  with more `-e` flags on this command line.

### What happens, step by step

1. `ansible-navigator` starts a container from `demojam-2027-ee:latest`,
   mounting this project directory at `/runner/project` (its default
   project-mount behavior) and your `-e` extra-vars into the play.
2. `network-drift-manager.yaml` validates `device_name` /
   `device_attributes` are present, confirms `.env` and `run_pipeline.py`
   exist, and confirms `python3.12` is available.
3. It writes your `device_name` + `device_attributes` to a temp JSON file
   under `/tmp` and runs:
   ```
   python3.12 /runner/project/run_pipeline.py --input /tmp/network-drift-input-<ts>.json
   ```
4. `run_pipeline.py` runs the real deterministic pipeline (Agent 1 → 2/3/4
   as applicable) and prints the full `PipelineResponse` JSON, plus a
   final `PIPELINE_JSON_RESULT={...}` marker line.
5. The playbook extracts that marker line and exposes it as a **job
   artifact** (`network_drift_result`) via `ansible.builtin.set_stats` —
   this is what an AAP Workflow node or EDA rulebook would consume later.
6. Full stdout/stderr is also saved to `/tmp/network-drift-<timestamp>.log`.

### Try all three demo scenarios

```bash
# Networking drift (Agent 1 -> NetBox check -> Agent 2 plans AAP revert)
ansible-navigator run network-drift-manager.yaml \
  -e device_name=rtr-core-01 \
  -e device_attributes='{"dns_servers": ["10.10.0.53"]}'

# Security drift (Agent 1 routes to Agent 3 -> GitHub policy check -> Agent 4 plans AAP revert)
ansible-navigator run network-drift-manager.yaml \
  -e device_name=rtr-core-01 \
  -e device_attributes='{"snmp_community": "public"}'

# No drift at all (only Agent 1 runs)
ansible-navigator run network-drift-manager.yaml \
  -e device_name=rtr-core-01 \
  -e device_attributes='{"vlan": 10}'
```

(Which values count as drift depends on `demo_fixtures/netbox/devices.json`
/ `demo_fixtures/github/security-policies/*.yml` when `DEMO_MODE=true`.)

### Apply mode (actually launch the AAP remediation job)

Only meaningful with `DEMO_MODE=false` and real `AAP_URL`/`AAP_TOKEN`:

```bash
ansible-navigator run network-drift-manager.yaml \
  -e device_name=rtr-core-01 \
  -e device_attributes='{"dns_servers": ["10.10.0.53"]}' \
  -e pipeline_apply=true
```

---

## Verifying the result

```bash
# Latest run's saved log
ls -t /tmp/network-drift-*.log | head -1 | xargs cat

# ansible-navigator's own log
tail -f ansible-navigator.log
```

Success looks like `PLAY RECAP ... failed=0` and a `network_drift_result`
artifact printed by the "Expose pipeline result as a job artifact"
task's effects (visible in the stats section if you add `-v`, or via
`ansible-runner`'s artifact dir if you enable
`playbook-artifact.enable: true` in `ansible-navigator.yml`).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Error: creating build container: ... unauthorized` | `podman login registry.redhat.io` with your subscription creds |
| `Error: short-name "demojam-2027-ee:latest" did not resolve` | Build Step 1 first, or check `podman images` for the tag |
| `'device_name' extra var is required` | You forgot `-e device_name=...` |
| `No .env file found ... and no secrets were injected` | Run `cp .env.example .env` and fill it in (Step 2) |
| Permission errors writing to `/tmp` inside the container | Already handled via `--user=0` in `ansible-navigator.yml`; if it still fails, check `ls -ld /tmp` / SELinux (`ls -Z /tmp`) on the host |
| Want to see what AAP would actually receive | Keep `pipeline_apply=false` — Agent 2/4's `extra_vars` plan is printed in full in the JSON output either way |

---

## Appendix A — Testing navigator/playbook wiring without `registry.redhat.io`

If you want to exercise Steps 2-3 before you have subscription access
for the real base image, build a throwaway substitute EE and point a
copy of `ansible-navigator.yml` at it (do **not** use this for anything
beyond wiring checks — it's missing the real RHEL packages):

```bash
mkdir -p /tmp/proxy-ee
cat > /tmp/proxy-ee/Containerfile <<'EOF'
FROM docker.io/library/python:3.12-slim
RUN pip install --no-cache-dir ansible-core ansible-runner
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EOF
cp requirements.txt /tmp/proxy-ee/
podman build -t demojam-2027-ee:latest -f /tmp/proxy-ee/Containerfile /tmp/proxy-ee

# Now run Step 3 exactly as written above - ansible-navigator.yml already
# points at the "demojam-2027-ee:latest" tag.
```

This exact recipe was used to validate this STEPS.md file itself: build
succeeded, `ansible-navigator run network-drift-manager.yaml -e
device_name=rtr-core-01 -e device_attributes='{"dns_servers":
["10.10.0.53"]}' -e demo_mode=true` completed with `PLAY RECAP ...
failed=0`, correct drift JSON, and the `PIPELINE_JSON_RESULT=` marker
line extracted successfully.

---

## Appendix B — Testing `mcp-netbox` standalone (outside the pipeline)

```bash
cd mcp-netbox
source ../venv/bin/activate     # reuses the main project's venv - same deps
python -m pytest -v             # 16 tests: NetBox client + both tool functions
```

To manually drive it over real stdio MCP (not via the pipeline), see the
"Wiring into the parent project" section of `mcp-netbox/README.md`.

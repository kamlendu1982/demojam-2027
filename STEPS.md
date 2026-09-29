# Local Test Workflow — Execution Environment → `.env` → `ansible-navigator`

This is the exact sequence to test the whole Network Drift Manager stack
on your local machine the same way it will eventually run in AAP:

```
Step 1: podman build   -> demojam-2027-ee:latest (Execution Environment)
Step 2: edit .env        -> credentials + settings the pipeline reads
Step 3: ansible-navigator run network-drift-manager.yaml -e @examples/navigator_extra_vars_networking_drift.json
                          -> runs INSIDE the EE container, launches run_pipeline.py
                             (the deterministic 4-agent workflow)
```

Everything below has been run **for real** on this machine, against the
**real** `registry.redhat.io` base image (not a stand-in) — build ->
navigator -> playbook -> pipeline -> `set_stats` artifact, `PLAY RECAP
failed=0`, for all three demo scenarios.

---

## Prerequisites

Already present on this machine and confirmed working:
- `podman` (real `registry.redhat.io` login succeeds)
- `ansible-navigator` (`26.4.0`)

```bash
cd /home/kashekha/labs/demo-jam/demojam-2027
```

---

## Step 0 (optional, fast) — sanity-check the pipeline with plain Python first

Before involving containers/Ansible at all, confirm the agent code itself
works in isolation. This is the fastest feedback loop while iterating.

```bash
python3 -m venv venv        # if you don't already have one - see note below
source venv/bin/activate
pip install -r requirements.txt

# Demo-safe defaults (DEMO_MODE=true, DRY_RUN=true) are already in .env
python run_pipeline.py --device rtr-core-01 --attributes '{"dns_servers": ["10.10.0.53"]}'

# Full test suite (14 tests, no network/MCP/AAP required)
python -m pytest -v
```

> **If you renamed/moved this project folder before**, an *old* `venv/`
> directory won't work — `venv/bin/activate` bakes in the absolute path
> it was created at (`VIRTUAL_ENV=/old/path/venv`). Symptom: `(venv)`
> shows in your prompt but `python -m pytest` says
> `No module named pytest` because `python` is quietly resolving to
> `/usr/bin/python` instead. Fix: `rm -rf venv && python3 -m venv venv`
> and reinstall.

If this doesn't pass, fix it here first — Steps 1-3 below just wrap this
same script in an Execution Environment and Ansible.

---

## Step 1 — Build the Execution Environment

`Containerfile` (in this directory) is loosely based on the pattern used
by `../aap-drift-manager/aap-drift-manager/Containerfile`, but installs
**this** project's own `requirements.txt` (already includes the `openai`
+ `mcp<2.0.0` pin) — and, importantly, does **not** run `microdnf
install` for anything. See the callout below for why.

```bash
podman login registry.redhat.io      # one-time, needs your RH subscription

podman build -t demojam-2027-ee:latest -f Containerfile .
```

Expect the last build line to be:
```
EE smoke test passed - all deps import OK
```

> **Real bug hit and fixed on this machine:** an earlier version of
> `Containerfile` ran `microdnf install -y python3.12 git gcc ...`
> (mirroring `aap-drift-manager`'s pattern) and failed with:
> ```
> error: cannot update repo 'rhel-9-for-x86_64-baseos-rpms':
> Status code: 403 for https://cdn.redhat.com/.../repomd.xml
> ```
> `podman login registry.redhat.io` only grants permission to **pull the
> base image** — it does *not* grant access to RHEL's RPM content repos
> (`cdn.redhat.com`). That needs real subscription-manager entitlements
> on the build host, which even a valid `registry.redhat.io` login
> doesn't provide (confirmed here: manually bind-mounting real
> entitlement certs from `/etc/pki/entitlement` + `/etc/rhsm` into the
> build *still* got a 403 — the entitlement wasn't authorized for RHEL
> content, only for the registry).
>
> The fix: it turns out none of that `microdnf install` was even
> necessary. `ee-supported-rhel9:latest` already ships `python3.12`
> (3.12.14), `pip`, `git` (2.52.0), and `openssh-clients`
> (`ssh-keyscan`) out of the box, and every package in
> `requirements.txt` installs from a prebuilt PyPI wheel — no compiler
> needed. Current `Containerfile` just does `pip install
> -r requirements.txt` directly on top of the base image. Verified: a
> real `podman build` against the real `registry.redhat.io` image
> completes cleanly with this Containerfile, no entitlements required.

If you genuinely need an RPM that isn't already in the base image later,
you'll need real RHEL entitlements on the build host — not just a
registry login.

---

## Step 2 — Configure `.env`

**You do NOT need real credentials to keep testing right now.** `.env`
already exists (git-ignored) with demo-safe defaults:
```bash
DEMO_MODE=true
DRY_RUN=true
```
With these, `Agent 1` reads `demo_fixtures/netbox/devices.json` instead
of calling a real NetBox MCP server, `Agent 3` reads
`demo_fixtures/github/security-policies/*.yml` instead of calling GitHub,
and no AAP job is ever launched, no LLM call is made. This is enough to
exercise the entire EE -> navigator -> playbook -> pipeline chain
end-to-end, which is everything Step 3 below does.

Leave `.env` as-is for now. Only fill in real values (see `.env.example`
for the full list: `MAAS_*`, `NETBOX_URL`/`NETBOX_TOKEN`,
`NETBOX_MCP_*`, `GITHUB_MCP_*`, `AAP_URL`/`AAP_TOKEN`) once you
specifically want to test against a live NetBox / GitHub / AAP / MaaS
endpoint — and even then, flip `DEMO_MODE=false` while keeping
`DRY_RUN=true` first, so no AAP job actually launches until you've
reviewed the printed plan.

> Note: `mcp-netbox`'s two tools (`netbox_get_ntp_servers`,
> `netbox_get_login_banner`) aren't wired into
> `config/attribute_classification.yaml` yet, so a normal pipeline run
> won't call them automatically today. To test `mcp-netbox` itself right
> now, see **Appendix B**.

---

## Step 3 — Run via `ansible-navigator`

`ansible-navigator.yml` (in this directory) is already configured to use
the image from Step 1, mount `/tmp` (so the run's input/log files
persist on the host), and run as `--user=0` to avoid uid/gid friction.

### Use an extra-vars FILE, not inline `-e key='{...}'`

**Real bug hit and fixed on this machine:** passing a nested JSON value
inline, e.g. `-e device_attributes='{"dns_servers": ["10.10.0.53"]}'`,
silently truncates at the first space when `ansible-navigator` forwards
it into the EE container — the pipeline then crashes with
`AttributeError: 'str' object has no attribute 'items'` because
`device_attributes` arrives as the mangled *string*
`{"dns_servers":` instead of a dict. Passing a **file** via `-e
@file.json` (Ansible's documented mechanism for exactly this) avoids the
problem entirely and is what's used everywhere below. Confirmed working
against the real EE for all three demo scenarios.

Three ready-to-use extra-vars files already exist in `examples/`:

```bash
cat examples/navigator_extra_vars_networking_drift.json
# {"device_name": "rtr-core-01", "device_attributes": {"dns_servers": ["10.10.0.53"]}, "pipeline_apply": false}
```

Run it:
```bash
ansible-navigator run network-drift-manager.yaml \
  -e @examples/navigator_extra_vars_networking_drift.json
```

- `device_name` / `device_attributes` are the **per-run extra-vars** —
  exactly the inputs your deterministic agentic workflow receives.
- `pipeline_apply: false` (default) = plan only, never launches an AAP job.
  Set it to `true` in the file (or override: `-e pipeline_apply=true`)
  once you're ready to actually remediate.
- `demo_mode` / other settings come from `.env` unless overridden.

For a custom one-off device/attributes combination, just write your own
small JSON file and point `-e @` at it:
```bash
cat > /tmp/my-vars.json <<'EOF'
{"device_name": "sw-access-12", "device_attributes": {"login_banner": "old text"}, "pipeline_apply": false}
EOF
ansible-navigator run network-drift-manager.yaml -e @/tmp/my-vars.json
```

### What happens, step by step

1. `ansible-navigator` starts a container from `demojam-2027-ee:latest`,
   mounting this project directory at `/runner/project` (its default
   project-mount behavior) and your extra-vars file's contents into the play.
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
  -e @examples/navigator_extra_vars_networking_drift.json

# Security drift (Agent 1 routes to Agent 3 -> GitHub policy check -> Agent 4 plans AAP revert)
ansible-navigator run network-drift-manager.yaml \
  -e @examples/navigator_extra_vars_security_drift.json

# No drift at all (only Agent 1 runs)
ansible-navigator run network-drift-manager.yaml \
  -e @examples/navigator_extra_vars_no_drift.json
```

All three verified: `PLAY RECAP ... failed=0` against the real EE.

(Which values count as drift depends on `demo_fixtures/netbox/devices.json`
/ `demo_fixtures/github/security-policies/*.yml` when `DEMO_MODE=true`.)

### Apply mode (actually launch the AAP remediation job)

Only meaningful with `DEMO_MODE=false` and real `AAP_URL`/`AAP_TOKEN` in
`.env`. Either edit `pipeline_apply` to `true` inside the vars file, or
override it on the command line (extra `-e` flags win over the file):

```bash
ansible-navigator run network-drift-manager.yaml \
  -e @examples/navigator_extra_vars_networking_drift.json \
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
| `error: cannot update repo 'rhel-9-for-x86_64-baseos-rpms' ... 403` during `microdnf install` | You're on an old `Containerfile` — pull the current one, which doesn't need `microdnf` at all (see Step 1 callout). A `registry.redhat.io` login does not grant RPM content-repo access. |
| `Error: short-name "demojam-2027-ee:latest" did not resolve` | Build Step 1 first, or check `podman images` for the tag |
| `AttributeError: 'str' object has no attribute 'items'` in Agent 1 | You passed `device_attributes` as inline `-e key='{...}'` — switch to `-e @file.json` (see Step 3) |
| `'device_name' extra var is required` | You forgot to pass an extra-vars file / `-e device_name=...` |
| `No .env file found ... and no secrets were injected` | Run `cp .env.example .env` and fill it in (Step 2) |
| `(venv)` shows in prompt but `python -m pytest` says `No module named pytest` | Stale venv from before a folder rename — see the callout in Step 0 |
| Permission errors writing to `/tmp` inside the container | Already handled via `--user=0` in `ansible-navigator.yml`; if it still fails, check `ls -ld /tmp` / SELinux (`ls -Z /tmp`) on the host |
| Want to see what AAP would actually receive | Keep `pipeline_apply=false` — Agent 2/4's `extra_vars` plan is printed in full in the JSON output either way |

---

## Appendix A — Testing navigator/playbook wiring without `registry.redhat.io`

If you don't have `registry.redhat.io` access on a given machine and
just want to exercise the navigator/playbook wiring, build a throwaway
substitute EE and point `ansible-navigator.yml`'s `image:` at it (do
**not** use this for anything beyond wiring checks — it's missing the
real RHEL base):

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

---

## Appendix B — Testing `mcp-netbox` standalone (outside the pipeline)

```bash
cd mcp-netbox
source ../venv/bin/activate     # reuses the main project's venv - same deps
python -m pytest -v             # 16 tests: NetBox client + both tool functions
```

To manually drive it over real stdio MCP (not via the pipeline), see the
"Wiring into the parent project" section of `mcp-netbox/README.md`.

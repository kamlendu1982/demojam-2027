# Infra Setup — Zero to a Working Demo Environment

End-to-end runbook for standing up the whole DemoJam environment from
scratch. This is the **big-picture order of operations** across all three
VMs; it deliberately doesn't repeat detail that's already documented
elsewhere — it links to that detail at each step instead:

- [`aap_config/README.md`](aap_config/README.md) — everything about the AAP
  Configuration-as-Code (`infra.aap_configuration`) that creates every AAP
  object below.
- [`arista_virtual_devices/README.md`](arista_virtual_devices/README.md) —
  Containerlab / Arista cEOS lab detail, NetBox registration detail, Splunk
  logging detail.
- [`STEPS.md`](STEPS.md) — a *different*, narrower workflow: testing the
  `network-drift-manager.yaml` pipeline locally in an EE, without any of
  this infra. Not needed to stand up the lab itself.

If you only need to re-run one piece (e.g. just redeploy NetBox), skip to
the matching job template in [Step 4](#step-4--run-the-create-network-infra-workflow)
rather than following this whole document top to bottom.

---

## Precondition

Three VMs, already provisioned, reachable over SSH from wherever you'll
bootstrap from (a laptop) and from each other as noted:

| # | Role | OS | Notes |
|---|---|---|---|
| 1 | **AAP** | RHEL | AAP 2.7 already installed and subscribed. This is the automation control point for everything else. |
| 2 | **Container Lab host** | Ubuntu | Runs Containerlab + the Arista cEOS virtual switches (Docker-based). Must have outbound internet access (installs Containerlab from `https://get.containerlab.dev`). |
| 3 | **NetBox host** | RHEL | Runs NetBox Community via `podman-compose`. |

Also needed before you start:

- A **Splunk URL/host** (already provisioned elsewhere, per the task) —
  this is the syslog/HEC target the Arista switches log to, and the
  source Splunk-side alerts/webhooks that eventually reach EDA. See
  [Step 6](#step-6--wire-up-splunk--eda).
- A **console.redhat.com offline token** (Automation Hub) — needed by the
  CaC bootstrap to pull certified collections.
- The **Arista cEOS64-lab image tar** (`.com` account + EULA required to
  download; ~500 MB, intentionally not in this repo — see `.gitignore`).
- This repo cloned somewhere you can run `ansible-playbook`/`ansible-vault`
  from (a laptop, or a 4th bastion/jump box) — **not** necessarily on any
  of the 3 VMs themselves. This is referred to as "the laptop" below.

```
┌────────────────┐        ┌──────────────────────┐        ┌─────────────────────┐
│  VM 1: AAP      │──────▶│ VM 3: NetBox (RHEL)   │        │ VM 2: Container Lab  │
│  (control point)│        │ podman-compose        │        │ (Ubuntu)             │
│                 │──────────────────────────────────────▶│ Docker + Containerlab │
│                 │        └──────────────────────┘        │  switch1 / switch2    │
└────────┬────────┘                                         └──────────┬───────────┘
         │ launches/orchestrates everything via SSH + REST             │ syslog/AAA
         ▼                                                              ▼
   (this repo's playbooks,                                     Splunk (external,
    via aap_config CaC)                                         already provisioned)
                                                                        │
                                                                        ▼
                                                              EDA (another team's
                                                               rulebook) → this repo's
                                                               Parse_EDA_Payload →
                                                               Network Drift Management
```

---

## Step 1 — Manual, one-time prep on the VMs

Everything else is automated (by `aap_config` or by the playbooks it
deploys as Job Templates), **except** these, which must happen first:

1. **SSH access.** Each of VM 2 and VM 3 needs a user AAP can SSH in as,
   with a key AAP will hold as a Machine credential:
   - VM 3 (NetBox/RHEL): a sudo-capable user (e.g. `ec2-user`).
   - VM 2 (Container Lab/Ubuntu): a sudo-capable user (e.g. `ubuntu`) —
     this same key is also used later to SSH-jump through to the Arista
     switches themselves (see `aap_config/README.md`'s
     ["Reaching the switches"](aap_config/README.md#reaching-the-switches)).
2. **Stage the Arista cEOS tar on VM 2** (one-time, until the Docker image
   is imported once):
   ```bash
   scp cEOS64-lab-4.32.0F.tar.xz ubuntu@<VM-2-IP>:/home/ubuntu/
   ```
   Full detail: [`arista_virtual_devices/README.md` § Onboarding steps, step 1](arista_virtual_devices/README.md#1-stage-the-arista-ceos-image-on-the-target-vm-one-time).
3. **Nothing manual needed on VM 3 for NetBox itself** —
   `netbox/deploy_netbox_community.yml` installs EPEL, `podman`,
   `podman-compose`, `git`, clones `netbox-docker`, and brings the stack
   up itself. Just needs SSH + sudo (step 1 above).
4. **AAP itself (VM 1)**: confirm it's licensed/subscribed and reachable
   over HTTPS from the laptop you'll bootstrap from.

---

## Step 2 — Bootstrap AAP Configuration as Code

This is the one part that **cannot** be done by AAP itself the first time
(AAP has no objects yet to run anything with) — run it once from the
laptop. Full detail and the full object inventory it creates (every
credential, inventory, project, job template, and the workflow) is in
[`aap_config/README.md`](aap_config/README.md); the short version:

```bash
cd demojam-2027   # repo root

# 1. Certified collections (needs the Automation Hub token)
export ANSIBLE_GALAXY_SERVER_AUTOMATION_HUB_TOKEN=<console.redhat.com offline token>
ansible-galaxy collection install -r collections/requirements.yml -p collections

# 2. Fill in every real secret + the three VMs' IPs
cp aap_config/vault.yml.example aap_config/group_vars/all/vault.yml
$EDITOR aap_config/group_vars/all/vault.yml
ansible-vault encrypt aap_config/group_vars/all/vault.yml

# 3. Apply — creates every AAP object listed in aap_config/README.md
ansible-playbook -i aap_config/inventory aap_config/apply.yml --ask-vault-pass
```

In `vault.yml`, at minimum set for **this** environment:
- `vault_aap_hostname` / `vault_aap_username` / `vault_aap_password` — VM 1.
- `vault_ubuntu_ssh_private_key` — the key for VM 2 (step 1 above).
- `vault_rhel_ssh_private_key` — the key for VM 3 (step 1 above).
- `vault_arista_password` (+ `vault_arista_enable_password` if set) — the
  switch login the lab will use once deployed.
- `vault_netbox_api_token` / `vault_netbox_admin_password` — placeholders
  are fine for a brand-new NetBox; `deploy_netbox_community.yml` now
  creates NetBox's admin user + a fresh API token itself on every run (see
  [Step 4](#step-4--run-the-create-network-infra-workflow)), so these vault
  values just need to be **some** real string, not necessarily reused
  from a prior environment.
- `vault_maas_api_key` / `vault_github_mcp_token` — only needed once you
  run the drift-detection pipeline ([Step 6](#step-6--wire-up-splunk--eda)).
- `vault_drift_aap_token` — leave blank on the **first** apply (chicken
  and egg: it's a token from the AAP instance this same apply creates
  objects on). Create it in AAP after this first apply, paste it in, then
  re-run `apply.yml` once more.

Also set the three VM IPs/hostnames for this environment in
`aap_config/group_vars/all/00_demojam_settings.yml`
(`demojam_netbox_host_ip`, `demojam_container_lab_ip`,
`demojam_splunk_host`) and `demojam_repo_branch` (back to `main` once
you're off a feature branch).

---

## Step 3 — (Optional) Wire the self-apply webhook

Once Step 2 has run successfully at least once, AAP can reconcile itself
on every future push instead of you re-running `apply.yml` by hand. In AAP,
open **DemoJam | Apply Config as Code**, copy its webhook URL + key, and
add it as a GitHub webhook (push events) on this repo. Detail:
[`aap_config/README.md` § Running it, step 2](aap_config/README.md#2-wire-the-webhook-once).

---

## Step 4 — Run the `Create Network Infra` workflow

All the objects from Step 2 exist now. In AAP, launch the workflow
**DemoJam | Create Network Infra**. It chains four Job Templates
(see `aap_config/group_vars/all/workflows.yml` /
`aap_config/group_vars/all/job_templates.yml` for the exact definitions):

| Order | Job Template | What it does | Runs on |
|---|---|---|---|
| 1 | **DemoJam \| Deploy NetBox Community** | Installs NetBox (podman-compose) on VM 3, creates the admin superuser, creates a fresh NetBox API token and exposes `netbox_token` + `netbox_url` via `set_stats` for the next nodes. | VM 3 |
| 2 (always) | **DemoJam \| Deploy Arista Lab** | Installs Docker + Containerlab on VM 2, imports the staged cEOS tar, deploys `switch1`/`switch2`. | VM 2 |
| 3 (on success) | **DemoJam \| NetBox Onboard Switches** | Registers `switch1`/`switch2` in NetBox (Manufacturer/Device Type/Role/Site bootstrap + Device + Interface + IP), using `netbox_token`/`netbox_url` from node 1. | localhost (REST calls to VM 3) |
| 4 (on success) | **DemoJam \| Configure Splunk Logging** | Pushes syslog + AAA accounting config to both switches, pointed at `demojam_splunk_host`. | localhost → switches (via VM 2 SSH jump) |

**Verify each stage** (full detail in the linked READMEs):
- NetBox UI reachable at `http://<VM-3-IP>:8000`, admin login works.
- `sudo containerlab inspect -t /opt/arista-lab/lab.clab.yml` on VM 2 shows
  `switch1`/`switch2` running, with management IPs on `172.20.20.0/24`.
- NetBox UI → Devices shows `switch1`/`switch2` with a primary IPv4.
- `show logging` on each switch (or the Splunk side) confirms messages are
  arriving from the switches' management IP.

> **Switch IPs can change between Containerlab redeploys.** If node 3/4
> fail because the IPs don't match, update
> `arista_virtual_devices/netbox_devices_inventory` with the real IPs from
> `containerlab inspect` and re-sync that inventory source (or just
> re-run the workflow — the SCM inventory source syncs on launch).

---

## Step 5 — (Optional) Push security policies

For the security-drift demo scenario, run **DemoJam | Push Security
Policies Network** (not part of the `Create Network Infra` workflow — run
it on its own, after Step 4) to push the ACLs in
`arista_virtual_devices/vars/all_policies.yml` to the switches.

---

## Step 6 — Wire up Splunk / EDA

Two separate directions of Splunk integration here:

### 6a. Switches → Splunk (already wired by Step 4)

`demojam_splunk_host` in `aap_config/group_vars/all/00_demojam_settings.yml`
is the only thing you need to set to the real Splunk URL/host for this —
**DemoJam | Configure Splunk Logging** (Step 4, node 4) already pushes
`logging host <splunk_host> 514 protocol udp` + AAA accounting config to
both switches using that value.

### 6b. Splunk → EDA → this repo (needs the other team's rulebook)

The EDA rulebook that watches Splunk and decides when to launch AAP is
**owned by another team**, not part of this repo (see the header comment
in `eda_integration/parse_eda_payload.yml`). What this repo provides for
that rulebook to call:

```
EDA rulebook (their repo) --launches--> an AAP Workflow Job Template:
    Node 1: Parse_EDA_Payload (eda_integration/parse_eda_payload.yml)
        -> set_stats: device_name, device_attributes, pipeline_apply
    Node 2 (on success): DemoJam | Network Drift Management
        -> receives device_name / device_attributes / pipeline_apply
           automatically via set_stats, same mechanism as Step 4 above
```

`payload_parser.py` doesn't assume a specific payload shape from the
rulebook — it locates the raw Splunk/AAA message text regardless of which
key(s) the rulebook uses, parses it deterministically where possible, and
only falls back to the MaaS LLM for genuinely ambiguous events. See the
full docstring in `eda_integration/payload_parser.py` for the three-layer
extraction logic.

> **Known gap:** unlike every other Job Template in this doc, **`Parse_EDA_Payload`
> is not yet declared in `aap_config/job_templates.yml`** — it exists as a
> playbook in the repo but has to be created by hand in AAP for now (or
> added to the CaC as a follow-up PR) before the other team's rulebook has
> anything to launch. Same for the Workflow Job Template chaining it to
> **DemoJam | Network Drift Management**.

---

## Known gaps (carried over from `aap_config/README.md`, still open)

- **`revert-network-config-from-netbox` Job Template doesn't exist yet.**
  Agent 2 of the drift pipeline launches it by name whenever
  `pipeline_apply: true` finds networking drift — until it's created,
  that path fails. Detail + exact spec in
  [`aap_config/README.md` § Known gaps](aap_config/README.md#known-gaps).
  Same applies to `revert-security-config-from-github` (Agent 4) — its
  playbook doesn't exist yet either.
- **EC2 inventory source has no credential** — relies on VM 1's AWS IAM
  instance profile; add an AWS credential if that role doesn't exist.
- **`vault_drift_aap_token`** — see the chicken-and-egg note under
  [Step 2](#step-2--bootstrap-aap-configuration-as-code).
- **`Parse_EDA_Payload` / its workflow aren't in the CaC yet** — see
  [Step 6b](#6b-splunk--eda--this-repo-needs-the-other-teams-rulebook) above.

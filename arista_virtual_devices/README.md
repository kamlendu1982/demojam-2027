# Arista Virtual Devices Lab (Containerlab)

Deploys two virtual Arista cEOS switches (`switch1`, `switch2`) on an Ubuntu
VM using [Containerlab](https://containerlab.dev/), orchestrated by Ansible.
Runs both from a laptop/control node (`ansible-navigator` / `ansible-playbook`)
and from an AAP Job Template.

```
┌─────────────┐   SSH (become)   ┌───────────────────────────────────────────┐
│  AAP / CLI  │ ───────────────▶ │  Ubuntu VM (ansible_host in inventory)     │
└─────────────┘                  │                                           │
                                  │  Docker                                  │
                                  │   └── containerlab deploy                │
                                  │         ├── switch1 (cEOS)  eth1 ─┐       │
                                  │         └── switch2 (cEOS)  eth1 ─┘       │
                                  │                 (directly linked)         │
                                  └───────────────────────────────────────────┘
```

NetBox is used as the Source of Truth for these two devices, registered by
`netbox_onboard_switches.yml` (see [NetBox registration](#netbox-registration)).

## Contents

| Path | Purpose |
|---|---|
| `deploy_arista_lab.yml` | Installs Docker + Containerlab, imports the Arista cEOS image, generates a Containerlab topology file, and deploys it. |
| `inventory` | Static inventory with the one deployment target host (`ubuntu-lab-host`). |
| `host_vars/ubuntu-lab-host.yml` | Configurable variables for `deploy_arista_lab.yml` (image names/tags, file paths). Scoped to that specific hostname so it can't leak into `netbox_devices_inventory`'s hosts. |
| `files/` | **Intentionally empty** — see [Staging the Arista image](#1-stage-the-arista-ceos-image-on-the-target-vm-one-time). Ignored by git (`.gitignore`) so a 500+ MB tar never gets committed by accident. |
| `netbox_onboard_switches.yml` | Registers `switch1`/`switch2` as Devices in NetBox (SOT). Idempotent - safe to re-run. |
| `netbox_devices_inventory` | Separate inventory listing the switches (name + management IP) to onboard into NetBox. Kept apart from `inventory` on purpose (see note in that file). |
| `tasks/onboard_one_switch.yml` | Reusable per-switch task sequence (Device + Interface + IP) included in a loop by `netbox_onboard_switches.yml`. |

## Prerequisites

- An Ubuntu VM (or similar) reachable over SSH, with a sudo-capable user.
- The Arista **cEOS64-lab** image tar file. This requires a free
  [arista.com](https://www.arista.com/en/support/software-download) account
  and EULA acceptance to download — it cannot be redistributed via this repo.
- Outbound internet access from the target VM (used once, to install
  Containerlab via `https://get.containerlab.dev`).
- Ansible control node (or AAP) with SSH access to the target VM.

## Onboarding steps

### 1. Stage the Arista cEOS image on the target VM (one-time)

The image is **not** shipped in this git project (500+ MB — too large for
GitHub). Copy it directly to the target VM before the first run:

```bash
scp cEOS64-lab-4.32.0F.tar.xz ubuntu@<target-vm-ip>:/home/ubuntu/
```

The playbook expects it at `/home/ubuntu/cEOS64-lab-4.32.0F.tar.xz` by
default (see `ceos_tar_remote_path` below). If you stage it at a different
path or with a different filename, override the variable to match — the
playbook will fail fast with a clear error if the file isn't found where
expected.

This is only required until the Docker image has been imported once; after
that, `docker images -q` short-circuits the check on subsequent runs.

### 2. Update the inventory

Edit `inventory` with your target VM's details:

```yaml
all:
  hosts:
    ubuntu-lab-host:
      ansible_host: 172.31.8.57      # <-- your VM's IP
      ansible_user: ubuntu           # <-- your SSH user
      # ansible_ssh_private_key_file: ~/.ssh/id_rsa
```

### 3. Review/override variables (optional)

All variables live in `host_vars/ubuntu-lab-host.yml`:

| Variable | Default | Description |
|---|---|---|
| `ceos_tar_name` | `cEOS64-lab-4.32.0F.tar.xz` | Filename of the Arista tar (used to build `ceos_tar_remote_path` and Docker image tags). |
| `ceos_image_repo` | `ceos` | Local Docker image repo name to import the tar into. |
| `ceos_image_tag` | `4.32.0F` | Local Docker image tag. |
| `ceos_tar_remote_path` | `/home/ubuntu/{{ ceos_tar_name }}` | Absolute path to the pre-staged tar **on the target VM**. |
| `lab_dir` | `/opt/arista-lab` | Directory on the target VM where the Containerlab topology file (`lab.clab.yml`) is generated and the lab is run from. |

Override any of these via `-e` (CLI), a job template survey (AAP), or by
adding a `host_vars/<hostname>.yml` file if a specific VM needs different
values.

### 4. Run the playbook

**Option A — AAP Job Template (recommended / verified working):**

1. **Project**: point at this git repo (or the branch/path containing
   `arista_virtual_devices/`).
2. **Inventory**: either sync this project's `inventory` file as a Project
   inventory source, or create an equivalent AAP inventory with a host
   matching `ubuntu-lab-host`'s `ansible_host`/`ansible_user`.
3. **Credential**: a Machine credential with SSH access to the target VM,
   with privilege escalation (`become`) enabled — the playbook installs
   packages and writes to `/opt`.
4. **Job Template**: Playbook = `arista_virtual_devices/deploy_arista_lab.yml`.
5. Launch. Override any `host_vars` values via **Extra Variables** or a
   survey if needed.

**Option B — local testing (`ansible-navigator` / `ansible-playbook`):**

```bash
cd arista_virtual_devices

# Using ansible-navigator with an Execution Environment:
ansible-navigator run deploy_arista_lab.yml -i inventory --mode stdout

# Or directly with ansible-playbook (if Docker/Containerlab tooling is
# already available on your control node's Python environment):
ansible-playbook -i inventory deploy_arista_lab.yml
```

Add `--ask-pass`/`--ask-become-pass` or point at your SSH key as needed,
depending on how `inventory` is configured.

### 5. Verify the deployment

On the target VM:

```bash
sudo containerlab inspect -t /opt/arista-lab/lab.clab.yml
docker ps   # should show switch1 and switch2 running
```

The playbook's final task also prints this inspect command in its output.

## What the playbook does (task-by-task)

1. **Ensure Docker is installed** (`apt`, idempotent).
2. **Check / install Containerlab** — skipped if `containerlab` is already
   on `PATH`.
3. **Check if the Arista Docker image already exists** (`docker images -q`).
4. **Verify the tar file is present** on the target VM — only checked when
   the image doesn't exist yet.
5. **Fail with a clear message** if the tar is missing at that point.
6. **Import the tar into Docker** as `{{ ceos_image_repo }}:{{ ceos_image_tag }}`
   — only when the image doesn't already exist.
7. **Create the lab directory** (`{{ lab_dir }}`).
8. **Generate the Containerlab topology file** (`lab.clab.yml`) defining
   `switch1` and `switch2`, directly linked via `eth1` <-> `eth1`.
9. **Deploy the topology** with `containerlab deploy`.
10. **Print the inspect command** for the user to check IPs/status.

## NetBox registration

Once `switch1`/`switch2` are deployed and you know their management IPs
(from `sudo containerlab inspect -t /opt/arista-lab/lab.clab.yml`),
`netbox_onboard_switches.yml` registers them in NetBox as the Source of
Truth. It's idempotent (safe to re-run) and self-bootstraps everything it
needs on a fresh NetBox instance - Manufacturer (`Arista`), Device Type
(`cEOS`), Device Role (`Network Switch`), and Site (`Containerlab`) - then
creates a Device + management Interface + IP Address per switch, and sets
that IP as the device's primary IPv4.

**1. Update `netbox_devices_inventory` with the real switch IPs:**

```yaml
arista_switches:
  hosts:
    switch1:
      ansible_host: <switch1 mgmt IP>
    switch2:
      ansible_host: <switch2 mgmt IP>
```

**2. Generate a NetBox API token** (NetBox UI → top-right profile icon →
API Tokens → Add a token), then run:

```bash
cd arista_virtual_devices
ansible-playbook -i netbox_devices_inventory netbox_onboard_switches.yml \
  -e netbox_token='<your-netbox-api-token>'
```

Never commit the token or put it in a vars file — pass it via `-e`, or in
AAP via a survey/credential.

**3. AAP Job Template setup:**

- **Inventory**: sync/import `netbox_devices_inventory` (contains the
  `arista_switches` group) — a different Inventory than the one used for
  `deploy_arista_lab.yml`, since these hosts aren't SSH targets.
- **Credential**: none needed for SSH (the play runs against `localhost`);
  instead add `netbox_token` as a survey variable or a custom credential
  injected as an extra var.
- **Job Template**: Playbook = `arista_virtual_devices/netbox_onboard_switches.yml`.

All the NetBox object/field names used (`role` on Device, `assigned_object_type`/
`assigned_object_id` on IP Address, etc.) were verified directly against this
NetBox instance's live OpenAPI schema (NetBox Community v4.7.1) rather than
assumed — NetBox 4.x renamed the Device API's role field from `device_role`
(3.x) to `role`, which the playbook accounts for.

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `Fail if Arista tar file is missing on target VM` | The tar isn't at `ceos_tar_remote_path` yet. Re-check step 1, or override the variable if you staged it elsewhere. |
| Containerlab install task hangs or fails | Target VM has no outbound internet access to `https://get.containerlab.dev`. |
| `docker: permission denied` type errors | Ensure the play's `become: true` is honored (AAP credential must have privilege escalation enabled). |
| SSH connection failures from AAP | Confirm the Machine credential's user/key matches `ansible_user` in inventory, and that the AAP execution node can reach `ansible_host`. |
| Re-running doesn't re-import the image | Expected — `docker images -q` makes the import idempotent. Remove the image (`docker rmi ceos:4.32.0F`) to force re-import. |
| `netbox_onboard_switches.yml` fails with "netbox_token is required" | Pass `-e netbox_token=...` (CLI) or set it via an AAP survey/credential — it's never hardcoded in the repo. |
| `netbox_onboard_switches.yml` fails with a 403 from NetBox | The token is invalid/expired, or lacks write permission on `dcim`/`ipam`. Regenerate it in the NetBox UI. |

## Roadmap

- Possibly drive `deploy_arista_lab.yml`'s variables (image name/tag, device
  names) from NetBox instead of `host_vars/ubuntu-lab-host.yml`, now that NetBox holds
  the switch inventory as the Source of Truth.

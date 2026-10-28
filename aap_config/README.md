# AAP Configuration as Code

Every AAP object this project uses is declared as YAML in this directory and
applied with [`infra.aap_configuration`](https://github.com/redhat-cop/infra.aap_configuration)
(Red Hat validated content). Nothing should be created by hand in the AAP UI;
a merged PR is the deployed configuration.

The object set mirrors what was built by hand on the previous AAP instance
(inspected read-only on 2026-10-15), with the fixes listed under
[Changes from the old instance](#changes-from-the-old-instance).

---

## Decisions

| Topic | Decision |
|---|---|
| Target | A **new, empty AAP 2.7 instance** — everything is created from here, nothing adopted |
| Tooling | `infra.aap_configuration` `dispatch` role (applies objects in dependency order) |
| Organization | Built-in **Default** |
| Naming | `DemoJam \| <Title Case Name>` for every object we create |
| Secrets | `ansible-vault` encrypted `group_vars/all/vault.yml`, committed; vault password never in git |
| Execution | Bootstrap once from a laptop, then **DemoJam \| Apply Config as Code** (GitHub push webhook) |
| EEs | Stock Red Hat `ee-supported-rhel9` (AAP 2.7) for everything except the drift pipeline |

---

## Layout

```
ansible.cfg                           # repo root: Automation Hub + Galaxy servers, collections path
collections/requirements.yml          # repo root: AAP project sync installs these automatically
.pre-commit-config.yaml               # blocks committing an unencrypted vault.yml
aap_config/
├── apply.yml                         # hosts: localhost → infra.aap_configuration.dispatch
├── inventory                         # localhost (laptop runs)
├── vault.yml.example                 # template for group_vars/all/vault.yml
└── group_vars/all/
    ├── 00_demojam_settings.yml       # non-secret env values: IPs, URLs, images, usernames
    ├── 00_connection.yml             # aap_hostname / credentials for the CaC run itself
    ├── organizations.yml             # Default org → Galaxy credentials
    ├── credential_types.yml
    ├── credentials.yml
    ├── execution_environments.yml
    ├── projects.yml
    ├── inventories.yml               # inventories, inventory sources, static hosts
    ├── job_templates.yml
    ├── workflows.yml
    └── vault.yml                     # ansible-vault encrypted (you create it)
```

To change an IP, URL or image, edit `00_demojam_settings.yml`; the object files only
reference those variables.

---

## Objects

### Naming

| Old name | New name |
|---|---|
| `add_switches` | DemoJam \| Add Switches |
| `DemoJam` (inventory) | DemoJam \| AWS |
| `NetBox` | DemoJam \| NetBox |
| `Container Lab` | DemoJam \| Container Lab |
| `DemoJam` (project) | DemoJam \| DemoJam 2027 |
| `Deploy Netbox Community` | DemoJam \| Deploy NetBox Community |
| `Deploy Arista Lab` | DemoJam \| Deploy Arista Lab |
| `Netbox Onboard Switches` | DemoJam \| NetBox Onboard Switches |
| `Configure Splunk Logging` | DemoJam \| Configure Splunk Logging |
| `push_security_policies_network` | DemoJam \| Push Security Policies Network |
| `DemoJamNetworkDriftManageent` | DemoJam \| Network Drift Management |
| `Create Network Infra` | DemoJam \| Create Network Infra |
| `DemoJamNetDriftCred` / `DemoJamNetDrift` | DemoJam \| NetBox API + DemoJam \| Network Drift Secrets |
| `DemoJam Ubuntu` / `DemoJam RHEL` | DemoJam \| Ubuntu SSH / DemoJam \| RHEL SSH |
| `aap-drift-manager-ee` | DemoJam \| Network Drift EE |

### Credential types

| Type | Injects |
|---|---|
| DemoJam \| NetBox API | env `NETBOX_URL`, `NETBOX_TOKEN`; extra vars `netbox_url`, `netbox_token` |
| DemoJam \| NetBox Admin | extra vars `netbox_admin_user`, `netbox_admin_pass`, `netbox_admin_email` |
| DemoJam \| Arista Switch Login | extra vars `ansible_user`, `ansible_password`, `ansible_become_password` |
| DemoJam \| Network Drift Secrets | env `MAAS_API_KEY`, `GITHUB_MCP_TOKEN`, `AAP_URL`, `AAP_TOKEN`; extra var `aap_url` |

The NetBox API type injects both env vars (read by the Python pipeline) and
extra vars (read by `netbox_onboard_switches.yml`), so one credential serves
both. The extra vars also override the stale EC2 URLs hard-coded as
defaults in `network-drift-manager.yaml` and `netbox_onboard_switches.yml`.

### Credentials

| Credential | Type | Used by |
|---|---|---|
| DemoJam \| Automation Hub | Ansible Galaxy/Automation Hub API Token | Default org (project sync) |
| DemoJam \| Ubuntu SSH | Machine | Deploy Arista Lab, Splunk, Security Policies (switch jump) |
| DemoJam \| RHEL SSH | Machine | Deploy NetBox Community |
| DemoJam \| Arista Switch Login | Arista Switch Login | Splunk, Security Policies |
| DemoJam \| NetBox API | NetBox API | NetBox Onboard Switches, Network Drift Management |
| DemoJam \| NetBox Admin | NetBox Admin | Deploy NetBox Community |
| DemoJam \| Network Drift Secrets | Network Drift Secrets | Network Drift Management |
| DemoJam \| CaC AAP Admin | Red Hat Ansible Automation Platform | Apply Config as Code |
| DemoJam \| CaC Vault | Vault | Apply Config as Code |

### Execution environments

| EE | Image | Used by |
|---|---|---|
| DemoJam \| Supported EE | `registry.redhat.io/ansible-automation-platform-27/ee-supported-rhel9:latest` | every template except the drift pipeline |
| DemoJam \| Network Drift EE | `quay.io/kashekha/aap-drift-manager-ee:latest` | Network Drift Management |

Checked on 2026-10-15: the 2.7 `ee-supported-rhel9` image ships
`ansible.platform` 2.7, `ansible.controller` 4.8.11, `arista.eos` 12.0.1,
`ansible.netcommon` 8.6.2, `amazon.aws` 10.3.0 (+ boto3) on ansible-core 2.16 /
Python 3.12. An `ee-supported-rhel10` image is not published under
`ansible-automation-platform-27`; revisit when it is.

**Network Drift EE is an external image.** It is a public image from another
project (`kashekha/aap-drift-manager-ee`, built 2026-04-05), **not** built from
this repo's `Containerfile`. It is used as-is because it already carries the
pipeline's Python dependencies (`pydantic-settings`, `python-dotenv`, `mcp`,
`openai`, `netbox-mcp-server`, …) that the stock EE lacks. If
`requirements.txt` changes, check that image still satisfies it.

### Project

**DemoJam | DemoJam 2027** — `https://github.com/kamlendu1982/demojam-2027.git`,
branch from `demojam_repo_branch` (currently `feat/aap-config-as-code` for
testing — set it back to `main` before merging), update on launch. The repo
is public, so no SCM credential.

### Inventories

| Inventory | Contents | Used by |
|---|---|---|
| DemoJam \| Add Switches | `switch1`, `switch2` (group `arista_switches`) from SCM source **DemoJam \| Arista Devices** → `arista_virtual_devices/netbox_devices_inventory` | Onboard Switches, Splunk, Security Policies |
| DemoJam \| AWS | EC2 instances from source **DemoJam \| AWS EC2** | Drift pipeline and Apply Config as Code (both run on implicit `localhost`) |
| DemoJam \| NetBox | `netbox-host` → 10.1.0.31 | Deploy NetBox Community |
| DemoJam \| Container Lab | `ubuntu-lab-host` → 10.1.0.32 | Deploy Arista Lab |

Each deploy playbook that targets `hosts: all` has a single-host inventory of
its own, so no `limit` or playbook change is needed.

### Job templates

| Template | Playbook | Inventory | Credentials |
|---|---|---|---|
| DemoJam \| Deploy NetBox Community | `netbox/deploy_netbox_community.yml` | NetBox | RHEL SSH, NetBox Admin |
| DemoJam \| Deploy Arista Lab | `arista_virtual_devices/deploy_arista_lab.yml` | Container Lab | Ubuntu SSH |
| DemoJam \| NetBox Onboard Switches | `arista_virtual_devices/netbox_onboard_switches.yml` | Add Switches | NetBox API |
| DemoJam \| Configure Splunk Logging | `arista_virtual_devices/configure_splunk_logging.yml` | Add Switches | Ubuntu SSH, Arista Switch Login |
| DemoJam \| Push Security Policies Network | `arista_virtual_devices/deploy_security_policies.yml` (limit `arista_switches`) | Add Switches | Ubuntu SSH, Arista Switch Login |
| DemoJam \| Network Drift Management | `network-drift-manager.yaml` | AWS | NetBox API, Network Drift Secrets |
| DemoJam \| Apply Config as Code | `aap_config/apply.yml` | AWS | CaC AAP Admin, CaC Vault |

### Workflow

**DemoJam | Create Network Infra**: Deploy NetBox Community → (always) Deploy
Arista Lab → Onboard Switches → Configure Splunk Logging.

---

## Reaching the switches

The switches sit on Containerlab's management bridge (`172.20.20.0/24`) inside
the Container Lab host and are only reachable through it. Every template that
connects to them attaches **two** credentials:

1. **DemoJam | Ubuntu SSH** (Machine). AAP loads its private key into
   `ssh-agent` for the job. The group var
   `ansible_ssh_common_args: -o ProxyCommand="ssh -W %h:%p … ubuntu@10.1.0.32"`
   (in `netbox_devices_inventory`) opens the jump with that key.
2. **DemoJam | Arista Switch Login** (custom). Injects `ansible_user`,
   `ansible_password` and `ansible_become_password` for the switch login
   itself. Extra vars outrank the Machine credential's `ubuntu` user, so the
   switch session logs in as `admin` while the jump uses `ubuntu`.

The built-in **Network** credential type can't replace #2: it injects
`ANSIBLE_NET_*` environment variables, which `ansible.netcommon.network_cli`
ignores (it reads the password only from `ansible_password`/`ansible_ssh_pass`).

---

## Changes from the old instance

- **Switches defined once.** They were in both `add_switches` (SCM source,
  `ProxyJump` via a stale `172.31.8.57`) and `DemoJam` (hand-added, with
  `ProxyCommand` via `10.1.0.32` and plain-text `ansible_password` host vars).
  Now only the repo file defines them, using the `ProxyCommand` that worked,
  and Splunk / Security Policies use **Add Switches** instead of DemoJam.
- **No secrets in templates or inventories.** The NetBox API token (survey
  default) and NetBox admin password (extra vars) are now credentials.
  **Both were stored in plain text on the old instance — rotate them.**
- **Container Lab host renamed to `ubuntu-lab-host`**, so
  `arista_virtual_devices/host_vars/ubuntu-lab-host.yml` is actually applied.
- **Onboard Switches** no longer attaches the Ubuntu SSH credential (it runs on
  localhost and never connects to the switches) and no longer has a survey.
- **Workflow nodes** no longer override the inventory (the templates don't
  prompt for it, so the overrides never applied).
- **The drift pipeline gets `AAP_URL` from a credential**, so remediation calls
  this instance rather than the old EC2 host hard-coded in the playbook.
- Demo Project / Demo Inventory / Demo Job Template are not managed and can be
  deleted by hand.

---

## Known gaps

- **`revert-network-config-from-netbox` job template does not exist** (same as
  the old instance). It is what Agent 2 launches, by name, to push NetBox's
  values back to a drifted switch: playbook `revert-network-config-from-netbox.yml`,
  inventory **Add Switches**, credentials **Ubuntu SSH + Arista Switch Login**,
  and `ask_variables_on_launch: true` (otherwise AAP drops the `extra_vars`
  Agent 2 sends). Until it exists, **Network Drift Management** (which runs
  with `pipeline_apply: true`) fails at Agent 2 whenever it finds networking
  drift. When it is added, name it `DemoJam | Revert Network Config From NetBox`
  and set `aap_job_template_netbox_remediation` to that name in the drift
  template's extra vars. The same applies to
  `revert-security-config-from-github` (Agent 4), whose playbook doesn't exist yet.
- **EC2 inventory source has no credential.** Like the old instance, it relies
  on the AAP host's AWS IAM instance profile. If the new instance has no such
  role, the source won't sync; add an **Amazon Web Services** credential then.
  `apply.yml` skips syncing inventory sources for this reason.
- **`vault_drift_aap_token`** must be a token from the *new* instance, which
  only exists after the first apply: create it, put it in the vault, re-apply.
- **RBAC** is not managed (the old instance had none beyond `admin`).

---

## Running it

### Prerequisites

- AAP 2.7 installed and subscribed.
- A console.redhat.com offline token (Automation Hub).
- The admin password of the new instance.

### 1. Bootstrap (once, from a laptop, at the repo root)

```bash
export ANSIBLE_GALAXY_SERVER_AUTOMATION_HUB_TOKEN=<offline token>
ansible-galaxy collection install -r collections/requirements.yml -p collections
cp aap_config/vault.yml.example aap_config/group_vars/all/vault.yml
$EDITOR aap_config/group_vars/all/vault.yml
ansible-vault encrypt aap_config/group_vars/all/vault.yml
ansible-playbook -i aap_config/inventory aap_config/apply.yml --ask-vault-pass
```

### 2. Wire the webhook (once)

In AAP open **DemoJam | Apply Config as Code** and copy its webhook URL and key.
In GitHub: **Settings → Webhooks → Add webhook**, content type
`application/json`, the copied secret, event **Just the push event**.

### 3. Steady state

Change YAML → PR → merge to `main` → webhook launches **Apply Config as Code**
→ AAP reconciles itself.

The project syncs whatever branch `demojam_repo_branch` names, so while it
points at a feature branch, pushes to that branch are what get applied.

Install the commit guard once per clone: `pip install pre-commit && pre-commit install`.

---

## Gotchas

- **Names are identity.** Objects are matched by name + organization; renaming
  in YAML creates a new object and leaves the old one behind.
- **Collections location.** AAP project sync only auto-installs
  `collections/requirements.yml` from the **repo root**.
- **Certified collections.** `infra.aap_configuration` depends on
  `ansible.platform`, which only exists on Automation Hub. The root
  `ansible.cfg` lists Automation Hub first; export
  `ANSIBLE_GALAXY_SERVER_AUTOMATION_HUB_TOKEN` before installing.
- **Injector templates** in `credential_types.yml` are marked `!unsafe` so
  Ansible doesn't try to render AAP's `{{ … }}` placeholders.

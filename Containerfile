# =============================================================================
# Network Drift Manager - Execution Environment
# =============================================================================
# Same pattern as ../aap-drift-manager/aap-drift-manager/Containerfile:
# the image contains ONLY runtime dependencies. The agent source code
# (src/, run_pipeline.py, network-drift-manager.yaml, mcp-netbox/) is NOT
# baked in here - it is mounted in by ansible-navigator (locally) or
# checked out from Git by AAP (in production) at /runner/project.
#
# This project's own requirements.txt already contains the two fixes
# noted in README.md as required for aap-drift-manager-ee (add `openai`,
# pin `mcp<2.0.0`) - see requirements.txt for details.
#
# WHY THERE'S NO `microdnf install` STEP HERE
# ============================================
# An earlier version of this file ran `microdnf install -y python3.12
# git gcc ...`, mirroring aap-drift-manager/Containerfile. That FAILS on
# any host that isn't an actively-subscribed, subscription-manager-
# registered RHEL system (confirmed here: even with real entitlement
# certs manually bind-mounted at /etc/pki/entitlement + /etc/rhsm, dnf
# still gets HTTP 403 from cdn.redhat.com/.../rhel-9-for-x86_64-baseos-rpms
# - `podman login registry.redhat.io` only authorizes pulling the base
# IMAGE, it does NOT grant RPM content-repo access). Turns out it's also
# unnecessary: `ee-supported-rhel9:latest` already ships everything that
# install step was trying to add:
#   python3.12 (3.12.14), python3.12-pip, git (2.52.0), openssh-clients
#   (ssh-keyscan), python3.12-cffi/cryptography (prebuilt, no compiler
#   needed). None of this project's requirements.txt packages need a
#   C compiler at install time either - they all ship prebuilt manylinux
#   wheels (verified: `pip install -r requirements.txt` succeeds against
#   this exact base image with zero RPM installs).
# If a future dependency genuinely needs an RPM that isn't already in
# the image, you'll need real RHEL entitlements (subscription-manager
# register on the actual build host, or bind-mount valid entitlement
# certs from one) - plain `podman login registry.redhat.io` is not
# enough.
#
# BUILD
#   podman login registry.redhat.io        # required for the base image
#   podman build -t demojam-2027-ee:latest -f Containerfile .
#
# See STEPS.md for the full local test workflow.
# =============================================================================

FROM registry.redhat.io/ansible-automation-platform-26/ee-supported-rhel9:latest

LABEL name="demojam-2027-ee" \
      version="1.0.0" \
      description="Runtime EE for the Network Drift Manager deterministic agent workflow"

USER root

# ---------------------------------------------------------
# Python dependencies
# ---------------------------------------------------------
# python3.12 + pip are already present in this base image - no microdnf
# install needed (see header comment). Copy only requirements.txt (not
# source code) to keep image lean. Covers both the main pipeline AND the
# embedded mcp-netbox server (mcp, httpx are shared deps - mcp-netbox has
# no extra deps beyond what's already listed here).
# ---------------------------------------------------------
COPY requirements.txt /tmp/requirements.txt

# --no-build-isolation + pre-installing hatchling is required for the
# netbox-mcp-server line in requirements.txt (git source, no prebuilt
# wheel on PyPI - pip has to build it). Every OTHER package here installs
# from a prebuilt wheel, so this doesn't affect them, but without it pip's
# isolated build-env subprocess trips over a broken leftover
# nsx_policy_python_sdk-*-py2.7-nspkg.pth file in this base image (a
# stale VMware NSX SDK namespace-package shim from Red Hat's own image
# build, unrelated to this project) with
# "ModuleNotFoundError: No module named 'json'" - confirmed by
# reproducing the failure, unrelated to network/credentials/pinning.
RUN python3.12 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python3.12 -m pip install --no-cache-dir hatchling \
    && python3.12 -m pip install --no-cache-dir --no-build-isolation -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# ---------------------------------------------------------
# SSH known hosts
# ---------------------------------------------------------
# ssh-keyscan comes from openssh-clients, already present in the base
# image. Harmless to keep even though this project doesn't clone git
# repos at runtime today - GitHub is reached over MCP, not git.
# ---------------------------------------------------------
RUN mkdir -p /etc/ssh \
    && ssh-keyscan github.com >> /etc/ssh/ssh_known_hosts 2>/dev/null || true

# ---------------------------------------------------------
# Runtime environment
# ---------------------------------------------------------
# PYTHONPATH is left empty here intentionally.
# ansible-navigator / AAP mount the project at /runner/project and set
# that as the working directory, so "import src.xxx" works without any
# path tricks (network-drift-manager.yaml sets PYTHONPATH explicitly too).
# ---------------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Switch to the standard EE unprivileged user
USER 1000

# ---------------------------------------------------------
# Smoke test
# ---------------------------------------------------------
# Verify all installed packages import correctly. No || true - a real
# import failure breaks the build immediately.
# ---------------------------------------------------------
RUN python3.12 -c "\
import pydantic, pydantic_settings, dotenv, httpx, yaml; \
import mcp, openai, typer, rich, tenacity; \
import netbox_mcp_server; \
print('EE smoke test passed - all deps import OK')" \
    && netbox-mcp-server --help > /dev/null \
    && echo "netbox-mcp-server console script is on PATH"

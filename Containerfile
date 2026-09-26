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
# System packages
# ---------------------------------------------------------
# python3.12 / python3.12-devel / python3.12-pip : agent code targets 3.12
# git / openssh-clients                          : mcp-netbox / future MCP
#                                                    stdio servers may need it
# gcc / gcc-c++ / libffi-devel / openssl-devel / make
#                                                 : compile native wheels
#                                                    (e.g. pydantic-core)
# ---------------------------------------------------------
RUN microdnf install -y \
        python3.12 \
        python3.12-devel \
        python3.12-pip \
        git \
        openssh-clients \
        gcc \
        gcc-c++ \
        libffi-devel \
        openssl-devel \
        make \
    && microdnf clean all \
    && rm -rf /var/cache/dnf

# ---------------------------------------------------------
# Python dependencies
# ---------------------------------------------------------
# Copy only requirements.txt (not source code) to keep image lean.
# Covers both the main pipeline AND the embedded mcp-netbox server
# (mcp, httpx are shared dependencies - mcp-netbox has no extra deps
# beyond what's already listed here).
# ---------------------------------------------------------
COPY requirements.txt /tmp/requirements.txt

RUN python3.12 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python3.12 -m pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# ---------------------------------------------------------
# SSH known hosts (harmless to keep even though this project doesn't
# clone git repos at runtime today - GitHub is reached over MCP, not git)
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
print('EE smoke test passed - all deps import OK')"

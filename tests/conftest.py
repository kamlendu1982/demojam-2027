import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Force demo + dry-run defaults for the whole test session, regardless of
# any local .env file, so tests never attempt real network calls.
os.environ["DEMO_MODE"] = "true"
os.environ["DRY_RUN"] = "true"
os.environ["MAAS_API_BASE"] = ""
os.environ["MAAS_API_KEY"] = ""
os.environ["MAAS_MODEL"] = ""
os.environ["AAP_JOB_TEMPLATE_NETBOX_REMEDIATION"] = "revert-network-config-from-netbox"
os.environ["AAP_JOB_TEMPLATE_GITHUB_REMEDIATION"] = "revert-security-config-from-github"

import pytest  # noqa: E402
from src.config import load_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _reload_settings():
    load_settings(refresh=True)
    yield

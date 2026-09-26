"""Loads config/attribute_classification.yaml and exposes a single
deterministic lookup function used by Agent 1.
"""

import functools
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

from src.config import PROJECT_ROOT

CLASSIFICATION_FILE = PROJECT_ROOT / "config" / "attribute_classification.yaml"


@functools.lru_cache(maxsize=1)
def _load() -> Dict:
    if not CLASSIFICATION_FILE.exists():
        return {"security_attributes": [], "networking_attributes": {}}
    with open(CLASSIFICATION_FILE) as fh:
        return yaml.safe_load(fh) or {}


def clear_cache() -> None:
    _load.cache_clear()  # useful for tests that swap the config file


def classify_from_config(attribute_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (category, netbox_path) for a known attribute.

    category is None if the attribute is not found in the static config —
    callers should fall back to the LLM classifier (src.llm.classify_attribute)
    in that case.
    """
    data = _load()

    if attribute_name in (data.get("security_attributes") or []):
        return "security", None

    networking = data.get("networking_attributes") or {}
    if attribute_name in networking:
        return "networking", networking[attribute_name].get("netbox_path")

    return None, None

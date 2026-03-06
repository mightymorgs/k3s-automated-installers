"""Fetch Docker Compose files from GitHub repos using raw content API."""

import urllib.request
from pathlib import Path
from typing import Optional

import yaml


def load_source_index(index_path: Path) -> dict:
    """Load the compose-sources.yaml index file."""
    if not index_path.exists():
        return {"sources": {}}
    return yaml.safe_load(index_path.read_text()) or {"sources": {}}


def resolve_compose_url(
    index: dict, source_name: str, app_name: str
) -> Optional[str]:
    """Resolve a compose file URL from the source index."""
    source = index.get("sources", {}).get(source_name)
    if not source:
        return None
    rel_path = source.get("app_mapping", {}).get(app_name)
    if not rel_path:
        return None
    repo = source["repo"]
    # Convert GitHub URL to raw content URL
    # https://github.com/org/repo -> https://raw.githubusercontent.com/org/repo/main/
    if "github.com" in repo:
        raw_base = repo.replace("github.com", "raw.githubusercontent.com")
        return f"{raw_base}/main/{rel_path}"
    return f"{repo}/{rel_path}"


def fetch_compose_file(url: str) -> Optional[dict]:
    """Fetch and parse a Docker Compose YAML file from a URL."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            content = response.read()
            return yaml.safe_load(content)
    except Exception:
        return None

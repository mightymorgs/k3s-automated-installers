"""URI call and cross-service dependency detection for sidecar generation.

Detects three types of cross-service references in Ansible playbooks:

1. ``url:`` fields in URI tasks (original behavior)
2. ``requires_apps`` from playbook metadata comments
3. Service URL variable references (``{{ service_url }}``) anywhere in the file,
   including nested request body URLs (e.g., Grafana datasource configs)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# Match {{ service_url }}, {{ service_api_base }}, {{ service_internal_url }}, etc.
_SVC_URL_VAR = re.compile(
    r"\{\{\s*(\w+?)(?:_url|_api_base|_internal_url|_internal_addr|_base_url)"
    r"\s*(?:\|[^}]*)?\}\}"
)

# Match requires_apps in metadata comments: #   requires_apps: ["app1", "app2"]
_REQUIRES_APPS = re.compile(
    r'#\s*requires_apps:\s*\[([^\]]*)\]'
)


def detect_uri_calls(playbook_path: Path) -> list[str]:
    """Detect ansible URI task URLs from a playbook file.

    Only extracts ``url`` from ``ansible.builtin.uri`` or ``uri`` task
    module args -- ignores URLs in ``body:``, ``vars:``, or other contexts.
    """
    content = playbook_path.read_text()
    urls: list[str] = []

    try:
        docs = list(yaml.safe_load_all(content))
    except yaml.YAMLError:
        return urls

    for doc in docs:
        if not isinstance(doc, list):
            continue
        for play in doc:
            if not isinstance(play, dict):
                continue
            tasks = play.get("tasks", [])
            if not isinstance(tasks, list):
                continue
            _extract_from_tasks(tasks, urls)

    return urls


def _extract_from_tasks(tasks: list[Any], urls: list[str]) -> None:
    """Walk task list (including blocks) and extract URI module URLs."""
    for task in tasks:
        if not isinstance(task, dict):
            continue

        # Handle block/rescue/always
        for block_key in ("block", "rescue", "always"):
            nested = task.get(block_key)
            if isinstance(nested, list):
                _extract_from_tasks(nested, urls)

        # Check for uri module (both FQCN and short form)
        for module_key in ("ansible.builtin.uri", "uri"):
            module_args = task.get(module_key)
            if isinstance(module_args, dict):
                url = module_args.get("url")
                if url and isinstance(url, str):
                    urls.append(url)


def detect_service_refs(playbook_path: Path) -> list[str]:
    """Detect service URL variable references anywhere in the file.

    Returns service names (normalized with hyphens) referenced via
    ``{{ service_url }}``, ``{{ service_internal_url }}``, etc.
    Excludes self-references (where the variable matches the app name).
    """
    content = playbook_path.read_text()

    # Determine this app's name from the path
    parts = playbook_path.parts
    app_name = None
    if "apps" in parts:
        app_idx = parts.index("apps")
        if app_idx + 1 < len(parts):
            app_name = parts[app_idx + 1]

    services: set[str] = set()
    for match in _SVC_URL_VAR.finditer(content):
        svc = match.group(1).replace("_", "-")
        if svc != app_name:
            services.add(svc)

    return sorted(services)


def detect_requires_apps(playbook_path: Path) -> list[str]:
    """Extract requires_apps from playbook metadata comments.

    Parses lines like:
        #   requires_apps: ["vault", "external-secrets"]

    Returns list of app names, excluding the app that owns this playbook.
    """
    content = playbook_path.read_text()

    parts = playbook_path.parts
    app_name = None
    if "apps" in parts:
        app_idx = parts.index("apps")
        if app_idx + 1 < len(parts):
            app_name = parts[app_idx + 1]

    apps: set[str] = set()
    for match in _REQUIRES_APPS.finditer(content):
        raw = match.group(1)
        for item in re.findall(r'"([^"]+)"', raw):
            normalized = item.strip().replace("_", "-")
            if normalized != app_name:
                apps.add(normalized)

    return sorted(apps)

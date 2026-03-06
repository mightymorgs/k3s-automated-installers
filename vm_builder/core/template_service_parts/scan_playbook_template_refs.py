"""Playbook scan helper for template src references."""

from __future__ import annotations

from pathlib import Path

import yaml


def scan_playbook_template_refs(playbook_path: Path) -> list[str]:
    """Find src paths used by ansible template tasks in a playbook."""
    playbook_path = Path(playbook_path)
    if not playbook_path.exists():
        return []

    try:
        content = playbook_path.read_text()
        data = yaml.safe_load(content)
    except (OSError, yaml.YAMLError):
        return []

    if not isinstance(data, list):
        return []

    refs: list[str] = []
    for play in data:
        if not isinstance(play, dict):
            continue
        tasks = play.get("tasks", [])
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if not isinstance(task, dict):
                continue
            template_args = task.get("ansible.builtin.template") or task.get(
                "template"
            )
            if isinstance(template_args, dict):
                src = template_args.get("src")
                if src and isinstance(src, str):
                    refs.append(src)

    return refs

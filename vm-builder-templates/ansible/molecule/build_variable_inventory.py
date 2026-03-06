#!/usr/bin/env python3
"""Build variable inventory: extract all vars from J2 + playbooks, cross-ref with BWS cache."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import jinja2
import jinja2.meta
import yaml

# Ansible builtins that should not be treated as user variables
ANSIBLE_BUILTINS = {
    "ansible_facts", "ansible_hostname", "ansible_os_family", "ansible_distribution",
    "ansible_connection", "ansible_user", "ansible_become", "ansible_python_interpreter",
    "inventory_hostname", "hostvars", "groups", "group_names", "play_hosts",
    "playbook_dir", "role_path", "item", "loop", "ansible_loop", "ansible_check_mode",
    "ansible_diff_mode", "ansible_verbosity", "omit", "undefined", "true", "false",
    "none", "True", "False", "None", "range", "lookup", "query",
    "target_hosts", "install_mode", "kubectl_action",  # common extra-vars (not BWS)
}

# Variable reference pattern in playbook YAML ({{ var_name }})
VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)")


def extract_j2_vars(template_path: Path) -> dict[str, dict]:
    """Extract undeclared variables from a Jinja2 template."""
    text = template_path.read_text()
    if not text.strip():
        return {}
    env = jinja2.Environment()
    env.globals = {}
    try:
        ast = env.parse(text)
        names = jinja2.meta.find_undeclared_variables(ast)
    except jinja2.TemplateSyntaxError:
        names = {m.group(1) for m in VAR_RE.finditer(text)}
    names = {n for n in names if n not in ANSIBLE_BUILTINS}
    return {n: {"source_file": template_path.name} for n in sorted(names)}


def extract_playbook_var_refs(playbook_path: Path) -> set[str]:
    """Extract variable references from playbook tasks ({{ var }})."""
    text = playbook_path.read_text()
    refs = {m.group(1) for m in VAR_RE.finditer(text)}
    return refs - ANSIBLE_BUILTINS


def resolve_bws_path(var_name: str, app: str, inventory: dict) -> str | None:
    """Try to find where this var would come from in BWS."""
    # Direct _config match
    config = inventory.get("_config", {}).get(app, {})
    if var_name in config:
        return f"_config.{app}.{var_name}"

    # Cross-app state: {app}_{field} pattern
    norm_app = app.replace("-", "_")
    for suffix in ["api_key", "admin_password", "root_token", "admin_token",
                    "url", "nodeport", "pod_name", "namespace", "service_name",
                    "service_port", "websecure_port"]:
        if var_name == f"{norm_app}_{suffix}":
            state_app = inventory.get("_state", {}).get("apps", {}).get(app, {})
            if suffix in state_app:
                return f"_state.apps.{app}.{suffix}"

    # Cross-app refs (other app's vars)
    for other_app, state in inventory.get("_state", {}).get("apps", {}).items():
        other_norm = other_app.replace("-", "_")
        for suffix in ["api_key", "admin_password", "root_token", "admin_token",
                        "url", "nodeport", "pod_name", "namespace", "service_name",
                        "service_port", "websecure_port"]:
            if var_name == f"{other_norm}_{suffix}" and suffix in state:
                return f"_state.apps.{other_app}.{suffix}"

    # Top-level special cases
    specials = {
        "vault_root_token": "_state.vault.root_token",
        "vault_unseal_key": "_state.vault.unseal_key",
        "vault_initialized": "_state.vault.initialized",
        "k3s_pod_cidr": "_state.k3s.pod_cidr",
        "k3s_service_cidr": "_state.k3s.service_cidr",
        "domain": "ingress.domain",
        "ingress_domain": "ingress.domain",
        "vm_hostname": "identity.hostname",
    }
    return specials.get(var_name)


def build_inventory(repo_root: Path, bws_cache_path: Path | None) -> dict:
    """Build the complete variable inventory."""
    apps_dir = repo_root / "vm-builder" / "vm-builder-templates" / "apps"
    inventory_data = {}

    if bws_cache_path and bws_cache_path.exists():
        bws_inventory = json.loads(bws_cache_path.read_text())
    else:
        bws_inventory = {}

    for app_dir in sorted(apps_dir.iterdir()):
        if not app_dir.is_dir():
            continue
        app = app_dir.name
        app_entry: dict = {"template_vars": {}, "playbook_vars": {}, "bws_coverage": {"resolved": [], "missing": []}}

        # Extract J2 template vars
        templates_dir = app_dir / "templates"
        if templates_dir.exists():
            for j2 in sorted(templates_dir.glob("*.j2")):
                for var_name, meta in extract_j2_vars(j2).items():
                    if var_name not in app_entry["template_vars"]:
                        app_entry["template_vars"][var_name] = {"source_files": [meta["source_file"]]}
                    elif meta["source_file"] not in app_entry["template_vars"][var_name]["source_files"]:
                        app_entry["template_vars"][var_name]["source_files"].append(meta["source_file"])

        # Extract playbook var refs
        for subdir in ["install", "config"]:
            pb_dir = app_dir / subdir
            if not pb_dir.exists():
                continue
            for pb in sorted(pb_dir.glob("*.yml")):
                for var_name in extract_playbook_var_refs(pb):
                    if var_name not in app_entry["playbook_vars"]:
                        bws_path = resolve_bws_path(var_name, app, bws_inventory) if bws_inventory else None
                        entry = {"source_files": [pb.name]}
                        if bws_path:
                            entry["bws_path"] = bws_path
                        app_entry["playbook_vars"][var_name] = entry
                    elif pb.name not in app_entry["playbook_vars"][var_name].get("source_files", []):
                        app_entry["playbook_vars"][var_name].setdefault("source_files", []).append(pb.name)

        # BWS coverage analysis
        if bws_inventory:
            all_vars = set(app_entry["template_vars"]) | set(app_entry["playbook_vars"])
            for var_name in sorted(all_vars):
                bws_path = resolve_bws_path(var_name, app, bws_inventory)
                if bws_path:
                    app_entry["bws_coverage"]["resolved"].append(var_name)
                else:
                    app_entry["bws_coverage"]["missing"].append(var_name)

        if app_entry["template_vars"] or app_entry["playbook_vars"]:
            inventory_data[app] = app_entry

    return inventory_data


def main():
    script_dir = Path(__file__).parent
    repo_root = script_dir.parents[3]  # molecule/ -> ansible/ -> vm-builder-templates/ -> vm-builder/ -> repo
    bws_cache = script_dir / "fixtures" / "bws-inventory.json"
    output = script_dir / "fixtures" / "variable-inventory.json"

    result = build_inventory(repo_root, bws_cache if bws_cache.exists() else None)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    total_vars = sum(
        len(v["template_vars"]) + len(v["playbook_vars"]) for v in result.values()
    )
    resolved = sum(len(v["bws_coverage"]["resolved"]) for v in result.values())
    missing = sum(len(v["bws_coverage"]["missing"]) for v in result.values())

    print(f"Variable inventory: {len(result)} apps, {total_vars} vars")
    print(f"BWS coverage: {resolved} resolved, {missing} missing")
    if missing > 0:
        print("\nMissing vars (not found in BWS):")
        for app, data in result.items():
            if data["bws_coverage"]["missing"]:
                print(f"  {app}: {', '.join(data['bws_coverage']['missing'])}")

    print(f"\nSaved to {output}")


if __name__ == "__main__":
    main()

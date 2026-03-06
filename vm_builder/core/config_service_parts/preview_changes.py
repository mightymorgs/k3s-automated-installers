"""Preview config changes by rendering J2 templates and diffing against k8s-base."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Optional

import jinja2

from vm_builder.core.config_service_parts.apply_live import _detect_statefulset_warnings
from vm_builder.core.errors import AppNotFoundError, ValidationError as VmValidationError


def _render_template(template_path: Path, variables: dict) -> str:
    """Render a single Jinja2 template with the given variables."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_path.parent)),
        undefined=jinja2.Undefined,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_path.name)
    return template.render(**variables)


def _find_base_manifest(app_dir: Path, template_name: str) -> Optional[Path]:
    """Find the matching k8s-base manifest for a J2 template.

    Template names follow the pattern: ``configmap.yaml.j2`` -> ``configmap.yaml``.
    """
    if template_name.endswith(".j2"):
        base_name = template_name[:-3]
    else:
        base_name = template_name

    base_dir = app_dir / "k8s-base"
    if not base_dir.is_dir():
        return None

    candidate = base_dir / base_name
    if candidate.exists():
        return candidate
    return None


def _generate_diff(
    base_content: str,
    rendered_content: str,
    from_label: str,
    to_label: str,
) -> str:
    """Generate a unified diff between base and rendered content."""
    base_lines = base_content.splitlines(keepends=True)
    rendered_lines = rendered_content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        base_lines,
        rendered_lines,
        fromfile=from_label,
        tofile=to_label,
    )
    return "".join(diff)


def preview_changes(
    self,
    vm_name: str,
    app_id: str,
    templates_dir: Optional[Path] = None,
) -> dict:
    """Render J2 templates with current _config and diff against k8s-base.

    Returns a dict with per-file diffs and a combined summary.
    """
    if not templates_dir:
        raise VmValidationError(
            "TEMPLATES_DIR not configured",
            context={"vm_name": vm_name, "app_id": app_id},
            hint="Set TEMPLATES_DIR environment variable",
        )

    app_dir = templates_dir / "apps" / app_id
    if not app_dir.is_dir():
        raise AppNotFoundError(
            f"App directory not found: {app_id}",
            context={"vm_name": vm_name, "app_id": app_id},
        )

    templates_subdir = app_dir / "templates"
    if not templates_subdir.is_dir():
        return {
            "app_id": app_id,
            "vm_name": vm_name,
            "diffs": [],
            "has_changes": False,
            "summary": "No J2 templates found for this app",
        }

    inventory = self._vm_service.get_vm(vm_name)
    app_config = inventory.get("_config", {}).get(app_id, {})

    j2_files = sorted(templates_subdir.glob("*.j2"))
    if not j2_files:
        return {
            "app_id": app_id,
            "vm_name": vm_name,
            "diffs": [],
            "has_changes": False,
            "summary": "No J2 templates found for this app",
        }

    diffs: list[dict] = []
    warnings: list[str] = []

    for j2_path in j2_files:
        rendered = _render_template(j2_path, app_config)

        # Collect StatefulSet immutable-field warnings
        warnings.extend(_detect_statefulset_warnings(rendered))

        base_path = _find_base_manifest(app_dir, j2_path.name)
        if base_path:
            base_content = base_path.read_text()
            from_label = f"k8s-base/{base_path.name}"
        else:
            base_content = ""
            from_label = "(no base manifest)"

        to_label = f"rendered/{j2_path.stem}"
        diff_text = _generate_diff(
            base_content, rendered, from_label, to_label,
        )

        diffs.append({
            "file": j2_path.name,
            "diff": diff_text,
            "has_changes": bool(diff_text.strip()),
            "rendered_preview": rendered,
        })

    has_changes = any(d["has_changes"] for d in diffs)
    changed_count = sum(1 for d in diffs if d["has_changes"])

    return {
        "app_id": app_id,
        "vm_name": vm_name,
        "diffs": diffs,
        "has_changes": has_changes,
        "warnings": warnings,
        "summary": (
            f"{changed_count} of {len(diffs)} manifests differ from base"
            if has_changes
            else "All rendered manifests match base (no changes)"
        ),
    }

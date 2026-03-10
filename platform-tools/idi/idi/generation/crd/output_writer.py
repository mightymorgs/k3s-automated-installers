"""CRD skill JSON output writer.

Serializes classified fields and CRD metadata into skill JSON files.
Supports both monolithic (schema v1.0) and decomposed (schema v2.0) formats.

Monolithic: catalog/skills/crd/{service}/{Kind}.json
Decomposed: catalog/skills/crd/{group}/{service}/{Kind}/manifest.json + subdirs
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from idi.generation.crd.field_classifier import ClassifiedField

logger = logging.getLogger(__name__)


def _python_type(value: Any) -> str:
    """Map a Python value to a JSON Schema type string."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


# ---------------------------------------------------------------------------
# Decomposed output (schema v2.0)
# ---------------------------------------------------------------------------


def _sanitize_path_segment(segment: str) -> str:
    """Replace unsafe characters in path segments. Allow [A-Za-z0-9._-]."""
    return re.sub(r'[^A-Za-z0-9._-]', '_', segment)


def _satisfaction_for_field(field: ClassifiedField) -> str:
    """Determine satisfaction mode for a ref field."""
    return "required_value" if field.required else "optional"


def _fact_ref_for_ref(field: ClassifiedField) -> str:
    """Build crdfacts:// URI for an input_ref in decomposed format.

    Uses target_field for the fragment if populated, falls back to leaf name.
    This ensures two consumer fields referencing Secret#name produce
    the same fact URI: crdfacts://core/Secret#name.
    """
    group = field.target_group or "core"
    kind = field.target_kind or "Unknown"
    fragment = field.target_field if field.target_field else field.field.rsplit(".", 1)[-1]
    return f"crdfacts://{group}/{kind}#{fragment}"


def _fact_ref_for_output(field: ClassifiedField) -> str:
    """Build crdfacts:// URI for an output_declaration in decomposed format.

    Uses target_field for the fragment if populated, falls back to leaf name.
    """
    group = field.target_group or "core"
    kind = field.target_kind or "Unknown"
    fragment = field.target_field if field.target_field else field.field.rsplit(".", 1)[-1]
    return f"crdfacts://{group}/{kind}#{fragment}"


def _resolve_filenames(fields: list[ClassifiedField], role: str) -> dict[str, str]:
    """Map field_path -> filename for fields of the given role.

    Returns dict mapping field_path to safe filename (without .json extension).
    Detects collisions and uses hyphen-joined paths when needed.
    """
    role_fields = [f for f in fields if f.role == role or
                   (role == "output_declaration" and f.role == "output_declaration") or
                   (role == "input_ref" and f.role == "input_ref" and f.target_kind) or
                   (role == "config_field" and f.role == "config_field")]

    # Filter properly based on role.
    if role == "input_ref":
        role_fields = [f for f in fields if f.role == "input_ref" and f.target_kind]
    elif role == "output_declaration":
        role_fields = [f for f in fields if f.role == "output_declaration"]
    elif role == "config_field":
        role_fields = [f for f in fields if f.role == "config_field"]

    # Default: use leaf field name.
    path_to_leaf: dict[str, str] = {}
    for f in role_fields:
        leaf = f.field.rsplit(".", 1)[-1]
        path_to_leaf[f.field] = leaf

    # Detect collisions (case-insensitive).
    seen_lower: dict[str, list[str]] = {}
    for field_path, leaf in path_to_leaf.items():
        lower = leaf.lower()
        seen_lower.setdefault(lower, []).append(field_path)

    # Resolve collisions with hyphen-joined paths.
    result: dict[str, str] = {}
    for field_path, leaf in path_to_leaf.items():
        lower = leaf.lower()
        if len(seen_lower[lower]) > 1:
            # Use hyphen-joined path: strip "spec." prefix, replace "." with "-".
            path_part = field_path
            if path_part.startswith("spec."):
                path_part = path_part[5:]
            result[field_path] = path_part.replace(".", "-")
        else:
            result[field_path] = leaf

    return result


def _compute_content_hash(file_contents: dict[str, dict]) -> str:
    """Compute deterministic SHA-256 hash of all files (excluding manifest.json).

    Args:
        file_contents: Dict mapping relative_path -> JSON-serializable dict.

    Returns:
        Hex digest of SHA-256 hash.
    """
    parts: list[str] = []
    for rel_path in sorted(file_contents.keys()):
        canonical = json.dumps(file_contents[rel_path], sort_keys=True, separators=(',', ':'))
        parts.append(f"{rel_path}\n{canonical}\n")
    combined = "".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def build_decomposed_skill(
    crd_info: dict[str, Any],
    fields: list[ClassifiedField],
    status_conditions: list[str] | None = None,
) -> dict[str, Any]:
    """Build decomposed CRD skill as a dict-of-dicts.

    Args:
        crd_info: Dict with kind, group, version, plural, scope, service, description.
        fields: Classified fields from field_classifier.
        status_conditions: Status conditions (default: ["Ready"]).

    Returns:
        Dict with keys: 'manifest', 'operation', 'refs', 'outputs', 'fields'.
        'refs', 'outputs', 'fields' are dicts mapping filename to content dict.
    """
    conditions = status_conditions or ["Ready"]
    kind = crd_info["kind"]
    group = crd_info["group"]
    service = crd_info["service"]
    plural = crd_info.get("plural", "")

    # Resolve filenames with collision detection.
    ref_names = _resolve_filenames(fields, "input_ref")
    output_names = _resolve_filenames(fields, "output_declaration")
    field_names = _resolve_filenames(fields, "config_field")

    # Build refs.
    refs: dict[str, dict[str, Any]] = {}
    for f in fields:
        if f.role != "input_ref" or not f.target_kind:
            continue
        fname = ref_names[f.field]
        refs[fname] = {
            "name": f.field.rsplit(".", 1)[-1],
            "field_path": f.field,
            "target_kind": f.target_kind,
            "target_group": f.target_group or group,
            "target_plural": "",  # Not available on ClassifiedField; filled by orchestrator if needed.
            "role": "input_ref",
            "required": f.required,
            "cross_namespace": f.cross_namespace,
            "fact_ref": _fact_ref_for_ref(f),
            "fact_shape": f.fact_shape or "identity",
            "satisfaction": _satisfaction_for_field(f),
            "detection_source": f.detection_source,
            "confidence": f.confidence,
        }

    # Build outputs.
    outputs: dict[str, dict[str, Any]] = {}
    for f in fields:
        if f.role != "output_declaration":
            continue
        fname = output_names[f.field]
        outputs[fname] = {
            "name": f.field.rsplit(".", 1)[-1],
            "field_path": f.field,
            "produces_kind": f.target_kind or "Unknown",
            "produces_group": f.target_group or "core",
            "produces_plural": "",
            "role": "output_declaration",
            "fact_ref": _fact_ref_for_output(f),
            "fact_shape": f.fact_shape or "identity",
            "detection_source": f.detection_source,
            "confidence": f.confidence,
        }

    # Build fields.
    field_dicts: dict[str, dict[str, Any]] = {}
    for f in fields:
        if f.role != "config_field":
            continue
        fname = field_names[f.field]
        entry: dict[str, Any] = {
            "name": f.field.rsplit(".", 1)[-1],
            "field_path": f.field,
            "type": f.field_type,
            "required": f.required,
            "cardinality": "many" if f.field_type == "array" else "one",
            "fact_shape": "config",
        }
        if f.description:
            entry["description"] = f.description
        field_dicts[fname] = entry

    # Build operation.
    operation = {
        "schema_version": "2.0",
        "action_id": f"configure.{service}.{kind.lower()}",
        "path": f"{service}/{kind}/apply",
        "phase": "configure",
        "executor": "crd",
        "description": f"Apply a {kind} CRD manifest",
        "execution": {
            "method": "kubectl_apply",
            "wait_condition": "condition=Ready",
        },
        "depends_on": [
            {
                "ref": refs[fname]["name"],
                "target_kind": refs[fname]["target_kind"],
                "target_group": refs[fname]["target_group"],
                "fact_ref": refs[fname]["fact_ref"],
                "required": refs[fname]["required"],
                "satisfaction": refs[fname]["satisfaction"],
            }
            for fname in sorted(refs.keys())
        ],
        "outputs": [
            {
                "output": outputs[fname]["name"],
                "produces_kind": outputs[fname]["produces_kind"],
                "produces_group": outputs[fname]["produces_group"],
                "fact_ref": outputs[fname]["fact_ref"],
            }
            for fname in sorted(outputs.keys())
        ],
    }

    # Compute content hash from all files except manifest.
    all_files: dict[str, dict] = {}
    all_files["operations/apply.json"] = operation
    for fname, content in sorted(refs.items()):
        all_files[f"refs/{fname}.json"] = content
    for fname, content in sorted(outputs.items()):
        all_files[f"outputs/{fname}.json"] = content
    for fname, content in sorted(field_dicts.items()):
        all_files[f"fields/{fname}.json"] = content

    content_hash = _compute_content_hash(all_files)

    # Build manifest.
    manifest = {
        "schema_version": "2.0",
        "kind": kind,
        "group": group,
        "version": crd_info["version"],
        "plural": plural,
        "scope": crd_info["scope"],
        "service": service,
        "description": crd_info.get("description") or f"{kind} CRD",
        "operations": ["apply"],
        "refs": sorted(refs.keys()),
        "outputs": sorted(outputs.keys()),
        "fields": sorted(field_dicts.keys()),
        "status_conditions": conditions,
        "content_hash": content_hash,
    }

    return {
        "manifest": manifest,
        "operation": operation,
        "refs": refs,
        "outputs": outputs,
        "fields": field_dicts,
    }


def write_decomposed_skill(
    crd_info: dict[str, Any],
    fields: list[ClassifiedField],
    output_dir: Path,
    status_conditions: list[str] | None = None,
) -> Path:
    """Write decomposed CRD skill files to the Kind directory.

    Creates: {output_dir}/{group}/{service}/{Kind}/ with subdirectories.
    Sanitizes path segments. Asserts output within output_dir.

    Returns:
        The Kind directory path.
    """
    skill = build_decomposed_skill(crd_info, fields, status_conditions)

    group_seg = _sanitize_path_segment(crd_info["group"])
    service_seg = _sanitize_path_segment(crd_info["service"])
    kind_seg = _sanitize_path_segment(crd_info["kind"])

    kind_dir = output_dir / group_seg / service_seg / kind_seg

    # Path traversal guard.
    resolved = kind_dir.resolve()
    assert resolved.is_relative_to(output_dir.resolve()), f"Path traversal: {kind_dir}"

    # Create directories.
    (kind_dir / "operations").mkdir(parents=True, exist_ok=True)
    if skill["refs"]:
        (kind_dir / "refs").mkdir(exist_ok=True)
    if skill["outputs"]:
        (kind_dir / "outputs").mkdir(exist_ok=True)
    if skill["fields"]:
        (kind_dir / "fields").mkdir(exist_ok=True)

    def _write(path: Path, content: dict) -> None:
        path.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n")

    # Write files.
    _write(kind_dir / "manifest.json", skill["manifest"])
    _write(kind_dir / "operations" / "apply.json", skill["operation"])

    written_files: set[str] = set()
    for fname, content in skill["refs"].items():
        fpath = f"refs/{fname}.json"
        assert fpath not in written_files, f"Duplicate file: {fpath}"
        written_files.add(fpath)
        _write(kind_dir / "refs" / f"{fname}.json", content)

    for fname, content in skill["outputs"].items():
        fpath = f"outputs/{fname}.json"
        assert fpath not in written_files, f"Duplicate file: {fpath}"
        written_files.add(fpath)
        _write(kind_dir / "outputs" / f"{fname}.json", content)

    for fname, content in skill["fields"].items():
        fpath = f"fields/{fname}.json"
        assert fpath not in written_files, f"Duplicate file: {fpath}"
        written_files.add(fpath)
        _write(kind_dir / "fields" / f"{fname}.json", content)

    logger.info("Wrote decomposed CRD skill: %s", kind_dir)
    return kind_dir


# ---------------------------------------------------------------------------
# Helm output (unrelated to CRD decomposition)
# ---------------------------------------------------------------------------


def build_helm_spec_json(
    service: str,
    chart: str,
    repository: str,
    values: dict[str, Any],
    produces_kinds: list[str],
    version: str | None = None,
    namespace: str | None = None,
) -> dict[str, Any]:
    """Build a Helm chart spec JSON document.

    Args:
        service: Service name.
        chart: Helm chart name.
        repository: Chart repository URL.
        values: Top-level values.yaml keys.
        produces_kinds: CRD Kinds this chart installs (format: group/Kind).
        version: Chart version.
        namespace: Install namespace.

    Returns:
        Dict matching helm-chart.schema.json.
    """
    install_config = []
    for key, value in values.items():
        if isinstance(value, dict):
            continue  # Skip nested objects, only top-level scalars.
        entry: dict[str, Any] = {
            "field": key,
            "type": _python_type(value),
        }
        if value is not None and not isinstance(value, (dict, list)):
            entry["default"] = value
        install_config.append(entry)

    doc: dict[str, Any] = {
        "schema_version": "1.0",
        "chart": chart,
        "repository": repository,
        "service": service,
        "description": f"{chart} Helm chart install",
        "install_config": install_config,
        "namespace": namespace or service,
        "execution": {"method": "helm_install"},
        "produces_kinds": produces_kinds,
    }
    if version:
        doc["version"] = version

    return doc


def write_helm_spec(
    service: str,
    chart: str,
    repository: str,
    values: dict[str, Any],
    produces_kinds: list[str],
    output_dir: Path,
    version: str | None = None,
    namespace: str | None = None,
) -> Path:
    """Write a Helm chart spec JSON file.

    Returns:
        Path to the written JSON file.
    """
    doc = build_helm_spec_json(
        service=service, chart=chart, repository=repository,
        values=values, produces_kinds=produces_kinds,
        version=version, namespace=namespace,
    )

    service_dir = output_dir / service
    service_dir.mkdir(parents=True, exist_ok=True)

    out_path = service_dir / f"{chart}.helm.json"
    out_path.write_text(json.dumps(doc, indent=2) + "\n")
    logger.info("Wrote Helm spec: %s", out_path)

    return out_path

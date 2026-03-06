"""CRD skill JSON output writer.

Serializes classified fields and CRD metadata into skill JSON files
matching crd-kind.schema.json and helm-chart.schema.json schemas.
Writes to catalog/skills/crd/{service}/{Kind}.json.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from idi.generation.crd.field_classifier import ClassifiedField

logger = logging.getLogger(__name__)


def _fact_ref_for_field(field: ClassifiedField) -> str:
    """Build a crdfacts:// URI for a classified field."""
    group = field.target_group or "core"
    kind = field.target_kind or "Unknown"
    # Extract the leaf field name for the fragment.
    leaf = field.field.rsplit(".", 1)[-1]
    return f"crdfacts://{group}/{kind}#{leaf}"


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


def build_crd_skill_json(
    crd_info: dict[str, Any],
    fields: list[ClassifiedField],
    status_conditions: list[str] | None = None,
) -> dict[str, Any]:
    """Build a CRD skill JSON document from CRD info and classified fields.

    Args:
        crd_info: Dict with kind, group, version, plural, scope, service, description.
        fields: Classified fields from field_classifier.
        status_conditions: Status conditions to wait for (default: ["Ready"]).

    Returns:
        Dict matching crd-kind.schema.json.
    """
    input_refs = []
    output_declarations = []
    config_fields = []

    for f in fields:
        if f.role == "input_ref" and f.target_kind:
            input_refs.append({
                "field": f.field,
                "target_kind": f.target_kind,
                "target_group": f.target_group or crd_info["group"],
                "role": "input_ref",
                "required": f.required,
                "cross_namespace": f.cross_namespace,
                "fact_ref": _fact_ref_for_field(f),
            })
        elif f.role == "output_declaration":
            output_declarations.append({
                "field": f.field,
                "produces_kind": f.target_kind or "Unknown",
                "produces_group": f.target_group or "core",
                "role": "output_declaration",
                "fact_ref": _fact_ref_for_field(f),
            })
        elif f.role == "config_field":
            entry: dict[str, Any] = {
                "field": f.field,
                "type": f.field_type,
            }
            if f.description:
                entry["description"] = f.description
            config_fields.append(entry)

    return {
        "schema_version": "1.0",
        "kind": crd_info["kind"],
        "group": crd_info["group"],
        "version": crd_info["version"],
        "plural": crd_info["plural"],
        "scope": crd_info["scope"],
        "service": crd_info["service"],
        "description": crd_info.get("description") or f"{crd_info['kind']} CRD",
        "input_refs": input_refs,
        "output_declarations": output_declarations,
        "config_fields": config_fields,
        "status_conditions": status_conditions or ["Ready"],
        "execution": {
            "method": "kubectl_apply",
            "wait_condition": "condition=Ready",
        },
    }


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


def write_crd_skill(
    crd_info: dict[str, Any],
    fields: list[ClassifiedField],
    output_dir: Path,
    status_conditions: list[str] | None = None,
) -> Path:
    """Write a CRD skill JSON file.

    Args:
        crd_info: CRD metadata dict.
        fields: Classified fields.
        output_dir: Base output directory (e.g. catalog/skills/crd).
        status_conditions: Status conditions.

    Returns:
        Path to the written JSON file.
    """
    doc = build_crd_skill_json(crd_info, fields, status_conditions)

    service_dir = output_dir / crd_info["service"]
    service_dir.mkdir(parents=True, exist_ok=True)

    out_path = service_dir / f"{crd_info['kind']}.json"
    out_path.write_text(json.dumps(doc, indent=2) + "\n")
    logger.info("Wrote CRD skill: %s", out_path)

    return out_path


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

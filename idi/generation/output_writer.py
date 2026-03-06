"""JSON output writing for the skill generation pipeline.

Handles writing the three artefact types that make up a generated skill:

- **manifest.json** -- resource-level metadata with content hash.
- **operations/*.json** -- one file per HTTP operation (create, list, etc.).
- **fields/*.json** -- one file per unique request field across all ops.

All functions take a :class:`GeneratorContext` as their first parameter
(replacing the old monolithic ``self``), keeping them stateless and testable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from idi.generation.constants import VALID_NAME_RE
from idi.generation.context import GeneratorContext
from idi.generation.field_extractor import build_heuristic_outputs
from idi.generation.utils import camel_to_snake, compute_json_content_hash

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path normalisation (with graceful fallback)
# ---------------------------------------------------------------------------

def _normalize_op_path(path: str) -> str:
    """Normalize operation path: strip .md suffix and leading/trailing slashes."""
    path = path.strip("/")
    if path.endswith(".md"):
        path = path[:-3]
    return path


try:
    from idi.common.paths import normalize_op_path as _normalize_op_path  # noqa: F811
except ImportError:
    pass  # Use local fallback defined above


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def emit_resource(
    ctx: GeneratorContext,
    base_dir: Path,
    resource_info: Dict[str, Any],
) -> None:
    """Write all skill artefacts for a single resource.

    Creates the directory structure ``base_dir/<resource>/`` containing:

    - ``manifest.json`` -- resource metadata with a content hash.
    - ``operations/<op>.json`` -- one file per operation.
    - ``fields/<field>.json`` -- one file per unique request field.

    The union of request fields is collected across *all* operations so
    that the manifest ``fields`` list and the individual field files
    represent the full resource surface area.

    Args:
        ctx: Generator context (provides ``api_name`` and heuristic
            output builder).
        base_dir: Parent directory under which the resource directory
            will be created (e.g., ``catalog/skills/api/authentik``).
        resource_info: Dict with keys ``resource`` (str), ``operations``
            (list of op dicts), and optionally ``description``,
            ``field_refs``.

    Raises:
        ValueError: If service or resource names violate the
            ``[a-z0-9_-]`` charset, or if an operation is missing
            both ``endpoint`` and ``path`` keys.
    """
    resource = resource_info["resource"]
    resource_dir = base_dir / resource
    resource_dir.mkdir(parents=True, exist_ok=True)
    ops_dir = resource_dir / "operations"
    ops_dir.mkdir(exist_ok=True)
    fields_dir = resource_dir / "fields"
    fields_dir.mkdir(exist_ok=True)

    # -- 1. Collect union of all request fields across operations ----------
    field_defs_by_name: Dict[str, dict] = {}
    all_op_infos: List[Dict[str, Any]] = []
    for op_data in resource_info["operations"]:
        all_op_infos.append(op_data["op_info"])
        for f in op_data["params"].get("request_fields", []):
            fname = camel_to_snake(f["name"])
            if fname not in field_defs_by_name:
                field_defs_by_name[fname] = f
    all_fields_sorted = sorted(field_defs_by_name.keys())

    # -- 2. Build unified field_refs_map across all operations -------------
    unified_refs_map: Dict[str, str] = {}
    for op_data in resource_info["operations"]:
        for k, v in op_data.get("field_refs_map", {}).items():
            canon_k = camel_to_snake(k)
            if canon_k not in unified_refs_map:
                unified_refs_map[canon_k] = v
    # Also derive from field_refs list (legacy FK detection format).
    for fr in resource_info.get("field_refs", []):
        field_name = camel_to_snake(fr["field"])
        fact_ref = fr.get("fact_ref")
        if not fact_ref:
            target_resource = fr.get("target_resource", "")
            if target_resource:
                fact_ref = f"facts://{ctx.api_name}/{target_resource}#id"
            else:
                continue
        if field_name not in unified_refs_map:
            unified_refs_map[field_name] = fact_ref

    # -- 3. Write manifest.json --------------------------------------------
    for label, value in [("service", ctx.api_name), ("resource", resource)]:
        if not VALID_NAME_RE.match(value):
            raise ValueError(
                f"{label} name '{value}' violates charset [a-z0-9_-].",
            )
    manifest: Dict[str, Any] = {
        "schema_version": "2.0",
        "service": ctx.api_name,
        "resource": resource,
        "description": resource_info.get("description", ""),
        "operations": sorted(
            set(op["operation"] for op in all_op_infos),
        ),
        "fields": all_fields_sorted,
        "field_refs": unified_refs_map if unified_refs_map else {},
    }
    manifest["content_hash"] = compute_json_content_hash(manifest)
    (resource_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
    )

    # -- 4. Write operations/*.json ----------------------------------------
    for op_data in resource_info["operations"]:
        op_info = op_data["op_info"]
        params = op_data["params"]
        depends_on = op_data.get("depends_on", [])
        outputs = op_data.get("outputs")
        idempotent = op_data.get("idempotent", False)
        op_field_refs = op_data.get("field_refs_map", {})

        req_fields = sorted(set(
            camel_to_snake(f["name"])
            for f in params.get("request_fields", [])
            if f.get("required")
        ))
        opt_fields = sorted(set(
            camel_to_snake(f["name"])
            for f in params.get("request_fields", [])
            if not f.get("required")
        ))

        endpoint = op_info.get("endpoint") or op_info.get("path")
        if not endpoint:
            raise ValueError("op_info missing both 'endpoint' and 'path'")

        op_path = f"{ctx.api_name}/{resource}/{op_info['operation']}"
        op_doc: Dict[str, Any] = {
            "schema_version": "2.0",
            "path": op_path,
            "method": op_info["method"],
            "endpoint": endpoint,
            "action": op_info.get("action", ""),
            "description": op_info.get("description", ""),
            "idempotent": idempotent,
            "required_fields": req_fields,
            "optional_fields": opt_fields,
        }

        # Determine outputs: explicit, empty, or heuristic fallback.
        if outputs is not None and len(outputs) > 0:
            op_doc["response_key_fields"] = sorted(set(outputs.values()))
            op_doc["outputs"] = outputs
        elif outputs is not None:
            op_doc["outputs"] = {}
        else:
            auto_outputs = build_heuristic_outputs(
                ctx, op_info, params.get("response_fields", []),
            )
            if auto_outputs:
                op_doc["response_key_fields"] = sorted(
                    set(auto_outputs.values()),
                )
                op_doc["outputs"] = auto_outputs
            else:
                op_doc["outputs"] = {}

        op_doc["requires"] = op_data.get("requires") or []

        # Build depends_on with self-reference guard.
        if depends_on:
            clean_deps: List[Dict[str, Any]] = []
            for dep in depends_on:
                dep_path = _normalize_op_path(dep.get("path", ""))
                # Self-reference guard: skip deps pointing to this operation.
                if dep_path == op_path:
                    continue
                d: Dict[str, Any] = {
                    "path": dep_path,
                    "field": dep["field"],
                    "source": dep.get("source", "field_ref"),
                }
                if dep["field"] in op_field_refs:
                    d["fact_ref"] = op_field_refs[dep["field"]]
                elif dep.get("fact_ref"):
                    d["fact_ref"] = dep["fact_ref"]
                if dep.get("lineage_type"):
                    d["lineage_type"] = dep["lineage_type"]
                if dep.get("discriminator_value"):
                    d["discriminator_value"] = dep["discriminator_value"]
                clean_deps.append(d)
            op_doc["depends_on"] = clean_deps
        else:
            op_doc["depends_on"] = []

        check_with = op_data.get("check_with")
        if check_with:
            op_doc["check_with"] = check_with

        op_file = ops_dir / f"{op_info['operation']}.json"
        op_file.write_text(json.dumps(op_doc, indent=2) + "\n")

    # -- 5. Write fields/*.json --------------------------------------------
    for fname, fdef in field_defs_by_name.items():
        emit_field(ctx, fields_dir, fdef, unified_refs_map)


def emit_field(
    ctx: GeneratorContext,
    fields_dir: Path,
    field_info: Dict[str, Any],
    field_refs_map: Dict[str, str],
) -> None:
    """Write a single ``fields/<name>.json`` file.

    The field name is normalised to snake_case.  Cardinality is inferred
    from the type string: types starting with ``'array'`` get ``'many'``,
    everything else gets ``'one'``.

    Args:
        ctx: Generator context (currently unused but kept for API
            consistency and future extension).
        fields_dir: Directory where the field JSON file will be written.
        field_info: Dict describing the field, containing at minimum
            ``name`` and optionally ``type``, ``description``,
            ``required``, ``enum_values``, ``default``, ``skip_hint``.
        field_refs_map: Mapping of snake_case field names to canonical
            ``facts://`` URIs.  If the field name is present, the URI
            is written as ``fact_ref``.
    """
    name = camel_to_snake(field_info["name"])
    ftype = field_info.get("type", "string")
    is_array = ftype.startswith("array")

    field_doc: Dict[str, Any] = {
        "name": name,
        "type": ftype,
        "description": field_info.get("description", ""),
        "optional": not field_info.get("required", False),
        "cardinality": "many" if is_array else "one",
    }

    if name in field_refs_map:
        field_doc["fact_ref"] = field_refs_map[name]

    if field_info.get("enum_values"):
        field_doc["values"] = field_info["enum_values"]

    if "default" in field_info:
        field_doc["default"] = field_info["default"]

    if field_info.get("skip_hint"):
        field_doc["skip_hint"] = field_info["skip_hint"]

    field_file = fields_dir / f"{name}.json"
    field_file.write_text(json.dumps(field_doc, indent=2) + "\n")

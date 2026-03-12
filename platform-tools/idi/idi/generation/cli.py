"""Generation orchestration and CLI entry point.

Provides the top-level :func:`generate` function that drives the full
OpenAPI-to-skill generation pipeline, and a :func:`main` CLI wrapper
that parses arguments and wires everything together.

Replaces the monolithic ``AtomicSkillGenerator.generate()`` and
``AtomicSkillGenerator._generate_json()`` methods with pure functions
that thread a :class:`GeneratorContext` through the call chain.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

from idi.generation.context import GeneratorContext
from idi.generation.dep_adapters import DepAdapterRegistry, OperationInfo as DepOpInfo
from idi.generation.dep_adapters.path_deps import detect_namespace_params
from idi.generation.field_extractor import (
    extract_request_fields,
    extract_response_fields,
)
from idi.generation.output_writer import emit_resource
from idi.generation.path_extractor import (
    extract_operation_info,
    extract_parameters,
)
from idi.generation.polymorphic import get_all_resource_names
from idi.generation.spec_loader import create_context, load_spec
from idi.generation.utils import camel_to_snake, clean_description, sanitize_name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate(ctx: GeneratorContext) -> Dict[str, int]:
    """Run the full generation pipeline over the spec in *ctx*.

    Two passes over the OpenAPI paths:

    1. **Discovery pass** -- groups operations by resource and registers
       every skill path in ``ctx.generated_skill_paths`` so that
       downstream logic (``check_with``, dangling-ref validation) can
       reference them.
    2. **Emit pass** -- delegates to :func:`_generate_json_v2` which
       builds all metadata and writes JSON artefacts.

    Paths starting with ``/openapi`` or ``/version`` are silently
    skipped.  Deprecated operations are counted in ``stats["skipped"]``.

    Args:
        ctx: Fully initialised generator context.

    Returns:
        Dict with keys ``resources``, ``skills``, ``skipped``.
    """
    paths = ctx.schema.get("paths", {})
    stats: Dict[str, int] = {"resources": 0, "skills": 0, "skipped": 0}

    print(f"API Style: {ctx.style}")
    print("Output format: json")
    print(f"Processing {len(paths)} paths...")

    # -- Pass 1: group operations by resource and track skill paths --------
    resources: Dict[str, List[Dict[str, Any]]] = {}

    for path, path_item in paths.items():
        if not path or path.startswith("/openapi") or path.startswith("/version"):
            continue

        path_params = path_item.get("parameters", [])

        for method in ("get", "post", "put", "patch", "delete"):
            if method not in path_item:
                continue

            operation = path_item[method]
            if operation.get("deprecated"):
                stats["skipped"] += 1
                continue

            op_info = extract_operation_info(ctx, path, method, operation)
            resource = sanitize_name(op_info["resource"])
            if not resource:
                resource = "default"

            if resource not in resources:
                resources[resource] = []

            resources[resource].append({
                "op_info": op_info,
                "operation": operation,
                "path_params": path_params,
            })

    # Register every skill path *before* the emit pass so check_with and
    # dangling-ref validation can look them up.
    for resource, operations in resources.items():
        for op_data in operations:
            op_type = op_data["op_info"]["operation"]
            skill_path = f"{ctx.api_name}/{resource}/{op_type}"
            ctx.generated_skill_paths[skill_path] = {
                "resource": resource,
                "operation": op_type,
                "method": op_data["op_info"]["method"],
                "endpoint": op_data["op_info"].get("endpoint", op_data["op_info"].get("path", "")),
            }

    # -- Pass 2: emit JSON artefacts ---------------------------------------
    _generate_json_v2(ctx, resources, stats)

    return stats


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Compiled once for path-parameter extraction inside _generate_json_v2.
_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")


def _get_response_schema(operation: Dict[str, Any]) -> Dict[str, Any]:
    """Extract response schema from an operation object."""
    for code in ("200", "201", "202"):
        resp = operation.get("responses", {}).get(code, {})
        schema = resp.get("content", {}).get("application/json", {}).get("schema", {})
        if schema:
            return schema
        if "schema" in resp:
            return resp["schema"]
    return {}


def _generate_json_v2(
    ctx: GeneratorContext,
    resources: Dict[str, List[Dict[str, Any]]],
    stats: Dict[str, int],
) -> None:
    """Emit JSON skill files for every resource.

    For each resource, deduplicates operations by type, extracts
    request/response fields, resolves FK references, builds dependency
    edges, and delegates to :func:`emit_resource` for filesystem
    output.

    Args:
        ctx: Fully initialised generator context.
        resources: Mapping of resource name to list of operation dicts
            (each with ``op_info``, ``operation``, ``path_params``).
        stats: Mutable stats dict -- ``resources`` and ``skills``
            counters are incremented in place.
    """
    dep_registry = DepAdapterRegistry()
    known_resources = get_all_resource_names(ctx, include_non_post=True)
    namespace_params = detect_namespace_params(ctx.schema)

    # Pre-compute canonical resource map for consistent name resolution.
    from idi.generation.dep_adapters.canonical_resources import (
        build_canonical_resource_map,
        learn_fk_suffixes,
    )
    canonical_map = build_canonical_resource_map(ctx.schema)

    # Learn FK suffix conventions from the spec's path parameters.
    fk_suffixes = learn_fk_suffixes(ctx.schema, canonical_map)

    # Pre-compute identifier index for identifier reference validation.
    from idi.generation.dep_adapters.verify import build_identifier_index
    identifier_index = build_identifier_index(ctx.schema, ctx.generated_skill_paths, fk_suffixes=fk_suffixes)

    for resource, operations in resources.items():
        seen: set = set()
        v2_operations: List[Dict[str, Any]] = []
        all_field_refs: List[Dict[str, Any]] = []
        resource_description = ""

        for op_data in operations:
            op_info = op_data["op_info"]
            op_type = op_info["operation"]

            # Deduplicate: keep only the first occurrence of each op type.
            if op_type in seen:
                continue
            seen.add(op_type)

            operation_obj = op_data["operation"]

            # -- Extract request and response fields -----------------------
            request_fields = extract_request_fields(ctx, op_info, operation_obj)
            response_fields = extract_response_fields(
                ctx, operation_obj,
                path=op_info.get("path"),
                method=op_info.get("method"),
            )

            # -- Detect dependencies via adapter registry --------------------
            params_raw = extract_parameters(ctx, operation_obj, op_data["path_params"])
            body_schema = {}
            if params_raw.get("body"):
                body_schema = params_raw["body"].get("schema", {})

            api_path = op_info.get("path", "")
            endpoint = op_info.get("endpoint") or api_path

            # Extract path param schemas (OAS3: param.schema, Swagger2: inline)
            path_param_schemas: dict[str, dict] = {}
            all_params = (op_data.get("path_params") or []) + operation_obj.get("parameters", [])
            for p in all_params:
                if p.get("in") == "path" and "name" in p:
                    path_param_schemas[p["name"]] = p.get("schema", p)

            dep_op = DepOpInfo(
                service=ctx.api_name,
                resource=resource,
                operation=op_type,
                path=api_path,
                method=op_info["method"],
                body_schema=body_schema,
                response_schema=_get_response_schema(operation_obj),
                path_params=_PATH_PARAM_RE.findall(endpoint),
                query_params=params_raw.get("query", []),
                path_param_schemas=path_param_schemas,
                namespace_params=namespace_params,
            )

            deps_detected, outputs_detected = dep_registry.detect(
                dep_op, ctx.schema, known_resources,
                skill_paths=ctx.generated_skill_paths,
                identifier_index=identifier_index,
                canonical_map=canonical_map,
                fk_suffixes=fk_suffixes,
            )

            depends_on: List[Dict[str, Any]] = []
            validated_deps: list = []
            for d in deps_detected:
                dep_path = f"{d.target_service or ctx.api_name}/{d.target_resource}/{d.target_operation}"
                # Cross-service deps bypass validation (can't check other services)
                if not d.target_service and dep_path not in ctx.generated_skill_paths:
                    logger.debug("Dropping phantom target: %s (field=%s)", dep_path, d.field)
                    continue
                validated_deps.append(d)
                depends_on.append({
                    "path": dep_path,
                    "source": d.source,
                    "field": d.field,
                    "type": "unknown",
                    "fact_ref": d.fact_ref,
                    "lineage_type": d.lineage_type,
                    "discriminator_value": d.discriminator_value,
                    "detection_source": d.detection_source.value,
                    "confidence": d.confidence,
                })

            # Build field_refs_map and all_field_refs from validated deps only.
            field_refs_map: Dict[str, str] = {}
            for d in validated_deps:
                fn = camel_to_snake(d.field)
                if d.fact_ref and fn not in field_refs_map:
                    field_refs_map[fn] = d.fact_ref

            all_field_refs.extend(
                {"field": d.field, "target_resource": d.target_resource, "fact_ref": d.fact_ref}
                for d in validated_deps
            )

            # -- Add path parameters as request fields ---------------------
            endpoint = op_info.get("endpoint") or op_info.get("path", "")
            path_param_names = _PATH_PARAM_RE.findall(endpoint)
            for param_name in path_param_names:
                param_type = "string"
                for pp in op_data.get("path_params", []):
                    if pp.get("name") == param_name:
                        param_type = pp.get("schema", {}).get(
                            "type", pp.get("type", "string"),
                        )
                        break
                request_fields.append({
                    "name": param_name,
                    "type": param_type,
                    "required": True,
                    "description": f"Path parameter: {param_name}",
                    "source": "path_param",
                })

            # -- Idempotency and check_with --------------------------------
            idempotent = op_info["method"] in ("GET", "PUT", "DELETE", "PATCH")

            check_with = None
            if op_type == "create":
                list_path = f"{ctx.api_name}/{resource}/list"
                if list_path in ctx.generated_skill_paths:
                    check_with = {"operation": "list", "match_field": "name"}

            # -- Description -----------------------------------------------
            desc = clean_description(
                operation_obj.get(
                    "description",
                    operation_obj.get("summary", f"{op_type} {resource}"),
                ),
            )
            if not resource_description:
                resource_description = desc

            # -- Adapter-based output extraction ---------------------------
            outputs_from_adapter = None
            if op_type in ("create", "update", "replace", "retrieve", "list"):
                responses = operation_obj.get("responses", {})
                response_schema = None
                for code in ("200", "201", "202"):
                    if code in responses:
                        resp = responses[code]
                        if "content" in resp:
                            content = resp.get("content", {})
                            json_content = content.get(
                                "application/json",
                                content.get("*/*", {}),
                            )
                            response_schema = json_content.get("schema", {})
                        elif "schema" in resp:
                            response_schema = resp["schema"]
                        if response_schema:
                            break

                if (
                    response_schema
                    and ctx.adapter is not None
                    and hasattr(ctx.adapter, "extract_outputs")
                ):
                    try:
                        adapter_outputs = ctx.adapter.extract_outputs(
                            response_schema, resource, op_type,
                        )
                        if adapter_outputs:
                            outputs_from_adapter = {}
                            for fact in adapter_outputs:
                                if hasattr(fact, "ref") and hasattr(fact, "response_field"):
                                    outputs_from_adapter[fact.ref.to_uri()] = fact.response_field
                                elif isinstance(fact, dict):
                                    outputs_from_adapter.update(fact)
                    except Exception:  # noqa: BLE001
                        pass

            # -- Collect into v2 operation list ----------------------------
            v2_operations.append({
                "op_info": op_info,
                "params": {
                    "request_fields": request_fields,
                    "response_fields": response_fields,
                },
                "depends_on": depends_on,
                "outputs": outputs_from_adapter,
                "idempotent": idempotent,
                "field_refs_map": field_refs_map,
                "check_with": check_with,
            })
            stats["skills"] += 1

        # -- Emit resource artefacts ---------------------------------------
        resource_info = {
            "resource": resource,
            "description": resource_description,
            "operations": v2_operations,
            "field_refs": all_field_refs,
        }
        emit_resource(ctx, ctx.output_dir, resource_info)
        stats["resources"] += 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _infer_api_name(spec: Dict[str, Any]) -> str:
    """Infer API name from spec title or first path segment.

    Tries the spec ``info.title`` first, falling back to the first
    non-parameter segment of the first path.

    Args:
        spec: Parsed OpenAPI specification dict.

    Returns:
        Sanitised API name string, or ``'api'`` as last resort.
    """
    info = spec.get("info", {})
    title = info.get("title", "")
    if title:
        return sanitize_name(title)

    paths = spec.get("paths", {})
    if paths:
        first_path = next(iter(paths))
        segments = [
            s for s in first_path.strip("/").split("/")
            if s and not s.startswith("{")
        ]
        if segments:
            return sanitize_name(segments[0])

    return "api"


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the skill generator.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Parsed :class:`argparse.Namespace`.
    """
    parser = argparse.ArgumentParser(
        description="Generate atomic skills from OpenAPI schemas (JSON format)",
    )
    parser.add_argument("--schema", "-s", required=True, help="OpenAPI schema path/URL")
    parser.add_argument("--output", "-o", required=True, help="Output directory")
    parser.add_argument("--name", "-n", help="API name")
    parser.add_argument(
        "--style",
        choices=["auto", "aws", "kubernetes", "rest", "cloudflare", "vault"],
        default="auto",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> None:
    """CLI entry point for skill generation.

    Parses arguments, loads the OpenAPI spec, creates a
    :class:`GeneratorContext`, and runs the generation pipeline.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).
    """
    args = parse_args(argv)

    print("=" * 60)
    print("  IDI Atomic Skill Generator")
    print("=" * 60)

    ctx = create_context(
        schema_path=args.schema,
        output_dir=args.output,
        api_name=args.name,
        style=args.style,
    )

    if args.dry_run:
        paths = ctx.schema.get("paths", {})
        print(f"[DRY-RUN] Service: {ctx.api_name}")
        print(f"[DRY-RUN] Style:   {ctx.style}")
        print(f"[DRY-RUN] Paths:   {len(paths)}")
        print(f"[DRY-RUN] Output:  {ctx.output_dir}")
        return

    stats = generate(ctx)

    print(f"\nGeneration complete:")
    print(f"  Resources: {stats['resources']}")
    print(f"  Skills:    {stats['skills']}")
    print(f"  Skipped:   {stats['skipped']}")

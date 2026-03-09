"""Fetch CRD JSON Schemas from datreeio/CRDs-catalog and wrap as OpenAPI.

Downloads pre-extracted JSON Schema files from the `datreeio/CRDs-catalog
<https://github.com/datreeio/CRDs-catalog>`__ GitHub repository and
assembles them into a full OpenAPI 3.0.3 spec with generated CRUD paths.

All functions are stateless module-level callables -- no ``self``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DATREEIO_BASE = "https://raw.githubusercontent.com/datreeio/CRDs-catalog/main"

OBJECTMETA_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "Standard Kubernetes object metadata",
    "properties": {
        "name": {"type": "string", "description": "Resource name"},
        "namespace": {"type": "string", "description": "Resource namespace"},
        "uid": {"type": "string", "description": "Unique resource identifier"},
        "resourceVersion": {
            "type": "string",
            "description": "Resource version for optimistic concurrency",
        },
        "creationTimestamp": {
            "type": "string",
            "format": "date-time",
            "description": "Creation timestamp",
        },
        "labels": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Map of labels",
        },
        "annotations": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Map of annotations",
        },
    },
}

LISTMETA_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "Standard Kubernetes list metadata",
    "properties": {
        "continue": {"type": "string"},
        "resourceVersion": {"type": "string"},
    },
}


# ---------------------------------------------------------------------------
# Schema fetching and cleaning
# ---------------------------------------------------------------------------


def fetch_crd_schema(
    group: str,
    stem: str,
    timeout: int = 30,
) -> Optional[Dict[str, Any]]:
    """Download a single JSON Schema from datreeio CRDs-catalog.

    Args:
        group: CRD API group (e.g. ``cert-manager.io``).
        stem: Filename stem (e.g. ``certificate_v1``).
        timeout: HTTP request timeout in seconds.

    Returns:
        Parsed JSON Schema dict, or ``None`` on failure.
    """
    url = f"{DATREEIO_BASE}/{group}/{stem}.json"
    try:
        req = Request(url, headers={"User-Agent": "IDI-SkillGenerator/1.0"})
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read())
    except (URLError, json.JSONDecodeError) as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


def clean_schema(schema: Any) -> Any:
    """Remove ``x-kubernetes-*`` extensions from a CRD JSON Schema.

    Converts ``x-kubernetes-preserve-unknown-fields: true`` to
    ``additionalProperties: true``. Recurses into nested properties.

    Args:
        schema: A JSON Schema dict (or non-dict passthrough).

    Returns:
        Cleaned schema with Kubernetes extensions removed.
    """
    if not isinstance(schema, dict):
        return schema

    cleaned: Dict[str, Any] = {}
    for key, value in schema.items():
        if key == "x-kubernetes-preserve-unknown-fields" and value:
            cleaned["additionalProperties"] = True
            continue
        if key.startswith("x-kubernetes-"):
            continue
        if key in ("properties", "patternProperties") and isinstance(value, dict):
            cleaned[key] = {k: clean_schema(v) for k, v in value.items()}
        elif key in ("items", "additionalProperties") and isinstance(value, dict):
            cleaned[key] = clean_schema(value)
        elif key in ("allOf", "oneOf", "anyOf") and isinstance(value, list):
            cleaned[key] = [clean_schema(v) for v in value]
        else:
            cleaned[key] = value

    return cleaned


# ---------------------------------------------------------------------------
# Path generation
# ---------------------------------------------------------------------------


def build_crd_paths(
    group: str,
    version: str,
    plural: str,
    kind: str,
    namespaced: bool,
    schema_ref: str,
) -> Dict[str, Any]:
    """Generate Kubernetes CRUD paths for a single CRD resource.

    Generates:
    - Cluster-scoped list (all namespaces) for namespaced resources
    - Namespaced (or cluster-scoped) list + create
    - Single resource: get, put, patch, delete
    - ``/status`` subresource: get, put, patch

    Args:
        group: API group (e.g. ``cert-manager.io``).
        version: API version (e.g. ``v1``).
        plural: Plural resource name (e.g. ``certificates``).
        kind: Kind name (e.g. ``Certificate``).
        namespaced: Whether the resource is namespace-scoped.
        schema_ref: JSON Pointer to the schema (e.g.
            ``#/components/schemas/Certificate``).

    Returns:
        Dict mapping path strings to their method definitions.
    """
    paths: Dict[str, Any] = {}
    tag = kind

    if namespaced:
        base = f"/apis/{group}/{version}/namespaces/{{namespace}}/{plural}"
        item = f"{base}/{{name}}"
        cluster_list = f"/apis/{group}/{version}/{plural}"
    else:
        base = f"/apis/{group}/{version}/{plural}"
        item = f"{base}/{{name}}"
        cluster_list = None

    ns_param = {
        "name": "namespace", "in": "path", "required": True,
        "schema": {"type": "string"}, "description": "Kubernetes namespace",
    }
    name_param = {
        "name": "name", "in": "path", "required": True,
        "schema": {"type": "string"}, "description": "Resource name",
    }
    list_query_params = [
        {"name": "limit", "in": "query", "schema": {"type": "integer"},
         "description": "Max items to return"},
        {"name": "continue", "in": "query", "schema": {"type": "string"},
         "description": "Pagination token"},
        {"name": "labelSelector", "in": "query", "schema": {"type": "string"},
         "description": "Label selector"},
        {"name": "fieldSelector", "in": "query", "schema": {"type": "string"},
         "description": "Field selector"},
    ]
    list_response = {"200": {"description": f"List of {kind}", "content": {
        "application/json": {"schema": {
            "type": "object",
            "properties": {
                "apiVersion": {"type": "string"},
                "kind": {"type": "string"},
                "metadata": {"$ref": "#/components/schemas/ListMeta"},
                "items": {"type": "array", "items": {"$ref": schema_ref}},
            },
        }},
    }}}

    list_params: List[Dict[str, Any]] = []
    if namespaced:
        list_params.append(ns_param)
    list_params.extend(list_query_params)

    item_params: List[Dict[str, Any]] = []
    if namespaced:
        item_params.append(ns_param)
    item_params.append(name_param)

    # Cluster-scoped list (all namespaces) for namespaced resources
    if cluster_list:
        paths[cluster_list] = {
            "get": {
                "tags": [tag],
                "operationId": f"listAll{kind}",
                "summary": f"List {kind} across all namespaces",
                "parameters": list_query_params,
                "responses": list_response,
            },
        }

    # List + Create
    paths[base] = {
        "get": {
            "tags": [tag],
            "operationId": f"list{kind}",
            "summary": f"List {kind} resources",
            "parameters": list_params,
            "responses": list_response,
        },
        "post": {
            "tags": [tag],
            "operationId": f"create{kind}",
            "summary": f"Create a {kind}",
            "parameters": [ns_param] if namespaced else [],
            "requestBody": {"required": True, "content": {
                "application/json": {"schema": {"$ref": schema_ref}},
            }},
            "responses": {"201": {"description": f"Created {kind}", "content": {
                "application/json": {"schema": {"$ref": schema_ref}},
            }}},
        },
    }

    # Get / Update / Patch / Delete
    paths[item] = {
        "get": {
            "tags": [tag],
            "operationId": f"read{kind}",
            "summary": f"Read a {kind}",
            "parameters": item_params,
            "responses": {"200": {"description": f"{kind} details", "content": {
                "application/json": {"schema": {"$ref": schema_ref}},
            }}},
        },
        "put": {
            "tags": [tag],
            "operationId": f"replace{kind}",
            "summary": f"Replace a {kind}",
            "parameters": item_params,
            "requestBody": {"required": True, "content": {
                "application/json": {"schema": {"$ref": schema_ref}},
            }},
            "responses": {"200": {"description": f"Updated {kind}", "content": {
                "application/json": {"schema": {"$ref": schema_ref}},
            }}},
        },
        "patch": {
            "tags": [tag],
            "operationId": f"patch{kind}",
            "summary": f"Patch a {kind}",
            "parameters": item_params,
            "requestBody": {"required": True, "content": {
                "application/merge-patch+json": {"schema": {"$ref": schema_ref}},
            }},
            "responses": {"200": {"description": f"Patched {kind}", "content": {
                "application/json": {"schema": {"$ref": schema_ref}},
            }}},
        },
        "delete": {
            "tags": [tag],
            "operationId": f"delete{kind}",
            "summary": f"Delete a {kind}",
            "parameters": item_params,
            "responses": {"200": {"description": f"Deleted {kind}"}},
        },
    }

    # Status subresource
    status_path = f"{item}/status"
    paths[status_path] = {
        "get": {
            "tags": [tag],
            "operationId": f"read{kind}Status",
            "summary": f"Read {kind} status",
            "parameters": item_params,
            "responses": {"200": {"description": f"{kind} status", "content": {
                "application/json": {"schema": {"$ref": schema_ref}},
            }}},
        },
        "put": {
            "tags": [tag],
            "operationId": f"replace{kind}Status",
            "summary": f"Replace {kind} status",
            "parameters": item_params,
            "requestBody": {"required": True, "content": {
                "application/json": {"schema": {"$ref": schema_ref}},
            }},
            "responses": {"200": {"description": f"Updated {kind} status", "content": {
                "application/json": {"schema": {"$ref": schema_ref}},
            }}},
        },
        "patch": {
            "tags": [tag],
            "operationId": f"patch{kind}Status",
            "summary": f"Patch {kind} status",
            "parameters": item_params,
            "requestBody": {"required": True, "content": {
                "application/merge-patch+json": {"schema": {"$ref": schema_ref}},
            }},
            "responses": {"200": {"description": f"Patched {kind} status", "content": {
                "application/json": {"schema": {"$ref": schema_ref}},
            }}},
        },
    }

    return paths


# ---------------------------------------------------------------------------
# Spec assembly
# ---------------------------------------------------------------------------


def build_openapi_from_datreeio(
    service_name: str,
    groups_config: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Fetch CRD schemas from datreeio and assemble an OpenAPI 3.0.3 spec.

    For each kind in *groups_config*, downloads the JSON Schema from
    datreeio, cleans it, injects an ObjectMeta ``$ref`` into the
    ``metadata`` property, generates CRUD paths, and assembles the
    final spec.

    Args:
        service_name: Service name for the spec title.
        groups_config: List of group config dicts, each with ``group``,
            ``version``, and ``kinds`` (list of dicts with ``stem``,
            ``kind``, ``plural``, ``namespaced``).

    Returns:
        Complete OpenAPI 3.0.3 spec dict.
    """
    all_paths: Dict[str, Any] = {}
    all_schemas: Dict[str, Any] = {}
    all_tags: List[Dict[str, str]] = []
    all_groups: set = set()

    for group_config in groups_config:
        group = group_config["group"]
        version = group_config["version"]
        all_groups.add(group)

        for kind_cfg in group_config["kinds"]:
            stem = kind_cfg["stem"]
            kind = kind_cfg["kind"]
            plural = kind_cfg["plural"]
            namespaced = kind_cfg["namespaced"]

            # Version in filename may differ from group default
            file_parts = stem.rsplit("_", 1)
            file_version = file_parts[1] if len(file_parts) == 2 else version

            schema = fetch_crd_schema(group, stem)
            if schema is None:
                continue

            cleaned = clean_schema(schema)
            if "description" not in cleaned:
                cleaned["description"] = (
                    f"{kind} custom resource ({group}/{file_version})"
                )

            # Inject ObjectMeta $ref so metadata resolves to our stub
            props = cleaned.get("properties", {})
            if "metadata" in props:
                props["metadata"] = {"$ref": "#/components/schemas/ObjectMeta"}

            all_schemas[kind] = cleaned
            schema_ref = f"#/components/schemas/{kind}"

            resource_paths = build_crd_paths(
                group, file_version, plural, kind, namespaced, schema_ref,
            )
            all_paths.update(resource_paths)
            all_tags.append({
                "name": kind,
                "description": f"{kind} ({group}/{file_version})",
            })

    # Standard K8s metadata schemas
    all_schemas["ObjectMeta"] = OBJECTMETA_SCHEMA
    all_schemas["ListMeta"] = LISTMETA_SCHEMA

    primary_group = sorted(all_groups)[0] if all_groups else service_name
    return {
        "openapi": "3.0.3",
        "info": {
            "title": f"{primary_group} API",
            "version": "1.0.0",
            "description": (
                f"OpenAPI spec generated from datreeio CRDs-catalog"
                f" ({', '.join(sorted(all_groups))})"
                if all_groups
                else f"OpenAPI spec for {service_name} (no schemas fetched)"
            ),
        },
        "paths": all_paths,
        "components": {"schemas": all_schemas},
        "tags": all_tags,
    }


# ---------------------------------------------------------------------------
# Entry point for download_specs.py
# ---------------------------------------------------------------------------


def convert_crd_service(
    service_name: str,
    config: Dict[str, Any],
    output_path: Path,
) -> bool:
    """Download CRD schemas from datreeio and write as an OpenAPI spec.

    Convenience entry point called by ``download_specs.download_all()``
    for services with ``source_type: crd`` or ``artifacthub``.

    Args:
        service_name: Service name (used as spec title fallback).
        config: Service config dict from the manifest (must contain
            ``crd_kinds``).
        output_path: Where to write the generated OpenAPI JSON file.

    Returns:
        ``True`` on success, ``False`` if ``crd_kinds`` is missing.
    """
    groups_config = config.get("crd_kinds")
    if not groups_config:
        logger.warning("No crd_kinds defined for %s", service_name)
        return False

    spec = build_openapi_from_datreeio(service_name, groups_config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(spec, indent=2), encoding="utf-8",
    )
    logger.info(
        "Wrote %s (%d paths, %d schemas)",
        output_path, len(spec["paths"]),
        len(spec["components"]["schemas"]),
    )
    return True

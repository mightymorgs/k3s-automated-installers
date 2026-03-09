"""Path and operation extraction for the skill generation pipeline.

Extracts operation metadata (resource name, operation type, HTTP method,
parameters) from OpenAPI paths for REST, AWS, and Kubernetes API styles.
Each extractor returns a normalised dict that downstream modules use for
skill file generation.

All functions are stateless module-level callables that accept a
:class:`GeneratorContext` (or raw dicts) instead of ``self``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from idi.generation.constants import K8S_WAIT_STRATEGIES, OPERATION_MAP
from idi.generation.context import GeneratorContext
from idi.generation.resource_namer import build_resource_name
from idi.generation.utils import clean_description


# ---------------------------------------------------------------------------
# REST extraction
# ---------------------------------------------------------------------------


def extract_rest_operation(
    ctx: GeneratorContext,
    path: str,
    method: str,
    operation: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract operation metadata from a standard REST API path.

    Determines the resource name (using disambiguation), operation type
    (create/retrieve/list/update/delete), and version from the OpenAPI
    spec's ``info.version``.

    Args:
        ctx: Generator context containing the parsed schema.
        path: REST API path (e.g., ``'/api/v3/core/applications/{id}'``).
        method: HTTP method (e.g., ``'get'``, ``'post'``).
        operation: OpenAPI operation dict for this path+method.

    Returns:
        Dict with keys: ``action``, ``resource``, ``operation``,
        ``method``, ``path``, ``namespaced``, ``api_group``,
        ``api_version``.
    """
    resource = build_resource_name(ctx, path)

    op_type = OPERATION_MAP.get(method.lower(), method.lower())
    is_list = method.lower() == "get" and not path.endswith("}")
    if is_list:
        op_type = "list"

    return {
        "action": operation.get("operationId", f"{method}_{resource}"),
        "resource": resource,
        "operation": op_type,
        "method": method.upper(),
        "path": path,
        "namespaced": False,
        "api_group": "",
        "api_version": ctx.schema.get("info", {}).get("version", ""),
    }


# ---------------------------------------------------------------------------
# AWS extraction
# ---------------------------------------------------------------------------


def _action_to_resource(action: str) -> str:
    """Convert an AWS action name to a resource name.

    Strips common verb prefixes (``Create``, ``Delete``, ``Describe``, ...)
    and converts the remaining CamelCase to lowercase-with-dashes.

    Args:
        action: AWS action name (e.g., ``'RunInstances'``).

    Returns:
        Lowercase-dashed resource name (e.g., ``'instances'``).
    """
    prefixes = [
        "Create", "Delete", "Describe", "List", "Get", "Put", "Update",
        "Modify", "Register", "Deregister", "Start", "Stop", "Run",
        "Terminate", "Add", "Remove", "Set", "Enable", "Disable",
        "Attach", "Detach", "Associate", "Disassociate", "Cancel",
        "Accept", "Reject", "Import", "Export", "Copy", "Move",
        "Allocate", "Release", "Assign", "Unassign", "Authorize",
        "Revoke", "Apply", "Reboot", "Bundle", "Confirm", "Monitor",
        "Unmonitor", "Reset", "Restore", "Search", "Send", "Verify",
        "Provision", "Deprovision", "Purchase", "Request", "Replace",
        "Report", "Withdraw", "Advertise",
    ]

    resource = action
    for prefix in prefixes:
        if resource.startswith(prefix):
            resource = resource[len(prefix):]
            break

    # Convert CamelCase to lowercase-with-dashes.
    resource = re.sub(r"(?<!^)(?=[A-Z])", "-", resource).lower()
    return resource.strip("-") or action.lower()


def extract_aws_operation(
    ctx: GeneratorContext,
    path: str,
    method: str,
    operation: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract operation metadata from an AWS-style API path.

    AWS APIs encode the action in the path query string
    (e.g., ``/?Action=RunInstances``).  The operation type is inferred
    from the action name prefix.

    Args:
        ctx: Generator context containing the parsed schema.
        path: AWS API path (e.g., ``'/?Action=RunInstances'``).
        method: HTTP method (e.g., ``'post'``).
        operation: OpenAPI operation dict for this path+method.

    Returns:
        Dict with keys: ``action``, ``resource``, ``operation``,
        ``method``, ``path``, ``namespaced``, ``api_group``,
        ``api_version``.
    """
    action_match = re.search(r"Action=([A-Za-z0-9]+)", path)
    if action_match:
        action_name = action_match.group(1)
    else:
        action_name = operation.get("operationId", "unknown")

    # Determine operation type from action name.
    action_lower = action_name.lower()
    if action_lower.startswith(
        ("create", "put", "add", "register", "run", "start", "launch"),
    ):
        op_type = "create"
    elif action_lower.startswith(
        ("delete", "remove", "deregister", "terminate", "cancel"),
    ):
        op_type = "delete"
    elif action_lower.startswith(("update", "modify", "change", "set")):
        op_type = "update"
    elif action_lower.startswith(("get", "describe", "list", "search", "query")):
        op_type = "retrieve"
    else:
        op_type = OPERATION_MAP.get(method.lower(), "execute")

    resource_name = _action_to_resource(action_name)

    return {
        "action": action_name,
        "resource": resource_name,
        "operation": op_type,
        "method": method.upper(),
        "path": path,
        "namespaced": False,
        "api_group": ctx.api_name,
        "api_version": ctx.schema.get("info", {}).get("version", ""),
    }


# ---------------------------------------------------------------------------
# Kubernetes extraction
# ---------------------------------------------------------------------------


def resource_to_kind(resource: str) -> str:
    """Convert a Kubernetes resource name to its Kind.

    Uses a built-in mapping for well-known resources and falls back to
    a heuristic title-case + deplural for unknown resources.

    Args:
        resource: Lowercase plural resource name
            (e.g., ``'deployments'``, ``'pods'``).

    Returns:
        PascalCase Kind string (e.g., ``'Deployment'``, ``'Pod'``).
    """
    kind_map = {
        "deployments": "Deployment",
        "statefulsets": "StatefulSet",
        "daemonsets": "DaemonSet",
        "replicasets": "ReplicaSet",
        "pods": "Pod",
        "services": "Service",
        "configmaps": "ConfigMap",
        "secrets": "Secret",
        "ingresses": "Ingress",
        "jobs": "Job",
        "cronjobs": "CronJob",
        "persistentvolumeclaims": "PersistentVolumeClaim",
        "persistentvolumes": "PersistentVolume",
        "namespaces": "Namespace",
        "nodes": "Node",
        "serviceaccounts": "ServiceAccount",
        "roles": "Role",
        "rolebindings": "RoleBinding",
        "clusterroles": "ClusterRole",
        "clusterrolebindings": "ClusterRoleBinding",
    }
    if resource.lower() in kind_map:
        return kind_map[resource.lower()]

    # Heuristic fallback: title-case and strip trailing 's'.
    titled = resource.title()
    if titled.endswith("s"):
        titled = titled[:-1]
    return titled


def extract_k8s_metadata(path: str, operation: str) -> Optional[Dict[str, Any]]:
    """Extract Kubernetes-specific metadata from an API path.

    Parses the path to determine the resource Kind, API version,
    whether the resource is namespaced, and the appropriate wait
    strategy.

    Args:
        path: Kubernetes API path
            (e.g., ``'/apis/apps/v1/namespaces/{namespace}/deployments'``).
        operation: Operation type string (e.g., ``'create'``, ``'list'``).

    Returns:
        Dict with keys ``kind``, ``api_version``, ``namespaced``,
        ``wait_strategy``, ``wait_condition``, ``wait_field``,
        ``wait_timeout``.  Returns ``None`` if the path cannot be parsed.
    """
    parts = path.strip("/").split("/")

    # Determine api_version.
    if parts[0] == "api" and len(parts) >= 2:
        api_version = parts[1]  # e.g., "v1"
    elif parts[0] == "apis" and len(parts) >= 3:
        api_version = f"{parts[1]}/{parts[2]}"  # e.g., "apps/v1"
    else:
        return None

    # Determine if namespaced.
    namespaced = "namespaces" in parts

    # Get resource name (last part, may have {name} suffix).
    resource_name = parts[-1].replace("{", "").replace("}", "")
    if resource_name == "name":
        resource_name = parts[-2]

    # Map resource to kind.
    kind = resource_to_kind(resource_name)

    # Get wait strategy.
    wait_info = K8S_WAIT_STRATEGIES.get(kind, {
        "strategy": "none",
        "timeout": 0,
    })

    return {
        "kind": kind,
        "api_version": api_version,
        "namespaced": namespaced,
        "wait_strategy": wait_info["strategy"],
        "wait_condition": wait_info.get("condition"),
        "wait_field": wait_info.get("field"),
        "wait_timeout": wait_info["timeout"],
    }


def extract_k8s_operation(
    ctx: GeneratorContext,
    path: str,
    method: str,
    operation: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract operation metadata from a Kubernetes-style API path.

    Parses paths like ``/apis/apps/v1/namespaces/{namespace}/deployments``
    to determine the resource name, API group/version, whether the
    resource is namespaced, and the operation type.

    Args:
        ctx: Generator context (unused directly, but kept for interface
            consistency with the other extractors).
        path: Kubernetes API path.
        method: HTTP method (e.g., ``'get'``, ``'post'``).
        operation: OpenAPI operation dict for this path+method.

    Returns:
        Dict with keys: ``action``, ``resource``, ``operation``,
        ``method``, ``path``, ``namespaced``, ``api_group``,
        ``api_version``.
    """
    parts = path.strip("/").split("/")

    # Find resource name.
    resource_parts = [p for p in parts if not p.startswith("{")]
    resource = resource_parts[-1] if resource_parts else "resource"

    # Check namespaced.
    namespaced = "{namespace}" in path or "namespaces" in parts

    # API group and version.
    api_group = ""
    api_version = ""
    if "apis" in parts:
        idx = parts.index("apis")
        if idx + 1 < len(parts):
            api_group = parts[idx + 1]
        if idx + 2 < len(parts):
            api_version = parts[idx + 2]
    elif "api" in parts:
        idx = parts.index("api")
        if idx + 1 < len(parts):
            api_version = parts[idx + 1]
            api_group = "core"

    # Operation type.
    op_type = OPERATION_MAP.get(method.lower(), method.lower())
    is_list = (
        method.lower() == "get"
        and not path.endswith("}")
        and not any(path.endswith(f"/{x}") for x in ["status", "scale", "log"])
    )
    if is_list:
        op_type = "list"

    return {
        "action": operation.get("operationId", f"{method}_{resource}"),
        "resource": resource,
        "operation": op_type,
        "method": method.upper(),
        "path": path,
        "namespaced": namespaced,
        "api_group": api_group,
        "api_version": api_version,
    }


# ---------------------------------------------------------------------------
# Dispatch and parameter extraction
# ---------------------------------------------------------------------------


def extract_operation_info(
    ctx: GeneratorContext,
    path: str,
    method: str,
    operation: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract operation metadata, dispatching to the correct style extractor.

    Routes to :func:`extract_aws_operation`,
    :func:`extract_k8s_operation`, or :func:`extract_rest_operation`
    based on ``ctx.style``.

    After extraction, two post-processing steps are applied:

    1. An ``endpoint`` alias is set (equal to ``path``) so the JSON
       emitter can read either key.
    2. A ``description`` is extracted from the OpenAPI operation's
       ``summary``, ``description``, or ``operationId`` (in that
       preference order).

    Args:
        ctx: Generator context with ``style`` indicating the API type.
        path: API path string.
        method: HTTP method string.
        operation: OpenAPI operation dict for this path+method.

    Returns:
        Normalised operation metadata dict with ``endpoint`` and
        ``description`` keys added.
    """
    if ctx.style == "aws":
        result = extract_aws_operation(ctx, path, method, operation)
    elif ctx.style == "kubernetes":
        result = extract_k8s_operation(ctx, path, method, operation)
    else:
        result = extract_rest_operation(ctx, path, method, operation)

    # Dual-write: alias 'endpoint' for the JSON emitter.
    result["endpoint"] = result["path"]

    # Extract description from the OpenAPI operation spec.
    # Prefer summary (short, one-line) over description (potentially long).
    # Fall back to humanised operationId if neither exists.
    op_description = ""
    if operation.get("summary"):
        op_description = operation["summary"]
    elif operation.get("description"):
        op_description = operation["description"]
    elif operation.get("operationId"):
        op_description = operation["operationId"].replace("_", " ").title()
    result["description"] = clean_description(op_description)

    return result


def extract_parameters(
    ctx: GeneratorContext,
    operation: Dict[str, Any],
    path_params: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Extract parameters from an OpenAPI operation.

    Collects path parameters, query parameters, and the request body
    from the operation dict.  Handles OpenAPI 3.0 ``requestBody``,
    Swagger 2.0 ``in: body`` parameters, and Swagger 2.0 ``in: formData``
    parameters (synthesised into a body schema).

    Args:
        ctx: Generator context (used for ``$ref`` resolution against
            ``ctx.schema``).
        operation: OpenAPI operation dict containing ``parameters``
            and/or ``requestBody``.
        path_params: Optional list of path-level parameter dicts to
            merge with the operation's own parameters.

    Returns:
        Dict with keys ``path`` (list), ``query`` (list), and ``body``
        (dict or ``None``).
    """
    params: Dict[str, Any] = {"path": [], "query": [], "body": None}

    all_params = (path_params or []) + operation.get("parameters", [])

    for param in all_params:
        param_info = {
            "name": param.get("name", ""),
            "type": param.get("schema", {}).get("type", param.get("type", "string")),
            "required": param.get("required", False),
            "description": clean_description(
                param.get("description", ""),
            )[:100],
        }

        if param.get("in") == "path":
            param_info["required"] = True
            params["path"].append(param_info)
        elif param.get("in") == "query":
            params["query"].append(param_info)

    # Request body -- OpenAPI 3.0 style.
    request_body = operation.get("requestBody", {})
    if request_body:
        content = request_body.get("content", {})
        json_content = content.get(
            "application/json",
            content.get("application/x-www-form-urlencoded", {}),
        )
        schema = json_content.get("schema", {})

        params["body"] = {
            "required": request_body.get("required", False),
            "schema": schema,
        }

    # Swagger 2.0 fallback: body parameter with in=body.
    if not params["body"]:
        for param in all_params:
            if param.get("in") == "body":
                schema = param.get("schema", {})
                params["body"] = {
                    "required": param.get("required", False),
                    "schema": schema,
                }
                break

    # Swagger 2.0 formData parameters (e.g., Slack API).
    # Synthesise a body schema from individual formData params.
    if not params["body"]:
        form_data_params = [p for p in all_params if p.get("in") == "formData"]
        if form_data_params:
            body_schema: Dict[str, Any] = {
                "type": "object",
                "properties": {},
                "required": [],
            }
            for param in form_data_params:
                param_name = param.get("name", "")
                body_schema["properties"][param_name] = {
                    "type": param.get("type", "string"),
                    "description": param.get("description", ""),
                }
                if param.get("required"):
                    body_schema["required"].append(param_name)

            params["body"] = {
                "required": True,  # formData is always part of the request body
                "schema": body_schema,
            }

    return params

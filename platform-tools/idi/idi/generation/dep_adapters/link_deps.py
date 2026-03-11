"""OpenAPI 3.0+ Links parser — ground-truth dependency detection.

Parses links objects from response definitions to extract explicit
runtime relationships between operations. Confidence 1.0, lineage 'explicit'.

Priority: 100 (highest — ground-truth from spec author).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from idi.generation.dep_adapters.base import (
    Dependency,
    DetectionSource,
    OperationInfo,
    Output,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Runtime expression parser
# ---------------------------------------------------------------------------

# Stage 1: Outer structure — classify expression type and extract payload.
_RUNTIME_EXPR_RE = re.compile(
    r"^\$(?:"
    r"(?P<resp_body>response\.body)#(?P<body_ptr>/.+)"
    r"|(?P<req_body>request\.body)#(?P<req_body_ptr>/.+)"
    r"|(?P<req_path>request\.path)\.(?P<path_param>\S+)"
    r"|(?P<req_query>request\.query)\.(?P<query_param>\S+)"
    r"|(?P<resp_header>response\.header)\.(?P<header_name>\S+)"
    r")$"
)


@dataclass(frozen=True)
class ParsedExpression:
    """Result of parsing an OpenAPI runtime expression."""

    source_type: str   # e.g. "response.body", "request.path"
    source_field: str  # e.g. "id", "data.user.id", "userId"


def _decode_json_pointer(pointer: str) -> str:
    """Decode an RFC 6901 JSON Pointer to a dot-joined field path.

    ``/data/user/id`` → ``data.user.id``
    ``/a~1b``         → ``a/b``
    ``/a~0b``         → ``a~b``
    """
    # Strip leading '/'
    if pointer.startswith("/"):
        pointer = pointer[1:]
    segments = pointer.split("/")
    # Unescape: ~1 → '/', then ~0 → '~' (order matters per RFC 6901)
    decoded = []
    for seg in segments:
        seg = seg.replace("~1", "/").replace("~0", "~")
        decoded.append(seg)
    return ".".join(decoded)


def parse_runtime_expression(expr: str) -> ParsedExpression | None:
    """Parse an OpenAPI runtime expression into its components.

    Returns ``None`` (with a warning log) if the expression cannot be parsed.
    """
    m = _RUNTIME_EXPR_RE.match(expr)
    if m is None:
        logger.warning("Cannot parse runtime expression: %s", expr)
        return None

    if m.group("resp_body"):
        field = _decode_json_pointer(m.group("body_ptr"))
        return ParsedExpression(source_type="response.body", source_field=field)

    if m.group("req_body"):
        field = _decode_json_pointer(m.group("req_body_ptr"))
        return ParsedExpression(source_type="request.body", source_field=field)

    if m.group("req_path"):
        return ParsedExpression(
            source_type="request.path", source_field=m.group("path_param"),
        )

    if m.group("req_query"):
        return ParsedExpression(
            source_type="request.query", source_field=m.group("query_param"),
        )

    if m.group("resp_header"):
        return ParsedExpression(
            source_type="response.header", source_field=m.group("header_name"),
        )

    # Should not reach here given the regex, but be safe.
    logger.warning("Cannot parse runtime expression: %s", expr)
    return None


# ---------------------------------------------------------------------------
# Target resolution helpers
# ---------------------------------------------------------------------------

def _find_operation_by_id(
    spec: dict[str, Any], operation_id: str,
) -> tuple[str, str] | None:
    """Find (path, method) for a given operationId. Returns None if not found."""
    for path, path_item in spec.get("paths", {}).items():
        for method in ("get", "put", "post", "delete", "patch", "options", "head", "trace"):
            op = path_item.get(method)
            if isinstance(op, dict) and op.get("operationId") == operation_id:
                return path, method
    return None


def _resolve_operation_ref(
    spec: dict[str, Any], ref: str,
) -> tuple[str, str] | None:
    """Resolve a same-document operationRef (JSON Pointer) to (path, method).

    Only ``#/paths/...`` references are supported. External URLs are rejected
    upstream (SSRF protection).
    """
    if not ref.startswith("#/"):
        return None

    # Strip '#/' prefix and split into segments
    pointer = ref[2:]
    segments = pointer.split("/")
    # Unescape JSON Pointer segments
    segments = [s.replace("~1", "/").replace("~0", "~") for s in segments]

    # Expected: ["paths", "<path>", "<method>"]
    if len(segments) < 3 or segments[0] != "paths":
        logger.warning("operationRef does not point to paths: %s", ref)
        return None

    path = segments[1]
    method = segments[2].lower()

    # Verify the path/method actually exists
    path_item = spec.get("paths", {}).get(path)
    if not isinstance(path_item, dict) or method not in path_item:
        logger.warning("operationRef target not found in spec: %s", ref)
        return None

    return path, method


def _resource_from_path(path: str) -> str:
    """Extract the primary resource name from an API path.

    ``/users/{userId}`` → ``users``
    ``/orgs/{orgId}/repos`` → ``repos``
    """
    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    return segments[-1] if segments else path.strip("/")


# ---------------------------------------------------------------------------
# Adapter class
# ---------------------------------------------------------------------------

class LinkDepsAdapter:
    """Extracts dependencies from OpenAPI 3.0+ links objects."""

    name = "link_deps"
    priority = 100  # Highest — ground-truth from spec author

    def matches(self, spec: dict[str, Any], service_name: str) -> bool:
        """Return True for OpenAPI 3.0+ specs."""
        version = spec.get("openapi", "")
        return isinstance(version, str) and version.startswith("3.")

    def detect_dependencies(
        self,
        operation: OperationInfo,
        spec: dict,
        known_resources: set[str],
    ) -> list[Dependency]:
        """Walk links in the current operation's responses and emit dependencies."""
        paths = spec.get("paths", {})
        path_item = paths.get(operation.path, {})
        op_obj = path_item.get(operation.method)
        if not isinstance(op_obj, dict):
            return []

        deps: list[Dependency] = []
        responses = op_obj.get("responses", {})

        for _status_code, response in responses.items():
            if not isinstance(response, dict):
                continue
            links = response.get("links", {})
            if not isinstance(links, dict):
                continue

            for link_name, link_obj in links.items():
                if not isinstance(link_obj, dict):
                    continue
                deps.extend(
                    self._process_link(link_name, link_obj, spec, operation),
                )

        return deps

    def detect_outputs(self, operation: OperationInfo, spec: dict) -> list[Output]:
        """Links declare consumption, not production. Always returns empty."""
        return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _process_link(
        self,
        link_name: str,
        link_obj: dict[str, Any],
        spec: dict[str, Any],
        operation: OperationInfo,
    ) -> list[Dependency]:
        """Process a single link object and return dependencies."""
        # Resolve target operation
        target = self._resolve_target(link_name, link_obj, spec)
        if target is None:
            return []

        target_path, target_method = target
        resource = _resource_from_path(target_path)

        # Parse parameter mappings
        parameters = link_obj.get("parameters", {})
        if not isinstance(parameters, dict):
            return []

        # If link has requestBody but no parameters, log and skip
        if not parameters and "requestBody" in link_obj:
            logger.info(
                "Link '%s' uses requestBody (not parameters) — skipping",
                link_name,
            )
            return []

        deps: list[Dependency] = []
        for param_name, expr in parameters.items():
            if not isinstance(expr, str):
                continue
            parsed = parse_runtime_expression(expr)
            if parsed is None:
                continue  # Warning already logged by parse_runtime_expression

            deps.append(Dependency(
                field=param_name,
                target_resource=resource,
                target_operation=target_method,
                fact_ref=f"facts://{operation.service}/{resource}#{parsed.source_field}",
                confidence=1.0,
                source="link_deps",
                lineage_type="explicit",
                detection_source=DetectionSource.OPENAPI_LINK,
            ))

        return deps

    def _resolve_target(
        self,
        link_name: str,
        link_obj: dict[str, Any],
        spec: dict[str, Any],
    ) -> tuple[str, str] | None:
        """Resolve the target (path, method) for a link object."""
        # Prefer operationId over operationRef
        operation_id = link_obj.get("operationId")
        if operation_id is not None:
            result = _find_operation_by_id(spec, operation_id)
            if result is None:
                logger.warning(
                    "Link '%s': operationId '%s' not found in spec",
                    link_name, operation_id,
                )
            return result

        operation_ref = link_obj.get("operationRef")
        if operation_ref is not None:
            # SSRF protection: reject external URLs
            if not operation_ref.startswith("#"):
                logger.warning(
                    "Link '%s': external operationRef rejected (SSRF protection): %s",
                    link_name, operation_ref,
                )
                return None
            result = _resolve_operation_ref(spec, operation_ref)
            if result is None:
                logger.warning(
                    "Link '%s': operationRef '%s' could not be resolved",
                    link_name, operation_ref,
                )
            return result

        logger.warning(
            "Link '%s': has neither operationId nor operationRef", link_name,
        )
        return None

"""Annotation-based dependency detection from OpenAPI vendor extensions.

Parses x-idi-annotations and x-restler-annotations for explicit
producer-consumer declarations. Confidence 0.99, lineage 'explicit'.

Priority: 92 (below OLM/links, above discriminator).
"""
from __future__ import annotations

import logging
from typing import Any

from idi.generation.dep_adapters.base import (
    Dependency,
    DetectionSource,
    OperationInfo,
    Output,
)

logger = logging.getLogger(__name__)

_ANNOTATION_KEYS = ("x-idi-annotations", "x-restler-annotations")
_IDI_DEP_REQUIRED = {"producer_endpoint", "producer_method", "producer_field", "consumer_field"}
_IDI_CLASS_REQUIRED = {"field", "classification"}
_RESTLER_REQUIRED = {"producer_resource_name", "producer_method", "consumer_resource_name", "consumer_method"}


class AnnotationDepsAdapter:
    """Parse x-idi-annotations and x-restler-annotations from OpenAPI specs.

    User escape hatch for when heuristic FK detection fails. Annotations are
    near-ground-truth (confidence 0.99, lineage_type "explicit").
    """

    name = "annotation_deps"
    priority = 92

    def __init__(self) -> None:
        self._cache: dict[int, list[Dependency]] = {}

    def matches(self, spec: dict, service_name: str) -> bool:
        return any(key in spec for key in _ANNOTATION_KEYS)

    def detect_dependencies(
        self,
        operation: OperationInfo,
        spec: dict,
        known_resources: set[str],
    ) -> list[Dependency]:
        spec_id = id(spec)
        if spec_id in self._cache:
            return self._cache[spec_id]

        deps: list[Dependency] = []

        for entry in spec.get("x-idi-annotations", []):
            if not isinstance(entry, dict):
                logger.warning("Non-dict x-idi-annotations entry — skipping: %s", entry)
                continue
            dep = self._parse_idi_annotation(entry, spec, operation.service)
            if dep is not None:
                deps.append(dep)

        for entry in spec.get("x-restler-annotations", []):
            if not isinstance(entry, dict):
                logger.warning("Non-dict x-restler-annotations entry — skipping: %s", entry)
                continue
            dep = self._parse_restler_annotation(entry, spec)
            if dep is not None:
                deps.append(dep)

        self._cache[spec_id] = deps
        return deps

    def detect_outputs(
        self,
        operation: OperationInfo,
        spec: dict,
    ) -> list[Output]:
        return []

    # ------------------------------------------------------------------
    # Internal parsers
    # ------------------------------------------------------------------

    def _parse_idi_annotation(
        self, entry: dict[str, Any], spec: dict, service: str
    ) -> Dependency | None:
        keys = set(entry)

        # Classification entry — log and skip
        if _IDI_CLASS_REQUIRED <= keys:
            logger.debug(
                "Classification annotation: field=%s classification=%s",
                entry["field"],
                entry["classification"],
            )
            return None

        # Dependency entry — validate required keys
        if not (_IDI_DEP_REQUIRED <= keys):
            logger.warning(
                "Malformed x-idi-annotations entry (missing keys %s) — skipping: %s",
                _IDI_DEP_REQUIRED - keys,
                entry,
            )
            return None

        endpoint = entry["producer_endpoint"]
        method = entry["producer_method"]

        if not self._validate_endpoint(spec, endpoint, method):
            return None

        resource = _resource_from_path(endpoint)

        return Dependency(
            field=entry["consumer_field"],
            target_resource=resource,
            fact_ref=f"facts://{service}/{resource}#{entry['producer_field']}",
            confidence=0.99,
            source="annotation_deps:x-idi-annotations",
            lineage_type="explicit",
            detection_source=DetectionSource.ANNOTATION,
        )

    def _parse_restler_annotation(
        self, entry: dict[str, Any], spec: dict
    ) -> Dependency | None:
        keys = set(entry)

        if not (_RESTLER_REQUIRED <= keys):
            logger.warning(
                "Malformed x-restler-annotations entry (missing keys %s) — skipping: %s",
                _RESTLER_REQUIRED - keys,
                entry,
            )
            return None

        producer = entry["producer_resource_name"]

        # Validate producer resource appears as a path segment
        paths = spec.get("paths", {}) or {}
        if not any(
            producer in path.strip("/").split("/")
            for path in paths
        ):
            logger.warning(
                "Annotation references non-existent resource '%s' — skipping",
                producer,
            )
            return None

        consumer_field = entry.get("consumer_parameter_name", f"{producer}_id")

        return Dependency(
            field=consumer_field,
            target_resource=producer,
            fact_ref=f"facts://_/{producer}#id",
            confidence=0.99,
            source="annotation_deps:x-restler-annotations",
            lineage_type="explicit",
            detection_source=DetectionSource.ANNOTATION,
        )

    def _validate_endpoint(self, spec: dict, endpoint: str, method: str) -> bool:
        paths = spec.get("paths", {}) or {}
        path_obj = paths.get(endpoint)
        if path_obj is None:
            logger.warning(
                "Annotation references non-existent endpoint %s %s — skipping",
                method,
                endpoint,
            )
            return False

        if method.lower() not in {k.lower() for k in path_obj}:
            logger.warning(
                "Annotation references non-existent method %s on %s — skipping",
                method,
                endpoint,
            )
            return False

        return True


def _resource_from_path(path: str) -> str:
    """Extract resource name from the last non-parameter path segment."""
    segments = [s for s in path.strip("/").split("/") if s and not s.startswith("{")]
    return segments[-1] if segments else "unknown"

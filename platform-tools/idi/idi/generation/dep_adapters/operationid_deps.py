"""operationId convention mining adapter.

Parses operationId strings for cross-resource patterns like
``createGroupForUser`` or ``listOrdersByCustomer`` and emits
lightweight dependencies when the target resource exists.

Confidence: 0.5 (convention-dependent, not structural).
Priority: 5 (lowest — advisory signal only).
"""
from __future__ import annotations

import re
from typing import Any

from idi.generation.dep_adapters.base import (
    Dependency,
    DetectionSource,
    OperationInfo,
    Output,
)

# ---------------------------------------------------------------------------
# Word splitting
# ---------------------------------------------------------------------------

# Split on camelCase/PascalCase boundaries
_CAMEL_RE = re.compile(
    r"[A-Z](?:[A-Z]+(?=[A-Z][a-z]|\d|\b)|[a-z]*)|[a-z]+|[0-9]+"
)


def _split_words(text: str) -> list[str]:
    """Split operationId into lowercase words.

    Handles camelCase, PascalCase, snake_case, and kebab-case.
    """
    if not text:
        return []
    # Replace separators with spaces, then apply camelCase split
    cleaned = text.replace("-", " ").replace("_", " ")
    words: list[str] = []
    for part in cleaned.split():
        words.extend(w.lower() for w in _CAMEL_RE.findall(part))
    return words


# ---------------------------------------------------------------------------
# Pattern extraction
# ---------------------------------------------------------------------------

_PREPOSITIONS = frozenset({"for", "by", "to", "from", "of", "in"})

# "Add X To Y" pattern: both X and Y (after verb) are targets
_ADD_VERBS = frozenset({"add", "assign", "attach", "link", "bind", "associate"})


def _extract_targets(words: list[str]) -> list[str]:
    """Extract cross-resource target names from word list.

    Patterns recognized:
    - ``{verb} {resource} For {parent}`` → [parent]
    - ``{verb} {resource} By {parent}``  → [parent]
    - ``Add {X} To {Y}``                 → [X, Y]  (both are cross-resource refs)
    """
    if len(words) < 2:
        return []

    targets: list[str] = []

    # Check for "Add X To Y" pattern first
    verb = words[0]
    if verb in _ADD_VERBS:
        # Find "to" preposition; subject is between verb and "to", target is after
        for i, w in enumerate(words[1:], start=1):
            if w == "to" and i + 1 < len(words):
                subject = "".join(words[1:i])
                after_to = "".join(words[i + 1:])
                if subject:
                    targets.append(subject)
                if after_to:
                    targets.append(after_to)
                return targets

    # General pattern: look for preposition, take words after it as target
    for i, w in enumerate(words):
        if w in _PREPOSITIONS and i + 1 < len(words):
            target = "".join(words[i + 1:])
            if target:
                targets.append(target)
            break

    return targets


# ---------------------------------------------------------------------------
# Resource matching (lightweight)
# ---------------------------------------------------------------------------

def _match_known(candidate: str, known: set[str], current: str) -> str | None:
    """Match candidate against known_resources. Returns resource name or None.

    Tries: exact, +s plural, -s singular. Skips self-refs.
    """
    if not candidate:
        return None

    singular = candidate[:-1] if candidate.endswith("s") and len(candidate) > 1 else candidate
    for variant in (candidate, candidate + "s", singular):
        if variant in known and variant != current:
            return variant
    return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class OperationIdDepAdapter:
    """Mines operationId strings for cross-resource dependency patterns."""

    name = "operationid_deps"
    priority = 5  # Below generic_odg (50), links (100), annotations (92)

    def matches(self, spec: dict[str, Any], service_name: str) -> bool:
        return True

    def detect_dependencies(
        self,
        operation: OperationInfo,
        spec: dict,
        known_resources: set[str],
    ) -> list[Dependency]:
        op_id = self._get_operation_id(operation, spec)
        if not op_id:
            return []

        words = _split_words(op_id)
        candidates = _extract_targets(words)
        if not candidates:
            return []

        deps: list[Dependency] = []
        seen: set[str] = set()
        for candidate in candidates:
            matched = _match_known(candidate, known_resources, operation.resource)
            if matched and matched not in seen:
                seen.add(matched)
                deps.append(Dependency(
                    field=f"operationId:{op_id}",
                    target_resource=matched,
                    target_operation="create",
                    confidence=0.5,
                    source="generic_odg:operationid",
                    lineage_type="convention",
                    detection_source=DetectionSource.OPERATIONID,
                ))
        return deps

    def detect_outputs(
        self, operation: OperationInfo, spec: dict,
    ) -> list[Output]:
        return []

    @staticmethod
    def _get_operation_id(operation: OperationInfo, spec: dict) -> str | None:
        """Look up operationId from spec paths."""
        paths = spec.get("paths", {})
        path_item = paths.get(operation.path, {})
        op_obj = path_item.get(operation.method.lower())
        if isinstance(op_obj, dict):
            return op_obj.get("operationId")
        return None

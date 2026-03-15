"""Stage 4: Apply schema and annotation overrides to classified facts.

Priority chain: schema > annotation > structural > heuristic.
Feature grouping (conditional_on, feature) is deferred to Stage 6.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from idi.generation.helm.models import Classification, HelmFact

if TYPE_CHECKING:
    from idi.generation.helm.context import HelmContext

logger = logging.getLogger(__name__)

_HEURISTIC_SOURCES = frozenset({"heuristic_keyword", "heuristic_default"})


def enrich_facts(facts: list[HelmFact], ctx: HelmContext) -> None:
    """Apply schema and annotation overrides to classified facts.

    Mutates facts in place. Priority: schema > annotation > structural > heuristic.
    """
    for fact in facts:
        seg_key = tuple(fact.path_segments)

        # 1. Schema overrides (highest authority)
        schema_info = ctx.schema_overrides.get(seg_key)
        if schema_info is not None:
            if schema_info.type and schema_info.type != fact.semantic_type:
                fact.classifications.append(Classification(
                    "semantic_type", schema_info.type, "schema_type_override", 0.90,
                    f"schema overrides semantic_type from '{fact.semantic_type}' "
                    f"to '{schema_info.type}'",
                ))
                fact.semantic_type = schema_info.type
            if schema_info.enum:
                fact.enum = schema_info.enum
            if schema_info.required:
                fact.required = True
            if schema_info.description:
                fact.description = schema_info.description
            if schema_info.format:
                fact.format = schema_info.format
            continue  # Schema found — skip annotation

        # 2. Annotation overrides (fallback when no schema)
        annot_info = ctx.annotations.get(seg_key)
        if annot_info is not None:
            # Description: always fill in if missing
            if annot_info.description and not fact.description:
                fact.description = annot_info.description
            # Enum: always fill in if missing
            if annot_info.enum and not fact.enum:
                fact.enum = annot_info.enum
            # Type: only override heuristic sources
            if annot_info.type and fact.source in _HEURISTIC_SOURCES:
                fact.semantic_type = annot_info.type

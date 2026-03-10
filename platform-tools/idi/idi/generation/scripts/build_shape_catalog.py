"""Build a cross-CRD shape catalog from confirmed reference fingerprints.

Analyzes all CRD skill ref files to extract structural fingerprints of
confirmed reference objects. Only shapes confirmed across 2+ CRDs with
a unique target Kind mapping are included (collision handling).

Seeding restriction: only detect_ref (0.9) and detect_ref_tuple (0.85)
are used to prevent circular self-reinforcement from heuristic detectors.

Usage:
    python -m idi.generation.scripts.build_shape_catalog

Or import:
    from idi.generation.scripts.build_shape_catalog import build_shape_catalog
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from idi.generation.crd.ref_detector import compute_schema_fingerprint


# Detection sources allowed to seed the catalog (high-confidence explicit detectors).
_SEED_SOURCES: frozenset[str] = frozenset({
    "ref_detector:kind_registry",
    "ref_detector:structural_ref",
    "ref_detector:array_ref",
    "ref_detector:ref_tuple",
    # Also accept the crd_dep: prefixed variants (used in Dependency.source).
    "crd_dep:ref_detector:kind_registry",
    "crd_dep:ref_detector:structural_ref",
    "crd_dep:ref_detector:array_ref",
    "crd_dep:ref_detector:ref_tuple",
})


def build_shape_catalog(
    skills_dir: str = "catalog/skills/crd/",
    output_path: str = "catalog/shape_catalog.json",
) -> dict:
    """Analyze all CRD skills to build a reference-shape catalog.

    Produces catalog/shape_catalog.json with corroborated reference shapes.
    Returns the catalog dict.
    """
    skills_path = Path(skills_dir)
    if not skills_path.is_dir():
        return _empty_catalog(output_path)

    # Collect (fingerprint, target_kind, source_crd_kind) tuples.
    data_points: list[tuple[str, str, str]] = []

    # Walk all skill directories.
    for ref_file in skills_path.rglob("*.json"):
        try:
            data = json.loads(ref_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(data, dict):
            continue

        # Look for ref entries in input_refs or output_declarations.
        source_kind = data.get("kind", "")
        for section_key in ("input_refs", "output_declarations"):
            for ref_entry in data.get(section_key, []):
                if not isinstance(ref_entry, dict):
                    continue

                # Check detection source.
                source = ref_entry.get("source", ref_entry.get("detection_source", ""))
                if source not in _SEED_SOURCES:
                    continue

                target_kind = ref_entry.get("target_kind", "")
                if not target_kind:
                    continue

                # Build fingerprint from the ref's schema if available.
                schema = ref_entry.get("schema", {})
                if not isinstance(schema, dict) or not schema.get("properties"):
                    # Try to build from the ref entry fields directly.
                    # Minimal fingerprint from the entry's known fields.
                    props: dict[str, dict] = {}
                    for fname in ("name", "namespace", "key", "kind", "apiGroup", "apiVersion"):
                        if fname in ref_entry:
                            props[fname] = {"type": "string"}
                    if not props:
                        continue
                    required = ref_entry.get("required_fields", [])
                    fp = compute_schema_fingerprint(props, required)
                else:
                    properties = schema["properties"]
                    required = schema.get("required", [])
                    fp = compute_schema_fingerprint(properties, required)

                if fp:
                    data_points.append((fp, target_kind, source_kind))

    if not data_points:
        return _empty_catalog(output_path)

    # Group by fingerprint.
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for fp, target_kind, source_kind in data_points:
        grouped[fp].append((target_kind, source_kind))

    # Build catalog entries.
    shapes: list[dict[str, Any]] = []

    for fp, entries in sorted(grouped.items()):
        # Collision detection: check all entries agree on target_kind.
        target_kinds = {tk for tk, _ in entries}
        if len(target_kinds) > 1:
            continue  # Ambiguous — discard.

        target_kind = next(iter(target_kinds))
        source_kinds = sorted({sk for _, sk in entries if sk})

        # Minimum corroboration: 2+ distinct CRDs.
        if len(source_kinds) < 2:
            continue

        # Assign confidence.
        confidence = 0.85 if len(source_kinds) >= 3 else 0.80

        # Extract required properties from fingerprint.
        required_props: list[str] = []
        for part in fp.split(","):
            if ":" in part and not part.endswith("?"):
                prop_name = part.split(":")[0]
                required_props.append(prop_name)

        shapes.append({
            "fingerprint": fp,
            "target_kind": target_kind,
            "confirmed_in": source_kinds,
            "confidence": confidence,
            "min_properties": len(fp.split(",")),
            "required_properties": required_props,
        })

    catalog = {
        "version": "1.0",
        "generated": datetime.now(timezone.utc).isoformat(),
        "shapes": shapes,
    }

    # Write output.
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    return catalog


def _empty_catalog(output_path: str) -> dict:
    """Write and return an empty catalog."""
    catalog = {
        "version": "1.0",
        "generated": datetime.now(timezone.utc).isoformat(),
        "shapes": [],
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return catalog


if __name__ == "__main__":
    result = build_shape_catalog()
    n = len(result.get("shapes", []))
    print(f"Shape catalog generated with {n} shapes.")
    sys.exit(0)

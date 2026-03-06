"""Manifest-driven batch skill generation.

Reads ``catalog/manifest.yaml`` and generates skills for all or selected
services using direct Python imports instead of subprocess calls.

All functions are stateless module-level callables -- no ``self``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Load and validate a spec manifest YAML file.

    Args:
        manifest_path: Path to the manifest file.

    Returns:
        Parsed manifest dict with at least a ``services`` key.

    Raises:
        FileNotFoundError: If the manifest file doesn't exist.
        ValueError: If the manifest is empty or missing ``services``.
    """
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)

    if not manifest:
        raise ValueError("Manifest is empty")
    if "services" not in manifest:
        raise ValueError("Manifest missing 'services' key")

    return manifest


# ---------------------------------------------------------------------------
# Single-service generation
# ---------------------------------------------------------------------------


def generate_service(
    name: str,
    config: Dict[str, Any],
    specs_dir: Path,
    output_base: Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Generate skills for a single service.

    Uses direct Python imports to :func:`idi.generation.spec_loader.create_context`
    and :func:`idi.generation.cli.generate` instead of subprocess calls.

    Args:
        name: Service name.
        config: Service configuration from manifest (keys: ``schema``,
            ``output``, ``style``, ``description``).
        specs_dir: Base directory for spec files.
        output_base: Base directory for skill output.
        dry_run: If ``True``, just report what would happen.

    Returns:
        Dict with ``success``, ``message``, and optionally ``stats`` keys.
    """
    schema_rel = config.get("schema", "")
    output_rel = config.get("output", "")
    style = config.get("style", "auto")

    schema_path = specs_dir / schema_rel
    output_dir = output_base / output_rel

    if not schema_path.exists():
        return {
            "success": False,
            "message": f"Schema not found: {schema_rel}",
        }

    if dry_run:
        return {
            "success": True,
            "message": f"Would generate: {name} ({style}) -> {output_rel}",
        }

    # Route style=kubernetes with crd_kinds to CRD pipeline.
    crd_kinds = config.get("crd_kinds")
    if style == "kubernetes" and crd_kinds:
        return _generate_crd_service(name, config, output_dir)

    try:
        from idi.generation.cli import generate
        from idi.generation.spec_loader import create_context

        ctx = create_context(
            schema_path=str(schema_path),
            output_dir=str(output_dir),
            api_name=name,
            style=style,
        )
        stats = generate(ctx)

        return {
            "success": True,
            "message": (
                f"Generated {stats.get('skills', 0)} skills across "
                f"{stats.get('resources', 0)} resources"
            ),
            "stats": stats,
        }
    except Exception as exc:
        logger.exception("Generation failed for %s", name)
        return {
            "success": False,
            "message": f"Generation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# CRD pipeline
# ---------------------------------------------------------------------------


def _generate_crd_service(
    name: str,
    config: Dict[str, Any],
    output_dir: Path,
) -> Dict[str, Any]:
    """Generate CRD skills for a Kubernetes-style service.

    Runs the CRD pipeline: load schemas -> classify fields -> build ODG ->
    write skill JSON files.

    Args:
        name: Service name.
        config: Service config from manifest (must have ``crd_kinds``).
        output_dir: Base output directory for CRD skills.

    Returns:
        Dict with ``success``, ``message``, and ``stats`` keys.
    """
    try:
        from idi.generation.crd.field_classifier import classify_fields
        from idi.generation.crd.odg_builder import build_odg
        from idi.generation.crd.output_writer import write_crd_skill
        from idi.generation.crd.schema_loader import load_crd_schemas

        chart_config = config.get("crd_kinds", [])
        if not chart_config:
            return {"success": False, "message": "No crd_kinds configured"}

        schemas, values = load_crd_schemas(name, config)
        if not schemas:
            return {
                "success": False,
                "message": f"No CRD schemas loaded for {name}",
            }

        # Classify fields for each CRD kind.
        all_kinds: Dict[str, Any] = {}
        for schema in schemas:
            kind = schema["kind"]
            group = schema["group"]
            fields = classify_fields(
                schema.get("spec_properties", {}),
                schema.get("spec_required", []),
                group,
                kind,
            )
            all_kinds[kind] = fields

        # Build dependency graph.
        primary_group = schemas[0]["group"] if schemas else ""
        deps = build_odg(all_kinds, name, primary_group)

        # Write skill files.
        skills_written = 0
        for schema in schemas:
            kind = schema["kind"]
            fields = all_kinds.get(kind, [])
            write_crd_skill(schema, fields, output_dir)
            skills_written += 1

        stats = {"kinds": len(schemas), "skills": skills_written, "deps": len(deps)}
        return {
            "success": True,
            "message": f"Generated {skills_written} CRD skills for {name}",
            "stats": stats,
        }
    except Exception as exc:
        logger.exception("CRD generation failed for %s", name)
        return {
            "success": False,
            "message": f"CRD generation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Bulk generation
# ---------------------------------------------------------------------------


def generate_all(
    manifest: Dict[str, Any],
    specs_dir: Path,
    output_base: Path,
    service: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Generate skills for all or a filtered service.

    Args:
        manifest: Parsed manifest dict.
        specs_dir: Base directory for spec files.
        output_base: Base directory for skill output.
        service: If provided, only generate this service.
        dry_run: If ``True``, preview only.

    Returns:
        Dict mapping service name to result dict.

    Raises:
        ValueError: If *service* is not found in the manifest.
    """
    services = manifest.get("services", {})

    if service:
        if service not in services:
            raise ValueError(
                f"Unknown service: '{service}'. "
                f"Available: {', '.join(sorted(services.keys()))}"
            )
        services = {service: services[service]}

    results: Dict[str, Dict[str, Any]] = {}

    for svc_name, config in sorted(services.items()):
        results[svc_name] = generate_service(
            name=svc_name,
            config=config,
            specs_dir=specs_dir,
            output_base=output_base,
            dry_run=dry_run,
        )

    return results


# ---------------------------------------------------------------------------
# Service listing
# ---------------------------------------------------------------------------


def list_services(
    manifest: Dict[str, Any],
    specs_dir: Path,
) -> List[Dict[str, Any]]:
    """List all services from the manifest with status info.

    Args:
        manifest: Parsed manifest dict.
        specs_dir: Base directory for spec files.

    Returns:
        Sorted list of dicts with ``name``, ``description``, ``schema``,
        ``style``, and ``exists`` keys.
    """
    services = manifest.get("services", {})
    result: List[Dict[str, Any]] = []

    for name, config in sorted(services.items()):
        schema_path = specs_dir / config.get("schema", "")
        result.append({
            "name": name,
            "description": config.get("description", ""),
            "schema": config.get("schema", ""),
            "style": config.get("style", "auto"),
            "exists": schema_path.exists(),
        })

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def cli(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for batch generation.

    Supports ``--service``, ``--list``, ``--dry-run``, ``--manifest``,
    ``--specs-dir``, and ``--output-base`` flags.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv``).

    Returns:
        Exit code: 0 for success, 1 for any failures.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate skills from all services in manifest",
    )
    parser.add_argument("--service", "-s", help="Generate only this service")
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        dest="list_mode",
        help="List services and exit",
    )
    parser.add_argument("--dry-run", "-n", action="store_true")
    parser.add_argument(
        "--manifest", "-m",
        default="catalog/manifest.yaml",
        help="Path to manifest file",
    )
    parser.add_argument(
        "--specs-dir",
        default=None,
        help="Specs directory (default: manifest parent)",
    )
    parser.add_argument(
        "--output-base",
        default=".",
        help="Output base directory",
    )

    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest)

    try:
        manifest = load_manifest(manifest_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    specs_dir = Path(args.specs_dir) if args.specs_dir else manifest_path.parent
    output_base = Path(args.output_base)

    if args.list_mode:
        services = list_services(manifest, specs_dir)
        for svc in services:
            status = "OK" if svc["exists"] else "missing"
            print(f"  {svc['name']:<20} {status:<10} {svc['description'][:40]}")
        return 0

    try:
        results = generate_all(
            manifest, specs_dir, output_base,
            service=args.service, dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    failed = sum(1 for r in results.values() if not r["success"])
    total = len(results)
    succeeded = total - failed

    print(f"\nResults: {succeeded}/{total} succeeded")
    if failed:
        for svc_name, result in results.items():
            if not result["success"]:
                print(f"  FAILED: {svc_name} - {result['message']}")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(cli())

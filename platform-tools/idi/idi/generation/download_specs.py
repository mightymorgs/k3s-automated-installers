"""Download OpenAPI specs from a manifest file.

Reads ``catalog/manifest.yaml`` and downloads specs for all or selected
services.  Supports direct URL downloads, validation, and status listing.

All functions are stateless module-level callables -- no ``self``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

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
# Spec validation
# ---------------------------------------------------------------------------


def validate_spec(path: Path) -> bool:
    """Check if a file is a valid OpenAPI/Swagger specification.

    Validates by checking for JSON/YAML parsability and the presence
    of expected top-level keys (``openapi``, ``swagger``, or ``paths``).

    Args:
        path: Path to the spec file.

    Returns:
        ``True`` if valid, ``False`` otherwise.
    """
    if not path.exists():
        return False

    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return False

    if not content.strip():
        return False

    # Try JSON first.
    stripped = content.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(content)
            return isinstance(data, dict) and any(
                k in data for k in ("openapi", "swagger", "paths")
            )
        except json.JSONDecodeError:
            return False

    # Fall back to YAML.
    try:
        data = yaml.safe_load(content)
        return isinstance(data, dict) and any(
            k in data for k in ("openapi", "swagger", "paths")
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Single spec download
# ---------------------------------------------------------------------------


def download_spec(
    url: str,
    output_path: Path,
    force: bool = False,
) -> bool:
    """Download a spec from a URL.

    Args:
        url: URL to download from.
        output_path: Where to save the downloaded file.
        force: If ``True``, re-download even if file exists.

    Returns:
        ``True`` if download succeeded (or file already exists and
        *force* is ``False``), ``False`` otherwise.
    """
    if output_path.exists() and not force:
        logger.info("Skipping %s (already exists)", output_path.name)
        return True

    try:
        logger.info("Downloading %s ...", url)
        req = Request(url, headers={"User-Agent": "IDI-SkillGenerator/1.0"})
        with urlopen(req, timeout=120) as response:  # noqa: S310
            content = response.read()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)

        # Validate downloaded content.
        if not validate_spec(output_path):
            logger.warning("Downloaded file is not a valid spec: %s", output_path)
            return False

        return True
    except (URLError, OSError) as exc:
        logger.error("Download failed for %s: %s", url, exc)
        return False


# ---------------------------------------------------------------------------
# Service listing
# ---------------------------------------------------------------------------


def list_services(
    manifest: Dict[str, Any],
    specs_dir: Path,
) -> List[Dict[str, Any]]:
    """List all services from the manifest with their download status.

    Args:
        manifest: Parsed manifest dict (must contain ``services``).
        specs_dir: Directory where spec files are stored.

    Returns:
        Sorted list of dicts with ``name``, ``description``, ``schema``,
        ``url``, ``exists``, and ``valid`` keys.
    """
    services = manifest.get("services", {})
    result: List[Dict[str, Any]] = []

    for name, config in sorted(services.items()):
        schema_path = specs_dir / config.get("schema", "")
        exists = schema_path.exists()
        valid = validate_spec(schema_path) if exists else False

        result.append({
            "name": name,
            "description": config.get("description", ""),
            "schema": config.get("schema", ""),
            "url": config.get("url", ""),
            "exists": exists,
            "valid": valid,
        })

    return result


# ---------------------------------------------------------------------------
# Bulk download
# ---------------------------------------------------------------------------


def download_all(
    manifest: Dict[str, Any],
    specs_dir: Path,
    service: Optional[str] = None,
    force: bool = False,
) -> Dict[str, bool]:
    """Download specs for all services, or a single filtered service.

    Dispatches by ``source_type``:
    - ``download``: fetch URL, validate, save
    - ``crd`` / ``artifacthub``: fetch from datreeio, wrap as OpenAPI
    - ``bundled``: verify file exists on disk
    - ``instance`` / ``manual``: skip (not downloadable)

    Args:
        manifest: Parsed manifest dict.
        specs_dir: Directory to store downloaded specs.
        service: If provided, only process this service.
        force: If ``True``, re-download existing files.

    Returns:
        Dict mapping service name to success boolean.

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

    results: Dict[str, bool] = {}

    for name, config in sorted(services.items()):
        schema_file = config.get("schema", "")
        source_type = config.get("source_type", "download")
        output_path = specs_dir / schema_file

        if source_type == "download":
            url = config.get("url", "")
            if not url:
                logger.info("Skipping %s (no URL)", name)
                results[name] = True
                continue
            results[name] = download_spec(url, output_path, force=force)

        elif source_type in ("crd", "artifacthub"):
            if output_path.exists() and not force:
                logger.info("Skipping %s (already exists)", name)
                results[name] = True
                continue
            from idi.generation.crd_schemas import convert_crd_service

            results[name] = convert_crd_service(name, config, output_path)

        elif source_type == "bundled":
            if output_path.exists():
                results[name] = True
            else:
                logger.warning("Bundled spec missing: %s", output_path)
                results[name] = False

        elif source_type in ("instance", "manual"):
            logger.info("Skipping %s (source_type=%s)", name, source_type)
            results[name] = True

        else:
            logger.warning(
                "Unknown source_type '%s' for %s", source_type, name,
            )
            results[name] = False

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def cli(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for spec downloading.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv``).

    Returns:
        Exit code: 0 for success, 1 for failure.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Download OpenAPI specs from manifest",
    )
    parser.add_argument(
        "--service", "-s",
        help="Download only this service",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        dest="list_mode",
        help="List services and exit",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Re-download existing files",
    )
    parser.add_argument(
        "--manifest", "-m",
        default="catalog/manifest.yaml",
        help="Path to manifest file",
    )

    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest)

    try:
        manifest = load_manifest(manifest_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    specs_dir = manifest_path.parent

    if args.list_mode:
        services = list_services(manifest, specs_dir)
        for svc in services:
            status = (
                "OK" if svc["valid"]
                else ("exists" if svc["exists"] else "missing")
            )
            print(f"  {svc['name']:<20} {status:<10} {svc['description'][:40]}")
        return 0

    results = download_all(
        manifest, specs_dir, service=args.service, force=args.force,
    )
    failed = sum(1 for v in results.values() if not v)
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(cli())

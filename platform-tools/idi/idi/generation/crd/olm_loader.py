"""OLM CSV loader — fetch OperatorHub.io CSV data with disk caching.

Downloads OLM ClusterServiceVersion (CSV) metadata from the OperatorHub.io
API and caches results to disk.  Follows the same fetch/cache pattern as
``schema_loader.py``.

No import-time side effects: all I/O happens inside function calls.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

logger = logging.getLogger(__name__)

OPERATORHUB_API = "https://operatorhub.io/api/operator"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class GVKRef:
    """A Group-Version-Kind reference extracted from an OLM CSV."""

    kind: str       # "Certificate"
    group: str      # "cert-manager.io"
    version: str    # "v1"
    plural: str     # "certificates"


def _sanitize_name(name: str) -> str:
    """Strip operator name to safe filesystem characters."""
    return _SAFE_NAME_RE.sub("", name)


def _fetch_url(url: str, timeout: int = 30, max_retries: int = 2) -> bytes | None:
    """Fetch *url*, retrying on transient errors.

    Returns raw response bytes, or ``None`` on definitive failure (404)
    or after exhausting retries.
    """
    req = Request(url, headers={"User-Agent": "IDI-CrdPipeline/1.0"})
    for attempt in range(1 + max_retries):
        try:
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.read()
        except HTTPError as exc:
            if exc.code == 404:
                return None  # definitive — do not retry
            if exc.code >= 500:
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                logger.warning("HTTP %s for %s after %d retries", exc.code, url, max_retries)
                return None
            logger.warning("HTTP %s for %s", exc.code, url)
            return None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            logger.warning("Timeout/network error for %s: %s", url, exc)
            return None
    return None  # pragma: no cover


def fetch_olm_csv(
    operator_name: str,
    cache_dir: str = "catalog/specs/olm/",
) -> dict | None:
    """Fetch OLM CSV from OperatorHub.io API, with disk caching.

    Caches to ``{cache_dir}/{operator_name}/csv.yaml``.
    Returns parsed CSV dict, or ``None`` if unavailable/malformed.
    Tries ``{operator_name}-operator`` as fallback on 404.
    """
    safe_name = _sanitize_name(operator_name)
    if not safe_name:
        logger.warning("Empty operator name after sanitization: %r", operator_name)
        return None

    cache_base = Path(cache_dir).resolve()
    cache_path = (cache_base / safe_name / "csv.yaml").resolve()

    # Guard against path traversal.
    if not str(cache_path).startswith(str(cache_base)):
        logger.warning("Path traversal blocked for operator name %r", operator_name)
        return None

    # Cache hit.
    if cache_path.is_file():
        try:
            return yaml.safe_load(cache_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read cached CSV at %s", cache_path)

    # Fetch from API — try primary name, then fallback.
    csv_data: dict | None = None
    for name_variant in (operator_name, f"{operator_name}-operator"):
        raw = _fetch_url(f"{OPERATORHUB_API}/{name_variant}")
        if raw is None:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Malformed JSON from OperatorHub for %s", name_variant)
            continue
        if isinstance(payload, dict):
            csv_data = payload
            break

    if csv_data is None:
        logger.debug("No OLM CSV found for %s", operator_name)
        return None

    # Write cache.
    try:
        os.makedirs(cache_path.parent, exist_ok=True)
        cache_path.write_text(yaml.dump(csv_data, default_flow_style=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write OLM cache for %s: %s", operator_name, exc)

    return csv_data


def extract_gvk_dependencies(csv: dict) -> tuple[list[GVKRef], list[GVKRef]]:
    """Extract owned and required GVK references from a parsed CSV.

    Returns ``(owned_gvks, required_gvks)``.
    Entries with missing ``kind``/``name`` or malformed name (no dot) are skipped.
    """
    crd_section = csv.get("spec", {}).get("customresourcedefinitions", {}) or {}
    owned_raw = crd_section.get("owned") or []
    required_raw = crd_section.get("required") or []

    def _parse_entries(entries: list) -> list[GVKRef]:
        result: list[GVKRef] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("kind")
            name = entry.get("name")
            if not kind or not name:
                logger.debug("Skipping OLM entry missing kind/name: %s", entry)
                continue
            if "." not in name:
                logger.debug("Skipping OLM entry with malformed name (no dot): %s", name)
                continue
            dot_idx = name.index(".")
            plural = name[:dot_idx]
            group = name[dot_idx + 1:]
            version = entry.get("version", "")
            result.append(GVKRef(kind=kind, group=group, version=version, plural=plural))
        return result

    return _parse_entries(owned_raw), _parse_entries(required_raw)


def extract_alm_examples(csv: dict) -> list[dict]:
    """Parse alm-examples annotation from an OLM CSV.

    Returns a list of K8s manifest dicts, each with at minimum:
    apiVersion, kind, metadata (with name and optional labels).
    Returns empty list if annotation is missing, malformed, or not JSON.
    """
    raw = csv.get("metadata", {}).get("annotations", {}).get("alm-examples")
    if raw is None:
        return []

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Malformed alm-examples JSON in OLM CSV")
        return []

    if not isinstance(parsed, list):
        return []

    result: list[dict] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if not isinstance(kind, str):
            continue
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            continue
        name = metadata.get("name")
        if not isinstance(name, str):
            continue
        result.append(entry)

    return result

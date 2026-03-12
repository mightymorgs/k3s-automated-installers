"""CRD schema loader — fetch ArtifactHub Helm charts, extract CRD schemas + values.yaml.

Downloads chart .tgz from ArtifactHub, extracts templates/crds.yaml,
strips Helm template directives, parses openAPIV3Schema per CRD Kind.
Also extracts values.yaml for Helm spec generation.
"""
from __future__ import annotations

import io
import json
import logging
import re
import tarfile
from typing import Any

import yaml
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

ARTIFACTHUB_API = "https://artifacthub.io/api/v1"


def strip_helm_directives(content: str) -> str:
    """Remove Helm template directives ({{ ... }}) from YAML content."""
    return re.sub(r'\{\{.*?\}\}', '', content)


def extract_spec_properties(
    schema: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Extract spec.properties and spec.required from an openAPIV3Schema."""
    spec = schema.get("properties", {}).get("spec", {})
    return spec.get("properties", {}), spec.get("required", [])


def extract_crds_from_chart(crds_yaml: str) -> list[dict[str, Any]]:
    """Parse CRD definitions from a crds.yaml file content.

    Strips Helm directives, parses YAML docs, extracts openAPIV3Schema
    from each CustomResourceDefinition.
    """
    cleaned = strip_helm_directives(crds_yaml)
    results: list[dict[str, Any]] = []

    for doc in yaml.safe_load_all(cleaned):
        if not doc or doc.get("kind") != "CustomResourceDefinition":
            continue

        spec = doc.get("spec", {})
        names = spec.get("names", {})
        scope_raw = spec.get("scope", "Namespaced")

        for version in spec.get("versions", []):
            openapi = version.get("schema", {}).get("openAPIV3Schema", {})
            if not openapi:
                continue

            props, required = extract_spec_properties(openapi)
            results.append({
                "kind": names.get("kind", ""),
                "group": spec.get("group", ""),
                "version": version.get("name", ""),
                "plural": names.get("plural", ""),
                "scope": "namespaced" if scope_raw == "Namespaced" else "cluster",
                "spec_properties": props,
                "spec_required": required,
                "description": openapi.get("description", ""),
            })

    return results


def _fetch_chart_artifacts(
    chart_config: dict[str, Any],
    timeout: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Download chart .tgz and extract CRD schemas + values.yaml."""
    repo = chart_config.get("repository", "")
    chart = chart_config.get("chart", "")
    version = chart_config.get("version", "")

    # Get content_url from ArtifactHub API
    repo_name = chart_config.get("artifacthub_repo", chart)
    api_url = f"{ARTIFACTHUB_API}/packages/helm/{repo_name}/{chart}"
    if version:
        api_url += f"/{version}"

    req = Request(api_url, headers={"User-Agent": "IDI-CrdPipeline/1.0"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310
        pkg_data = json.loads(resp.read())

    content_url = pkg_data.get("content_url", "")
    if not content_url:
        raise ValueError(f"No content_url for {chart}")

    # Download and extract .tgz
    req = Request(content_url, headers={"User-Agent": "IDI-CrdPipeline/1.0"})
    with urlopen(req, timeout=60) as resp:  # noqa: S310
        tgz_data = resp.read()

    crds: list[dict[str, Any]] = []
    values: dict[str, Any] = {}

    with tarfile.open(fileobj=io.BytesIO(tgz_data), mode="r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if not name.endswith(".yaml"):
                continue
            f = tar.extractfile(member)
            if not f:
                continue
            content = f.read().decode()

            # Fast pre-filter: only parse files that mention CRDs
            if "CustomResourceDefinition" not in content:
                # Still extract values.yaml
                if name.endswith("values.yaml") and name.count("/") == 1:
                    values = yaml.safe_load(content) or {}
                continue

            crds.extend(extract_crds_from_chart(content))

    return crds, values


def load_crd_schemas(
    service: str,
    chart_config: dict[str, Any],
    timeout: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load CRD schemas and values.yaml from ArtifactHub.

    Args:
        service: Service name (e.g. 'cert-manager').
        chart_config: Chart config with 'chart', 'repository', optional 'version'.
        timeout: HTTP timeout.

    Returns:
        Tuple of (list of CRD kind dicts, values.yaml dict).
    """
    try:
        crds, values = _fetch_chart_artifacts(chart_config, timeout)
    except Exception as exc:
        logger.warning("Failed to fetch chart for %s: %s", service, exc)
        return [], {}

    for crd in crds:
        crd["service"] = service

    return crds, values

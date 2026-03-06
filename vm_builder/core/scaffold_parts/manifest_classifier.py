"""Classify K8s manifests by Kind and assign golden-master numeric prefixes."""

from pathlib import Path
from typing import NamedTuple

import yaml

# Golden master prefix convention: prefix < 40 = protected (always apply),
# prefix >= 40 = workload (kubectl {{ kubectl_action }})
KIND_PREFIX_MAP: dict[str, str] = {
    "Namespace": "00",
    "ServiceAccount": "05",
    "ClusterRole": "05",
    "ClusterRoleBinding": "05",
    "Role": "05",
    "RoleBinding": "05",
    "Secret": "10",
    "ConfigMap": "10",
    "PersistentVolumeClaim": "30",
    "StatefulSet": "40",
    "Deployment": "40",
    "DaemonSet": "40",
    "Job": "40",
    "CronJob": "40",
    "Service": "50",
    "IngressRoute": "60",
    "Ingress": "60",
}

PROTECTED_PREFIXES = frozenset({"00", "05", "10", "20", "30"})


class ClassifiedManifest(NamedTuple):
    """A K8s manifest classified with a numeric prefix and protection status."""

    kind: str
    name: str
    prefix: str
    is_protected: bool
    content: dict
    filename: str


def classify_manifest(doc: dict) -> ClassifiedManifest:
    """Classify a single K8s manifest document."""
    kind = doc.get("kind", "Unknown")
    name = doc.get("metadata", {}).get("name", "unnamed")
    prefix = KIND_PREFIX_MAP.get(kind, "40")
    is_protected = prefix in PROTECTED_PREFIXES
    filename = f"{prefix}-{kind.lower()}.yaml"
    return ClassifiedManifest(
        kind=kind,
        name=name,
        prefix=prefix,
        is_protected=is_protected,
        content=doc,
        filename=filename,
    )


def classify_helm_output(output_dir: Path) -> list[ClassifiedManifest]:
    """Classify all YAML files in a helm template output directory."""
    manifests: list[ClassifiedManifest] = []
    for yaml_file in sorted(output_dir.rglob("*.yaml")):
        text = yaml_file.read_text()
        for doc in yaml.safe_load_all(text):
            if doc and isinstance(doc, dict) and "kind" in doc:
                manifests.append(classify_manifest(doc))

    seen: set[tuple[str, str]] = set()
    unique: list[ClassifiedManifest] = []
    for m in manifests:
        key = (m.kind, m.name)
        if key not in seen:
            seen.add(key)
            unique.append(m)
    return sorted(unique, key=lambda m: (m.prefix, m.kind))

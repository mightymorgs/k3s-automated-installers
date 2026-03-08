"""Generate kustomization.yaml from classified workload manifests."""

from pathlib import Path

import yaml

from vm_builder.core.scaffold_parts.manifest_classifier import ClassifiedManifest


def generate_kustomization(
    manifests: list[ClassifiedManifest], app_name: str, namespace: str
) -> dict:
    """Generate kustomization.yaml content for workload (non-protected) manifests."""
    workload_files = sorted(
        f"{m.filename}.j2" for m in manifests if not m.is_protected
    )
    return {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "namespace": "{{ app_namespace }}",
        "resources": workload_files,
    }


def write_kustomize_base(
    output_dir: Path,
    manifests: list[ClassifiedManifest],
    j2_contents: dict[str, str],
    app_name: str,
    namespace: str,
) -> None:
    """Write kustomization.yaml and J2 template files to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    kustomization = generate_kustomization(manifests, app_name, namespace)
    (output_dir / "kustomization.yaml").write_text(
        yaml.dump(kustomization, default_flow_style=False, sort_keys=False)
    )

    for filename, content in j2_contents.items():
        (output_dir / filename).write_text(content)

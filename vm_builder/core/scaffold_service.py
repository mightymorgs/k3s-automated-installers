"""Scaffold service -- orchestrates all scaffold_parts into a single pipeline.

Thin facade following the existing ``RegistryService`` pattern:
import part functions, call them in the correct pipeline order.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import yaml

from vm_builder.core.scaffold_parts.compose_parser import parse_compose
from vm_builder.core.scaffold_parts.compose_sources import (
    fetch_compose_file,
    load_source_index,
    resolve_compose_url,
)
from vm_builder.core.scaffold_parts.config_generator import generate_config_playbooks
from vm_builder.core.scaffold_parts.helm_downloader import (
    download_chart,
    extract_values,
    render_chart,
)
from vm_builder.core.scaffold_parts.j2_converter import convert_to_j2_template
from vm_builder.core.scaffold_parts.kustomize_generator import write_kustomize_base
from vm_builder.core.scaffold_parts.manifest_classifier import (
    ClassifiedManifest,
    classify_helm_output,
)
from vm_builder.core.scaffold_parts.metadata_generator import generate_sidecar
from vm_builder.core.scaffold_parts.playbook_generator import (
    PlaybookConfig,
    generate_install_playbook,
    generate_uninstall_playbook,
    generate_verify_playbook,
)
from vm_builder.core.scaffold_parts.pushsecret_generator import (
    detect_secret_fields,
    generate_pushsecret_template,
)
from vm_builder.core.scaffold_parts.statefulset_converter import (
    convert_deployment_to_statefulset,
)


class ScaffoldService:
    """Orchestrate the full scaffold pipeline from Helm chart to app directory."""

    def scaffold(
        self,
        app_name: str,
        helm_chart: str,
        namespace: str,
        output_dir: Optional[Path] = None,
        helm_repo: Optional[str] = None,
        helm_values: Optional[str] = None,
        compose_file: Optional[str] = None,
        compose_source: Optional[str] = None,
        nodeport: int = 0,
        category: str = "Application",
        dry_run: bool = False,
    ) -> None:
        """Run the full scaffold pipeline.

        Steps:
          1. Download and render Helm chart
          2. Classify rendered manifests
          3. Convert Deployments to StatefulSets
          4. Convert all manifests to J2 templates
          5. Write kustomize base (workloads) and protected templates
          6. Generate install/verify/uninstall playbooks
          7. (Optional) Fetch + parse Compose, generate config playbooks
          8. Detect secrets and generate PushSecret template
          9. Generate .idi-meta.yaml sidecars for each phase directory
        """
        if output_dir is None:
            output_dir = Path("apps") / app_name

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # -- Step 1: Download and render Helm chart --
            chart_tgz = download_chart(helm_chart, tmp / "charts", repo_url=helm_repo)
            values = extract_values(chart_tgz)
            values_path = None
            if helm_values:
                values_path = Path(helm_values)
            rendered_dir = render_chart(
                chart_tgz, app_name, tmp / "rendered",
                values_file=values_path, namespace=namespace,
            )

            # -- Step 2: Classify rendered manifests --
            manifests = classify_helm_output(rendered_dir)

            if dry_run:
                return

            # -- Step 3: Convert Deployments to StatefulSets --
            converted: list[ClassifiedManifest] = []
            for m in manifests:
                if m.kind == "Deployment":
                    new_doc = convert_deployment_to_statefulset(m.content, app_name)
                    converted.append(ClassifiedManifest(
                        kind="StatefulSet",
                        name=m.name,
                        prefix=m.prefix,
                        is_protected=m.is_protected,
                        content=new_doc,
                        filename=f"{m.prefix}-statefulset.yaml",
                    ))
                else:
                    converted.append(m)

            # -- Step 4: Convert all manifests to J2 templates --
            j2_workloads: dict[str, str] = {}
            j2_protected: dict[str, str] = {}
            for m in converted:
                j2_content = convert_to_j2_template(m.content, app_name, namespace)
                j2_filename = f"{m.filename}.j2"
                if m.is_protected:
                    j2_protected[j2_filename] = j2_content
                else:
                    j2_workloads[j2_filename] = j2_content

            # -- Step 5: Write kustomize base and protected templates --
            kustomize_dir = output_dir / "k8s-base"
            workload_manifests = [m for m in converted if not m.is_protected]
            write_kustomize_base(kustomize_dir, workload_manifests, j2_workloads, app_name, namespace)

            templates_dir = output_dir / "templates"
            if j2_protected:
                templates_dir.mkdir(parents=True, exist_ok=True)
                for filename, content in j2_protected.items():
                    (templates_dir / filename).write_text(content)

            # -- Step 6: Detect container port and image for playbook config --
            container_port = 8080
            image = ""
            has_pvc = any(m.kind == "PersistentVolumeClaim" for m in converted)
            has_secrets = any(m.kind == "Secret" for m in converted)
            for m in converted:
                containers = (
                    m.content.get("spec", {})
                    .get("template", {})
                    .get("spec", {})
                    .get("containers", [])
                )
                for c in containers:
                    for p in c.get("ports", []):
                        if cp := p.get("containerPort"):
                            container_port = cp
                    if img := c.get("image"):
                        image = img

            config = PlaybookConfig(
                app_name=app_name,
                app_namespace=namespace,
                nodeport=nodeport,
                container_port=container_port,
                image=image,
                has_pvc=has_pvc,
                has_secrets=has_secrets,
                category=category,
            )

            # -- Step 7: Generate install/verify/uninstall playbooks --
            install_dir = output_dir / "install"
            install_dir.mkdir(parents=True, exist_ok=True)
            (install_dir / "01-apply-kustomize.yml").write_text(
                generate_install_playbook(config)
            )
            (install_dir / "02-verify.yml").write_text(
                generate_verify_playbook(config)
            )

            uninstall_dir = output_dir / "uninstall"
            uninstall_dir.mkdir(parents=True, exist_ok=True)
            (uninstall_dir / "01-remove.yml").write_text(
                generate_uninstall_playbook(config)
            )

            # -- Step 8: (Optional) Compose wiring -> config playbooks --
            compose_data = None
            if compose_file:
                compose_data = yaml.safe_load(Path(compose_file).read_text())
            elif compose_source:
                index_path = Path("catalog") / "compose-sources.yaml"
                index = load_source_index(index_path)
                url = resolve_compose_url(index, compose_source, app_name)
                if url:
                    compose_data = fetch_compose_file(url)

            if compose_data:
                parsed = parse_compose(compose_data)
                edges = parsed.edges_for(app_name)
                config_playbooks = generate_config_playbooks(app_name, edges, nodeport)
                if config_playbooks:
                    config_dir = output_dir / "config"
                    config_dir.mkdir(parents=True, exist_ok=True)
                    for content, filename in config_playbooks:
                        (config_dir / filename).write_text(content)

            # -- Step 9: Detect secrets and generate PushSecret template --
            secret_fields = detect_secret_fields([m.content for m in converted])
            if secret_fields:
                pushsecret_content = generate_pushsecret_template(app_name, secret_fields)
                if pushsecret_content:
                    if not templates_dir.exists():
                        templates_dir.mkdir(parents=True, exist_ok=True)
                    (templates_dir / "pushsecret.yaml.j2").write_text(pushsecret_content)

            # -- Step 10: Generate .idi-meta.yaml sidecars --
            for phase_dir in [install_dir, uninstall_dir]:
                sidecar = generate_sidecar(phase_dir, app_name)
                sidecar_path = phase_dir / ".idi-meta.yaml"
                sidecar_path.write_text(
                    yaml.dump(sidecar, default_flow_style=False, sort_keys=False)
                )

            # Also generate config sidecar if config dir exists
            config_dir = output_dir / "config"
            if config_dir.exists():
                sidecar = generate_sidecar(config_dir, app_name)
                (config_dir / ".idi-meta.yaml").write_text(
                    yaml.dump(sidecar, default_flow_style=False, sort_keys=False)
                )

"""Register scaffold command group."""

from pathlib import Path

import click

from vm_builder.core.scaffold_service import ScaffoldService


def register_scaffold_group(root: click.Group) -> None:
    @root.command("scaffold")
    @click.argument("app_name")
    @click.option("--helm-chart", required=True, help="Helm chart reference (e.g., grafana/grafana)")
    @click.option("--helm-repo", default=None, help="Helm repo URL")
    @click.option("--helm-values", default=None, type=click.Path(exists=True), help="Custom values.yaml")
    @click.option("--compose-file", default=None, type=click.Path(exists=True), help="Docker Compose file for wiring")
    @click.option("--compose-source", default=None, help="Compose source name (e.g., linuxserver)")
    @click.option("--namespace", required=True, help="Target K8s namespace")
    @click.option("--nodeport", default=0, type=int, help="NodePort to assign")
    @click.option("--category", default="Application", help="Registry category")
    @click.option("--output-dir", default=None, type=click.Path(), help="Output directory (default: apps/{app})")
    @click.option("--dry-run", is_flag=True, help="Preview without writing files")
    def scaffold(app_name, helm_chart, helm_repo, helm_values, compose_file,
                 compose_source, namespace, nodeport, category, output_dir, dry_run):
        """Scaffold a new app from a Helm chart and optional Compose file."""
        out = Path(output_dir) if output_dir else None
        svc = ScaffoldService()
        svc.scaffold(
            app_name=app_name,
            helm_chart=helm_chart,
            helm_repo=helm_repo,
            helm_values=helm_values,
            compose_file=compose_file,
            compose_source=compose_source,
            namespace=namespace,
            nodeport=nodeport,
            category=category,
            output_dir=out,
            dry_run=dry_run,
        )
        if dry_run:
            click.echo(f"[DRY RUN] Would scaffold {app_name} to {output_dir or f'apps/{app_name}/'}")
        else:
            click.echo(f"Scaffolded {app_name} successfully.")

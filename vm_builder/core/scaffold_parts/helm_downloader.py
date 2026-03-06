"""Download Helm charts and render via helm template."""

import io
import subprocess
import tarfile
from pathlib import Path
from typing import Optional

import yaml


class HelmChart:
    """Represents a downloaded Helm chart."""

    def __init__(self, chart_path: Path, values: dict):
        self.chart_path = chart_path
        self.values = values


def download_chart(
    chart_ref: str,
    dest_dir: Path,
    repo_url: Optional[str] = None,
) -> Path:
    """Download a Helm chart. Returns path to the .tgz file."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    if repo_url:
        repo_name = chart_ref.split("/")[0]
        result = subprocess.run(
            ["helm", "repo", "add", repo_name, repo_url, "--force-update"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"helm repo add failed: {result.stderr}")

    result = subprocess.run(
        ["helm", "pull", chart_ref, "--destination", str(dest_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"helm pull failed: {result.stderr}")

    tgz_files = list(dest_dir.glob("*.tgz"))
    if not tgz_files:
        raise RuntimeError(f"No .tgz file found in {dest_dir}")
    return tgz_files[0]


def render_chart(
    chart_path: Path,
    release_name: str,
    output_dir: Path,
    values_file: Optional[Path] = None,
    namespace: Optional[str] = None,
) -> Path:
    """Render a Helm chart via helm template. Returns the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "helm", "template", release_name, str(chart_path),
        "--output-dir", str(output_dir),
    ]
    if values_file:
        cmd.extend(["-f", str(values_file)])
    if namespace:
        cmd.extend(["--namespace", namespace])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"helm template failed: {result.stderr}")
    return output_dir


def extract_values(chart_tgz: Path) -> dict:
    """Extract values.yaml from a chart .tgz archive."""
    try:
        with tarfile.open(chart_tgz, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith("/values.yaml") or member.name == "values.yaml":
                    f = tar.extractfile(member)
                    if f:
                        return yaml.safe_load(f.read()) or {}
    except (tarfile.TarError, yaml.YAMLError):
        pass
    return {}

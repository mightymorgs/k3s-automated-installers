"""Tests for path variable type detection."""

import textwrap
from pathlib import Path

from vm_builder.core.template_service_parts.extract_jinja2_variables import (
    extract_jinja2_variables,
)


def test_path_suffix_detected_as_directory(tmp_path: Path) -> None:
    """Variables with dir/directory/mount/mount_point/root suffixes get type 'directory'."""
    template = tmp_path / "test.yaml.j2"
    template.write_text(
        textwrap.dedent("""\
        downloads_dir: {{ downloads_dir }}
        backup_directory: {{ backup_directory }}
        nfs_mount: {{ nfs_mount }}
        smb_mount_point: {{ smb_mount_point }}
        data_root: {{ data_root }}
        storage_path: {{ storage_path | default('/data') }}
        nfs_path: {{ nfs_path }}
        """)
    )
    result = extract_jinja2_variables(template)
    assert result["downloads_dir"]["type"] == "directory"
    assert result["backup_directory"]["type"] == "directory"
    assert result["nfs_mount"]["type"] == "directory"
    assert result["smb_mount_point"]["type"] == "directory"
    assert result["data_root"]["type"] == "directory"
    assert result["storage_path"]["type"] == "directory"
    assert result["nfs_path"]["type"] == "directory"


def test_exact_name_detected_as_directory(tmp_path: Path) -> None:
    """Variables with exact names 'mount_point' or 'root_folder' get type 'directory'."""
    template = tmp_path / "test.yaml.j2"
    template.write_text(
        textwrap.dedent("""\
        mp: {{ mount_point }}
        rf: {{ root_folder }}
        """)
    )
    result = extract_jinja2_variables(template)
    assert result["mount_point"]["type"] == "directory"
    assert result["root_folder"]["type"] == "directory"


def test_non_path_vars_stay_string(tmp_path: Path) -> None:
    """Normal variables and URL-like _path vars stay type 'string'."""
    template = tmp_path / "test.yaml.j2"
    template.write_text(
        textwrap.dedent("""\
        image: {{ image | default('nginx:latest') }}
        timezone: {{ timezone }}
        cpu_request: {{ cpu_request | default('200m') }}
        health_path: {{ health_path | default('/api?mode=version') }}
        """)
    )
    result = extract_jinja2_variables(template)
    assert result["image"]["type"] == "string"
    assert result["timezone"]["type"] == "string"
    assert result["cpu_request"]["type"] == "string"
    assert result["health_path"]["type"] == "string"


def test_path_detection_case_insensitive(tmp_path: Path) -> None:
    """Path detection works regardless of casing."""
    template = tmp_path / "test.yaml.j2"
    template.write_text("val: {{ DATA_DIR }}\nsp: {{ STORAGE_PATH }}\n")
    result = extract_jinja2_variables(template)
    assert result["DATA_DIR"]["type"] == "directory"
    assert result["STORAGE_PATH"]["type"] == "directory"

"""Health command handler."""

from __future__ import annotations

import shutil
import subprocess

import click
from rich.console import Console
from rich.table import Table

_console = Console()


def show_system_health() -> None:
    """Check system health: BWS CLI, gh CLI, and repo sync status."""
    click.echo("=" * 70)
    click.echo("System Health Check")
    click.echo("=" * 70)
    click.echo()

    checks: list[tuple[str, bool, str]] = []

    # Check BWS CLI availability
    bws_ok, bws_msg = _check_bws()
    checks.append(("BWS CLI", bws_ok, bws_msg))

    # Check gh CLI availability
    gh_ok, gh_msg = _check_gh()
    checks.append(("GitHub CLI (gh)", gh_ok, gh_msg))

    # Check git repo status
    git_ok, git_msg = _check_git()
    checks.append(("Git Repository", git_ok, git_msg))

    table = Table(title="Health Status")
    table.add_column("Component", style="cyan", no_wrap=True)
    table.add_column("Status", style="bold")
    table.add_column("Details", style="yellow")

    for name, ok, msg in checks:
        status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        table.add_row(name, status, msg)

    _console.print(table)

    all_ok = all(ok for _, ok, _ in checks)
    click.echo()
    if all_ok:
        click.echo("OK: All health checks passed")
    else:
        click.echo("WARNING: Some checks failed", err=True)


def _check_bws() -> tuple[bool, str]:
    """Check BWS CLI is available and configured."""
    if not shutil.which("bws"):
        return False, "bws CLI not found in PATH"
    try:
        from vm_builder import bws  # noqa: PLC0415

        bws.check_prerequisites()
        return True, "Available and configured"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _check_gh() -> tuple[bool, str]:
    """Check GitHub CLI is available."""
    if not shutil.which("gh"):
        return False, "gh CLI not found in PATH"
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, "Authenticated"
        return False, "Not authenticated"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _check_git() -> tuple[bool, str]:
    """Check git repo status."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False, "Not a git repository"
        dirty = len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0
        if dirty == 0:
            return True, "Clean working tree"
        return True, f"{dirty} uncommitted changes"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

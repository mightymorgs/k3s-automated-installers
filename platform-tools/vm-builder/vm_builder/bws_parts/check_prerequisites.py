"""Prerequisite checks for BWS CLI access."""

from __future__ import annotations


def check_prerequisites() -> None:
    """Verify BWS CLI installed and token present."""
    from vm_builder import bws as bws_mod

    if not bws_mod.os.getenv("BWS_ACCESS_TOKEN"):
        raise EnvironmentError(
            "BWS_ACCESS_TOKEN not set.\n"
            "Run: export BWS_ACCESS_TOKEN=$(cat secrets/secrets.json | "
            "cut -d'=' -f2 | tr -d '\"')\n"
            "Or: source secrets/secrets.json"
        )

    try:
        result = bws_mod.subprocess.run(
            ["bws", "--version"],
            capture_output=True,
            check=True,
            text=True,
        )
        print(f"✓ BWS CLI available: {result.stdout.strip()}")
    except FileNotFoundError:
        raise EnvironmentError(
            "BWS CLI not installed.\n"
            "See: https://bitwarden.com/help/secrets-manager-cli/\n"
            "Install: brew install bitwarden-cli (or equivalent)"
        )
    except bws_mod.subprocess.CalledProcessError as exc:
        raise bws_mod.BWSError(f"BWS CLI check failed: {exc.stderr}")

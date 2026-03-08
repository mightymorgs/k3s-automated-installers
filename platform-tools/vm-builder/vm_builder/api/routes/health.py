"""Health check endpoint."""

import subprocess
from fastapi import APIRouter
from vm_builder import bws
from vm_builder.bws import BWSError
from vm_builder.api.deps import get_repo_status

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health_check():
    """Check BWS CLI and gh CLI availability and BWS connectivity."""
    # BWS check
    bws_status = {"available": False, "connected": False, "error": None}
    try:
        bws.check_prerequisites()
        bws_status["available"] = True
    except (EnvironmentError, BWSError) as e:
        bws_status["error"] = str(e)

    # BWS connectivity check (only if prerequisites passed)
    if bws_status["available"]:
        try:
            bws.list_secrets()
            bws_status["connected"] = True
        except (BWSError, Exception) as e:
            bws_status["error"] = f"BWS reachable but query failed: {e}"

    # gh CLI check
    gh_status = {"available": False, "error": None}
    try:
        result = subprocess.run(
            ["gh", "--version"], capture_output=True, text=True, check=True,
        )
        gh_status["available"] = True
        gh_status["version"] = result.stdout.strip().split("\n")[0]
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        gh_status["error"] = str(e)

    # Repo sync status
    repo_status_obj = get_repo_status()
    if repo_status_obj:
        repo_status = {
            "available": repo_status_obj.available,
            "action": repo_status_obj.action,
            "error": repo_status_obj.error,
            "repo_dir": repo_status_obj.repo_dir,
        }
    else:
        repo_status = {
            "available": False,
            "action": None,
            "error": "Repo not synced yet",
            "repo_dir": None,
        }

    # Status: ok requires bws available+connected, degraded otherwise
    if bws_status["available"] and bws_status["connected"]:
        status = "ok"
    else:
        status = "degraded"

    return {
        "status": status,
        "bws": bws_status,
        "gh": gh_status,
        "repo": repo_status,
    }

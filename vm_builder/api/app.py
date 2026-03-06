"""FastAPI application factory."""

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from vm_builder.core.errors import VmBuilderError
from vm_builder.api.routes import health, init, hypervisor, vm, vm_config, registry, schema_routes, vm_health, webhook, vm_apps, storage
from vm_builder.api.deps import get_repo_service, set_repo_status
from vm_builder import bws

logger = logging.getLogger(__name__)

# Candidate paths for the built React SPA
_SPA_CANDIDATES = [
    Path(__file__).parent.parent.parent / "vm-builder-web" / "dist",  # dev: relative to source
    Path("/app/web/dist"),                                   # container: Dockerfile COPY target
]


# BWS paths for config values fetched at startup
_BWS_CONFIG_KEYS = {
    "GH_TOKEN": "inventory/shared/secrets/github/pat",
    "GITHUB_REPO": "inventory/shared/config/github/repo",
    "BWS_PROJECT_ID": "inventory/shared/config/bws/projectid",
}


def load_bws_config() -> bool:
    """Fetch config values from BWS and set as env vars.

    Returns:
        True if all values were loaded, False if any are missing
        (expected on first boot before /init is run).
    """
    all_loaded = True
    for env_var, bws_path in _BWS_CONFIG_KEYS.items():
        try:
            value = bws.get_secret(bws_path)
            os.environ[env_var] = str(value)
            logger.info("BWS config loaded: %s", env_var)
        except Exception:
            logger.info("BWS config not found: %s (run /init to configure)", bws_path)
            all_loaded = False
    return all_loaded


def reload_bws_config() -> bool:
    """Re-fetch config from BWS and clear cached services.

    Called after /init saves new secrets so the app picks them up
    without a container restart.

    Returns:
        True if all values were loaded, False otherwise.
    """
    result = load_bws_config()
    get_repo_service.cache_clear()
    return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle for the FastAPI app.

    On startup:
    1. Load config from BWS (graceful if missing on first boot).
    2. Sync enterprise repo (clone or pull) if config loaded.
    3. Auto-generate registry when templates are available.
    """
    # --- Load config from BWS ---
    config_loaded = load_bws_config()

    # --- Repo sync (skip if config not loaded — first boot) ---
    repo_svc = get_repo_service()
    if config_loaded:
        status = repo_svc.ensure_repo()
        set_repo_status(status)

        if status.available:
            logger.info(
                "Repo sync: %s (action=%s)", repo_svc.github_repo, status.action
            )
        else:
            logger.warning(
                "Repo sync unavailable: %s -- using fallback registry",
                status.error,
            )
    else:
        logger.warning(
            "BWS config not loaded (first boot?) -- skipping repo sync. "
            "Complete setup at /init then click Sync Repository."
        )

    # --- Registry auto-generation ---
    templates_dir = os.environ.get("TEMPLATES_DIR")
    live_path = os.environ.get("LIVE_REGISTRY_PATH")
    if templates_dir and Path(templates_dir).exists() and live_path and not Path(live_path).exists():
        try:
            from vm_builder.api.deps import get_registry_service
            svc = get_registry_service()
            result = svc.generate()
            logger.info(
                "Startup: auto-generated registry with %d apps",
                len(result.get("apps", {})),
            )
        except Exception:
            logger.exception("Startup: registry auto-generation failed")

    # --- Polling fallback ---
    poll_interval = int(os.environ.get("REFRESH_POLL_INTERVAL_SECONDS", "0"))
    poller = None
    poll_task = None

    if poll_interval > 0:
        from vm_builder.api.deps import get_refresh_coordinator
        from vm_builder.core.refresh_poller import RefreshPoller

        poller = RefreshPoller(
            coordinator=get_refresh_coordinator(),
            repo_service=repo_svc,
            interval_seconds=poll_interval,
        )
        poll_task = asyncio.create_task(poller.start())

    yield

    # --- Shutdown ---
    if poller:
        poller.stop()
    if poll_task:
        await poll_task
    logger.info("Shutting down vm-builder")


def create_app() -> FastAPI:
    app = FastAPI(
        title="vm-builder",
        version="0.1.0",
        description="VM inventory management and deployment orchestration",
        lifespan=lifespan,
    )

    @app.exception_handler(VmBuilderError)
    async def vm_builder_error_handler(request: Request, exc: VmBuilderError):
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.message,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "category": exc.category,
                    "hint": exc.hint,
                    "context": exc.context,
                    "request_id": request_id,
                },
            },
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",  # Vite dev server
            "http://localhost:8080",  # Production container
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Audit middleware: logs every API request/response with redacted secrets.
    # Must be added after CORS so it wraps the actual request processing.
    from vm_builder.api.middleware import AuditMiddleware
    from vm_builder.api.deps import get_audit_logger

    app.add_middleware(AuditMiddleware, audit_logger=get_audit_logger())

    app.include_router(health.router)
    app.include_router(init.router)
    app.include_router(hypervisor.router)
    # vm_health must be registered before vm so that /vms/health
    # is matched before the parameterized /vms/{vm_name} route.
    app.include_router(vm_health.router)
    # vm_apps must be registered before vm so that /vms/{vm_name}/apps
    # is matched before the parameterized /vms/{vm_name} route.
    app.include_router(vm_apps.router)
    app.include_router(vm_config.router)
    app.include_router(vm.router)
    app.include_router(registry.router)
    app.include_router(schema_routes.router)
    app.include_router(webhook.router)
    app.include_router(storage.router)

    # Initialize audit logging for BWS module
    from vm_builder.bws import set_audit_logger as set_bws_audit_logger
    set_bws_audit_logger(get_audit_logger())

    # Serve React SPA static files in production.
    # StaticFiles handles /assets/* (JS, CSS bundles).
    # A catch-all route serves index.html for all client-side routes
    # so React Router can handle them.
    spa_env = os.environ.get("SPA_DIST_DIR")
    candidates = [Path(spa_env)] if spa_env else _SPA_CANDIDATES
    spa_dir: Path | None = None
    for static_dir in candidates:
        if static_dir.exists():
            spa_dir = static_dir
            break

    if spa_dir:
        app.mount("/assets", StaticFiles(directory=str(spa_dir / "assets")), name="spa-assets")

        index_html = spa_dir / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_catchall(full_path: str):
            """Serve index.html for all unmatched routes (SPA client-side routing)."""
            # If the path points to a real file in dist/, serve it
            candidate = spa_dir / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_html)

    return app


app = create_app()

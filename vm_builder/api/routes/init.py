"""Init (shared secrets) API routes."""

import asyncio
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from vm_builder.api.deps import get_init_service
from vm_builder.core.models import SharedSecrets, TailscaleSecrets, TerraformSecrets, \
    CloudflareSecrets, GitHubSecrets, HashiCorpSecrets, ConsoleSecrets, AnsibleSecrets, BWSConfig

router = APIRouter(prefix="/api/v1/init", tags=["init"])


class InitSecretsRequest(BaseModel):
    tailscale: TailscaleSecrets
    terraform: TerraformSecrets
    cloudflare: CloudflareSecrets
    github: GitHubSecrets
    hashicorp: Optional[HashiCorpSecrets] = None
    console: ConsoleSecrets
    ansible: Optional[AnsibleSecrets] = None
    bws: Optional[BWSConfig] = None
    overwrite: bool = False


@router.get("/status")
async def get_init_status():
    svc = get_init_service()
    statuses = await asyncio.to_thread(svc.get_existing_secrets)
    return {"secrets": [s.model_dump() for s in statuses]}


@router.post("/secrets")
async def create_shared_secrets(body: InitSecretsRequest):
    svc = get_init_service()
    secrets = SharedSecrets(
        tailscale=body.tailscale,
        terraform=body.terraform,
        cloudflare=body.cloudflare,
        github=body.github,
        hashicorp=body.hashicorp,
        console=body.console,
        ansible=body.ansible,
        bws=body.bws,
    )
    results = await asyncio.to_thread(svc.write_secrets, secrets, body.overwrite)
    return {"results": [r.model_dump() for r in results]}

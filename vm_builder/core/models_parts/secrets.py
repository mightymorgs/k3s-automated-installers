"""Shared-secret and secret-write models."""

from __future__ import annotations

from enum import Enum
from typing import ClassVar, Optional

from pydantic import BaseModel


class TailscaleSecrets(BaseModel):
    """Tailscale OAuth and API credentials."""

    oauthclientid: str
    oauthclientsecret: str
    tailnet: str
    apikey: Optional[str] = None


class TerraformSecrets(BaseModel):
    """Terraform Cloud credentials."""

    cloudtoken: str
    cloudorganization: str


class CloudflareSecrets(BaseModel):
    """Cloudflare API credentials."""

    apitoken: str
    accountid: str
    zoneid: str


class GitHubSecrets(BaseModel):
    """GitHub personal access tokens."""

    pat: str
    patsecretswrite: str
    repo: Optional[str] = None


class HashiCorpSecrets(BaseModel):
    """HashiCorp Cloud Platform credentials."""

    cloudprojectid: str
    cloudprojectname: str


class ConsoleSecrets(BaseModel):
    """Console login credentials for VMs."""

    username: str
    password: str


class AnsibleSecrets(BaseModel):
    """Ansible vault credentials."""

    vaultpassword: str


class BWSConfig(BaseModel):
    """BWS project configuration."""

    projectid: str


class SharedSecrets(BaseModel):
    """All shared secrets written to BWS during init."""

    tailscale: TailscaleSecrets
    terraform: TerraformSecrets
    cloudflare: CloudflareSecrets
    github: GitHubSecrets
    hashicorp: Optional[HashiCorpSecrets] = None
    console: ConsoleSecrets
    ansible: Optional[AnsibleSecrets] = None
    bws: Optional[BWSConfig] = None

    # Fields that use inventory/shared/config/ instead of secrets/
    _CONFIG_FIELDS: ClassVar[dict[tuple[str, str], str]] = {
        ("github", "repo"): "inventory/shared/config/github/repo",
        ("bws", "projectid"): "inventory/shared/config/bws/projectid",
    }

    def to_bws_dict(self) -> dict[str, str]:
        """Return {bws_path: value} mapping for all secrets."""
        result: dict[str, str] = {}
        for category_name in [
            "tailscale",
            "terraform",
            "cloudflare",
            "github",
            "hashicorp",
            "console",
            "ansible",
            "bws",
        ]:
            category = getattr(self, category_name)
            if category is None:
                continue
            for field_name, value in category.model_dump().items():
                if value is None:
                    continue
                override_key = (category_name, field_name)
                if override_key in self._CONFIG_FIELDS:
                    path = self._CONFIG_FIELDS[override_key]
                else:
                    path = f"inventory/shared/secrets/{category_name}/{field_name}"
                result[path] = value
        return result


class SecretWriteStatus(str, Enum):
    """Outcome of writing a single secret to BWS."""

    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"
    ERROR = "error"


class SecretWriteResult(BaseModel):
    """Result of writing a single secret to BWS."""

    path: str
    status: SecretWriteStatus
    error: Optional[str] = None


class SecretStatus(BaseModel):
    """Existence check for a single BWS secret path."""

    path: str
    exists: bool

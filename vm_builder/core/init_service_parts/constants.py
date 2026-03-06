"""Constants for InitService operations."""

from __future__ import annotations

ALL_SECRET_PATHS = [
    "inventory/shared/secrets/tailscale/oauthclientid",
    "inventory/shared/secrets/tailscale/oauthclientsecret",
    "inventory/shared/secrets/tailscale/tailnet",
    "inventory/shared/secrets/terraform/cloudtoken",
    "inventory/shared/secrets/terraform/cloudorganization",
    "inventory/shared/secrets/cloudflare/apitoken",
    "inventory/shared/secrets/cloudflare/accountid",
    "inventory/shared/secrets/cloudflare/zoneid",
    "inventory/shared/secrets/github/pat",
    "inventory/shared/secrets/github/patsecretswrite",
    "inventory/shared/secrets/console/username",
    "inventory/shared/secrets/console/password",
    "inventory/shared/secrets/hashicorp/cloudprojectid",
    "inventory/shared/secrets/hashicorp/cloudprojectname",
    "inventory/shared/config/github/repo",
    "inventory/shared/config/bws/projectid",
]

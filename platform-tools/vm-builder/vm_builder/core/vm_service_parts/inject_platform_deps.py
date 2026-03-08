"""Auto-inject platform dependencies (traefik, authentik) based on registry metadata."""

from __future__ import annotations


def inject_platform_deps(apps: list[str], registry_data: dict) -> list[str]:
    """Add traefik/authentik to app list when selected apps require them.

    Rules:
    - If any selected app has ``ingress.enabled: true`` -> add ``traefik``
    - If any selected app has ``sso.enabled: true`` -> add ``authentik``

    Already-present entries are not duplicated.  Returns a new list.
    """
    if not apps or not registry_data:
        return list(apps) if apps else []

    all_apps = registry_data.get("apps", {})
    needs_ingress = False
    needs_sso = False

    for app_id in apps:
        meta = all_apps.get(app_id, {})
        if meta.get("ingress", {}).get("enabled"):
            needs_ingress = True
        if meta.get("sso", {}).get("enabled"):
            needs_sso = True
        if needs_ingress and needs_sso:
            break

    result = list(apps)
    if needs_ingress and "traefik" not in result:
        result.append("traefik")
    if needs_sso and "authentik" not in result:
        result.append("authentik")
    return result

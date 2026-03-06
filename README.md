# k3s-automated-installers

Automated app lifecycle generator for k3s portfolios. Converts Helm charts, CRD schemas, Docker Compose files, and OpenAPI specs into molecule-tested Ansible playbooks for all three deployment phases.

## What It Does

```
catalog/ (4 input sources)          vm-builder-templates/apps/{app}/
  compose/   ─┐                       install/   ← Phase 3: kustomize + golden-master playbooks
  openapi/   ─┤─→ generate ─→         config/    ← Phase 4: cross-app wiring playbooks
  crd/       ─┤   + molecule test      ingress/   ← Phase 5: IngressRoute + SSO playbooks
  helm/      ─┘
```

**Phase 3 (Install):** Helm chart → `helm template` → classify manifests → convert to J2 templates → kustomize base → golden-master install playbooks

**Phase 4 (Config/Wiring):** Classify fields from OpenAPI/CRD/compose → determine cross-app edges → mechanical assembler → wiring playbooks

**Phase 5 (Ingress + SSO):** CRD IngressRoute templates → TLS cert-manager → Authentik OAuth2 provider playbooks

All generated playbooks are molecule-tested (Tier 1: syntax, Tier 2: --syntax-check) before output.

## Catalog Structure

```
catalog/
  compose/    # Docker Compose files (community wiring blueprints)
  openapi/    # OpenAPI specs (REST API definitions)
  crd/        # CRD skill artifacts (from operator schemas)
  helm/       # Helm values specs (from chart values.yaml)
```

## Output Target

Generated playbooks write directly into the vm-builder-templates app structure:

```
vm-builder-templates/apps/{app}/
  install/    # Phase 3: 01-deploy.yml, kustomize base, J2 templates
  config/     # Phase 4: 05-wire-{provider}.yml
  ingress/    # Phase 5: IngressRoute, TLS, SSO
  templates/  # Shared J2 templates
  k8s-base/   # Kustomize manifests
```

## Related

- [attention-driven-architecture](https://github.com/mightymorgs/attention-driven-architecture) — IDI monorepo (upstream patterns, not modified)

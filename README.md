# k3s-automated-installers

Automated app lifecycle generator for k3s portfolios. Converts Helm charts, CRD schemas, Docker Compose files, and OpenAPI specs into molecule-tested Ansible playbooks for all three deployment phases.

## What It Does

```
catalog/specs/ (raw inputs)     catalog/skills/ (atomic skills)     vm-builder-templates/apps/{app}/
  compose/   ─┐                   compose/   ─┐                       install/  ← Phase 3
  openapi/   ─┤─→ generate ─→    openapi/   ─┤─→ compile ─→         config/   ← Phase 4
  crd/       ─┤   skills          crd/       ─┤   playbooks          ingress/  ← Phase 5
  helm/      ─┘                   helm/      ─┘
```

**Phase 3 (Install):** Helm chart → `helm template` → classify manifests → convert to J2 templates → kustomize base → golden-master install playbooks

**Phase 4 (Config/Wiring):** Classify fields from OpenAPI/CRD/compose → determine cross-app edges → mechanical assembler → wiring playbooks

**Phase 5 (Ingress + SSO):** CRD IngressRoute templates → TLS cert-manager → Authentik OAuth2 provider playbooks

All generated playbooks are molecule-tested (Tier 1: syntax, Tier 2: --syntax-check) before output.

## Catalog Structure

```
catalog/
  manifest.yaml          # All apps, spec sources, metadata
  specs/                  # Raw downloaded inputs
    compose/              # Docker Compose files
    openapi/              # OpenAPI specs (.json/.yaml)
    crd/                  # CRD schemas (from ArtifactHub)
    helm/                 # Helm values.yaml
  skills/                 # Generated atomic skill artifacts
    compose/              # Skills from compose analysis
    openapi/              # Skills from OpenAPI (facts:// URIs)
    crd/                  # Skills from CRD schemas (crdfacts:// URIs)
    helm/                 # Skills from Helm values
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

- [attention-driven-architecture](https://github.com/mightymorgs/attention-driven-architecture) — IDI monorepo (upstream patterns, ported here)

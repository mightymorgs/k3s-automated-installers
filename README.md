# k3s-automated-installers

Programmatic wiring compiler for k3s app portfolios. Auto-generates Phase 4 config playbooks from CRD schemas, Helm values, Docker Compose, and OpenAPI specs.

## Catalog Structure

```
catalog/
  compose/    # Docker Compose files (community wiring blueprints)
  openapi/    # OpenAPI specs (REST API definitions)
  crd/        # CRD skill artifacts (generated from operator schemas)
  helm/       # Helm values specs (generated from chart values.yaml)
```

## Related

- [attention-driven-architecture](https://github.com/mightymorgs/attention-driven-architecture) — IDI monorepo (upstream patterns, not modified)

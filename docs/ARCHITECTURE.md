# Architecture

## System Overview

k3s-automated-installers is a self-contained pipeline that converts infrastructure knowledge from four machine-readable sources into molecule-tested Ansible playbooks — covering app installation (Phase 3), cross-app wiring (Phase 4), and ingress/SSO configuration (Phase 5).

The core insight: infrastructure knowledge already exists in Helm charts, CRD schemas, Docker Compose files, and OpenAPI specs. Every Helm `values.yaml` contains real working defaults. Every Compose stack encodes proven cross-app wiring. Every CRD schema describes what an operator creates and consumes. An LLM trying to configure infrastructure from scratch wastes tokens reproducing knowledge that already exists in these sources.

This system extracts that knowledge, unifies it through a lifecycle event graph, and emits playbooks with real defaults and real wiring — deterministically, with no manual authoring.

```
                    CATALOG (4 input sources)
                    ========================
        Helm charts    CRD schemas    Compose files    OpenAPI specs
             |              |              |                |
             v              v              v                v
        ┌─────────────────────────────────────────────────────┐
        │           SPEC DOWNLOAD + SKILL GENERATION           │
        │                                                      │
        │  spec_loader → path_extractor → field_extractor      │
        │  → dep_adapters → output_writer                      │
        │                                                      │
        │  Output: catalog/skills/{type}/{service}/*.json      │
        │          with facts:// and crdfacts:// URIs          │
        └──────────────────────┬───────────────────────────────┘
                               │
                               v
        ┌─────────────────────────────────────────────────────┐
        │              LIFECYCLE EVENT SCHEMA                   │
        │                                                      │
        │  Normalize all paradigms into one graph model:       │
        │                                                      │
        │  LifecycleEvent → PRODUCES → Fact                    │
        │  LifecycleEvent → CONSUMES → Fact                    │
        │  LifecycleEvent → PROVIDES_CAPABILITY → Capability   │
        │  LifecycleEvent → REQUIRES_CAPABILITY → Capability   │
        └──────────────────────┬───────────────────────────────┘
                               │
                               v
        ┌─────────────────────────────────────────────────────┐
        │       FALKORDB LITE (embedded graph, no Docker)      │
        │                                                      │
        │  Tree-sitter extractors → GraphOps → FalkorDB        │
        │  Edge builders: intra-service, cross-service,        │
        │                 field-ref, compose, helm values       │
        │                                                      │
        │  Queryable via Cypher (openCypher compatible)        │
        └──────────────────────┬───────────────────────────────┘
                               │
                               v
        ┌─────────────────────────────────────────────────────┐
        │              PLAYBOOK COMPILATION                    │
        │                                                      │
        │  Phase 3: Helm → kustomize → golden-master install   │
        │  Phase 4: Graph query → field classify → assemble    │
        │  Phase 5: CRD IngressRoute → TLS → SSO playbooks    │
        │                                                      │
        │  All playbooks molecule-tested before output          │
        └──────────────────────┬───────────────────────────────┘
                               │
                               v
        ┌─────────────────────────────────────────────────────┐
        │          vm-builder-templates/apps/{app}/             │
        │                                                      │
        │  install/   — Phase 3 playbooks + kustomize          │
        │  config/    — Phase 4 wiring playbooks               │
        │  ingress/   — Phase 5 IngressRoute + SSO             │
        │  templates/ — Shared J2 templates                    │
        │  k8s-base/  — Kustomize manifests                    │
        └──────────────────────┬───────────────────────────────┘
                               │
                               v
        ┌─────────────────────────────────────────────────────┐
        │            EXECUTION (GitHub Actions)                │
        │                                                      │
        │  Phase 3: Install apps on k3s (parallel)             │
        │  Phase 4: Configure cross-app wiring                 │
        │  Phase 5: Ingress + SSO                              │
        │                                                      │
        │  BWS: single source of truth for all vars            │
        └─────────────────────────────────────────────────────┘
```

## Component Map

| Component | Location | Purpose |
|-----------|----------|---------|
| Spec downloader | `scripts/download_specs.py` | Download raw specs to `catalog/specs/` |
| Skill generator | `scripts/generate_skills.py` | Convert specs to atomic skill JSON in `catalog/skills/` |
| Enrichment | `scripts/enrich_skills.py` | Add cross-service dependency edges |
| Graph ingestion | `scripts/ingest_skills.py` | Populate FalkorDB from skill artifacts |
| Scaffold pipeline | `vm_builder/core/scaffold_parts/` | Helm → kustomize → install playbooks |
| Wiring compiler | `vm_builder/core/wiring_compiler_parts/` | Graph query → classify → assemble wiring playbooks |
| VM Builder API | `vm_builder/api/` | FastAPI backend for GUI + workflow triggers |
| VM Builder Web | `vm-builder-web/` | React SPA for cluster management |
| Templates | `vm-builder-templates/apps/` | 32 apps with phase-structured playbooks |
| Workflows | `.github/workflows/` | Phase 0-5 execution pipelines |
| BWS integration | `vm_builder/bws_parts/` | Bitwarden Secrets Manager state management |

## Key Design Decisions

**No Docker required for development.** FalkorDB Lite is an embedded Python graph database (`pip install`). The full pipeline — download, generate, ingest, query — runs locally without containers.

**IDI patterns, not IDI code.** The canonical facts model, tree-sitter extractors, GraphOp pattern, and dep adapter architecture originated in the IDI monorepo. They are ported here as self-contained modules with no upstream dependency.

**BWS is the single source of truth.** Every playbook variable comes from Bitwarden Secrets Manager via Phase 4 extra-vars. No hardcoded hosts, ports, URLs, or API keys in playbooks.

**Molecule-tested before output.** Every generated playbook passes Tier 1 (YAML syntax) and Tier 2 (`ansible-playbook --syntax-check`) before being written to the templates directory.

## Directory Structure

```
k3s-automated-installers/
├── catalog/
│   ├── manifest.yaml              # All 32 apps with spec sources
│   ├── specs/                     # Raw downloaded inputs
│   │   ├── openapi/               # OpenAPI specs
│   │   ├── crd/                   # CRD schemas
│   │   ├── helm/                  # Helm values.yaml
│   │   └── compose/               # Docker Compose files
│   └── skills/                    # Generated atomic skill artifacts
│       ├── openapi/               # REST skills (facts:// URIs)
│       ├── crd/                   # CRD skills (crdfacts:// URIs)
│       ├── helm/                  # Helm value specs
│       └── compose/               # Compose wiring edges
├── schemas/                       # JSON Schema for all artifacts
├── scripts/                       # Pipeline CLI scripts
├── vm_builder/                    # FastAPI backend (291 files)
├── vm-builder-web/                # React SPA
├── vm-builder-templates/          # 32 apps + playbooks + terraform
│   ├── apps/{app}/
│   │   ├── install/               # Phase 3
│   │   ├── config/                # Phase 4
│   │   └── ingress/               # Phase 5
│   └── ansible/molecule/          # Molecule test infrastructure
├── .github/
│   ├── workflows/                 # Phase 0-5 execution
│   ├── actions/                   # Composite actions (BWS, Tailscale)
│   └── scripts/                   # sync-app-state.sh, bws-helpers.sh
├── Dockerfile.vm-builder
└── docker-compose.yml
```

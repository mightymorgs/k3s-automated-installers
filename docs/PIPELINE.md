# The Pipeline: From Specs to Zero-Touch App Installs

## The Problem

Setting up a k3s cluster with interconnected apps requires hundreds of manual decisions: which apps talk to which, what URLs and API keys to pass, which ports to expose, what order to install, how to verify everything works. A single media stack (sonarr + radarr + prowlarr + sabnzbd + jellyfin) needs 12+ wiring playbooks, each with 10-20 fields that must be exactly right.

Today these playbooks are hand-written. Adding a new app means hours of reading docs, writing YAML, debugging connections, and testing. This doesn't scale — every new app multiplies the manual wiring effort with every other app it connects to.

## The Insight

All the knowledge needed to wire these apps already exists in machine-readable form:

- **Helm values.yaml** tells you what config knobs exist and what their defaults are
- **Docker Compose files** from the community tell you which apps connect to which — someone already figured out that sonarr needs sabnzbd's URL and API key
- **CRD schemas** tell you what an operator needs and what it produces — a cert-manager Certificate needs an Issuer and produces a Secret
- **OpenAPI specs** tell you exactly what fields a POST endpoint expects, what types they are, and what the response contains

The pipeline extracts this knowledge, unifies it in a graph, and mechanically generates the same playbooks a human would write — but deterministically, validated, and for ANY app connected to ANY other app. Point it at a Helm chart and an OpenAPI spec, and it produces working playbooks. The 32-app portfolio is the baseline we validate against, not the limit.

## The Canonical Facts Model

Every piece of infrastructure knowledge is expressed as a **fact** with a URI:

```
facts://sonarr/api-v3-downloadclient#id        — REST API output
facts://authentik/providers-oauth2#pk           — REST API output (pk → id alias)
crdfacts://cert-manager.io/Certificate#secretName  — CRD output declaration
crdfacts://core/Secret#name                     — K8s core resource
```

Facts are the universal currency. A REST operation PRODUCES `facts://sonarr/api-v3-downloadclient#id`. A CRD Kind CONSUMES `crdfacts://cert-manager.io/Issuer#name`. The graph connects producers to consumers through fact URIs.

**Alias canonicalization** handles naming inconsistencies across APIs: `pk`, `uuid`, `guid`, `uid` all canonicalize to `id`. `name`, `title`, `label`, `display_name` all canonicalize to `name`. This means `facts://authentik/oauth2#pk` and `facts://authentik/oauth2#uuid` match the same canonical fact.

## Lifecycle Events: The Unifier

The raw facts model has a problem: REST operations, CRD Kinds, Helm charts, and Compose services are different things. A Certificate CRD can't directly express "cert-manager must be installed first." A Helm chart can't express "the k3s cluster must exist."

**Lifecycle events** normalize all paradigms into one traversable pattern:

```
LifecycleEvent → PRODUCES → Fact
LifecycleEvent → CONSUMES → Fact
```

Each source maps to lifecycle events:

| Source | Example | Event | Method |
|--------|---------|-------|--------|
| REST API | `POST /api/v3/downloadclient` | CREATE:downloadclient | http_call |
| CRD | `kubectl apply Certificate` | CREATE:certificate | kubectl_apply |
| Helm | `helm install cert-manager` | INSTALL:cert-manager | helm_install |
| Compose | `sonarr` service | INSTALL:sonarr | compose |
| Ansible | `01-deploy.yml` | INSTALL:grafana | ansible_playbook |

The resolver traverses `LifecycleEvent→CONSUMES→Fact←PRODUCES←LifecycleEvent` — one algorithm, one edge pattern, all paradigm boundaries crossed automatically.

### Capabilities: Automatic Fork Points

When multiple things provide the same capability, the system detects fork points automatically:

```
postgres  → PROVIDES_CAPABILITY → database
mysql     → PROVIDES_CAPABILITY → database
mariadb   → PROVIDES_CAPABILITY → database

langfuse  → REQUIRES_CAPABILITY → database
awx       → REQUIRES_CAPABILITY → database
```

The resolver finds all providers for a required capability and presents valid alternatives. No hardcoded taxonomy — cross-app dependencies are derived statistically from large Docker Compose databases (awesome-compose, LinuxServer, Bitnami, DockSTARTer, and others). When hundreds of compose stacks show that langfuse pairs with postgres in 95% of cases, and awx pairs with postgres in 90%, those are statistical confidence scores derived from real-world evidence.

The more compose stacks you compile, the higher the confidence. A dependency that appears in 3 out of 5 stacks scores differently than one appearing in 300 out of 500. These compose-derived edges are then **confirmed by other sources** — Helm values that expose the same connection knob, CRD schemas with matching input_ref fields, OpenAPI specs with the right POST endpoint. Each confirming source raises the confidence score. The compose stacks provide the initial topology; Helm, CRDs, and REST APIs validate and enrich it.

## The Three-Way Join

No single source covers all cross-app wiring. The power comes from combining them:

```
CRD schema:    GrafanaDatasource has a `url` field (string)
Helm values:   grafana chart has `datasources[].url` knob
Compose:       grafana env var GF_DATASOURCE_URL=http://prometheus:9090

Result:        GrafanaDatasource.url → prometheus
               (DEPENDS_ON, confidence: 0.95, source: crd+compose+helm)
```

| Wiring target | CRD | Helm | Compose | Discovered by |
|--------------|-----|------|---------|---------------|
| grafana→prometheus | GrafanaDatasource.url | datasources[].url | GF_DATASOURCE_URL | All three |
| sonarr→sabnzbd | — | — | SABNZBD_URL | Compose only |
| cert-manager→vault | ClusterIssuer.vault | issuer.vault.server | — | CRD + Helm |
| loki→alertmanager | — | ruler.alertmanager_url | ALERTMANAGER_URL | Helm + Compose |

CRDs define the WHAT (fields, types). Compose defines the WHO (which apps connect). Helm values define the HOW (what config knobs to turn). Together they give you everything needed to generate a wiring playbook.

## Phase 3: Zero-Touch Installation

**Input:** Helm chart for an app
**Output:** Golden-master-compliant install playbook + kustomize base + J2 templates

The scaffold pipeline:

```
Helm chart
  → helm template (render to raw K8s manifests)
  → classify manifests (Secrets/PVCs = protected, Deployments/Services = workload)
  → convert Deployments → StatefulSets (persistence)
  → convert manifests → J2 templates (parameterize with BWS vars)
  → generate kustomize base
  → generate golden-master install playbook:
      - numeric-prefix ordering (<40 = always apply, ≥40 = kubectl_action)
      - split-apply (Secrets always kubectl apply, workloads use kubectl_action)
      - two-step wait (rollout status + pod ready)
      - dry-run=server validation
      - health check with retries
  → generate PushSecret CRD template (if secrets detected)
  → molecule test (Tier 1 + Tier 2)
```

The generated playbook follows the exact same patterns as the hand-written golden master at `apps/_golden-master/install/01-deploy.yml` (854 lines, 23 improvements).

## Phase 4: Automated Cross-App Wiring

**Input:** Cross-app edges from the lifecycle event graph
**Output:** Wiring playbooks that configure apps to talk to each other

For each cross-app edge (e.g., sonarr→sabnzbd):

```
1. Query graph: what fields does sonarr's downloadclient POST need?
2. Mechanical classifier (6 layers, ~70% of fields):
   Layer 1: host/url/baseUrl → provider_address (use sabnzbd's ClusterIP)
   Layer 2: apiKey/token/password → provider_credential (from BWS)
   Layer 3: boolean with default → static_default
   Layer 4: enum → static_default (first value)
   Layer 5: enrichment FK edge → provider_ref
   Layer 6: BWS _state pattern → consumer_ref/provider_ref
3. LLM classifier (remaining ~30%, field classification only — no code gen)
4. Mechanical assembler → complete Ansible playbook:
   - Skip if provider not installed
   - Validate required vars
   - Verify consumer API accessible
   - Verify provider API accessible
   - Idempotent check (GET existing)
   - Create wiring (POST with classified fields)
   - Display result
5. Molecule validation (Tier 1 + Tier 2)
6. LLM repair loop if validation fails (max 3 retries, reclassify fields)
```

The LLM classifies fields. It does NOT generate code. The assembler is purely mechanical — template expansion from classified fields.

## Phase 5: Ingress + SSO

**Input:** CRD schemas for Traefik IngressRoute + cert-manager Certificate + Authentik OAuth2 Provider
**Output:** Ingress playbooks that expose apps with TLS and SSO

Each app that has `ingress.enabled: true` in its metadata gets:
- Traefik IngressRoute CRD (from CRD schema)
- cert-manager Certificate CRD (from CRD schema)
- Authentik OAuth2 Provider + Application (from OpenAPI spec)

All three are lifecycle events in the graph. The resolver chains them: IngressRoute CONSUMES a Certificate, Certificate CONSUMES an Issuer, Issuer CONSUMES a Vault PKI mount. The playbook assembler generates the full chain.

## The BWS Loop

Bitwarden Secrets Manager is the state database for everything:

```
Scaffold seeds BWS _config with all Helm chart vars + defaults
Phase 3 installs apps → extracts API keys/URLs → writes to BWS _state
Phase 4 reads BWS _state + _config → configures cross-app wiring → writes results back
Phase 5 reads BWS _state + _config → configures ingress/SSO → writes results back
GUI reads BWS → shows live state → user edits _config → triggers re-execution
```

Every Helm chart variable is written to BWS `_config` with its default value from `values.yaml`. This means every configurable knob for every app is available in BWS before the first deploy — the GUI can show them, the user can override them, and the playbooks consume them.

Every playbook variable comes from BWS via extra-vars. No hardcoded values. `_config` holds the template variable values (how it was built), `_state` holds runtime state (what's running now). The generated playbooks reference BWS vars using the pattern `{{ app_field }}` which maps to `_state.apps.{app}.{field}` or `_config.{app}.{field}`.

## What Makes This Different

This is not an LLM generating infrastructure code. This is a **compiler**:

1. **Deterministic** — same inputs always produce the same playbooks
2. **Validated** — every generated playbook passes molecule tests before output
3. **Grounded** — every field value traces back to a real source (schema, compose file, Helm default)
4. **Repairable** — if validation fails, the LLM reclassifies fields (not regenerates code)
5. **Self-contained** — no Docker, no Neo4j, no external services needed for development
6. **Incremental** — add a new app to the manifest, run the pipeline, get working playbooks
7. **Universal** — works for ANY app with a Helm chart, OpenAPI spec, or Docker Compose file — not limited to a fixed app list

The end state: `pip install`, point at a Helm chart, get a fully wired app with install + config + ingress playbooks, molecule-tested, ready to deploy on any k3s cluster. The 32-app portfolio is the test suite, not the boundary.

# The Canonical Facts Model

> An executable dependency graph for fully programmatic multi-app k3s deployment. Actions and facts are first-class nodes. Edges encode consumption, production, ownership, and emission. The compiler walks the graph backwards from desired state and emits forward execution waves.

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

## The Model

Five node types. Seven edge types. One compiler.

Installing 32 interconnected k3s apps requires hundreds of wiring decisions — sonarr needs sabnzbd's API key, grafana needs prometheus's endpoint, cert-manager needs vault's PKI mount. Each decision is a field in an API call, a CRD spec, or a config file. Each field's value comes from somewhere else in the stack.

A static dependency map can tell you *what* depends on *what*. But it cannot answer: **what is the exact ordered sequence of actions needed to make the desired state true?**

This model answers that question programmatically. It encodes the actions themselves — not just the relationships — so the graph can be compiled into an execution plan without human intervention.

The shift:

```
Old: "Grafana depends on Prometheus"          → structure, not executable
New: "install.prometheus PRODUCES fact:prometheus.service_url
      configure.grafana.datasource CONSUMES fact:prometheus.service_url"
                                              → executable, sortable, verifiable
```

## Design Influences

The model borrows from two dependency resolution systems:

**From Nix:** Actions expose derivation-like declared inputs and outputs, even when execution is impure. Identity is content-addressed (hash of resolved inputs determines whether re-execution is needed). If resolved input values haven't changed, skip. If an action re-executes but produces identical output values, all downstream actions skip too (early cutoff). Many actions (API calls, Helm installs, CRD applies) are inherently impure — they mutate cluster state, call external APIs, write to mutable storage. The model does not claim purity. It claims **declared inputs and outputs with content-addressed invalidation**, which is the useful part of the Nix model without the false promise of hermeticity.

**From Bazel:** Facts flow between actions as typed *providers* — not opaque blobs. Each fact has a shape (identity, addressability, credential). Actions declare typed inputs and outputs. Type mismatches are caught at compile time, not execution time.

The hybrid: **Nix's content-addressed invalidation model + Bazel's typed provider contracts.**

### Nodes

```
Fact       — a single piece of infrastructure data with a globally unique URI
Action     — an operation that consumes facts and produces facts
App        — groups related facts and actions (the 32-app portfolio)
Artifact   — a generated output (playbook, CRD manifest, config template)
Capability — a provider-agnostic role (e.g., "database") with multiple possible providers
```

### Edges

```
Action ──CONSUMES──▶ Fact             "this action needs this fact to exist"
Action ──PRODUCES──▶ Fact             "this action makes this fact true"
Action ──TARGETS──▶  App              "this action operates on this app"
Action ──EMITS──▶    Artifact         "this action generates this output file"
Fact   ──BELONGS_TO──▶ App            "this fact is owned by this app"
Action ──PROVIDES_CAPABILITY──▶ Capability  "this action can satisfy this role"
Action ──REQUIRES_CAPABILITY──▶ Capability  "this action needs this role filled"
```

### The Compiler

```
1. Define desired end state (set of target facts)
2. Walk backwards: for each target fact, find the action that PRODUCES it
3. For each producing action, find the facts it CONSUMES
4. Recurse until all leaf facts are either:
   a. Already satisfied (exist in BWS _state)
   b. Produced by an action with no unsatisfied inputs
   c. A fork point (multiple producers — prompt for selection)
5. Topological sort the reachable action subgraph
6. Emit execution waves (actions in the same wave have no mutual dependencies)
```

This is the fully programmatic bit. No human decides the sequence. The graph decides.

## Facts: Definitions and Instances

The model distinguishes between two levels of fact:

**Fact definition** — a schema-level declaration that a certain kind of data *can* exist. Derived from specs at compile time. Example: "a cert-manager Certificate produces a Secret name."

**Fact instance** — a concrete realized value in a specific deployment. Exists at runtime in BWS `_state`. Example: "the wildcard certificate produced Secret `wildcard-tls` in namespace `cert-manager`."

Fact definitions live in the graph (as Fact nodes). Fact instances live in BWS `_state` (as key-value pairs). The compiler works with definitions to build the action graph. The executor resolves definitions to instances at runtime.

```
Compile time:  crdfacts://core/Secret#name         (definition — "a Secret name will exist")
Runtime:       bws._state.cert-manager.secret_name = "wildcard-tls"  (instance — the actual value)
```

This distinction matters for content addressing. An action's `input_hash` must include **resolved instance values**, not just definition URIs, because two runs with the same fact definitions but different values (e.g., rotated credential) must produce different hashes.

## Fact URIs

A fact URI uniquely identifies a fact definition across all paradigms. Four URI schemes cover four input paradigms. A fifth scheme (`statefacts://`) covers lifecycle state facts produced by actions themselves.

```
facts://sonarr/api-v3-downloadclient#id                  REST API output
facts://authentik/providers-oauth2#pk                     REST API (pk → id via alias)
crdfacts://cert-manager.io/Certificate#secretName         CRD output declaration
crdfacts://core/Secret#name                               K8s core resource
helmfacts://grafana/datasources#url                       Helm values cross-app ref
statefacts://grafana/datasource.prometheus#configured      Lifecycle state (action output)
statefacts://grafana/datasource.prometheus#verified        Verification state
```

The `statefacts://` scheme eliminates the naming inconsistency between spec-derived facts and action-produced lifecycle facts. All facts use the same URI structure.

### URI Structure

```
scheme://namespace/resource#field
```

| Component | REST (`facts://`) | CRD (`crdfacts://`) | Helm (`helmfacts://`) | State (`statefacts://`) |
|-----------|-------------------|---------------------|----------------------|------------------------|
| Namespace | Service name | API group | Chart name | Service name |
| Resource  | API resource path | Kind name | Values key path | Action target |
| Field     | Response field | Spec/status field | Nested value key | State field |

### Fact Shapes

Every fact has a shape that classifies what it carries. Shapes enable type-safe matching between producers and consumers (Bazel-style typed providers).

| Shape | What it carries | Detection signals |
|-------|----------------|-------------------|
| **identity** | Name or ID of a resource | field ends in `name`, `id`, `ref`; inside `*Ref` object |
| **addressability** | How to reach a resource | field contains `host`, `port`, `url`, `endpoint`; format: `uri` |
| **credential** | Authentication to a resource | field contains `password`, `token`, `secret`, `key`; `sensitive: true` |
| **config** | A configuration parameter | none of the above; has a default value |
| **lifecycle** | Action completion state | `statefacts://` scheme; `configured`, `verified`, `ready` fields |

### Alias Canonicalization

Different APIs use different names for the same concept. The alias registry normalizes them:

```python
FIELD_ALIAS_GROUPS = {
    "id":         {"id", "pk", "uuid", "guid", "uid"},
    "name":       {"name", "title", "label", "display_name"},
    "created_at": {"created_at", "created", "timestamp", "date_created"},
    "owner":      {"owner", "owner_id", "creator", "created_by"},
}
```

When authentik returns `pk` and sonarr expects `id`, both canonicalize to `id` — they match. Field normalization also applies: `camelCase` → `snake_case`, lowercase, ID suffix stripping (`tunnel_id` → `tunnel`).

## Actions

Actions are first-class nodes — not metadata hanging off edges. Every action declares:
- what facts it **consumes** (preconditions)
- what facts it **produces** (postconditions)
- **how** to execute (executor type + parameters)
- what **artifacts** it emits (generated files)

### Action Schema

```python
@dataclass
class Action:
    action_id: str          # "install.prometheus", "configure.grafana.datasource.prometheus"
    phase: str              # install | configure | verify | delete
    executor: str           # helm | crd | ansible | api | template | config_file
    service: str            # target app ("grafana")
    source_service: str     # source app if cross-app ("prometheus"), else None

    # What this action needs (input derivation refs)
    consumes: list[FactRef] # facts that must exist before this action runs

    # What this action makes true (output derivation refs)
    produces: list[FactRef] # facts that exist after this action succeeds

    # Execution parameters (executor-specific)
    executor_args: dict     # {"chart": "prometheus/prometheus", "namespace": "monitoring"}

    # Static values (not from other actions)
    defaults: dict          # {"replicaCount": 1, "installCRDs": True}

    # Idempotency
    idempotency_mode: str   # "check_before_create" | "apply" | "upsert" | "none"
    idempotency_check: str  # GET endpoint or kubectl get command for pre-check

    # Content addressing (Nix-style) — computed at execution time, not compile time
    input_hash: str | None  # null in Action JSON; at runtime: hash(sorted(resolved_values) + executor_args + defaults + template_version)

    # Artifact generation
    artifact_template: str  # path to Jinja2/Ansible template, if any
```

### Action Phases

```
INSTALL    — deploy an app (Helm install, Ansible playbook, docker compose up)
CONFIGURE  — wire two apps together (API call, CRD apply, config file)
VERIFY     — confirm a wiring is working (GET endpoint, health check)
DELETE     — remove a resource or wiring
```

### Executors

The graph does not care whether something is a Helm install, a CRD apply, or an API call. It only cares about what facts an action needs and what facts it produces.

| Executor | What it does | Example |
|----------|-------------|---------|
| `helm` | `helm install/upgrade` | install.prometheus |
| `crd` | `kubectl apply` a CRD manifest | configure.cert-manager.issuer |
| `ansible` | Run an Ansible playbook | install.grafana |
| `api` | HTTP call to a REST API | configure.sonarr.downloadclient.sabnzbd |
| `template` | Render a Jinja2 template to a file | emit IngressRoute manifest |
| `config_file` | Write a config file from classified fields | configure.loki.alertmanager |

### Verification Actions

Verification is not a side-effect bolted onto configure actions. Verification actions are first-class nodes in the graph with their own CONSUMES/PRODUCES edges.

```
Action: configure.grafana.datasource.prometheus
  CONSUMES: facts://prometheus/service#url
  CONSUMES: statefacts://grafana/service#api_ready
  PRODUCES: statefacts://grafana/datasource.prometheus#configured

Action: verify.grafana.datasource.prometheus
  CONSUMES: statefacts://grafana/datasource.prometheus#configured
  PRODUCES: statefacts://grafana/datasource.prometheus#verified
```

The verify action is only reachable if the configure action succeeded. And downstream actions that depend on verified state (e.g., a dashboard that needs the datasource) naturally sort after verification.

## How Input Sources Map to Actions

Each of the four input sources generates actions with typed CONSUMES/PRODUCES edges.

### OpenAPI Specs → API Actions

```
POST /api/v3/downloadclient in sonarr
  → Action: configure.sonarr.downloadclient.sabnzbd
    phase: configure
    executor: api
    consumes: [facts://sabnzbd/api#apikey, facts://sonarr/system#api_ready]
    produces: [statefacts://sonarr/downloadclient.sabnzbd#configured]
    executor_args: {method: POST, endpoint: /api/v3/downloadclient}
    idempotency_mode: check_before_create
    idempotency_check: GET /api/v3/downloadclient?name=SABnzbd
```

### CRD Schemas → CRD Actions

```
Certificate in cert-manager
  → Action: configure.cert-manager.certificate.wildcard
    phase: configure
    executor: crd
    consumes: [crdfacts://cert-manager.io/Issuer#name]
    produces: [crdfacts://core/Secret#name]
    executor_args: {kind: Certificate, apiVersion: cert-manager.io/v1}
    idempotency_mode: apply
```

### Helm Charts → Install Actions

```
helm install cert-manager
  → Action: install.cert-manager
    phase: install
    executor: helm
    consumes: []  (no cross-app deps for install)
    produces: [
      crdfacts://cert-manager.io/Certificate#name,
      crdfacts://cert-manager.io/Issuer#name,
      statefacts://cert-manager/service#api_ready
    ]
    executor_args: {chart: jetstack/cert-manager, namespace: cert-manager}
    defaults: {installCRDs: true, replicaCount: 1}
```

### Docker Compose → Cross-App Evidence

Compose files don't generate actions directly. They provide **statistical confidence** for edges discovered from other sources, and they surface cross-app edges that schemas alone miss.

```
sonarr depends_on sabnzbd in 95% of media stacks
  → confidence boost on: configure.sonarr.downloadclient.sabnzbd CONSUMES facts://sabnzbd/api#apikey

grafana env GF_DATASOURCE_URL=http://prometheus:9090
  → evidence for: configure.grafana.datasource.prometheus CONSUMES facts://prometheus/server#endpoint
```

Confidence scoring from signal agreement:

| Signals | Confidence | Meaning |
|---------|-----------|---------|
| CRD + Helm + Compose all agree | 0.95 | High confidence — three independent confirmations |
| Two sources agree | 0.80 | Likely edge |
| Single source only | 0.50 | Possible — needs verification |

## Phase 3: Zero-Touch Installation (The Scaffold Pipeline)

**Input:** Helm chart for an app
**Output:** Golden-master-compliant install playbook + kustomize base + J2 templates

We don't deploy with Helm. Helm is used as a **source** — `helm template` renders the chart to raw K8s manifests, then the scaffold pipeline converts those into kustomize + StatefulSets. This is deliberate: kustomize + StatefulSets enable non-destructive live updates to the cluster via `kubectl apply`. Helm's upgrade/rollback model would require tearing down and recreating resources. With kustomize, changing a var in BWS triggers a `kubectl apply` that patches only what changed — pods stay running, no downtime.

The scaffold pipeline:

```
Helm chart (source only — not used for deployment)
  → helm template (render to raw K8s manifests)
  → classify manifests (Secrets/PVCs = protected, Deployments/Services = workload)
  → convert Deployments → StatefulSets (persistent, rolling-update capable)
  → convert manifests → J2 templates (parameterize with BWS vars)
  → generate kustomize base (the actual deployment mechanism)
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

This is how install actions actually execute. The action graph declares `install.{app}` with its CONSUMES/PRODUCES edges; the scaffold pipeline is the mechanical process that turns a Helm chart into the Ansible playbook that fulfills that install action.

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

## Content Addressing and Early Cutoff

Every action has an `input_hash` — the hash of its **resolved input values** (not just URIs), executor args, defaults, and template version. This uses resolved values because two runs with the same fact URIs but different values (e.g., rotated credential at the same URI) must trigger re-execution.

### Skip Unchanged Actions

```
input_hash = sha256(
    sorted(resolved_fact_values)     # actual values from BWS _state, not just URIs
    + executor_args                   # method, endpoint, headers
    + defaults                        # static field values
    + artifact_template_hash          # template content version
)

if bws_state[action_id].input_hash == current_input_hash:
    skip  # nothing changed, don't re-execute
```

The hash includes everything that could affect the action's output. If any of these change — a credential rotates, an executor arg is updated, a template is modified — the action re-runs.

### Early Cutoff

If an action re-executes (because an input changed) but produces **identical output facts**, all downstream actions skip. This prevents cascading re-execution when a leaf change doesn't propagate.

```
install.sabnzbd re-executes (new chart version)
  → sabnzbd API key unchanged (same output fact value)
  → configure.sonarr.downloadclient.sabnzbd skips (input_hash unchanged)
  → verify.sonarr.downloadclient.sabnzbd skips
```

### Fixed-Output Actions

Most actions are impure (API calls, Helm installs, CRD applies against a mutable cluster). A narrow subset — **predictable install facts** like service URLs derived from namespace + service name — can declare expected output values in advance, like Nix's fixed-output derivations:

```python
Action: install.prometheus
  expected_outputs: {
      "facts://prometheus/service#url": "prometheus-server.monitoring.svc.cluster.local:9090",
      "statefacts://prometheus/service#api_ready": True,
  }
  # Output facts are verified against expected values after execution
  # If outputs match: downstream input_hash remains stable → early cutoff
  # If outputs differ: downstream actions re-evaluate
```

This applies to a small set of install actions where the output is deterministic from the Helm release name and namespace. Most configure actions, CRD applies, and API calls cannot predict their outputs — they are standard impure actions with post-execution output capture.

## Satisfaction Modes

Not every CONSUMES edge means the same thing. The `satisfaction` property on a CONSUMES edge declares what "satisfied" means for that input:

| Mode | Meaning | Compiler behavior |
|------|---------|-------------------|
| **`required_value`** | Fact instance must exist with a concrete value in BWS `_state` | Block action until producing action completes |
| **`required_verified`** | Fact must exist AND its verify action must have succeeded | Block until verify action in the producing chain passes |
| **`any_provider`** | Any action providing this capability satisfies it (fork point) | Present provider options; user selects |
| **`optional_with_default`** | Use fact value if available; fall back to default if not | Action proceeds with default; skip if provider not installed |

```cypher
// Required value — hard block
(:Action {action_id: "configure.sonarr.downloadclient.sabnzbd"})
  -[:CONSUMES {satisfaction: "required_value", shape: "credential"}]->
  (:Fact {uri: "facts://sabnzbd/api#apikey"})

// Optional with default — soft dependency
(:Action {action_id: "configure.sonarr.downloadclient.sabnzbd"})
  -[:CONSUMES {satisfaction: "optional_with_default", default: "tv-sonarr"}]->
  (:Fact {uri: "facts://sonarr/config#tv_category"})

// Any provider — fork point
(:Action {action_id: "install.langfuse"})
  -[:CONSUMES {satisfaction: "any_provider"}]->
  (:Fact {uri: "facts://database/service#endpoint"})
```

Satisfaction modes affect topological sorting: `required_value` and `required_verified` create hard edges in the DAG. `optional_with_default` creates soft edges that are dropped if the provider isn't installed. `any_provider` triggers fork point resolution.

## Capabilities and Fork Points

When multiple actions can produce the same fact (or interchangeable facts), the system detects a fork point.

```
Action: install.postgres   PRODUCES facts://database/service#endpoint (shape: addressability)
Action: install.mysql      PRODUCES facts://database/service#endpoint (shape: addressability)
Action: install.mariadb    PRODUCES facts://database/service#endpoint (shape: addressability)

Action: install.langfuse   CONSUMES facts://database/service#endpoint (satisfaction: any_provider)
```

### Capability Derivation (Heuristic Bootstrap)

Capability clusters are initially **seeded from Docker Compose stack co-occurrence statistics**. This is a heuristic bootstrap mechanism, not foundational truth. Compose examples are noisy, some ecosystems are overrepresented, and valid alternatives may barely appear in public stacks.

**Bootstrap (automatic, heuristic):**
1. Services that appear as `depends_on` alternatives for the same consumers cluster together
2. postgres and mysql both serve as database targets for langfuse, grafana, awx in compose stacks
3. Therefore: `{postgres, mysql, mariadb}` form an initial cluster
4. The cluster label comes from the most frequent parent key in Helm values (`database.host`)
5. Confidence reflects compose coverage — not absolute truth

**Refinement (curated, authoritative):**
Compose-derived clusters are refined by additional evidence:
- **Helm values:** do multiple charts expose the same config key pattern (`database.host`, `database.port`)?
- **CRD schemas:** do multiple operators accept the same input_ref Kind?
- **Curated labels:** a `capabilities.yaml` file can override or correct cluster names and membership
- **User overrides:** fork selections in BWS `_state` are authoritative for that deployment

When the compiler encounters a fork point, it pauses for user selection:

```
langfuse requires capability: database
  Option A: postgres (confidence: 0.95, compose + helm + curated)
  Option B: mysql (confidence: 0.60, compose only)
  Option C: mariadb (confidence: 0.55, compose only)
```

Selected forks persist in BWS `_state` and apply to all future compilations.

## FalkorDB Schema

The graph is stored in FalkorDB Lite (embedded, `pip install`, no Docker). Both FalkorDB and Neo4j speak openCypher.

### Schema Definition

```cypher
// --- Node indexes ---

// Fact nodes
CREATE INDEX FOR (f:Fact) ON (f.uri)
CREATE INDEX FOR (f:Fact) ON (f.service)
CREATE INDEX FOR (f:Fact) ON (f.shape)

// Action nodes
CREATE INDEX FOR (a:Action) ON (a.action_id)
CREATE INDEX FOR (a:Action) ON (a.service)
CREATE INDEX FOR (a:Action) ON (a.phase)
CREATE INDEX FOR (a:Action) ON (a.executor)
CREATE INDEX FOR (a:Action) ON (a.input_hash)

// App nodes
CREATE INDEX FOR (app:App) ON (app.name)

// Artifact nodes
CREATE INDEX FOR (art:Artifact) ON (art.path)

// Capability nodes
CREATE INDEX FOR (c:Capability) ON (c.name)
```

### Node Properties

```cypher
// Fact
(:Fact {
    uri: "facts://sonarr/api-v3-downloadclient#id",
    service: "sonarr",
    resource: "api-v3-downloadclient",
    field: "id",
    canonical_field: "id",
    shape: "identity",          // identity | addressability | credential | config
    paradigm: "rest"            // rest | crd | helm | compose
})

// Action
(:Action {
    action_id: "configure.sonarr.downloadclient.sabnzbd",
    phase: "configure",         // install | configure | verify | delete
    executor: "api",            // helm | crd | ansible | api | template | config_file
    service: "sonarr",
    source_service: "sabnzbd",
    executor_args_json: '{"method":"POST","endpoint":"/api/v3/downloadclient"}',
    defaults_json: '{"enable":true,"protocol":"usenet","name":"SABnzbd"}',
    idempotency_mode: "check_before_create",
    idempotency_check: "GET /api/v3/downloadclient",
    input_hash: "a1b2c3d4...",
    artifact_template: "templates/wire-downloadclient.yml.j2"
})

// App
(:App {
    name: "sonarr",
    namespace: "media",
    helm_chart: "sonarr/sonarr",
    has_api: true,
    has_crd: false
})

// Artifact
(:Artifact {
    path: "apps/sonarr/configure/wire-sabnzbd.yml",
    type: "ansible_playbook",   // ansible_playbook | crd_manifest | config_template
    generated_by: "configure.sonarr.downloadclient.sabnzbd"
})

// Capability
(:Capability {
    name: "database",
    providers: ["postgres", "mysql", "mariadb"],
    derived_from: "compose_cooccurrence"
})
```

### Edge Properties

```cypher
// Action consumes a fact (precondition)
(:Action)-[:CONSUMES {
    satisfaction: "required_value",  // required_value | required_verified | any_provider | optional_with_default
    default: null,                  // fallback value when satisfaction is optional_with_default
    shape: "credential",            // expected shape
    lineage: "copy",                // copy | transform | reference
    confidence: 0.95
}]->(:Fact)

// Action produces a fact (postcondition)
(:Action)-[:PRODUCES {
    shape: "identity",
    propagated: false               // true if fact flows transitively to downstream consumers
}]->(:Fact)

// Action targets an app
(:Action)-[:TARGETS]->(:App)

// Action emits an artifact
(:Action)-[:EMITS]->(:Artifact)

// Fact belongs to an app
(:Fact)-[:BELONGS_TO]->(:App)

// Capability edges
(:Action)-[:PROVIDES_CAPABILITY {confidence: 0.95}]->(:Capability)
(:Action)-[:REQUIRES_CAPABILITY]->(:Capability)
```

### Illustrative Query Fragments

These Cypher fragments illustrate the compiler's intent. The full recursive backward walk, fork resolution, and early-cutoff logic require procedural code around these patterns — they are not standalone compiler queries.

```cypher
// 1. Find all actions needed for a desired fact (backward walk)
MATCH path = (target_fact:Fact {uri: $desired_fact_uri})
  <-[:PRODUCES]-(a:Action)-[:CONSUMES]->(dep_fact:Fact)
  <-[:PRODUCES]-(dep_action:Action)
RETURN path

// 2. Build the full action dependency graph for installed apps
MATCH (a:Action)-[:CONSUMES]->(f:Fact)<-[:PRODUCES]-(dep:Action)
WHERE a.service IN $installed_apps AND dep.service IN $installed_apps
RETURN a.action_id AS action,
       collect(dep.action_id) AS depends_on

// 3. Find fork points (multiple producers for same fact)
MATCH (a1:Action)-[:PRODUCES]->(f:Fact)<-[:PRODUCES]-(a2:Action)
WHERE a1.action_id <> a2.action_id
RETURN f.uri, collect(DISTINCT a1.action_id + a2.action_id) AS providers

// 4. Get execution waves (topological layers)
// (computed in Python after fetching the dependency graph from query 2)

// 5. Check what's already satisfied (early cutoff)
MATCH (a:Action)
WHERE a.input_hash = $stored_hash
RETURN a.action_id AS skip_action

// 6. Get the full action chain for a wiring target
MATCH (consumer:App {name: $consumer})<-[:TARGETS]-(a:Action {phase: "configure"})
      -[:CONSUMES]->(f:Fact)-[:BELONGS_TO]->(provider:App {name: $provider})
RETURN a.action_id, f.uri, a.executor, a.executor_args_json
```

## The 22 Wiring Targets

Every known cross-app wiring decomposes into install → configure → verify action chains. The 22 targets below serve as the validation corpus — they exercise the model's expressiveness and verify that the decomposition is plausible. Full automatic derivation end-to-end for all 22 remains the goal, not a current claim.

### Media Stack (Compose-dominant — no CRDs)

| Wiring Target | Install Actions | Configure Action | Executor | Key Consumed Facts |
|---------------|----------------|-----------------|----------|-------------------|
| prowlarr→radarr | install.prowlarr, install.radarr | configure.radarr.indexer.prowlarr | api | facts://prowlarr/api#apikey, facts://prowlarr/service#url |
| prowlarr→sonarr | install.prowlarr, install.sonarr | configure.sonarr.indexer.prowlarr | api | facts://prowlarr/api#apikey, facts://prowlarr/service#url |
| prowlarr→qbittorrent | install.prowlarr, install.qbittorrent | configure.prowlarr.downloadclient.qbittorrent | api | facts://qbittorrent/service#url, facts://qbittorrent/auth#password |
| prowlarr→sabnzbd | install.prowlarr, install.sabnzbd | configure.prowlarr.downloadclient.sabnzbd | api | facts://sabnzbd/api#apikey, facts://sabnzbd/service#url |
| sonarr→sabnzbd | install.sonarr, install.sabnzbd | configure.sonarr.downloadclient.sabnzbd | api | facts://sabnzbd/api#apikey, facts://sabnzbd/service#url |
| sonarr→qbittorrent | install.sonarr, install.qbittorrent | configure.sonarr.downloadclient.qbittorrent | api | facts://qbittorrent/service#url, facts://qbittorrent/auth#password |
| sonarr→jellyfin | install.sonarr, install.jellyfin | configure.sonarr.notification.jellyfin | api | facts://jellyfin/api#apikey, facts://jellyfin/service#url |
| radarr→sabnzbd | install.radarr, install.sabnzbd | configure.radarr.downloadclient.sabnzbd | api | facts://sabnzbd/api#apikey |
| radarr→qbittorrent | install.radarr, install.qbittorrent | configure.radarr.downloadclient.qbittorrent | api | facts://qbittorrent/service#url |
| radarr→jellyfin | install.radarr, install.jellyfin | configure.radarr.notification.jellyfin | api | facts://jellyfin/api#apikey |

### Monitoring Stack (CRD + Helm)

| Wiring Target | Install Actions | Configure Action | Executor | Key Consumed Facts |
|---------------|----------------|-----------------|----------|-------------------|
| grafana→prometheus | install.grafana, install.prometheus | configure.grafana.datasource.prometheus | api | facts://prometheus/service#url, facts://grafana/auth#admin_credential |
| grafana→loki | install.grafana, install.loki | configure.grafana.datasource.loki | api | facts://loki/service#url |
| grafana→alertmanager | install.grafana, install.alertmanager | configure.grafana.datasource.alertmanager | api | facts://alertmanager/service#url |
| prometheus→alertmanager | install.prometheus, install.alertmanager | configure.prometheus.alertmanager | helm | helmfacts://prometheus/alertmanager#url |
| loki→alertmanager | install.loki, install.alertmanager | configure.loki.ruler.alertmanager | helm | helmfacts://alertmanager/service#url |

### Security Stack (CRD-dominant)

| Wiring Target | Install Actions | Configure Action | Executor | Key Consumed Facts |
|---------------|----------------|-----------------|----------|-------------------|
| cert-manager→vault | install.cert-manager, install.vault | configure.cert-manager.issuer.vault | crd | facts://vault/pki#mount_path, facts://vault/auth#token |
| awx→vault | install.awx, install.vault | configure.awx.credential.vault | api | facts://vault/service#url, facts://vault/auth#token |
| langfuse→vault | install.langfuse, install.vault | configure.langfuse.externalsecret | crd | crdfacts://external-secrets/SecretStore#name |
| teleport→authentik | install.teleport, install.authentik | configure.teleport.oidc.authentik | crd | facts://authentik/providers-oauth2#client_id, facts://authentik/providers-oauth2#client_secret |

### Infrastructure Stack (Mixed)

| Wiring Target | Install Actions | Configure Action | Executor | Key Consumed Facts |
|---------------|----------------|-----------------|----------|-------------------|
| alertmanager→awx | install.alertmanager, install.awx | configure.alertmanager.receiver.awx | helm | facts://awx/webhook#url |
| argocd→awx | install.argocd, install.awx | configure.argocd.notification.awx | crd | facts://awx/webhook#url |
| traefik→loki | install.traefik, install.loki | configure.traefik.accesslog.loki | helm | helmfacts://loki/service#url |
| kibana→elastic | install.kibana, install.elastic | configure.kibana.elasticsearch | helm | helmfacts://elastic/service#url, helmfacts://elastic/auth#password |

### Compiled Execution Plan (All 22 Targets)

When all 32 apps are installed, the compiler produces these waves:

```
Wave 1 (no dependencies — leaf installs):
  install.vault, install.prometheus, install.alertmanager,
  install.loki, install.elastic, install.authentik,
  install.cert-manager, install.sabnzbd, install.qbittorrent,
  install.jellyfin, install.postgres

Wave 2 (depends on Wave 1 installs):
  install.grafana, install.sonarr, install.radarr,
  install.prowlarr, install.langfuse, install.awx,
  install.traefik, install.teleport, install.kibana,
  install.argocd

Wave 3 (cross-app configuration):
  configure.grafana.datasource.prometheus
  configure.grafana.datasource.loki
  configure.grafana.datasource.alertmanager
  configure.prometheus.alertmanager
  configure.loki.ruler.alertmanager
  configure.cert-manager.issuer.vault
  configure.awx.credential.vault
  configure.langfuse.externalsecret
  configure.teleport.oidc.authentik
  configure.alertmanager.receiver.awx
  configure.argocd.notification.awx
  configure.traefik.accesslog.loki
  configure.kibana.elasticsearch
  configure.prowlarr.downloadclient.sabnzbd
  configure.prowlarr.downloadclient.qbittorrent
  configure.sonarr.downloadclient.sabnzbd
  configure.sonarr.downloadclient.qbittorrent
  configure.radarr.downloadclient.sabnzbd
  configure.radarr.downloadclient.qbittorrent

Wave 4 (depends on prowlarr configured — see edges below):
  configure.sonarr.indexer.prowlarr
  configure.radarr.indexer.prowlarr

  # Why Wave 4, not Wave 3? These actions CONSUMES prowlarr's download client
  # configuration state, not just prowlarr's install state:
  #   configure.sonarr.indexer.prowlarr
  #     CONSUMES statefacts://prowlarr/downloadclient.sabnzbd#configured
  #     CONSUMES statefacts://prowlarr/downloadclient.qbittorrent#configured
  #     CONSUMES facts://prowlarr/api#apikey
  # The first two facts are PRODUCED by Wave 3 actions, forcing Wave 4 ordering.
  # Prowlarr must have its download clients wired before it can serve as an
  # indexer proxy — otherwise sonarr/radarr indexer tests fail at verification.

Wave 5 (notifications — depends on media apps + jellyfin):
  configure.sonarr.notification.jellyfin
  configure.radarr.notification.jellyfin

Wave 6 (verification — all configure actions done):
  verify.grafana.datasource.prometheus
  verify.grafana.datasource.loki
  verify.sonarr.downloadclient.sabnzbd
  verify.cert-manager.issuer.vault
  ... (one verify per configure)
```

Actions within the same wave execute in parallel. The compiler guarantees every CONSUMES fact is satisfied before the consuming action runs.

## Worked Example: grafana → prometheus

### The desired fact

```
Target: statefacts://grafana/datasource.prometheus#verified
```

### Backward walk

```
statefacts://grafana/datasource.prometheus#verified
  ← PRODUCES ← verify.grafana.datasource.prometheus
    CONSUMES → statefacts://grafana/datasource.prometheus#configured
      ← PRODUCES ← configure.grafana.datasource.prometheus
        CONSUMES → facts://prometheus/service#url                   (shape: addressability)
        CONSUMES → facts://grafana/auth#admin_credential            (shape: credential)
        CONSUMES → statefacts://grafana/service#api_ready           (shape: lifecycle)
          ← PRODUCES ← install.grafana
            CONSUMES → [] (leaf)
          ← PRODUCES ← install.prometheus
            CONSUMES → [] (leaf)
```

### Resolved action graph

```
install.prometheus       → [] (no deps)
install.grafana          → [] (no deps)
configure.grafana.datasource.prometheus → [install.prometheus, install.grafana]
verify.grafana.datasource.prometheus    → [configure.grafana.datasource.prometheus]
```

### Execution waves

```
Wave 1: install.prometheus, install.grafana    (parallel)
Wave 2: configure.grafana.datasource.prometheus
Wave 3: verify.grafana.datasource.prometheus
```

### Action details

```python
Action(
    action_id="configure.grafana.datasource.prometheus",
    phase="configure",
    executor="api",
    service="grafana",
    source_service="prometheus",
    consumes=[
        FactRef(uri="facts://prometheus/service#url", shape="addressability"),
        FactRef(uri="facts://grafana/auth#admin_credential", shape="credential"),
    ],
    produces=[
        FactRef(uri="statefacts://grafana/datasource.prometheus#configured", shape="lifecycle"),
    ],
    executor_args={
        "method": "POST",
        "endpoint": "/api/datasources",
        "headers": {"Authorization": "Bearer {{ grafana_admin_api_key }}"},
        "body": {
            "name": "Prometheus",
            "type": "prometheus",
            "url": "{{ prometheus_service_url }}",
            "access": "proxy",
            "isDefault": True,
        },
    },
    idempotency_mode="check_before_create",
    idempotency_check="GET /api/datasources/name/Prometheus",
)
```

### Early cutoff in action

```
Day 1: Full execution. All waves run. BWS _state records input_hash for each action.

Day 2: User upgrades prometheus chart version.
  install.prometheus re-executes (new chart)
  → prometheus_service_url unchanged (same ClusterIP)
  → configure.grafana.datasource.prometheus: input_hash unchanged → SKIP
  → verify.grafana.datasource.prometheus: input_hash unchanged → SKIP

Day 3: User changes grafana_admin_api_key in BWS _config.
  install.grafana: input_hash unchanged → SKIP
  configure.grafana.datasource.prometheus: input_hash CHANGED (credential rotated)
  → re-executes POST /api/datasources with new auth header
  → output fact unchanged (datasource still configured)
  → verify: input_hash unchanged → SKIP (early cutoff)
```

## The GraphOp Pattern

All graph writes go through typed intermediaries, keeping extractors database-agnostic:

```python
GraphOp = MergeNode | MergeEdge | DeleteEdge

@dataclass(frozen=True)
class MergeNode:
    label: str                    # "Action"
    key: dict[str, str]           # {"action_id": "install.prometheus"}
    properties: dict[str, Any]    # {"executor": "helm", "phase": "install", ...}

@dataclass(frozen=True)
class MergeEdge:
    source_label: str             # "Action"
    source_key: dict[str, str]    # {"action_id": "configure.grafana..."}
    target_label: str             # "Fact"
    target_key: dict[str, str]    # {"uri": "facts://prometheus/service#url"}
    rel_type: str                 # "CONSUMES"
    properties: dict[str, Any]    # {"shape": "addressability", "confidence": 0.95}
```

Extractors parse spec files and emit `GraphOp` lists. The FalkorDB executor converts them to parameterized Cypher. Only the executor knows the database.

## Pipeline: Specs → Skill JSON → Action JSON → Graph → Execution Waves

The pipeline has a strict phase separation with **two cached JSON layers**, analogous to Nix's evaluation → instantiation → realisation:

```
Nix equivalent:    .nix expression    →  .drv file          →  /nix/store output
This pipeline:     Raw specs          →  Skill JSON          →  Action JSON     → Graph → Execution
                   (source of truth)     (operation .drv)       (compiled .drv)    (read-only projection)
```

Both JSON layers are serialized to disk, inspectable, and version-controlled. **The graph is a read-only projection** — it is never mutated directly. All writes go through the JSON files. If the graph is lost or corrupted, it is rebuilt deterministically from the JSON files.

This is the package manager model: JSON files are the packages, the graph is the installed index. TreeSitter or any other consumer can ingest the JSON files directly — the graph is one consumer, not the canonical store.

**Skill JSON is the first `.drv` equivalent** — a normalized, validated, cached intermediate form. The hard work (RESTler/RestTestGen edge detection, CRD field classification, enrichment) happens once during skill generation and is cached as skill JSON. The action compiler reads this intermediate form — it does not re-derive edges from raw specs.

**Action JSON is the second `.drv` equivalent** — the compiled output of the action compiler. It contains the full action graph in serialized form: all Action nodes, Fact nodes, CONSUMES/PRODUCES edges with satisfaction modes, and content-addressed input hashes. This is what gets ingested into the graph.

### Why Skill JSON must stay as the intermediate

1. **Edges are already computed.** RESTler/RestTestGen producer-consumer analysis, the 6-layer CRD field classifier, and cross-service enrichment all run during skill generation. Their output (the `depends_on` arrays, `input_refs`, `output_declarations`) is captured in skill JSON. Re-running these from raw specs would be slow and non-deterministic.

2. **Validation is already done.** Skill JSON is validated against `operation.schema.json` and `crd-kind.schema.json`. The action compiler can trust the intermediate form.

3. **Multiple consumers.** The graph DB, the action compiler, debugging tools, and future consumers all read skill JSON. It's the shared contract.

4. **Inspectability.** You can `cat catalog/skills/openapi/sonarr/api-v3-downloadclient/create.json` and see exactly what was extracted. You can't inspect an action graph as easily.

### What the action compiler adds beyond skill JSON

Skill JSON describes **operations** (individual API calls, CRD applies). It does not describe **lifecycle**. The action compiler fills that gap:

| Skill JSON provides | Action compiler adds |
|---------------------|---------------------|
| `depends_on[].fact_ref` | → CONSUMES edges with satisfaction modes |
| `outputs{}` | → PRODUCES edges with shapes |
| `method` (POST/PUT) | → phase classification (configure) |
| CRD `input_refs` | → CONSUMES edges |
| CRD `output_declarations` | → PRODUCES edges |
| — | install actions (from Helm chart specs) |
| — | verify actions (one per configure action) |
| — | `statefacts://` lifecycle facts |
| — | content-addressed `input_hash` |
| — | satisfaction modes on CONSUMES edges |
| — | artifact emission links |

### Action JSON: The Compiled Intermediate

Action JSON is the serialized output of the action compiler. One file per action, stored at `catalog/actions/{service}/{action_id}.json`.

```json
{
  "action_id": "configure.sonarr.downloadclient.sabnzbd",
  "phase": "configure",
  "executor": "api",
  "service": "sonarr",
  "source_service": "sabnzbd",
  "consumes": [
    {"uri": "facts://sabnzbd/api#apikey", "shape": "credential", "satisfaction": "required_value"},
    {"uri": "facts://sabnzbd/service#url", "shape": "addressability", "satisfaction": "required_value"},
    {"uri": "statefacts://sonarr/service#api_ready", "shape": "lifecycle", "satisfaction": "required_value"}
  ],
  "produces": [
    {"uri": "statefacts://sonarr/downloadclient.sabnzbd#configured", "shape": "lifecycle"}
  ],
  "executor_args": {"method": "POST", "endpoint": "/api/v3/downloadclient"},
  "defaults": {"enable": true, "protocol": "usenet", "name": "SABnzbd"},
  "idempotency_mode": "check_before_create",
  "idempotency_check": "GET /api/v3/downloadclient?name=SABnzbd",
  "input_hash": null,
  "artifact_template": "templates/wire-downloadclient.yml.j2"
}
```

The `input_hash` is `null` in the serialized file — it is computed at execution time from resolved BWS `_state` values, not at compile time. This is intentional: the JSON file captures the **structure** of the action (what it consumes, produces, and how it executes), while the hash captures the **state** of a specific run.

### Why two JSON layers

| Layer | What it captures | When it changes | Location |
|-------|-----------------|-----------------|----------|
| **Skill JSON** | Operations extracted from specs (edges, fields, types) | When specs are re-downloaded or enrichment runs | `catalog/skills/` |
| **Action JSON** | Compiled actions with lifecycle, satisfaction, verification | When the action compiler runs (new skills, schema changes) | `catalog/actions/` |
| **Graph** | Read-only projection for query and compilation | Rebuilt from Action JSON on any change | FalkorDB Lite |

The graph is never the source of truth. The JSON files are. This means:
- **Packaging:** Action JSON files can be bundled into a package (tarball, OCI layer, git subtree) and distributed. A consumer installs the package and ingests the JSON into their local graph.
- **Reproducibility:** Delete the graph, re-ingest from `catalog/actions/`, get the same graph. No migration scripts, no stateful transforms.
- **Multiple consumers:** TreeSitter, LSP servers, CI validators, and the graph DB all consume the same JSON files. The graph is one consumer among many.
- **Diffability:** `git diff catalog/actions/sonarr/configure.sonarr.downloadclient.sabnzbd.json` shows exactly what changed in the compiled action. Graph diffs are opaque.

### Pipeline Steps

```
1. SPEC DOWNLOAD
   Helm charts, CRD schemas, OpenAPI specs, Docker Compose files
   → catalog/specs/{helm,crd,openapi,compose}/

2. SKILL GENERATION (the .drv step — cached, validated, inspectable)
   OpenAPI: spec_loader → path_extractor → RESTler/RestTestGen edges
            → field_extractor → dep_adapters → output_writer
   CRD:    schema_loader → field_classifier (6 layers) → odg_builder → output_writer
   Helm:   values.yaml → recursive nested walker → build_helm_spec_json
   Compose: parse_compose → WiringEdge extraction → confidence scores
   Enrichment: structural FK matching + optional LLM classification
   → catalog/skills/{openapi,crd,helm,compose}/

3. ACTION COMPILATION (skill JSON → action JSON — the second .drv step)
   Read skill JSON intermediate form
   Map operations → configure actions (CONSUMES/PRODUCES from depends_on/outputs)
   Generate install actions from Helm chart specs
   Generate verify actions (one per configure)
   Classify satisfaction modes on CONSUMES edges
   Define hashable input structure per action (input_hash computed at execution time)
   Serialize to Action JSON files (input_hash = null on disk)
   → catalog/actions/{service}/{action_id}.json

4. GRAPH INGESTION (action JSON → read-only graph)
   Action JSON files → GraphOps → FalkorDB executor → FalkorDB Lite
   Schema applied, indexes created
   The graph is a read-only projection of the JSON files
   If the graph is destroyed, rebuild from catalog/actions/ deterministically

5. COMPILATION (graph → execution plan)
   Given: desired end state (set of target facts) + installed apps from BWS _state
   Backward walk → reachable action subgraph
   Fork point resolution (user selects among capability providers)
   Topological sort → execution waves
   Soft edges (optional_with_default) dropped if provider not installed

6. ARTIFACT EMISSION
   Each action emits its artifact (playbook, CRD manifest, config)
   Artifacts parameterized with BWS _config/_state variables

7. EXECUTION
   Resolve fact definitions → instance values from BWS _state
   Compute input_hash per action (hash of resolved values + executor_args + defaults + template_hash)
   Skip actions where input_hash matches last-run hash (early cutoff)
   Wave-parallel execution with idempotency checks
   BWS _state updated after each action completes
   Persist: resolved input_hash + output fact values for early cutoff on next run
```

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

### Dynamic Wiring at Runtime

Playbooks don't run against a fixed app list. The Phase 4 workflow discovers what's installed at runtime:

1. **Read BWS inventory** — query `_state.apps` for all entries with `status: installed`
2. **Filter by `requires_apps`** — each wiring playbook declares which apps it needs (e.g., `05-wire-sabnzbd.yml` requires both `sonarr` and `sabnzbd`). A playbook only runs when ALL its required apps are present.
3. **Parallel execution** — all eligible wiring playbooks run as parallel background subshells on the self-hosted runner
4. **Per-app failure isolation** — one app's wiring failure doesn't block others

This means the same generated playbooks work on any VM with any subset of apps installed. A VM with sonarr + radarr + sabnzbd gets the media wiring. A VM with grafana + prometheus + loki gets the monitoring wiring. No workflow changes needed — BWS inventory drives everything dynamically.

### Live Configuration Updates

When a user changes any value in BWS `_config` (via the GUI or API), only the delta is applied:

1. **User edits a var** — e.g., changes `grafana.admin_password` in BWS `_config`
2. **Workflow detects deviation** from defaults — only changed vars are passed as extra-vars
3. **`kubectl apply` updates only those changes** — the playbook applies the diff, not a full redeploy
4. **Wiring playbooks re-run with new values** — if the changed var affects cross-app wiring (e.g., a new API key), the relevant wiring playbooks pick up the new value automatically

This is true live configuration. Edit a port, change a password, toggle a feature flag — the system converges to the new state without reinstalling anything. The playbooks are idempotent by design, so re-running with updated vars only touches what changed.

## What Makes This Different

This is not an LLM generating infrastructure code. This is a **compiler**:

1. **Deterministic** — same inputs always produce the same playbooks
2. **Validated** — every generated playbook passes molecule tests before output
3. **Grounded** — every field value traces back to a real source (schema, compose file, Helm default)
4. **Repairable** — if validation fails, the LLM reclassifies fields (not regenerates code)
5. **Self-contained** — no Docker, no Neo4j, no external services needed for development
6. **Incremental** — add a new app to the manifest, run the pipeline, get working playbooks
7. **Universal** — works for ANY app with a Helm chart, OpenAPI spec, or Docker Compose file — not limited to a fixed app list

The end state is a **package manager for k3s apps**. A catalogue of version-pinned applications, each containing pre-generated atomic skills, install playbooks, wiring playbooks, and ingress configuration. Adding an app to your cluster is:

1. Select apps from the catalogue (GUI or CLI)
2. Skills unpack into the skills directory, tree-sitter ingests them into the graph
3. The graph resolves dependencies and cross-app wiring automatically
4. Playbooks execute — install, configure, wire, expose — all dynamically based on which apps are selected
5. BWS tracks state, any var change applies as a live delta

No manual YAML. No reading docs to figure out which port sonarr needs to talk to prowlarr. The catalogue already knows, because it was compiled from Helm charts, CRD schemas, OpenAPI specs, and thousands of community Docker Compose stacks. The 32-app portfolio is the initial catalogue — it grows as new apps are added.

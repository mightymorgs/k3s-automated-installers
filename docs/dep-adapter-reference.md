# Dep Adapter Reference

> **Status:** Post-implementation reference (retroactive from Phase 1 spec requirement)
> **Date:** 2026-03-11
> **Scope:** All dependency detection adapters in `platform-tools/idi/idi/generation/dep_adapters/` and CRD pipeline modules in `platform-tools/idi/idi/generation/crd/`

---

## 1. Architecture Overview

The dependency detection pipeline uses a layered adapter architecture. Each adapter implements the `DepAdapter` protocol and is registered with a priority. Higher-priority adapters override lower-priority ones when they produce conflicting results for the same field.

```
                    +-----------------------+
                    |   DepAdapterRegistry   |
                    |   (dep_adapters/)      |
                    +-----------+-----------+
                                |
              +-----------------+------------------+
              |                 |                   |
    +---------v----+  +---------v------+  +---------v--------+
    | OlmDepAdapter|  | CrdDepAdapter  |  | RbacDepAdapter   |
    | priority: 95 |  | priority: 80   |  | priority: 70     |
    +--------------+  +--------+-------+  +------------------+
                               |
                    +----------v-----------+
                    |   GenericODGAdapter   |
                    |   priority: 50       |
                    +----------+-----------+
                               |
              +------+------+------+------+
              |      |      |      |      |
           body_fk path_deps query_fk output_det discriminator
```

### Adapter Priority Chain

| Priority | Adapter | Scope | Source |
|:---:|---------|-------|--------|
| 95 | `olm_deps` | OLM ClusterServiceVersion ground-truth | Phase 4 |
| 90 | `discriminator` | OpenAPI discriminator polymorphism | Original |
| 80 | `crd_dep` | CRD schema walker + ref detector pipeline | Phase 2 |
| 70 | `rbac_deps` | Helm chart RBAC rule analysis | Phase 4 |
| 50 | `generic_odg` | Always-on heuristic FK detection | Original |

---

## 2. Protocol and Data Types

### 2.1 DepAdapter Protocol

File: `dep_adapters/base.py`

```python
class DepAdapter(Protocol):
    name: str
    priority: int

    def matches(self, spec: dict, service_name: str) -> bool: ...
    def detect_dependencies(
        self, operation: OperationInfo, spec: dict,
        known_resources: set[str],
    ) -> list[Dependency]: ...
    def detect_outputs(
        self, operation: OperationInfo, spec: dict,
    ) -> list[Output]: ...
```

### 2.2 Core Data Types

**OperationInfo** -- context for a single API operation:
- `service`, `resource`, `operation`, `path`, `method`
- `body_schema`, `response_schema`
- `path_params`, `query_params`

**Dependency** -- a detected FK relationship:
- `field`: dot-path to the consuming field
- `target_resource`: plural name of the target resource
- `target_operation`: typically "create"
- `fact_ref`: URI (e.g., `crdfacts://core/Secret#name`)
- `confidence`: 0.0-1.0 (threshold: 0.7 for emission)
- `source`: detection source identifier
- `lineage_type`: "copy" or "reference"
- `satisfaction`: "required_value" or "optional_with_default"
- `target_service`: set for cross-service deps (e.g., "k8s")

**Output** -- a detected producer:
- `field`: dot-path to the producing field
- `fact_ref`: URI for the produced fact
- `priority`: POST=3, PUT-create=2, PATCH=1

### 2.3 ClassifiedField (CRD Pipeline)

File: `crd/field_classifier.py`

The CRD-specific data model used by the ref_detector pipeline before conversion to Dependency/Output.

- `field`: dot-path (e.g., `spec.issuerRef`)
- `role`: `input_ref` | `output_declaration` | `config_field`
- `confidence`: 0.0-1.0
- `target_kind`: resolved Kind (e.g., "Issuer") or None
- `target_group`: API group (e.g., "cert-manager.io")
- `detection_source`: which detector produced this
- `fact_shape`: "identity", "lifecycle", or "config"
- `target_field`: canonical target field for URI fragment (default: "name")

---

## 3. REST Dep Adapters

### 3.1 generic_odg.py -- Generic ODG Heuristic Adapter

**Priority:** 50 (lowest, always-on)

**Purpose:** Thin facade wiring `body_fk`, `path_deps`, `query_fk`, and `output_detection` behind the DepAdapter protocol.

**Matching:** Always matches (`return True`).

**Spike origin:** RESTler (Dependencies.fs) + RestTestGen (NormalizedParameterName.java)

**Sub-modules:**

| Module | Purpose | Spike Origin |
|--------|---------|-------------|
| `body_fk.py` | Recursive body schema FK detection | RESTler Dependencies.fs:140-210 |
| `path_deps.py` | Path parameter hierarchy deps | RESTler Dependencies.fs:78-139 |
| `query_fk.py` | Query parameter FK detection | Novel (v11 addition) |
| `output_detection.py` | Producer/output classification | RESTler Dependencies.fs:22-52 |
| `target_inference.py` | Resource name resolution | RESTler DynamicObjectNaming.fs + RestTestGen |
| `naming.py` | Convention detection + Porter stemming | RestTestGen NormalizedParameterName.java |
| `obj_pattern.py` | Structural pattern detection | Novel |

**CFM mapping:**
- Body FK: field ending in `_id`/`_name`/`_ref` -> CONSUMES edge (shape: identity)
- Path deps: `/{resource}/{id}` -> CONSUMES edge with confidence decay per ancestor level (0.7, 0.6, 0.5)
- Query FK: query param matching resource name -> CONSUMES edge (satisfaction: optional_with_default)
- Outputs: POST=3, PUT-create=2, PATCH=1 priority -> PRODUCES edge

### 3.2 discriminator.py -- OpenAPI Discriminator Adapter

**Priority:** 90

**Purpose:** Detect polymorphic endpoints via OpenAPI `discriminator` keyword.

**Matching:** Spec has schemas with `discriminator.propertyName` + `discriminator.mapping`.

**Spike origin:** Novel (addresses gap not covered by analyzed tools).

**CFM mapping:** Discriminator value -> specialized Dependency with `discriminator_value` field.

### 3.3 merge.py -- Dependency Merge Engine

**Purpose:** Deduplicate and merge deps from multiple adapters. Highest confidence wins. Self-ref filter removes deps where `target_resource == current resource`.

### 3.4 yaml_adapter.py -- YAML-Defined Adapters

**Purpose:** Load dep_adapter definitions from YAML files (generated/ directory). Used for machine-generated adapters.

---

## 4. CRD Dep Adapters

### 4.1 crd_dep.py -- CRD Dependency Bridge

**Priority:** 80

**File:** `dep_adapters/crd_dep.py` (275 LOC)

**Purpose:** Orchestrator wiring `schema_walker` + `ref_detector` into Dependency/Output objects via the DepAdapter protocol.

**Matching:** Spec has K8s-style API paths (`/apis/` or `/api/v1/namespaces`).

**Pipeline:**
1. Extract spec schema from CRD body envelope
2. Walk spec properties via `walk_crd_schema()`
3. For each walked field, call `classify_walked_field()` with sibling fields
4. Filter on `role == "input_ref"` and `target_kind is not None`
5. Resolve target against `known_resources` (cross-service for core K8s)
6. Emit `Dependency` with `crdfacts://` URI

**Sibling field population:** String fields with enum values, patterns, or formats get sibling fields populated for `detect_enum_kind` and `detect_constraint_fk` (C29).

**Cross-service resolution:** Core K8s resources (Secret, ConfigMap, etc.) are emitted as cross-service deps with `target_service="k8s"`.

**Output detection:**
- Status fields via `walk_crd_status()` + `detect_status_output()`
- Scale subresource declarations (C20) from CRD metadata

### 4.2 olm_deps.py -- OLM Dependency Adapter

**Priority:** 95 (highest -- ground-truth from operator author)

**File:** `dep_adapters/olm_deps.py`

**Purpose:** Translates OLM ClusterServiceVersion required GVKs into Dependencies. Parses OLM CSV data from OperatorHub.io.

**Data source:** `crd/olm_loader.py` fetches and caches CSV from OperatorHub.io API.

**Key types:**
- `GVKRef`: `kind`, `group`, `version`, `plural` (4 fields; `plural` extracted from OLM name)
- Required GVKs -> Dependency with `field=f"olm:required:{req.group}/{req.kind}"`
- Owned GVKs -> registered in KindRegistry for other detectors

**CFM mapping:** OLM required -> CONSUMES edge at priority 95. `#name` fragment convention.

### 4.3 rbac_deps.py -- RBAC Dependency Adapter

**Priority:** 70

**File:** `dep_adapters/rbac_deps.py`

**Purpose:** Extracts operator-resource edges from Helm chart RBAC rules (ClusterRole/Role).

**Data source:** Downloads Helm chart `.tgz` from ArtifactHub and extracts RBAC templates.

**Detection:**
- Verb analysis: `create`/`patch` verbs -> Output (operator creates this resource)
- Resource matching: RBAC `resources` list -> Dependency or Output
- Webhook parsing (C21): extracts webhook configuration dependencies

**CFM mapping:** RBAC rules -> Dependency/Output with `priority: int` field.

**Known limitation:** Makes network calls to ArtifactHub at runtime during adapter execution (spec item P4-04). No offline/cached mode.

---

## 5. CRD Pipeline Modules

### 5.1 kind_registry.py -- Unified Kind Registry

**File:** `crd/kind_registry.py`

**Purpose:** Single auto-populated registry replacing 6 hardcoded dictionaries. Supports runtime registration from CRD specs, CamelCase-aware longest-match field lookup.

**Bootstrap:** 18 core K8s resources + 2 aliases (Claim -> PVC, Volume -> PV).

**Public API:**
- `register(kind, plural, group)` -- add a Kind
- `register_from_crd(crd_spec)` -- auto-register from CRD spec
- `is_ref_field(field_name, current_group)` -> `(is_ref, kind, plural, group)`
- `kind_to_plural(kind)` -> plural or None
- `plural_to_kind(plural)` -> Kind or None
- `group_for_kind(kind)` -> group or None
- `kinds_for_group(group)` -> set of Kind names
- `all_kinds()`, `all_plurals()`, `core_plurals()`

**Lookup strategy (is_ref_field):**
1. Well-known compounds: `secretkeyref`, `configmapkeyref`
2. Dynamic suffix matching: `{Kind}Ref`, `{Kind}Name` (longest-first, CamelCase boundary check)
3. Short-name alias fallback: `store` -> `SecretStore`

**Multi-group tie-breaking:** Same Kind in multiple groups -> prefer current_group, then core, else suppress (precision > recall).

### 5.2 schema_walker.py -- CRD Schema Traversal

**File:** `crd/schema_walker.py`

**Purpose:** Recursively yield every field in a CRD spec/status schema as `WalkedField`. Handles nested objects and array items.

**Configuration:**
- `max_depth`: 8 (increased from 5 to cover depth-7 provider auth chains)
- `EXCLUDED_FIELDS`: 15 fields excluded at every level (status, namespace, apiVersion, etc.)
  - `kind`: excluded at depth 1 only (root K8s envelope); allowed at depth > 1 for discriminator detection
  - `selector`: removed from exclusion list (PushSecret support)
- `_K8S_ENVELOPE`: 4 fields skipped at root level only (apiVersion, kind, metadata, status)

**Two entry points:**
- `walk_crd_schema(properties, required, prefix="spec", max_depth=8)` -- spec fields
- `walk_crd_status(status_properties, prefix="status", max_depth=3)` -- status fields (shallower)

### 5.3 ref_detector.py -- Multi-Strategy Ref/Output Detection

**File:** `crd/ref_detector.py` (~1600 LOC)

**Purpose:** Given a WalkedField, classify it using multiple detection strategies in priority order.

**Detection pipeline (classify_walked_field):**

| Step | Detector | Confidence | Phase | Behavior |
|:---:|---------|:---:|:---:|---------|
| 0 | Side-effect dictionary | 0.95 | P2 | Exclusive |
| 1 | `detect_ref` (KindRegistry suffix) | 0.9 | P2 | Exclusive |
| 2 | `detect_ref_tuple` (name+kind+namespace) | 0.85 | P3 | Exclusive |
| 3 | `detect_kubernetes_extensions` (C32) | 0.8-0.95 | P5A | Embedded=exclusive, list-map=additive |
| 4 | `detect_enum_kind` (sibling Kind enum) | 0.95 | P2 | Additive |
| 5 | `detect_example_kinds` (examples/defaults) | 0.8 | P3 | Additive |
| 6 | `detect_apigroup_literal` (enum group values) | 0.85 | P3 | Additive |
| 7 | `detect_passthrough_manifest` (C26) | 0.95 | P3 | Additive |
| 8 | `detect_constraint_fk` (C29) | 0.75-0.80 | P5A | Additive |
| 9 | `detect_embedded_workload` (C22) | 0.8 | P5A | Additive |
| 10 | `detect_cataloged_shape` (C30) | 0.8-0.85 | P5A | Additive |
| 11 | Side-effect NLP | 0.6 | P2 | Fallback |
| 12 | Default config_field | 0.5 | P2 | Always |
| 13 | `suppress_false_positives` | -- | P3 | Post-filter |

**Key data types:**
- `ManifestFlags`: Pass-in accumulator for manifest-level flags (e.g., `accepts_arbitrary_resources`)
- `WorkloadFingerprint`: Shape definitions for PodTemplateSpec, JobSpec, ServiceSpec
- `ShapeCatalog`: Pre-computed cross-CRD reference shapes

### 5.4 field_classifier.py -- Field Classification Facade

**File:** `crd/field_classifier.py`

**Purpose:** Delegates to schema_walker + ref_detector pipeline. Iterates walked fields, calls `classify_walked_field`, applies parent-child deduplication.

### 5.5 output_writer.py -- Decomposed Skill JSON Serializer

**File:** `crd/output_writer.py`

**Purpose:** Serializes classified fields into decomposed skill JSON (schema v2.0).

**Output structure:**
```
catalog/skills/crd/{group}/{service}/{Kind}/
  manifest.json          -- Kind metadata
  operations/apply.json  -- kubectl_apply action
  refs/{name}.json       -- per input_ref (CONSUMES edge)
  outputs/{name}.json    -- per output_declaration (PRODUCES edge)
  fields/{name}.json     -- per config_field (Fact node)
```

**Key features:**
- Collision detection: same leaf name -> hyphen-joined paths
- Content hash: SHA-256 of all files except manifest.json
- Path sanitization: `[A-Za-z0-9._-]` only
- `target_plural`/`produces_plural`: populated from KindRegistry when provided

### 5.6 side_effect_registry.py -- Operator Side-Effect Detection

**File:** `crd/side_effect_registry.py`

**Purpose:** Domain-specific knowledge of which CRDs create other resources as side effects (e.g., Certificate creates Secret).

### 5.7 schema_loader.py -- CRD Schema Fetcher

**File:** `crd/schema_loader.py`

**Source:** datreeio/CRDs-catalog on GitHub + local Helm chart CRDs.

### 5.8 olm_loader.py -- OLM CSV Fetcher

**File:** `crd/olm_loader.py`

**Purpose:** Fetch and cache OLM ClusterServiceVersion data from OperatorHub.io API.

---

## 6. URI Schemes

### 6.1 crdfacts://

Used by CRD pipeline for cross-resource dependency edges.

**Format:** `crdfacts://{group}/{Kind}#{field}`

**Examples:**
- `crdfacts://cert-manager.io/Issuer#name` -- Certificate depends on Issuer
- `crdfacts://core/Secret#name` -- ExternalSecret depends on Secret
- `crdfacts://external-secrets.io/SecretStore#name` -- ExternalSecret depends on SecretStore

**Fragment convention:** `#name` (CFM convention, not consuming field name).

### 6.2 facts://

Used by REST dep_adapters for REST API dependency edges.

**Format:** `facts://{service}/{resource}#{field}`

---

## 7. Detection Sources and Confidence Ranges

| Detection Source | Confidence | Description |
|-----------------|:---:|-------------|
| `side_effect:operator_dict` | 0.95 | Domain-specific operator knowledge |
| `ref_detector:kind_registry` | 0.9 | KindRegistry suffix match (*Ref, *Name) |
| `ref_detector:ref_tuple` | 0.85 | Object with name+kind+namespace fields |
| `ref_detector:kubernetes_ext_embedded` | 0.95 | x-kubernetes-embedded-resource |
| `ref_detector:kubernetes_ext_list_map` | 0.8 | x-kubernetes-list-type: map |
| `ref_detector:enum_kind` | 0.95 | Sibling field with Kind enum values |
| `ref_detector:example_kinds` | 0.8 | Examples/defaults containing Kind names |
| `ref_detector:apigroup_literal` | 0.85 | API group literal in enum values |
| `ref_detector:passthrough_manifest` | 0.95 | Passthrough manifest detection |
| `ref_detector:constraint_fk` | 0.75-0.80 | DNS-name pattern + namespace sibling |
| `ref_detector:embedded_workload` | 0.8 | PodTemplateSpec/JobSpec/ServiceSpec shape |
| `ref_detector:cataloged_shape` | 0.8-0.85 | Pre-computed cross-CRD shape match |
| `side_effect:nlp_output` | 0.6 | NLP description analysis (output) |
| `side_effect:nlp_input` | 0.6 | NLP description analysis (input) |
| `default:config_field` | 0.5 | Default fallback |

**Emission threshold:** No edge emitted below confidence 0.7 (precision > recall).

---

## 8. Known Gaps and Limitations

### 8.1 Detection Gaps (from edge detection audit)

| Category | Impact | Status |
|----------|:---:|--------|
| SecretKeySelector shape | 18 edges | Not yet implemented |
| Parent-kind-name detector | 16 edges | Not yet implemented |
| REF_TUPLE_UNRESOLVABLE | 4 edges | External-secrets generators; needs registry expansion |
| Description-only refs | 2 edges | Low-confidence NLP; enhancement possible |

### 8.2 Architectural Limitations

- **RBAC adapter network dependency:** Makes HTTP calls to ArtifactHub at runtime (no offline mode)
- **constraint_fk target resolution:** Emits with `target_kind=None` when Kind cannot be resolved; filtered downstream
- **Short-name aliases:** `_SHORT_NAME_ALIASES = {"store": "SecretStore"}` -- contradicts dict elimination goal but necessary for external-secrets ecosystem

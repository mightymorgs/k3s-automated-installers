# Kahn's Sort Readiness Analysis

> Date: 2026-03-11
> Context: CRD detection pipeline at 301 input refs, 3 output declarations, 0 false positives after corpus validation

---

## 1. The Core Problem

Kahn's topological sort requires a directed acyclic graph where edges mean "A must exist before B can be created." To build this graph, you need two pieces of information for every CRD Kind:

1. **What it consumes** (input refs) — "Certificate needs an Issuer to exist first"
2. **What it produces** (output declarations) — "Certificate creates a Secret"

The detection pipeline currently captures input refs extremely well (301 edges, 0 FPs) but almost completely fails to capture output declarations (3 edges total, all from a hand-crafted dictionary).

Without the output side, you can't match producers to consumers. You know Certificate consumes Issuer, but nothing in the graph says "applying an Issuer manifest produces an Issuer resource." The sort has no way to determine that Issuer is a root node with no dependencies.

---

## 2. Current State: What the Pipeline Actually Produces

### Input Refs (301 edges — programmatic, comprehensive)

| Detection Source | Count | Description |
|---|---:|---|
| `ref_detector:kind_registry` | 200 | Field name suffix matches KindRegistry (e.g., `issuerRef` → Issuer) |
| `ref_detector:secret_key_selector` | 76 | `{key, name, namespace?}` shape → Secret |
| `ref_detector:parent_kind_name` | 22 | Parent field name depluralized → Kind (e.g., `secrets.name` → Secret) |
| `ref_detector:ref_tuple` | 2 | Structural `{name, namespace, kind?}` reference tuple |
| `ref_detector:array_ref` | 1 | Array of refs (e.g., `secretStoreRefs[]`) |
| **Total** | **301** | |

### Output Declarations (3 edges — hand-crafted, incomplete)

| Source Kind | Produces | Field | Detection Source |
|---|---|---|---|
| Certificate | Secret | `spec.secretName` | `side_effect:operator_dict` |
| ClusterExternalSecret | ExternalSecret | `spec.externalSecretName` | `side_effect:operator_dict` |
| ExternalSecret | Secret | `spec.target.name` | `side_effect:operator_dict` |

These three entries come from a hand-written side-effect dictionary. No programmatic detector contributes output declarations in the current pipeline.

---

## 3. Why This Blocks Kahn's Sort

### 3.1 The dependency graph for cert-manager

The input refs tell us:

```
Certificate ──→ Issuer
Certificate ──→ Secret (for keystores)
CertificateRequest ──→ Issuer
Challenge ──→ Issuer
Challenge ──→ Secret (for DNS providers)
Order ──→ Issuer
ClusterIssuer ──→ Secret (for provider credentials)
Issuer ──→ Secret (for provider credentials)
```

The output declarations tell us:

```
Certificate ──produces──→ Secret
```

For Kahn's sort, we need to answer: "What order do I apply these manifests?" The algorithm needs to find nodes with zero in-degree (no unsatisfied dependencies) and process them first. But the graph above has a problem:

- **Issuer** is consumed by Certificate, CertificateRequest, Challenge, and Order. But nothing produces Issuer. The sort can't determine whether Issuer is a root node (apply first) or whether it depends on something else.
- **Secret** is consumed by nearly everything but only produced by Certificate. In reality, Secrets are also created by `kubectl create secret`, Helm charts, or external systems. The sort doesn't know this.

### 3.2 The dependency graph for external-secrets

```
ExternalSecret ──→ SecretStore
ClusterExternalSecret ──→ SecretStore
PushSecret ──→ SecretStore

ExternalSecret ──produces──→ Secret
ClusterExternalSecret ──produces──→ ExternalSecret
```

SecretStore is consumed by three Kinds but nothing declares it as produced. The correct sort order is `SecretStore → ExternalSecret → (Secret available)`, but the graph can't express this because SecretStore has no producer edge.

### 3.3 The dependency graph for traefik

```
IngressRoute ──→ Middleware, Service, Secret
IngressRouteTCP ──→ Middleware, Service, Secret
IngressRouteUDP ──→ Service
Middleware ──→ Middleware (self-ref: chaining), TraefikService
TraefikService ──→ Service, TraefikService (self-ref: mirroring)
```

No output declarations at all. The sort can't determine that Middleware and TraefikService are independent resources that should be created before IngressRoute.

---

## 4. The Missing Axiom

Every CRD Kind implicitly produces itself. When you `kubectl apply` an Issuer manifest, you create an Issuer resource. This is not a schema-level signal — it's an axiom of how Kubernetes works. No field in the Issuer CRD schema says "this produces an Issuer." It's inherent to the CRD system.

The detection pipeline is designed to find signals in JSON schemas. This axiom isn't in any schema. It needs to be injected at the graph construction layer, not the detection layer.

### What the axiom gives you

If every CRD Kind produces itself, the complete graph for cert-manager becomes:

```
Issuer ──produces──→ Issuer           (axiom)
ClusterIssuer ──produces──→ ClusterIssuer  (axiom)
Certificate ──produces──→ Certificate  (axiom)
Certificate ──produces──→ Secret       (side-effect detection)

Certificate ──consumes──→ Issuer
CertificateRequest ──consumes──→ Issuer
Challenge ──consumes──→ Issuer
```

Now the sort works:

1. **Issuer** and **ClusterIssuer** have no intra-app dependencies (their Secret deps are external) → apply first
2. **Certificate** depends on Issuer → apply second
3. **CertificateRequest**, **Challenge**, **Order** depend on Issuer → apply second (parallel with Certificate)

### What the axiom doesn't give you

- **Cross-service ordering.** If cert-manager's Certificate produces a Secret that external-secrets' ExternalSecret consumes, the axiom alone doesn't capture this. You need the side-effect detection (Certificate → Secret) AND knowledge that ExternalSecret consumes Secrets.
- **External resource dependencies.** Core K8s resources (Secret, ConfigMap, Service, ServiceAccount, Namespace) are always available — they're created by other mechanisms (Helm, kubectl, operators). The sort needs to treat these as pre-existing.

---

## 5. The Polymorphic Edge Problem

The corpus validation found 8 "PARTIAL" edges where a reference can target multiple Kinds. Examples:

| Field | Current Target | Actual Targets |
|---|---|---|
| `Certificate.spec.issuerRef` | Issuer | Issuer **or** ClusterIssuer |
| `ExternalSecret.spec.secretStoreRef` | SecretStore | SecretStore **or** ClusterSecretStore |
| `ExternalSecret.spec.data.sourceRef.storeRef` | SecretStore | SecretStore **or** ClusterSecretStore |
| `TraefikService.spec.mirroring` | TraefikService | Service **or** TraefikService |
| `*.caProvider.name` | ConfigMap | Secret **or** ConfigMap |

These polymorphic references have a `kind` field with an enum listing the valid targets. The current pipeline emits one edge per detection, picking one target. For Kahn's sort, this matters:

- If Certificate can reference either Issuer or ClusterIssuer, then the sort order is: both Issuer AND ClusterIssuer must be available before Certificate. The sort needs edges to both targets.
- The `detect_enum_kind` detector already handles this — it emits one edge per enum value. But it currently runs at step 6 (additive), and `detect_parent_kind_name` at step 3 (exclusive) catches the `name` field first, short-circuiting before `detect_enum_kind` can process the sibling `kind` enum.

This is a pipeline ordering issue: exclusive detectors at steps 1-4 prevent additive detectors at steps 5+ from contributing polymorphic edges.

---

## 6. Complete Gap Inventory

### 6.1 Gaps that block Kahn's sort

| Gap | Nature | Fix Location |
|---|---|---|
| **No implicit self-production** | Every CRD Kind produces itself — this is a K8s axiom, not a schema signal | Graph construction layer (not detection) |
| **External deps not modeled** | Core K8s resources (Secret, ConfigMap, Service, etc.) are pre-existing, not produced by CRDs | Graph construction layer — mark core resources as always-available |
| **Only 3 side-effect outputs** | Cross-Kind production (Certificate→Secret) requires domain knowledge or operator documentation | Side-effect dictionary expansion or NLP-based detection |
| **Polymorphic edges are single-target** | References with `kind` enum emit one edge instead of N edges | Pipeline ordering fix or multi-target edge support |

### 6.2 Gaps that affect sort quality but don't block it

| Gap | Nature | Impact |
|---|---|---|
| **No required vs. optional distinction in sort** | 301 edges include both required and optional refs; sort treats all equally | Over-constraining — optional deps shouldn't block creation |
| **No cross-service ordering** | Each service is sorted independently; no inter-service dependency graph | Can't determine global apply order (e.g., cert-manager before external-secrets) |
| **Self-referential Kinds** | Middleware→Middleware, TraefikService→TraefikService create self-loops | Need Tarjan's SCC to detect and handle these |

---

## 7. What the Sort Module Needs

The sort module operates on a graph built FROM detection results, not on the detection results directly. It has three layers:

### Layer 1: Graph Construction

Take the 301 input refs and 3 output declarations and build a Kind-level dependency graph:

1. **Inject self-production axiom:** For every CRD Kind K, add edge `K produces K`.
2. **Mark external resources:** Core K8s resources (Secret, ConfigMap, Service, ServiceAccount, Namespace, Ingress, IngressClass, etc.) are always-available. They have zero in-degree by definition.
3. **Expand polymorphic edges:** Where a ref has a `kind` enum with N values, emit N edges instead of 1.
4. **Partition required vs. optional:** Required refs are hard dependencies (block creation). Optional refs are soft (don't block, but inform ordering preference).

### Layer 2: Topological Sort (Kahn's Algorithm)

Standard Kahn's on the graph from Layer 1:

1. Find all nodes with in-degree 0 (no unsatisfied required dependencies).
2. Process them (add to sorted output), decrement in-degree of their dependents.
3. Repeat until empty or stuck.

If stuck (remaining nodes all have in-degree > 0), there's a cycle.

### Layer 3: Cycle Resolution (Tarjan's SCC)

When Kahn's gets stuck:

1. Run Tarjan's SCC to find strongly connected components.
2. Each SCC is a group of mutually dependent Kinds that must be created together (or in a specific order with partial creation).
3. Collapse each SCC into a single node and re-run Kahn's on the condensed graph.

Known SCCs in the current data:
- `Middleware → Middleware` (self-loop, trivial SCC)
- `TraefikService → TraefikService` (self-loop, trivial SCC)

No non-trivial SCCs exist in the current 3-service dataset.

---

## 8. What Doesn't Need to Change in the Detection Pipeline

The detection pipeline's job is to find references in CRD schemas. It does this well:

- **301 input refs, 0 false positives** after the wrapper guard fix
- **19 detection sources** across 5 detector families
- **All detection is programmatic** — no hand-crafted per-CRD rules (the side-effect dictionary is the only exception, and it's explicitly scoped to operator-created outputs that can't be inferred from schemas)

The Kahn's sort readiness issues are NOT detection problems. They're graph construction problems:

1. Self-production is an axiom, not a schema signal.
2. External resource availability is deployment context, not schema content.
3. Polymorphic edges are a pipeline ordering issue (exclusive vs. additive detector priority).
4. Cross-service ordering requires a global view that individual CRD schemas don't contain.

The detection pipeline should continue to focus on precision (finding real references, avoiding false positives). The sort module should handle graph construction, axiom injection, and cycle resolution as a separate downstream concern.

---

## 9. Estimated Implementation Effort

| Component | LOC | Depends On |
|---|---:|---|
| Graph construction (axiom injection, external resource marking) | ~80 | Detection pipeline output |
| Kahn's topological sort | ~60 | Graph construction |
| Tarjan's SCC for cycle detection | ~80 | Kahn's (called when stuck) |
| Polymorphic edge expansion (detect_enum_kind on sibling `kind` fields) | ~30 | Pipeline ordering change |
| Required vs. optional edge partitioning | ~20 | Graph construction |
| **Total** | **~270** | |

All components are well-defined algorithms with known implementations. The research question is not "how to implement Kahn's sort" but "how to model the self-production axiom and external resource boundaries correctly for the K8s domain."

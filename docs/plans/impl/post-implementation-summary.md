# Post-Implementation Summary: CRD Phases 1-5A

> **Date:** 2026-03-11
> **Scope:** Retroactive summary covering Phases 1-5A implementation
> **Audit reference:** `docs/plans/impl/spec-vs-implementation-audit.md`
> **Edge audit reference:** `docs/plans/impl/edge-detection-audit.md`

---

## 1. What Was Implemented

### Phase 1: KindRegistry + Dict Elimination + Skill Decomposition

| Component | Status | LOC |
|-----------|--------|:---:|
| `crd/kind_registry.py` | Complete | 291 |
| `crd/output_writer.py` (decomposed format) | Complete | 459 |
| Dict elimination (6 dicts, ~101 entries) | Complete | -101 |
| Decomposed skill structure (schema v2.0) | Complete | -- |
| `crdfacts://` URI scheme | Complete | -- |
| `docs/dep-adapter-reference.md` | Created (retroactive) | -- |

**Spec deviations:**
- 20 core resources instead of 18 (added Claim, Volume aliases)
- `_SHORT_NAME_ALIASES` dict added (not in spec) -- needed for `store` -> `SecretStore`
- `kinds_for_group()` method added to KindRegistry (not in frozen API)
- Contract document (`crd-phase1-contract.md`) never written
- Post-summaries never written

### Phase 2: Detection Pipeline Decomposition

| Component | Status | LOC |
|-----------|--------|:---:|
| `crd/schema_walker.py` | Complete | 200 |
| `crd/ref_detector.py` (multi-strategy detection) | Complete | ~1600 |
| `crd/field_classifier.py` (simplified) | Complete | 129 |
| `dep_adapters/crd_dep.py` (orchestrator) | Complete | 275 |
| Delete `adapters/kubernetes_crd.py` (379 LOC) | Complete | -379 |
| `ClassifiedField.detection_source` | Complete | -- |
| `ClassifiedField.fact_shape` | Complete | -- |

**Spec deviations:**
- `crd_dep.py` is 275 LOC (spec target: ~50 LOC) -- includes Phase 5A additions
- `classify_walked_field` returns `list[ClassifiedField]` (spec said `tuple[list, ManifestFlags]`; plan corrected to pass-in accumulator)
- Generic status confidence threshold: 0.6 (plan value), not 0.75 (spec value)

### Phase 3: Schema Signal Extraction

| Component | Status |
|-----------|--------|
| `detect_ref_tuple` (C19) | Complete |
| `detect_example_kinds` (C24) | Complete |
| `detect_apigroup_literal` (C25) | Complete |
| `detect_passthrough_manifest` (C26) | Complete |
| `detect_status_output` with addressability (C27) | Complete |
| `suppress_false_positives` (C28) | Complete |
| `ManifestFlags` accumulator | Complete |

**Spec deviations:**
- Pass-in accumulator pattern instead of tuple return (deliberate plan correction)

### Phase 4: External Data Source Integration

| Component | Status | LOC |
|-----------|--------|:---:|
| `dep_adapters/rbac_deps.py` | Complete | ~350 |
| `dep_adapters/olm_deps.py` | Complete | ~200 |
| `crd/olm_loader.py` | Complete | ~180 |

**Spec deviations:**
- `extract_rbac_edges` name and parameter (string content vs. file path)
- `GVKRef` has `plural` field (not in spec; better than spec)
- OLM adapter `field` format includes group (plan correction)
- RBAC adapter makes network calls at runtime (spec concern P4-04)

### Phase 5A: Structural Detection Extensions

| Component | Status |
|-----------|--------|
| `detect_scale_subresource` (C20) | Complete |
| Webhook parsing (C21) -- in rbac_deps.py | Complete |
| `detect_embedded_workload` (C22) | Complete |
| `detect_constraint_fk` (C29) | Complete |
| `detect_cataloged_shape` (C30) / `build_shape_catalog.py` | Complete |
| `detect_kubernetes_extensions` (C32) | Complete |

**Spec deviations:**
- `build_shape_catalog.py` inside Python package (not at `scripts/` root)

---

## 2. Bug Fixes Applied (Post-Audit)

### Bug 1: detect_kubernetes_extensions invalid role
- **Problem:** `role="passthrough_manifest"` not a valid ClassifiedField role; silently discarded
- **Fix:** Single Kind enum -> `input_ref`; true passthrough -> `config_field` + ManifestFlags

### Bug 2: detect_constraint_fk never receives sibling data
- **Problem:** `sibling_fields` only populated for enum fields; C29 targets DNS-pattern fields
- **Fix:** Also populate sibling_fields for string fields with pattern or format constraints

### Bug 3: detect_constraint_fk results filtered (by design)
- **Problem:** `target_kind=None` results filtered by crd_dep.py
- **Resolution:** Correct behavior per precision > recall. Bug 2 fix enables C29 to function

### Bug 4: target_plural always empty string
- **Problem:** `output_writer.py` never resolved target_plural from KindRegistry
- **Fix:** Added optional `registry` parameter; `kind_to_plural()` called when provided

### Bug 5: max_depth=5 too shallow
- **Problem:** 25 expected edges at depth 6-7 unreachable
- **Fix:** Changed default from 5 to 8

### Bug 6: `kind` in EXCLUDED_FIELDS blocks discriminators
- **Problem:** `kind` excluded at every level; blocks `services[].kind` with enum
- **Fix:** Only exclude `kind` at depth 1 (root K8s envelope)

### Bug 7: `selector` in EXCLUDED_FIELDS blocks PushSecret
- **Problem:** `PushSecret.spec.selector` children unreachable
- **Fix:** Removed `selector` from EXCLUDED_FIELDS (matchLabels/matchExpressions don't trigger ref detection)

---

## 3. Test Results

### Before fixes
- **Tests passing:** 781
- **Edge detection:** 194 detected / 266 expected = 72.9%

### After fixes
- **Tests passing:** 787 (+6 new tests)
- **Edge detection (projected):** Up to 224 detectable (depth + selector + kind fixes)
  - DEPTH_LIMIT: 25 edges now reachable (max_depth 5 -> 8)
  - EXCLUDED_ANCESTOR: 2 edges now reachable (selector removed)
  - EXCLUDED_KIND_SIBLING: 3 edges potentially detectable (kind at depth > 1)
  - **Projected rate:** ~84.2% (224/266)

### Remaining gaps (not addressable by bug fixes alone)
- SECRET_KEY_SELECTOR_MISSED: 18 edges (needs new detector)
- MISSING_PARENT_KIND_DETECTOR: 16 edges (needs new detector)
- REF_TUPLE_UNRESOLVABLE: 4 edges (generatorRef; needs registry expansion)
- DESCRIPTION_ONLY_REF: 2 edges (NLP enhancement)
- DETECTOR_MISS: 2 edges (debug required)

---

## 4. Known Issues

### 4.1 Critical

| Issue | Audit ID | Status |
|-------|----------|--------|
| All contract documents missing | XP-01 | Not created (retroactive creation not practical) |
| All post-summaries missing | XP-02 | This document serves as consolidated summary |
| dep-adapter-reference.md | XP-03 | Created (retroactive) |

### 4.2 High

| Issue | Audit ID | Status |
|-------|----------|--------|
| RBAC adapter makes runtime network calls | P4-04 | Not fixed (architectural change needed) |

### 4.3 Medium

| Issue | Audit ID | Status |
|-------|----------|--------|
| crd_dep.py 275 LOC vs spec target 50 | P2-04 | Accepted (includes Phase 5A additions) |
| `_SHORT_NAME_ALIASES` dict | P1-05 | Documented in dep-adapter-reference.md |
| Claim/Volume aliases not in spec | P1-06 | Documented |
| Golden-file test structure differs | P1-10 | Accepted (inline fixtures work correctly) |
| RBAC API name differs from spec | P4-01 | Accepted (better testability) |

### 4.4 Low

| Issue | Audit ID | Status |
|-------|----------|--------|
| Stale docstrings in adapters/__init__.py | P2-02 | Not fixed (cosmetic) |
| `kinds_for_group()` not in frozen API | P1-04 | Documented |
| `GVKRef.plural` not in spec | P4-02 | Accepted (better than spec) |

---

## 5. File Inventory

### New files created (Phases 1-5A)

| File | Phase | LOC |
|------|:---:|:---:|
| `crd/kind_registry.py` | 1 | 291 |
| `crd/schema_walker.py` | 2 | 200 |
| `crd/ref_detector.py` | 2-5A | ~1600 |
| `dep_adapters/olm_deps.py` | 4 | ~200 |
| `dep_adapters/rbac_deps.py` | 4 | ~350 |
| `crd/olm_loader.py` | 4 | ~180 |
| `scripts/build_shape_catalog.py` | 5A | ~150 |

### Files modified

| File | Changes |
|------|---------|
| `crd/field_classifier.py` | Simplified to facade (~129 LOC) |
| `crd/output_writer.py` | Decomposed format (schema v2.0) |
| `dep_adapters/crd_dep.py` | Orchestrator for schema walker pipeline |
| `adapters/__init__.py` | Removed KubernetesCrdAdapter references |

### Files deleted

| File | Phase | LOC removed |
|------|:---:|:---:|
| `adapters/kubernetes_crd.py` | 2 | 379 |

---

## 6. Architecture Decisions Record

1. **Pass-in accumulator over tuple return** (Phase 3): `ManifestFlags` passed as mutable parameter instead of changing `classify_walked_field` return type. Preserves backward compatibility.

2. **Precision > recall** (all phases): No edge emitted below confidence 0.7. False edge -> deadlock or phantom cycle. Missing edge -> suboptimal ordering. This constraint is maintained throughout.

3. **`crdfacts://` URI scheme** (Phase 1): All CRD dependency edges use `crdfacts://{group}/{Kind}#{field}` format with `#name` fragment convention.

4. **Schema walker depth 8** (Bug fix): Increased from 5 to cover depth-7 provider auth chains in external-secrets and cert-manager.

5. **Depth-aware `kind` exclusion** (Bug fix): `kind` excluded at root level only (K8s envelope), allowed at deeper levels for discriminator enum detection.

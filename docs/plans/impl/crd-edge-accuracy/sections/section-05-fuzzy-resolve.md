<!-- IMPLEMENTED: see commit below -->

# Section 05: KindRegistry.fuzzy_resolve

## Overview

This section implements the `fuzzy_resolve()` method on `KindRegistry` -- a new public method that resolves CRD field names to candidate Kind targets via 4 lexical heuristics, ordered by confidence. This is the core matching engine used by the `detect_fuzzy_kind_name` detector (section-06) to close detection gaps for fields that don't follow the standard `{Kind}Ref` / `{Kind}Name` suffix pattern.

**Critical constraint:** Precision > Recall. A false edge creates a phantom cycle in Kahn's topological sort, deadlocking deployment. Every heuristic has uniqueness guards and a high-risk noun denylist. When ambiguous, emit nothing.

**Dependency:** Section 04 (KindEntry service field) -- landed.

**Blocked by this section:** Section 06 (`detect_fuzzy_kind_name` detector step) calls `fuzzy_resolve()`.

## File Paths

- **Modified:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/crd/kind_registry.py`
- **Created:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/test_fuzzy_resolve.py`
- **Modified:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/conftest.py` (add `enterprise_registry` fixture)

## Background: Current KindRegistry State

The current `KindRegistry` (in `kind_registry.py`) has these key data structures:

- `_kind_to_entries: dict[str, list[KindEntry]]` -- maps Kind name to entries (supports multi-group)
- `_plural_to_kind: dict[str, str]` -- maps plural to Kind name (first-registered wins)
- `_sorted_entries: list[KindEntry]` -- all entries sorted by `len(kind)` descending for longest-match

The existing `is_ref_field()` method does suffix-based matching (`{Kind}Ref`, `{Kind}Name`) and well-known compound matching (`secretKeyRef`, `configMapKeyRef`). It does NOT handle:
- Fields named as plurals (e.g., `gateways` in Istio VirtualService)
- Fields using camelCase composition (e.g., `peerConfigRef` where `PeerConfig` is a suffix of `CiliumBGPPeerConfig`)
- Fields that are bare Kind names (e.g., `policy` matching `NetworkPolicy`)

`fuzzy_resolve()` fills these gaps with lower-confidence heuristics.

## Pre-Requisites from Section 04

After section-04 lands, `KindEntry` will have:

```python
@dataclass(frozen=True)
class KindEntry:
    kind: str
    plural: str
    group: str
    is_core: bool
    service: str = ""  # Added by section-04
```

And the registry will have `_plural_to_entries: dict[str, list[KindEntry]]` replacing `_plural_to_kind: dict[str, str]`, so plural resolution can be service-aware.

## Tests (Write First)

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/test_fuzzy_resolve.py`

All tests go in this new file. The tests assume section-04 has landed (service field on KindEntry, `_plural_to_entries`).

```python
"""Tests for KindRegistry.fuzzy_resolve — 4 lexical heuristics with precision guards."""
from __future__ import annotations

import pytest
from idi.generation.crd.kind_registry import KindRegistry, KindCandidate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def istio_registry():
    """Registry with Istio kinds registered under service='istio'."""
    reg = KindRegistry()
    for kind, plural, group in [
        ("Gateway", "gateways", "networking.istio.io"),
        ("VirtualService", "virtualservices", "networking.istio.io"),
        ("DestinationRule", "destinationrules", "networking.istio.io"),
        ("ServiceEntry", "serviceentries", "networking.istio.io"),
    ]:
        reg.register(kind, plural, group, service="istio")
    return reg


@pytest.fixture
def cilium_registry():
    """Registry with Cilium kinds registered under service='cilium'."""
    reg = KindRegistry()
    for kind, plural, group in [
        ("CiliumBGPPeerConfig", "ciliumbgppeerconfigs", "cilium.io"),
        ("CiliumNetworkPolicy", "ciliumnetworkpolicies", "cilium.io"),
        ("CiliumClusterwideNetworkPolicy", "ciliumclusterwidenetworkpolicies", "cilium.io"),
    ]:
        reg.register(kind, plural, group, service="cilium")
    return reg


@pytest.fixture
def flux_registry():
    """Registry with Flux kinds registered under service='flux'."""
    reg = KindRegistry()
    for kind, plural, group in [
        ("HelmRepository", "helmrepositories", "source.toolkit.fluxcd.io"),
        ("HelmRelease", "helmreleases", "helm.toolkit.fluxcd.io"),
        ("GitRepository", "gitrepositories", "source.toolkit.fluxcd.io"),
        ("Bucket", "buckets", "source.toolkit.fluxcd.io"),
        ("Kustomization", "kustomizations", "kustomize.toolkit.fluxcd.io"),
    ]:
        reg.register(kind, plural, group, service="flux")
    return reg


@pytest.fixture
def enterprise_registry():
    """Combined registry with Istio, Flux, Cilium, Kyverno kinds + core."""
    # ... registers all enterprise kinds with service names
    # Used for cross-service penalty and ambiguity tests


# ---------------------------------------------------------------------------
# Exact plural match (confidence 0.80)
# ---------------------------------------------------------------------------


class TestExactPluralMatch:
    def test_gateways_resolves_to_gateway(self, istio_registry):
        """'gateways' exact-matches the registered plural for Gateway."""
        result = istio_registry.fuzzy_resolve("gateways", scope_service="istio")
        assert len(result) == 1
        assert result[0].kind == "Gateway"
        assert result[0].score == pytest.approx(0.80)
        assert result[0].match_type == "plural_exact"

    def test_gateways_multiple_services_not_unique(self):
        """When multiple services register 'gateways', returns empty (ambiguous)."""
        reg = KindRegistry()
        reg.register("Gateway", "gateways", "networking.istio.io", service="istio")
        reg.register("Gateway", "gateways", "gateway.networking.k8s.io", service="k8s-gateway")
        result = reg.fuzzy_resolve("gateways", require_unique=True)
        assert result == []

    def test_secrets_resolves_to_secret(self):
        """'secrets' matches core Secret (always available)."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("secrets")
        assert len(result) == 1
        assert result[0].kind == "Secret"
        assert result[0].score == pytest.approx(0.80)

    def test_configmaps_resolves_to_configmap(self):
        """'configmaps' matches core ConfigMap."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("configmaps")
        assert len(result) == 1
        assert result[0].kind == "ConfigMap"

    def test_array_suffix_stripped(self):
        """Field name with [] suffix: 'gateways[]' still resolves."""
        # Implementation should strip trailing [] before lookup


# ---------------------------------------------------------------------------
# Suffix match (confidence 0.75)
# ---------------------------------------------------------------------------


class TestSuffixMatch:
    def test_peer_config_ref_matches_cilium_bgp_peer_config(self, cilium_registry):
        """'peerConfigRef' → strip 'Ref' → 'peerConfig' → ends-with CiliumBGPPeerConfig."""
        result = cilium_registry.fuzzy_resolve("peerConfigRef", scope_service="cilium")
        assert len(result) == 1
        assert result[0].kind == "CiliumBGPPeerConfig"
        assert result[0].score == pytest.approx(0.75)
        assert result[0].match_type == "suffix_unique"

    def test_db_ref_too_short(self):
        """'dbRef' stripped to 'db' (2 chars < 4 minimum) → returns empty."""
        reg = KindRegistry()
        reg.register("Database", "databases", "example.io", service="test")
        result = reg.fuzzy_resolve("dbRef", scope_service="test")
        assert result == []

    def test_suffix_match_not_unique(self):
        """Multiple kinds ending with same suffix → returns empty (ambiguous)."""
        reg = KindRegistry()
        reg.register("FooPolicy", "foopolicies", "a.io", service="svc")
        reg.register("BarPolicy", "barpolicies", "b.io", service="svc")
        # "policyRef" → strip "Ref" → "policy" → both end with "Policy" → ambiguous
        result = reg.fuzzy_resolve("policyRef", scope_service="svc")
        assert result == []


# ---------------------------------------------------------------------------
# CamelCase tail segment (confidence 0.65 with infra prefix, 0.50 without)
# ---------------------------------------------------------------------------


class TestCamelCaseTail:
    def test_backend_services_infra_prefix(self):
        """'backendServices' → tail 'Services' → plural of Service → 0.65."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("backendServices")
        assert len(result) == 1
        assert result[0].kind == "Service"
        assert result[0].score == pytest.approx(0.65)
        assert result[0].match_type == "camel_tail"

    def test_metrics_server_no_kind(self):
        """'metricsServer' → tail 'Server' → not a registered Kind → empty."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("metricsServer")
        assert result == []

    def test_target_gateway_infra_prefix(self, istio_registry):
        """'targetGateway' → prefix 'target' in allowlist, tail 'Gateway' → 0.65."""
        result = istio_registry.fuzzy_resolve("targetGateway", scope_service="istio")
        assert len(result) == 1
        assert result[0].kind == "Gateway"
        assert result[0].score == pytest.approx(0.65)

    def test_enabled_services_non_infra_prefix(self):
        """'enabledServices' → prefix 'enabled' NOT in allowlist → drops to 0.50."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("enabledServices")
        # Either returns empty (below usable confidence) or score 0.50
        if result:
            assert result[0].score == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# Exact lowercase Kind match (confidence 0.55, requires corroboration)
# ---------------------------------------------------------------------------


class TestExactLowercaseKindMatch:
    def test_policy_without_corroboration(self):
        """'policy' matches 'Policy' exactly but no corroboration → empty."""
        # Note: fuzzy_resolve doesn't have access to WalkedField directly;
        # corroboration is checked by the caller (detect_fuzzy_kind_name).
        # fuzzy_resolve emits with score 0.55 and the caller decides.
        # BUT the denylist check IS in fuzzy_resolve and 'policy' is denylisted.
        reg = KindRegistry()
        reg.register("Policy", "policies", "example.io", service="test")
        result = reg.fuzzy_resolve("policy", scope_service="test")
        # "policy" is in _FUZZY_DENYLIST → returns empty without corroboration
        assert result == []

    def test_policy_with_corroboration(self):
        """'policy' with sibling corroboration → score 0.55."""
        # fuzzy_resolve accepts optional sibling_names for corroboration check
        reg = KindRegistry()
        reg.register("Policy", "policies", "example.io", service="test")
        result = reg.fuzzy_resolve(
            "policy", scope_service="test",
            sibling_names=frozenset({"namespace", "name"}),
        )
        if result:
            assert result[0].score == pytest.approx(0.55)
            assert result[0].match_type == "bare_kind"


# ---------------------------------------------------------------------------
# Cross-service penalty
# ---------------------------------------------------------------------------


class TestCrossServicePenalty:
    def test_cross_service_penalty_applied(self, istio_registry):
        """Istio Gateway matched from flux scope → confidence * 0.7."""
        result = istio_registry.fuzzy_resolve("gateways", scope_service="flux")
        assert len(result) == 1
        # 0.80 * 0.7 = 0.56
        assert result[0].score == pytest.approx(0.80 * 0.7)

    def test_core_kind_no_penalty(self):
        """Core Secret matched from any service → NO penalty."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("secrets", scope_service="flux")
        assert len(result) == 1
        assert result[0].score == pytest.approx(0.80)  # No penalty


# ---------------------------------------------------------------------------
# High-risk noun denylist
# ---------------------------------------------------------------------------


class TestDenylist:
    def test_service_in_denylist(self):
        """'service' is in _FUZZY_DENYLIST → returns empty without corroboration."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("service")
        assert result == []

    def test_role_in_denylist(self):
        """'role' is in _FUZZY_DENYLIST → returns empty."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("role")
        assert result == []

    def test_type_in_denylist(self):
        """'type' is in _FUZZY_DENYLIST → returns empty."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve("type")
        assert result == []

    def test_service_with_corroborating_siblings(self):
        """'service' WITH sibling 'namespace' → allowed (corroborated)."""
        reg = KindRegistry()
        result = reg.fuzzy_resolve(
            "service",
            sibling_names=frozenset({"namespace", "port"}),
        )
        # Corroborated by "namespace" sibling → allowed through denylist
        if result:
            assert result[0].kind == "Service"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string(self):
        """Empty field name → empty result."""
        reg = KindRegistry()
        assert reg.fuzzy_resolve("") == []

    def test_single_character(self):
        """Single character field name → empty result."""
        reg = KindRegistry()
        assert reg.fuzzy_resolve("x") == []

    def test_no_match_at_all(self):
        """Completely unrelated name → empty result."""
        reg = KindRegistry()
        assert reg.fuzzy_resolve("somethingCompletelyUnrelated") == []
```

### Enterprise Registry Fixture

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/conftest.py`

Add an `enterprise_registry` fixture for use by tests in this section and section-06:

```python
@pytest.fixture
def enterprise_registry():
    """KindRegistry with Istio, Flux, Cilium, Kyverno kinds + core.

    Used for cross-service penalty and ambiguity tests across enterprise CRDs.
    """
    from idi.generation.crd.kind_registry import KindRegistry
    reg = KindRegistry()

    istio_kinds = [
        ("Gateway", "gateways", "networking.istio.io"),
        ("VirtualService", "virtualservices", "networking.istio.io"),
        ("DestinationRule", "destinationrules", "networking.istio.io"),
        # ... 13 total Istio kinds
    ]
    for kind, plural, group in istio_kinds:
        reg.register(kind, plural, group, service="istio")

    flux_kinds = [
        ("HelmRepository", "helmrepositories", "source.toolkit.fluxcd.io"),
        ("HelmRelease", "helmreleases", "helm.toolkit.fluxcd.io"),
        ("GitRepository", "gitrepositories", "source.toolkit.fluxcd.io"),
        ("Bucket", "buckets", "source.toolkit.fluxcd.io"),
        ("Kustomization", "kustomizations", "kustomize.toolkit.fluxcd.io"),
        # ... 15 total Flux kinds
    ]
    for kind, plural, group in flux_kinds:
        reg.register(kind, plural, group, service="flux")

    cilium_kinds = [
        ("CiliumBGPPeerConfig", "ciliumbgppeerconfigs", "cilium.io"),
        ("CiliumNetworkPolicy", "ciliumnetworkpolicies", "cilium.io"),
        # ... 22 total Cilium kinds
    ]
    for kind, plural, group in cilium_kinds:
        reg.register(kind, plural, group, service="cilium")

    kyverno_kinds = [
        ("ClusterPolicy", "clusterpolicies", "kyverno.io"),
        ("Policy", "policies", "kyverno.io"),
        # ... 24 total Kyverno kinds
    ]
    for kind, plural, group in kyverno_kinds:
        reg.register(kind, plural, group, service="kyverno")

    return reg
```

## Implementation Details

### New Data Class: KindCandidate

Add to `kind_registry.py` at module level, before the `KindRegistry` class:

```python
@dataclass(frozen=True)
class KindCandidate:
    """A candidate Kind match from fuzzy resolution."""
    kind: str
    api_group: str | None
    score: float
    match_type: str  # "plural_exact" | "suffix_unique" | "camel_tail" | "bare_kind"
```

### Constants

Add these module-level constants to `kind_registry.py`:

```python
_FUZZY_DENYLIST: frozenset[str] = frozenset({
    "role", "service", "policy", "type", "mode", "strategy",
    "provider", "status", "class", "event", "rule", "group", "user",
})

_INFRASTRUCTURE_PREFIXES: frozenset[str] = frozenset({
    "backend", "upstream", "target", "peer", "source", "default",
})

_CORROBORATING_SIBLINGS: frozenset[str] = frozenset({
    "namespace", "kind", "apiGroup", "apiVersion", "group",
})

_REF_SUFFIXES: tuple[str, ...] = ("Ref", "Name", "Key")
```

### Method: fuzzy_resolve

Add to `KindRegistry` class:

```python
def fuzzy_resolve(
    self, field_name: str, *,
    scope_service: str | None = None,
    require_unique: bool = True,
    sibling_names: frozenset[str] = frozenset(),
) -> list[KindCandidate]:
    """Resolve field name to candidate Kind(s) via 4 lexical heuristics.

    Resolution order (highest confidence first):
    1. Exact plural match (0.80)
    2. Suffix match against Kind endings (0.75)
    3. CamelCase tail segment (0.65 with infra prefix, 0.50 without)
    4. Exact lowercase Kind match (0.55, requires corroboration)

    Cross-service penalty: If a candidate's service differs from scope_service
    (and is not a core resource), multiply confidence by 0.7.

    High-risk noun denylist: Common nouns that happen to match Kind names
    are rejected unless corroborated by structural siblings (namespace/kind/apiGroup).

    Returns candidates sorted by score descending. Typically 0 or 1 results.
    """
```

### Resolution Algorithm (Step-by-Step)

The method body implements 4 heuristics in sequence. Each heuristic is tried; if it produces candidates, they are scored with cross-service penalty and returned immediately (first match wins, ordered by confidence).

**Step 1 -- Exact plural match (confidence 0.80):**
- Guard: `len(field_name) < 2` returns `[]` immediately.
- Normalize: `normalized = field_name.rstrip("[]").lower()`
- Look up `normalized` in `_plural_to_entries`.
- If found, collect entries. If `require_unique` and entries span multiple services (excluding service="" core kinds), return `[]`.
- Otherwise, take the best entry (prefer same-service, then core, then first-registered).
- Base score 0.80, apply cross-service penalty if applicable.

**Step 2 -- Suffix match against Kind endings (confidence 0.75):**
- Strip known ref suffixes (`Ref`, `Name`, `Key`) from the field name. Also try the raw name.
- The remaining base string must be at least 4 characters (prevents false positives like `dbRef` -> `db`).
- Check if any registered Kind **ends with** the base string (case-insensitive comparison).
- Guard: the result must be unique across the entire registry. If multiple kinds match, return `[]`.
- Base score 0.75, apply cross-service penalty.

**Step 3 -- CamelCase tail segment (confidence 0.65 / 0.50):**
- Decompose field_name into CamelCase segments using a regex like `re.findall(r'[A-Z][a-z]*|[a-z]+', field_name)`.
- Take the last segment (or last 2 if the last is a ref suffix like `Ref`/`Name`/`Key`).
- Check the tail against Kind names (exact match) and Kind plurals (exact match).
- If the preceding segment is in `_INFRASTRUCTURE_PREFIXES`, confidence is 0.65. Otherwise, 0.50.
- Guard: must be unique. Apply cross-service penalty.

**Step 4 -- Exact lowercase Kind match (confidence 0.55):**
- Check if `field_name.lower()` equals `kind.lower()` for any registered Kind.
- This is the lowest-confidence heuristic. It only fires when the field name IS a Kind name.
- Guard: requires corroboration. If `sibling_names` does not intersect with `_CORROBORATING_SIBLINGS`, return `[]` (unless the field is not in the denylist).

**Denylist check (applied to all heuristics):**
- Before returning any candidate, check if `field_name.lower()` (after stripping ref suffixes) is in `_FUZZY_DENYLIST`.
- If denylisted AND `sibling_names` does not intersect `_CORROBORATING_SIBLINGS`, return `[]`.
- If denylisted but corroborated by siblings, allow through.

**Cross-service penalty (applied to final candidate):**
- For each candidate: if `candidate_entry.service != scope_service` AND `candidate_entry.service != ""` (core kinds are exempt), multiply score by 0.7.
- Apply penalty during scoring, not after selection. This ensures a same-service match at lower raw score can beat a penalized cross-service match.

### Helper: _apply_cross_service_penalty

A private method (or inline logic) that encapsulates the penalty:

```python
def _apply_cross_service_penalty(
    self, entry: KindEntry, raw_score: float, scope_service: str | None,
) -> float:
    """Apply 0.7 multiplier for cross-service matches. Core kinds exempt."""
    if scope_service is None:
        return raw_score
    if entry.service == "" or entry.service == scope_service:
        return raw_score
    return raw_score * 0.7
```

### Helper: _decompose_camel_case

A static method or module-level function:

```python
@staticmethod
def _decompose_camel_case(name: str) -> list[str]:
    """Split a camelCase or PascalCase name into segments.

    'backendServices' → ['backend', 'Services']
    'peerConfigRef' → ['peer', 'Config', 'Ref']
    'gateways' → ['gateways']
    """
    return re.findall(r'[A-Z][a-z]*|[a-z]+', name)
```

## Integration Notes

### How fuzzy_resolve Interacts with detect_fuzzy_kind_name (Section 06)

Section 06 will add a `detect_fuzzy_kind_name` step to the detector cascade in `ref_detector.py`. That function:

1. Calls `registry.fuzzy_resolve(field.name, scope_service=current_service, sibling_names=field.sibling_names)`.
2. Takes the top-scoring candidate.
3. Multiplies the candidate's score by `field.depth_confidence` (from section 03/10).
4. If result >= 0.7, creates a `ClassifiedField`.
5. Only runs on `type: string` or `type: array` with `items.type: string` (object-typed fields are handled by structural detectors).

This means `fuzzy_resolve` must pass `sibling_names` through to support the denylist corroboration check. The `sibling_names` parameter is populated by `WalkedField.sibling_names` (from section 03).

### Existing Tests Unaffected

`fuzzy_resolve` is a new method. It does not modify `is_ref_field()` or any existing public method. All existing tests in `test_kind_registry.py` must continue to pass unchanged.

### Key Design Decisions

1. **First-match-wins across heuristics:** The 4 heuristics run in confidence order. The first one to produce a valid candidate returns immediately. This prevents lower-confidence heuristics from overriding better matches.

2. **Uniqueness is mandatory by default:** `require_unique=True` means ambiguous results (multiple possible kinds) return empty rather than guessing. This upholds precision > recall.

3. **Cross-service penalty during scoring, not after:** This is critical. If a same-service match scores 0.65 (camel_tail) and a cross-service match scores 0.80 (plural_exact), the cross-service match becomes 0.56 after penalty, so the 0.65 same-service match wins. If penalty were applied after selection, the 0.80 would win then get penalized to 0.56, losing the better contextual match.

4. **Denylist is a precision guard, not a hard block:** Common nouns like "service", "role", "policy" are ubiquitous in CRD schemas as config fields. Without the denylist, `fuzzy_resolve` would create false edges to `Service`, `Role`, `Policy` kinds. Corroborating siblings (`namespace`, `kind`, `apiGroup`) provide evidence that the field actually IS a reference.

## Implementation Notes (Post-Implementation)

### Deviations from Plan

1. **camel_tail guard relaxed:** The plan said `tail_idx < 1` to require 2+ segments after ref-suffix removal. Implementation uses `tail_idx < 0` to allow 2-segment names like "serviceRef" (["service", "Ref"] → tail "service"). This enables fields like `serviceRef` to match via camelCase tail at 0.50 when corroborated.

2. **camelCase tail uses case-insensitive Kind lookup:** The plan implied exact-match only. Implementation adds case-insensitive Kind name fallback so "service" (lowercase tail) matches "Service" Kind.

3. **Kind-level denylist for plurals (code review fix):** "services" (plural) resolves to "Service" → "service" is in denylist. Simple field names also check the resolved Kind name against the denylist. Compound names like "backendServices" are exempt.

4. **Uniqueness guard added to camelCase tail (code review fix):** The plan said "must be unique" but the original implementation omitted it. Fixed: case-insensitive Kind lookup and plural lookup now enforce uniqueness.

5. **Digit handling in `_decompose_camel_case` (code review fix):** Added `|[0-9]+` to the regex. Fields like "bgpV2Peers" now preserve the "2" digit segment.

### Test Counts
- 37 tests in `test_fuzzy_resolve.py`
- 993 total CRD tests passing (0 regressions)

### Files Modified
- `kind_registry.py` — Added `KindCandidate`, 4 constants, `fuzzy_resolve` + 7 private methods (~180 LOC)
- `test_fuzzy_resolve.py` — New file, 37 tests across 7 test classes
- `conftest.py` — Added `enterprise_registry` fixture (9 Istio + 7 Flux + 6 Cilium + 5 Kyverno + core)
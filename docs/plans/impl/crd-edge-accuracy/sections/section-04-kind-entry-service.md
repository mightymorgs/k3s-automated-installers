Now I have a comprehensive understanding of the codebase. Let me generate the section content.

# Section 04 — KindEntry Service Field

## Overview

This section adds a `service: str` field to `KindEntry` in `kind_registry.py`, enabling service-aware resolution for the `fuzzy_resolve` method (section-05). The change also converts the internal `_plural_to_kind` dict to `_plural_to_entries` so that plural resolution can distinguish between Kinds registered by different services. Finally, all call sites that invoke `register()` are updated to pass the service name.

**Precision motivation:** Without service scoping, a field named `gateways` in a Cilium CRD could ambiguously resolve to Istio's `Gateway` Kind. The `service` field enables a cross-service confidence penalty in `fuzzy_resolve` (section-05), reducing false edges.

**Dependencies:** None. This section is in Batch 1 (parallelizable).

**Blocks:** section-05 (`fuzzy_resolve` reads `KindEntry.service` and iterates `_plural_to_entries`).

## Files Modified

| File | Action |
|------|--------|
| `platform-tools/idi/idi/generation/crd/kind_registry.py` | Add `service` to `KindEntry`, update `register()`, convert `_plural_to_kind` to `_plural_to_entries` |
| `platform-tools/idi/idi/generation/generate_all.py` | Pass `service=svc_name` to `registry.register()` in both Pass 1 and fallback paths |
| `platform-tools/idi/idi/generation/dep_adapters/olm_deps.py` | Pass `service=service` to `registry.register()` |
| `platform-tools/idi/tests/generation/crd/test_kind_registry.py` | Add service-field tests |
| `platform-tools/idi/tests/generation/crd/conftest.py` | Update `populated_registry` to pass `service` |

## Tests (Write First)

**File:** `platform-tools/idi/tests/generation/crd/test_kind_registry.py`

Add a new test class `TestKindEntryService` alongside the existing test classes. These tests validate the new `service` field on `KindEntry`, the updated `register()` signature, and the `_plural_to_entries` data structure.

```python
class TestKindEntryService:
    """Tests for service-aware KindEntry registration (section-04)."""

    def test_register_with_service_stores_service(self):
        """register() with service= stores service string on KindEntry."""
        reg = KindRegistry()
        reg.register("Gateway", "gateways", "networking.istio.io", service="istio")
        entries = reg._kind_to_entries["Gateway"]
        assert len(entries) == 1
        assert entries[0].service == "istio"

    def test_core_resources_have_empty_service(self):
        """Core K8s resources registered at init have service='' (empty string)."""
        reg = KindRegistry()
        entries = reg._kind_to_entries["Secret"]
        assert all(e.service == "" for e in entries)

    def test_register_without_service_defaults_empty(self):
        """register() without service= defaults to empty string."""
        reg = KindRegistry()
        reg.register("MyKind", "mykinds", "example.io")
        entries = reg._kind_to_entries["MyKind"]
        assert entries[0].service == ""

    def test_plural_to_entries_returns_list(self):
        """_plural_to_entries maps plural string to list of KindEntry."""
        reg = KindRegistry()
        reg.register("Gateway", "gateways", "networking.istio.io", service="istio")
        entries = reg._plural_to_entries.get("gateways", [])
        assert len(entries) == 1
        assert entries[0].kind == "Gateway"
        assert entries[0].service == "istio"

    def test_plural_to_entries_multiple_services(self):
        """Same plural from different services produces multiple entries."""
        reg = KindRegistry()
        reg.register("Gateway", "gateways", "networking.istio.io", service="istio")
        reg.register("Gateway", "gateways", "gateway.networking.k8s.io", service="contour")
        entries = reg._plural_to_entries.get("gateways", [])
        assert len(entries) == 2
        services = {e.service for e in entries}
        assert services == {"istio", "contour"}

    def test_plural_to_kind_still_works(self):
        """Public plural_to_kind() method continues to work after internal change."""
        reg = KindRegistry()
        assert reg.plural_to_kind("secrets") == "Secret"
        reg.register("Gateway", "gateways", "networking.istio.io", service="istio")
        assert reg.plural_to_kind("gateways") == "Gateway"

    def test_plural_to_kind_returns_none_for_unknown(self):
        """plural_to_kind() still returns None for unregistered plurals."""
        reg = KindRegistry()
        assert reg.plural_to_kind("notregistered") is None
```

All existing tests in `TestRegistration`, `TestLookups`, `TestIsRefFieldBasic`, `TestIsRefFieldLongestMatch`, `TestIsRefFieldCamelCase`, `TestIsRefFieldWellKnownCompounds`, `TestIsRefFieldMultiGroup`, `TestIsRefFieldAliases`, and `TestRefPatternsCoverage` must continue to pass unchanged. The `service` field defaults to `""`, so no existing `KindEntry` construction or comparison breaks.

## Implementation Details

### 1. Add `service` to `KindEntry`

**File:** `platform-tools/idi/idi/generation/crd/kind_registry.py`

Add `service: str = ""` to the frozen dataclass. The default ensures backward compatibility with all existing code that constructs `KindEntry` without a service parameter.

```python
@dataclass(frozen=True)
class KindEntry:
    """A registered Kubernetes resource Kind."""
    kind: str
    plural: str
    group: str
    is_core: bool
    service: str = ""  # Service that owns this Kind; "" for core K8s resources
```

### 2. Update `register()` signature

Add `service: str = ""` parameter. Pass it through to the `KindEntry` constructor.

```python
def register(
    self,
    kind: str,
    plural: str,
    group: str = "",
    is_core: bool = False,
    service: str = "",
) -> None:
    """Register a Kind with its plural form, optional API group, and owning service."""
    entry = KindEntry(kind=kind, plural=plural, group=group, is_core=is_core, service=service)
    # ... rest unchanged
```

### 3. Convert `_plural_to_kind` to `_plural_to_entries`

Replace the internal dict `_plural_to_kind: dict[str, str]` with `_plural_to_entries: dict[str, list[KindEntry]]`. This allows plural resolution to be service-aware (needed by `fuzzy_resolve` in section-05).

In `__init__`:
```python
def __init__(self) -> None:
    self._kind_to_entries: dict[str, list[KindEntry]] = {}
    self._plural_to_entries: dict[str, list[KindEntry]] = {}  # Changed from _plural_to_kind
    self._sorted_entries: list[KindEntry] = []
    self._load_core_resources()
```

In `register()`, update the plural mapping logic:
```python
# Update plural -> entries mapping (append, no longer first-wins).
plural_list = self._plural_to_entries.setdefault(plural, [])
if entry not in plural_list:
    plural_list.append(entry)
```

### 4. Update `plural_to_kind()` public method

The public API `plural_to_kind(plural) -> str | None` must continue to work. Reimplement it on top of `_plural_to_entries`:

```python
def plural_to_kind(self, plural: str) -> str | None:
    """Return Kind for a plural. Returns None if not registered."""
    entries = self._plural_to_entries.get(plural, [])
    if entries:
        return entries[0].kind
    return None
```

### 5. Update `register_from_crd()` to accept service

The `register_from_crd` method should also accept and forward a `service` parameter:

```python
def register_from_crd(self, crd_spec: dict, service: str = "") -> None:
    """Auto-register from CRD spec sub-dict."""
    names = crd_spec.get("names", {})
    kind = names.get("kind")
    plural = names.get("plural")
    group = crd_spec.get("group", "")
    if not kind or not plural:
        return
    self.register(kind, plural, group, service=service)
```

### 6. Update call sites in `generate_all.py`

**Pass 1** (global registry population in `generate_all()`): Pass the service name.

```python
# PASS 1: Populate global KindRegistry from ALL services.
registry = KindRegistry()
for svc_name, config in all_services.items():
    if config.get("style") == "kubernetes" and config.get("crd_kinds"):
        schemas = _load_crd_schemas_for_service(svc_name, config, specs_dir)
        for schema in schemas:
            registry.register(
                schema["kind"], schema["plural"], schema.get("group", ""),
                service=svc_name,
            )
```

**Fallback path** in `_generate_crd_service()` (when registry is None): Pass the service name.

```python
if registry is None:
    registry = KindRegistry()
    for schema in schemas:
        registry.register(
            schema["kind"], schema["plural"], schema.get("group", ""),
            service=name,
        )
```

### 7. Update call site in `olm_deps.py`

**File:** `platform-tools/idi/idi/generation/dep_adapters/olm_deps.py`

The `register()` call at line 56 needs to pass `service`. The `service` variable is already available in scope (it is the first argument to the enclosing method).

```python
self.registry.register(gvk.kind, gvk.plural, group=gvk.group, service=service)
```

### 8. Update conftest.py `populated_registry` fixture

**File:** `platform-tools/idi/tests/generation/crd/conftest.py`

The `populated_registry` fixture registers test CRDs but currently does not pass a service name. Update it to pass the service name from the fixture data (each fixture dict has a `"service"` key from the loader):

```python
@pytest.fixture
def populated_registry(core_only_registry, all_fixtures):
    """KindRegistry with 18 core + all 21 test CRDs registered."""
    for fix in all_fixtures:
        core_only_registry.register(
            kind=fix["kind"],
            plural=fix["plural"],
            group=fix["group"],
            service=fix.get("service", ""),
        )
    return core_only_registry
```

## Verification Checklist

1. All 7 new `TestKindEntryService` tests pass.
2. All existing `test_kind_registry.py` tests pass unchanged (the `service=""` default preserves backward compatibility).
3. The `_rebuild_sorted` method continues to work correctly (the dedup key tuple `(kind, plural, group)` should be extended to `(kind, plural, group, service)` to avoid collapsing same-Kind entries from different services).
4. `plural_to_kind()` returns the same results as before for all existing callers.
5. Run `uv run pytest tests/generation/crd/ -v` from `platform-tools/idi/` -- all tests pass.
6. Run `uv run pytest tests/ -v` from `platform-tools/idi/` -- full suite passes.

## Important Detail: `_rebuild_sorted` dedup key

The existing `_rebuild_sorted` method deduplicates using `(kind, plural, group)` as the key. With the addition of `service`, two entries for the same Kind+plural+group but different services would be collapsed. Update the dedup key to include `service`:

```python
def _rebuild_sorted(self) -> None:
    """Rebuild _sorted_entries sorted by len(kind) descending."""
    all_entries: list[KindEntry] = []
    for entries in self._kind_to_entries.values():
        all_entries.extend(entries)
    seen: set[tuple[str, str, str, str]] = set()  # Added service
    unique: list[KindEntry] = []
    for e in all_entries:
        key = (e.kind, e.plural, e.group, e.service)  # Added service
        if key not in seen:
            seen.add(key)
            unique.append(e)
    self._sorted_entries = sorted(unique, key=lambda e: len(e.kind), reverse=True)
```

This is important because `KindEntry` is a frozen dataclass and participates in equality checks. Two entries that differ only by `service` must both be retained in `_sorted_entries` for `fuzzy_resolve` (section-05) to perform correct service-aware scoring.
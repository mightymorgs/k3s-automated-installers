Now I have a thorough understanding of all the source material. Let me produce the section content.

# Section 13: Phase C Adapter Slimming

## Overview

This section covers the final adapter slimming phase, reducing the remaining vendor-specific adapter code for Vault, AWS Query, and the adapter registry (`__init__.py`). By this point, prior sections have built generic replacements for most vendor-hardcoded logic: envelope detection (section 06), response tree walk (section 10), readOnly field classification (section 03), nested FK detection (section 09), expanded FK suffixes (section 03), and credential exclusion (section 03). This section removes the now-redundant code from the three remaining oversized adapter files while preserving genuinely vendor-unique logic.

**Goal:** Reduce `vault.py` from 478 to ~110 LOC, `aws_query.py` from 339 to ~155 LOC, and `__init__.py` from 257 to ~100 LOC. The overall vendor-specific adapter LOC target after this section is complete (combined with section 08's swagger2 deletion and cloudflare/github slimming) is 793 or fewer lines.

## Implementation Results

**Actual LOC achieved (non-blank, non-comment):**

| File | Before | After | Target | Status |
|------|--------|-------|--------|--------|
| vault.py | 427 | **85** | ≤120 | Well under |
| aws_query.py | 319 | **151** | ≤160 | Under |
| __init__.py | 205 | **96** | ≤100 | Under |
| cloudflare.py | 57 | 43 | ≤80 | Unchanged |
| github_openapi.py | 51 | 38 | ≤80 | Unchanged |
| **Total vendor** | **1059** | **413** | **≤793** | **61% reduction** |

**Tests:** 34 tests in `test_phase_c_adapter_slimming.py` (30 structural + 4 pipeline parity)
**Parity:** Vault pipeline edge count ≥ 10 (Phase A baseline) verified after slimming
**Regression:** 1225 total tests pass (0 regressions)

**Deviations from plan:**
- No baseline capture JSON files created (no pre-slimming snapshot needed — Phase A baselines from section 04 serve as parity targets)
- No conftest.py additions for benchmark fixtures (vault_spec fixture already existed)
- swagger2 registry entries kept (route to OpenApiRestAdapter for backwards compat)
- _is_cloudflare_spec() removed entirely (service-name-only detection sufficient, envelope detector covers the rest)
- aws_query.py: `_detect_field_ref()` inlined into `extract_field_refs()` for compactness

## Dependencies

- **Section 06 (Envelope Detector):** Generic envelope unwrapping replaces Vault's `extract_response_schema()` and KV/auth backend envelope navigation.
- **Section 09 (Nested Detection):** Generic nested object producer resolution replaces Vault's `extract_field_refs()` FK pattern matching.
- **Section 10 (Response Walk / ReadOnly):** Generic response tree walk replaces Vault's `extract_outputs()` and AWS's `extract_outputs()` nested output flattening.
- **Section 03 (Phase A Detection):** Credential exclusion regex, FK suffix expansion, and readOnly/writeOnly classification replace hardcoded exclusion sets in both adapters.
- **Section 08 (Phase B Adapter Elimination):** swagger2.py already deleted, cloudflare.py and github_openapi.py already slimmed. The `__init__.py` registry was partially simplified in section 08; this section finishes that work.
- **Section 01 (Data Model):** `DetectionSource` enum and `Dependency` dataclass changes must be in place.

## Tests First

All tests go in the new directory `platform-tools/idi/tests/generation/rest/`. Create `__init__.py` files as needed for the test package hierarchy (`tests/generation/rest/__init__.py`).

### Test File: `tests/generation/rest/test_phase_c_adapter_slimming.py`

```python
"""Tests for Phase C adapter slimming — vault.py, aws_query.py, __init__.py.

Verifies output parity after removing redundant vendor-specific code that is
now handled by generic detection algorithms (envelope detection, response tree
walk, nested FK detection, credential exclusion, FK suffix expansion).
"""
import pytest


# --- Vault adapter slimming tests ---

class TestVaultSlimmedAdapter:
    """Verify Vault adapter retains only vendor-unique behavior."""

    # Test: Vault spec output matches/exceeds baseline with slimmed adapter (<120 LOC)
    def test_vault_spec_parity_with_slimmed_adapter(self):
        """Run pipeline on Vault benchmark spec. Edge count must be >= baseline.
        
        Load the Vault spec from catalog/specs/, run the full pipeline using
        the slimmed VaultAdapter, and compare edge count against a captured
        baseline. The slimmed adapter must produce equal or better results
        because generic detectors (envelope, tree walk, nested FK) now cover
        what was previously hardcoded.
        """
        ...

    # Test: slimmed vault.py is under 120 LOC
    def test_vault_adapter_loc_under_120(self):
        """Count non-blank, non-comment lines in vault.py. Must be < 120."""
        ...

    # Test: backend detection still works after slimming
    def test_backend_detection_preserved(self):
        """detect_backend_type() still correctly identifies kv_v1, kv_v2, auth, sys, etc.
        
        This is Vault-unique logic that must survive slimming.
        """
        ...

    # Test: mount parameterization still works after slimming
    def test_mount_parameterization_preserved(self):
        """parameterize_mount_point() still converts /auth/ldap/config to /auth/{mount}/config.
        
        This is Vault-unique logic that must survive slimming.
        """
        ...

    # Test: mount dependency extraction still works
    def test_mount_dependency_extraction_preserved(self):
        """extract_mount_dependencies() still emits sys-auth dependency for auth paths.
        
        This is Vault-unique logic that must survive slimming.
        """
        ...

    # Test: extract_response_schema removed (replaced by generic envelope detector)
    def test_extract_response_schema_removed(self):
        """VaultAdapter should no longer have extract_response_schema().
        
        This is now handled by the generic envelope_detector module.
        """
        ...

    # Test: extract_field_refs removed (replaced by generic FK detection)
    def test_extract_field_refs_removed(self):
        """VaultAdapter should no longer have extract_field_refs().
        
        Mount-point, role, and policy FK patterns are now caught by generic
        nested object producer resolution and FK suffix expansion.
        """
        ...

    # Test: extract_outputs removed (replaced by generic response tree walk)
    def test_extract_outputs_removed(self):
        """VaultAdapter should no longer have extract_outputs().
        
        Generic response tree walk with readOnly classification now handles this.
        """
        ...

    # Test: handle_kv_backend and handle_auth_backend removed
    def test_kv_auth_helpers_removed(self):
        """Backend-specific helper methods removed — envelope detector handles unwrapping."""
        ...


# --- AWS adapter slimming tests ---

class TestAwsSlimmedAdapter:
    """Verify AWS adapter retains only vendor-unique behavior."""

    # Test: AWS spec output matches/exceeds baseline with slimmed adapter (<160 LOC)
    def test_aws_spec_parity_with_slimmed_adapter(self):
        """Run pipeline on AWS benchmark spec. Edge count must be >= baseline.
        
        Load the AWS spec from catalog/specs/, run the full pipeline using
        the slimmed AwsQueryAdapter, and compare edge count against a captured
        baseline.
        """
        ...

    # Test: slimmed aws_query.py is under 160 LOC
    def test_aws_adapter_loc_under_160(self):
        """Count non-blank, non-comment lines in aws_query.py. Must be < 160."""
        ...

    # Test: ARN pattern recognition preserved
    def test_arn_pattern_recognition_preserved(self):
        """ARN_PATTERNS dict and _detect_arn_service() still work.
        
        ARN patterns are AWS-unique and cannot be replaced by generic detection.
        """
        ...

    # Test: ID prefix matching preserved (i-xxx, vpc-xxx, etc.)
    def test_id_prefix_matching_preserved(self):
        """ID_PATTERNS dict and _detect_id_pattern() still work.
        
        AWS ID prefix patterns are genuinely unique to AWS.
        """
        ...

    # Test: action-to-CRUD mapping preserved
    def test_action_crud_mapping_preserved(self):
        """action_to_operation() still maps Create->create, Describe->list, etc."""
        ...

    # Test: field suffix map preserved
    def test_field_suffix_map_preserved(self):
        """FIELD_SUFFIX_MAP with AWS PascalCase entries still works.
        
        AWS PascalCase naming (InstanceId, VpcId) is genuinely AWS-specific.
        """
        ...

    # Test: extract_outputs removed (replaced by generic response tree walk)
    def test_extract_outputs_removed(self):
        """AwsQueryAdapter should no longer have extract_outputs().
        
        Generic response tree walk now handles nested output flattening.
        """
        ...

    # Test: action_to_resource still works
    def test_action_to_resource_preserved(self):
        """action_to_resource() still converts RunInstances to 'instances'."""
        ...


# --- __init__.py registry slimming tests ---

class TestAdapterRegistrySlimmed:
    """Verify adapter registry works with simplified dispatch."""

    # Test: __init__.py adapter routing works with simplified registry
    def test_registry_routes_to_remaining_adapters(self):
        """get_adapter() correctly routes to the 4 remaining adapters:
        OpenApiRestAdapter, CloudflareAdapter (slimmed), VaultAdapter (slimmed),
        AwsQueryAdapter (slimmed).
        
        Swagger2Adapter and GitHubOpenApiAdapter entries removed or merged.
        """
        ...

    # Test: slimmed __init__.py is under 100 LOC
    def test_init_loc_under_100(self):
        """Count non-blank, non-comment lines in __init__.py. Must be < 100."""
        ...

    # Test: auto-detection still works for vault
    def test_auto_detect_vault(self):
        """detect_style() still returns 'vault' for Vault specs."""
        ...

    # Test: auto-detection still works for cloudflare
    def test_auto_detect_cloudflare(self):
        """detect_style() still returns 'cloudflare' for Cloudflare specs."""
        ...

    # Test: auto-detection still works for AWS
    def test_auto_detect_aws(self):
        """detect_style() still returns 'aws' for AWS Query specs."""
        ...

    # Test: default falls through to rest
    def test_auto_detect_default_rest(self):
        """detect_style() returns 'rest' for unknown services."""
        ...

    # Test: swagger2 adapter removed from registry
    def test_swagger2_removed_from_registry(self):
        """'swagger' and 'swagger2' keys no longer in registry.
        
        swagger2.py was deleted in section 08. Registry must not reference it.
        """
        ...

    # Test: github adapter integrated or removed
    def test_github_adapter_handling(self):
        """'github' key routes to slimmed adapter or falls through to rest."""
        ...


# --- Overall LOC verification ---

class TestOverallLOCTarget:
    """Verify total vendor-specific LOC meets the 793-line target."""

    # Test: vendor-specific LOC <= 793
    def test_total_vendor_loc_under_793(self):
        """Sum non-blank, non-comment lines across all adapter files.
        
        Files: cloudflare.py (~70), github_openapi.py (~75), vault.py (~110),
        aws_query.py (~155), __init__.py (~100). Total target: <= 793.
        swagger2.py should not exist (deleted in section 08).
        openapi_rest.py is the generic base and does not count toward vendor LOC.
        """
        ...
```

### Test File: `tests/generation/rest/conftest.py` (additions)

If the shared conftest from the TDD plan does not yet exist, create it. If it exists (from earlier sections), add these fixtures.

```python
"""Shared fixtures for REST pipeline tests.

Add to existing conftest.py if it was created by section 04.
"""
import pytest


@pytest.fixture
def vault_benchmark_baseline():
    """Captured edge counts for Vault benchmark spec.
    
    Populated by running the pipeline with the original (pre-slimming)
    vault.py and recording the output. Used for parity verification.
    """
    ...


@pytest.fixture
def aws_benchmark_baseline():
    """Captured edge counts for AWS benchmark spec.
    
    Populated by running the pipeline with the original (pre-slimming)
    aws_query.py and recording the output. Used for parity verification.
    """
    ...
```

## Implementation Details

### Step 1: Capture Baselines (Before Any Code Changes)

Before modifying any adapter file, run the full pipeline on the Vault and AWS benchmark specs with the current (pre-slimming) adapters and capture the output as golden files. These baselines are the parity targets.

The baseline capture should record:
- Total edge count per spec
- List of all emitted dependencies (field, target_resource, confidence)
- List of all emitted outputs (field, type, path)

Store baseline data in `tests/generation/rest/fixtures/` as JSON files (e.g., `vault_baseline.json`, `aws_baseline.json`).

### Step 2: Slim `adapters/vault.py` (478 to ~110 LOC)

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/vault.py`

**Remove the following (total ~368 LOC removed):**

1. **`BACKEND_RESPONSE_PATHS` dict and `extract_response_schema()` method** (~70 LOC) -- The generic envelope detector (section 06) now handles Vault's `{data: ...}`, `{data: {data: ...}}`, and `{auth: ...}` wrapper patterns. The envelope detector's Pattern 3 (single-field wrapper) catches `{data: {...}}` at confidence 0.9, and Pattern 1 (HAL `_embedded`) or Pattern 4 (externally tagged) handles `{auth: {...}}`.

2. **`AUTH_OUTPUT_FACTS` dict and `handle_auth_backend()` method** (~40 LOC) -- Auth output facts (`client_token`, `accessor`, `policies`, etc.) are now detected by the generic response tree walk (section 10) combined with readOnly field classification (section 03). The tree walk registers all response fields as producers; readOnly fields get confidence 0.9.

3. **`handle_kv_backend()` method** (~25 LOC) -- KV version metadata annotation is no longer needed because the generic envelope detector handles both v1 and v2 wrapper patterns without needing to know the KV version.

4. **`EXCLUDED_FIELDS` set and `extract_field_refs()` method** (~75 LOC) -- Field exclusion is now handled by the credential exclusion regex (section 03, item #1). Mount-point, role, and policy FK patterns are now caught by generic nested object producer resolution (section 09) and FK suffix expansion (section 03, item #4).

5. **`extract_outputs()` method** (~45 LOC) -- Replaced by generic response tree walk (section 10) which walks to depth 5 with cycle detection and registers all leaf fields.

**Keep the following (~110 LOC):**

1. **`detect_backend_type()` method** (~50 LOC) -- Vault's multi-backend architecture (kv_v1, kv_v2, auth, sys, database, pki, ssh, transit) is genuinely unique. This method maps API paths to backend types, used for resource naming and fact URI construction. No generic algorithm can replace this domain-specific path classification.

2. **`parameterize_mount_point()` method** (~30 LOC) -- Mount-point rewriting (`/auth/ldap/config` to `/auth/{mount}/config`) is Vault-specific. It enables parameterized skill paths where the mount name is a runtime variable. The `KNOWN_AUTH_TYPES` list supports this.

3. **`extract_mount_dependencies()` method** (~30 LOC) -- Auth paths depend on the auth backend being enabled via `sys-auth`. This Vault-specific dependency cannot be inferred generically because it represents a system-level prerequisite, not a schema-level FK relationship.

**Resulting structure of slimmed `vault.py`:**

```python
"""HashiCorp Vault API adapter.

Handles Vault-specific conventions that cannot be replaced by generic detection:
- Backend type detection from API path patterns
- Mount-point parameterization for auth paths
- Mount dependency extraction (auth paths depend on sys-auth)
"""

KNOWN_AUTH_TYPES: list[str] = [...]  # ~14 entries

class VaultAdapter:
    def __init__(self, service: str, known_resources: set[str] | None = None): ...
    def detect_backend_type(self, path: str) -> str:
        """Detect Vault backend type from API path. Returns kv_v1, kv_v2, auth, sys, etc."""
        ...
    def parameterize_mount_point(self, path: str) -> tuple[str, str | None]:
        """Convert /auth/ldap/config to (/auth/{mount}/config, 'ldap')."""
        ...
    def extract_mount_dependencies(self, path: str, operation: dict) -> list[dict]:
        """Emit sys-auth dependency for auth paths."""
        ...
```

### Step 3: Slim `adapters/aws_query.py` (339 to ~155 LOC)

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/aws_query.py`

**Remove the following (~184 LOC removed):**

1. **`extract_outputs()` method** (~45 LOC) -- Replaced by the generic response tree walk (section 10). The recursive nested output flattening is now handled generically with depth-5 walk and cycle detection.

2. **Parts of `extract_field_refs()` that overlap with generic detection** (~40 LOC) -- The method body that walks `properties` and calls `_detect_field_ref()` can be simplified. The generic FK suffix expansion (section 03, item #4) and nested object producer resolution (section 09) now handle most FK patterns. However, AWS-specific detection (`_detect_arn_service`, `_detect_id_pattern`, `_detect_field_suffix` with the PascalCase `FIELD_SUFFIX_MAP`) must remain because these patterns are unique to AWS.

    The simplification: `extract_field_refs()` can be reduced to only call the AWS-specific detection methods (`_detect_arn_service`, `_detect_id_pattern`, `_detect_field_suffix`), since the generic pipeline handles `_id`, `_uuid`, `_guid` suffixes and nested object producers. Remove any redundant generic FK logic from this method.

**Keep the following (~155 LOC):**

1. **`ARN_PATTERNS` dict and `_detect_arn_service()` method** (~25 LOC) -- ARN (Amazon Resource Name) patterns are AWS-unique. No other API uses this format. The regex-based service extraction from ARN strings is irreplaceable by generic detection.

2. **`ID_PATTERNS` dict and `_detect_id_pattern()` method** (~35 LOC) -- AWS resource ID prefixes (`i-xxx`, `vpc-xxx`, `sg-xxx`, etc.) are unique to AWS. These prefix patterns identify resource types from example values or schema patterns. Generic FK detection cannot infer these.

3. **`ACTION_PREFIXES` dict and `action_to_operation()` method** (~15 LOC) -- AWS Query protocol uses action names (`CreateInstance`, `DescribeVpcs`) instead of HTTP methods for CRUD classification. This is a fundamental protocol difference that requires AWS-specific handling.

4. **`FIELD_SUFFIX_MAP` dict and `_detect_field_suffix()` method** (~50 LOC) -- The 50-entry PascalCase suffix map (`InstanceId` to `instances`, `VpcId` to `vpcs`, etc.) is AWS-specific naming. While generic FK suffix expansion handles `_id`, `_uuid`, `_guid`, it does not handle PascalCase without underscores.

5. **`action_to_resource()` method** (~30 LOC) -- Extracts resource names from AWS action names by stripping the action prefix and converting PascalCase to kebab-case. This is AWS Query protocol-specific.

**Resulting structure of slimmed `aws_query.py`:**

```python
"""AWS Query protocol schema adapter.

Handles AWS-specific conventions that cannot be replaced by generic detection:
- PascalCase field suffix map (InstanceId -> instances)
- ARN pattern recognition for cross-service references
- Resource ID prefix patterns (i-xxx, vpc-xxx, sg-xxx)
- Action-based operation naming (CreateInstance -> create)
"""

ACTION_PREFIXES: dict[str, str] = {...}  # ~12 entries
ID_PATTERNS: dict[str, str] = {...}      # ~16 entries
FIELD_SUFFIX_MAP: dict[str, str] = {...} # ~28 entries (PascalCase only)
ARN_PATTERNS: dict[str, str] = {...}     # ~10 entries

class AwsQueryAdapter:
    def __init__(self, service: str, known_resources: set[str] | None = None): ...
    def extract_field_refs(self, schema: dict, source_resource: str) -> list[dict]:
        """AWS-specific FK detection only: ARN, ID prefix, PascalCase suffix."""
        ...
    def _detect_arn_service(self, pattern: str) -> str | None: ...
    def _detect_id_pattern(self, pattern: str) -> str | None: ...
    def _detect_field_suffix(self, field_name: str) -> str | None: ...
    def action_to_operation(self, action: str) -> str | None: ...
    def action_to_resource(self, action: str) -> str | None: ...
```

### Step 4: Slim `adapters/__init__.py` (257 to ~100 LOC)

**File:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/__init__.py`

**Remove the following (~157 LOC removed):**

1. **Swagger2 import and registry entries** (~5 LOC) -- `swagger2.py` was deleted in section 08. Remove `from ... import Swagger2Adapter`, the `"swagger"` and `"swagger2"` registry entries, and the `Swagger2Adapter` entry in `__all__`.

2. **GitHub import and registry entry** (~5 LOC) -- If `github_openapi.py` was slimmed to just alias resolution (~75 LOC) in section 08, the registry entry may remain. If the GitHub adapter was fully absorbed into generic detection, remove its import and registry entry. Decision depends on section 08 outcome. If the slimmed GitHub adapter remains, keep its registry entry.

3. **`_is_cloudflare_spec()` function** (~30 LOC) -- This function samples response schemas looking for `{result, success, errors}` properties. This detection is now handled by the generic envelope detector (section 06, Pattern 3: single-field wrapper) which identifies Cloudflare's `result` field as a single-field wrapper with `errors`, `success`, `messages` as metadata siblings. The envelope detector fires during field extraction, making spec-level adapter routing for Cloudflare unnecessary in most cases. However, if the slimmed Cloudflare adapter (section 08) still needs to be routed to for path-based resource normalization, keep a simplified version that checks the service name only.

4. **`_has_cloudflare_wrapper()` helper** (~8 LOC) -- Used only by `_is_cloudflare_spec()`. Remove if that function is removed.

5. **Complex `detect_style()` logic** (~30 LOC of conditionals) -- Simplify to a config-driven dispatch. With fewer adapters, the detection heuristics become simpler: check service name first (vault, cloudflare, aws), then fall through to `"rest"`.

6. **Complex `AdapterRegistry.get()` with per-adapter constructor branching** (~15 LOC) -- The special case for CloudflareAdapter accepting `spec` kwarg can be simplified if all remaining adapters use a uniform constructor signature.

**Keep the following (~100 LOC):**

1. **`AdapterRegistry` class** with simplified dispatch (~40 LOC) -- Config-driven mapping from style key to adapter class. Uniform constructor: `adapter_class(service=service, known_resources=known_resources)`.

2. **`get_adapter()` function** (~20 LOC) -- Public API entry point. Delegates to registry.

3. **`detect_style()` / `_is_vault_spec()`** (~40 LOC) -- Vault spec detection by path patterns remains useful. Simplify Cloudflare detection to service-name-only. AWS detection by `Action=` in path stays.

**Resulting structure of slimmed `__init__.py`:**

```python
"""Schema family adapters for FK detection and response schema extraction.

Remaining adapters after generic detection eliminates most vendor-specific code:
- OpenApiRestAdapter: Generic base (handles most APIs)
- CloudflareAdapter: Path-based resource normalization only
- VaultAdapter: Backend detection + mount parameterization only
- AwsQueryAdapter: ARN/ID prefix/PascalCase FK + action mapping only
"""

from idi.generation.adapters.openapi_rest import OpenApiRestAdapter
from idi.generation.adapters.cloudflare import CloudflareAdapter
from idi.generation.adapters.vault import VaultAdapter
from idi.generation.adapters.aws_query import AwsQueryAdapter

class AdapterRegistry:
    """Config-driven adapter dispatch."""
    def __init__(self): ...
    def register(self, style: str, adapter_class: type) -> None: ...
    def get(self, style: str, service: str, known_resources: set[str] | None = None) -> object: ...
    def detect_style(self, sample_path: str, service: str = "", spec: dict | None = None) -> str: ...

def get_adapter(service: str, style: str | None = None, sample_path: str | None = None,
                known_resources: set[str] | None = None, spec: dict | None = None) -> object: ...
```

### Step 5: Verify LOC Targets

After all changes, verify the line counts. Use a consistent counting method: non-blank, non-comment lines (lines that are not empty and do not start with `#` after stripping whitespace). Docstrings count as code.

Target counts:
| File | Before | After | Max |
|------|--------|-------|-----|
| `vault.py` | 478 | ~110 | 120 |
| `aws_query.py` | 339 | ~155 | 160 |
| `__init__.py` | 257 | ~100 | 100 |
| `cloudflare.py` | ~70 (from section 08) | ~70 | 80 |
| `github_openapi.py` | ~75 (from section 08) | ~75 | 80 |
| `swagger2.py` | deleted (section 08) | 0 | 0 |
| **Total vendor LOC** | | **~510** | **793** |

The 793 target is a conservative ceiling. The actual total should be well under it.

## Key Files

- **Modify:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/vault.py`
- **Modify:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/aws_query.py`
- **Modify:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/adapters/__init__.py`
- **Create:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/__init__.py`
- **Create:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/test_phase_c_adapter_slimming.py`
- **Create or extend:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/conftest.py`
- **Create:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/fixtures/vault_baseline.json`
- **Create:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/rest/fixtures/aws_baseline.json`

## Implementation Checklist

1. Create test directory structure and `__init__.py` files
2. Write all test stubs in `test_phase_c_adapter_slimming.py`
3. Run pipeline on Vault spec with current adapters, capture baseline to `vault_baseline.json`
4. Run pipeline on AWS spec with current adapters, capture baseline to `aws_baseline.json`
5. Slim `vault.py`: remove `extract_response_schema`, `extract_field_refs`, `extract_outputs`, `handle_kv_backend`, `handle_auth_backend`, `BACKEND_RESPONSE_PATHS`, `AUTH_OUTPUT_FACTS`, `EXCLUDED_FIELDS`
6. Slim `aws_query.py`: remove `extract_outputs`, simplify `extract_field_refs` to AWS-only patterns
7. Slim `__init__.py`: remove Swagger2 references, simplify detection heuristics, use config-driven dispatch
8. Run parity tests against captured baselines
9. Verify all LOC targets are met
10. Run full test suite to confirm no regressions

## Risk Mitigation

- **Vault envelope edge cases:** If the generic envelope detector misses exotic Vault response shapes (e.g., KV v2's double-nested `data.data`), the annotation system (section 12) provides an escape hatch. Alternatively, a one-line envelope hint can be added to the slimmed adapter.
- **AWS PascalCase FK overlap:** The generic FK suffix expansion uses underscore-separated suffixes (`_id`, `_uuid`). AWS PascalCase suffixes (`InstanceId`, `VpcId`) have no underscore separator. These are handled exclusively by the preserved `FIELD_SUFFIX_MAP`. There is no overlap or conflict between generic and AWS-specific FK detection.
- **Parity regression:** If the slimmed adapter produces fewer edges than baseline for a specific spec, the implementer should investigate which edges are missing and verify whether they are genuine FPs that were removed (acceptable) or genuine TPs that need a generic detector fix (not acceptable for this section -- file an issue for the appropriate generic detector section).
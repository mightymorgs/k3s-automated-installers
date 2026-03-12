I now have everything I need. Let me generate the section content.

# Section 5: OpenAPI Links Parser

## Overview

This section implements a new dependency adapter `dep_adapters/link_deps.py` that parses OpenAPI 3.0+ `links` objects from response definitions. Links are explicit, author-declared runtime relationships between API operations -- they are ground-truth dependencies at confidence 1.0. This is the highest-fidelity signal available in an OpenAPI spec.

**Depends on:** Section 04 (Phase A integration must be complete; data model changes from Section 01 must be in place)
**Blocks:** Section 08 (Phase B adapter elimination)

### Key files

| File | Action |
|------|--------|
| `platform-tools/idi/tests/generation/rest/test_link_deps.py` | **Create** -- unit tests |
| `platform-tools/idi/tests/generation/rest/__init__.py` | **Create** -- package init |
| `platform-tools/idi/tests/generation/rest/conftest.py` | **Create** -- shared fixtures |
| `platform-tools/idi/idi/generation/dep_adapters/link_deps.py` | **Create** -- links parser adapter |

---

## Background

### What OpenAPI Links Are

OpenAPI 3.0+ defines a `links` object on responses that explicitly declares how the output of one operation feeds into the input of another. For example:

```yaml
paths:
  /users:
    post:
      operationId: createUser
      responses:
        '201':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/User'
          links:
            GetUser:
              operationId: getUser
              parameters:
                userId: '$response.body#/id'
```

This declares: "After calling `createUser`, you can call `getUser` by passing the `id` field from the response body as the `userId` parameter." This is an explicit dependency edge at confidence 1.0.

### Runtime Expressions (OpenAPI 3.0 Spec)

Links use runtime expressions to reference values from the source operation:

- `$response.body#/path/to/field` -- a field in the response body, located via JSON Pointer
- `$request.path.paramName` -- a path parameter from the request
- `$request.query.paramName` -- a query parameter from the request
- `$response.header.Header-Name` -- a response header value

### JSON Pointer (RFC 6901)

The `#/path/to/field` portion after `body` uses RFC 6901 JSON Pointer syntax:

- `/` separates path segments
- `~0` escapes the `~` character (literal tilde)
- `~1` escapes the `/` character (literal slash)

Example: `$response.body#/a~1b` resolves to the field named `a/b`.

### Target Resolution

Links specify their target operation via one of two mechanisms:

- `operationId` -- a string matching an operation's `operationId` field (preferred)
- `operationRef` -- a JSON Pointer or URI reference to the target operation

For `operationRef`, only same-document references (`#/paths/...`) are supported. External URLs (e.g., `https://example.com/spec.json#/paths/...`) must be skipped with a warning -- fetching external URLs opens SSRF and local file read risks.

### Adapter Architecture

The adapter follows the `DepAdapter` protocol defined in `dep_adapters/base.py`:

```python
class DepAdapter(Protocol):
    name: str
    priority: int

    def matches(self, spec: dict, service_name: str) -> bool: ...
    def detect_dependencies(self, operation: OperationInfo, spec: dict, known_resources: set[str]) -> list[Dependency]: ...
    def detect_outputs(self, operation: OperationInfo, spec: dict) -> list[Output]: ...
```

The `DepAdapterRegistry` in `registry.py` auto-discovers adapters from Python files in the `dep_adapters/` directory, instantiates them, and sorts by priority (highest first). The registry skip list in `_discover_python()` excludes helper modules like `base`, `registry`, `merge`, etc. -- the new `link_deps.py` will be auto-discovered without any registry changes.

The `Dependency` dataclass (from `base.py`) currently has these fields:

```python
@dataclass
class Dependency:
    field: str
    target_resource: str
    target_operation: str = "create"
    fact_ref: str | None = None
    confidence: float = 0.5
    source: str = "unknown"
    lineage_type: str = "copy"
    discriminator_value: str | None = None
    target_service: str | None = None
    satisfaction: str = ""
```

Note: The plan calls for adding `detection_source: DetectionSource` in Section 01 (data model). If Section 01 is already implemented when this section executes, use `DetectionSource.OPENAPI_LINK`. If not yet available, use a string `"rest:openapi_link"` as the `source` field value and add a TODO to update when the enum lands.

---

## Tests First

Create the test directory and files. All tests go in `platform-tools/idi/tests/generation/rest/test_link_deps.py`.

### Test directory setup

Create `platform-tools/idi/tests/generation/rest/__init__.py` as an empty file.

### Shared fixtures

Create `platform-tools/idi/tests/generation/rest/conftest.py` with these fixtures:

```python
"""Shared fixtures for REST pipeline tests."""
import pytest
from idi.generation.dep_adapters.base import OperationInfo


@pytest.fixture
def minimal_openapi_spec():
    """Valid OAS 3.0 spec with 2 operations, no links."""
    # Return a dict with openapi: "3.0.0", info, paths with /users POST and /users/{userId} GET
    ...


@pytest.fixture
def spec_with_links():
    """OAS 3.0 spec with links objects on createUser response pointing to getUser."""
    # Return a spec where POST /users 201 response has a link with operationId: getUser
    # and parameters: {userId: "$response.body#/id"}
    ...
```

### Test stubs for `test_link_deps.py`

The following tests must be implemented. Each test description specifies the exact behavior to verify.

```python
"""Tests for OpenAPI Links Parser — dep_adapters/link_deps.py."""
import pytest
from idi.generation.dep_adapters.base import OperationInfo


class TestLinksAdapterMatching:
    """Tests for the matches() method."""

    def test_matches_openapi_30_spec(self):
        """Spec with openapi: '3.0.0' -> matches() returns True."""

    def test_matches_openapi_31_spec(self):
        """Spec with openapi: '3.1.0' -> matches() returns True."""

    def test_no_match_swagger_20(self):
        """Spec with swagger: '2.0' (no 'openapi' key) -> matches() returns False."""

    def test_no_match_no_version(self):
        """Spec with neither 'openapi' nor 'swagger' key -> matches() returns False."""

    def test_spec_without_links(self):
        """OAS 3.0 spec with no links objects -> detect_dependencies returns empty list."""


class TestLinkResolution:
    """Tests for resolving link targets."""

    def test_link_with_operation_id(self):
        """Link with operationId -> resolves to correct target operation.

        Given a link with operationId: 'getUser', the adapter must find the
        path/method combination that declares operationId: 'getUser' and emit
        a Dependency with the correct target_resource and target_operation.
        """

    def test_link_with_relative_operation_ref(self):
        """Link with operationRef '#/paths/~1users~1{userId}/get' -> resolves correctly.

        The operationRef is a JSON Pointer into the same document. The ~1 escapes
        represent '/' characters in the path '/users/{userId}'.
        """

    def test_link_with_external_url_operation_ref(self):
        """Link with operationRef 'https://example.com/spec#/paths/...' -> skipped with warning.

        SSRF protection: external URLs must never be fetched. The adapter must
        log a warning and skip the link without emitting a dependency.
        """

    def test_link_referencing_nonexistent_operation_id(self):
        """Link with operationId 'doesNotExist' -> skipped with warning.

        Broken links must be detected and logged, not emitted as dependencies.
        """

    def test_multiple_links_from_same_response(self):
        """Response with 2 links -> each emits a separate Dependency.

        Given links {GetUser: {...}, DeleteUser: {...}}, two dependencies
        must be emitted, one for each target operation.
        """


class TestRuntimeExpressionParsing:
    """Tests for the two-stage runtime expression parser."""

    def test_response_body_json_pointer(self):
        """'$response.body#/id' -> parsed as response body field 'id'."""

    def test_response_body_nested_pointer(self):
        """'$response.body#/data/user/id' -> parsed as 'data.user.id'."""

    def test_request_path_param(self):
        """'$request.path.userId' -> parsed as request path parameter 'userId'."""

    def test_request_query_param(self):
        """'$request.query.filter' -> parsed as request query parameter 'filter'."""

    def test_response_header(self):
        """'$response.header.Location' -> parsed as response header 'Location'."""

    def test_json_pointer_tilde1_escape(self):
        """'$response.body#/a~1b' -> resolves to field 'a/b'.

        RFC 6901: ~1 represents a literal '/' character.
        """

    def test_json_pointer_tilde0_escape(self):
        """'$response.body#/a~0b' -> resolves to field 'a~b'.

        RFC 6901: ~0 represents a literal '~' character.
        """

    def test_unparseable_expression(self):
        """'$$invalid.expression' -> skipped with warning, no Dependency emitted.

        Critical: unparseable expressions must NEVER emit at confidence 1.0.
        The adapter must log a warning and skip the expression entirely.
        """


class TestDependencyEmission:
    """Tests for the emitted Dependency objects."""

    def test_confidence_is_1_0(self):
        """Links emit dependencies at confidence 1.0 (ground-truth)."""

    def test_lineage_type_is_explicit(self):
        """Links emit dependencies with lineage_type='explicit'."""

    def test_source_identifies_adapter(self):
        """Dependencies have source identifying the links adapter.

        Should be 'link_deps' or contain 'openapi_link' depending on
        whether DetectionSource enum (Section 01) is available.
        """

    def test_detect_outputs_returns_empty(self):
        """detect_outputs() returns empty list -- links declare consumption, not production."""


class TestAdapterRegistration:
    """Tests for priority and registry integration."""

    def test_priority_above_generic_odg(self):
        """LinkDepsAdapter.priority > GenericODGAdapter.priority (50).

        Links are ground-truth and must take precedence over heuristic detection.
        """

    def test_auto_discovered_by_registry(self):
        """DepAdapterRegistry discovers and instantiates LinkDepsAdapter.

        The file link_deps.py must not be in the registry's skip list,
        and the class must satisfy the DepAdapter protocol duck-typing check.
        """
```

---

## Implementation Details

### File: `platform-tools/idi/idi/generation/dep_adapters/link_deps.py`

Create a new file implementing the `LinkDepsAdapter` class. The implementation has four main components.

#### 1. Class structure

```python
"""OpenAPI 3.0+ Links parser — ground-truth dependency detection.

Parses links objects from response definitions to extract explicit
runtime relationships between operations. Confidence 1.0, lineage 'explicit'.

Priority: 100 (highest — ground-truth from spec author).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from idi.generation.dep_adapters.base import Dependency, OperationInfo, Output

logger = logging.getLogger(__name__)


class LinkDepsAdapter:
    """Extracts dependencies from OpenAPI 3.0+ links objects."""

    name = "link_deps"
    priority = 100  # Highest — ground-truth from spec author

    def matches(self, spec: dict[str, Any], service_name: str) -> bool:
        """Return True for OpenAPI 3.0+ specs (have 'openapi' key with version >= 3.0)."""
        ...

    def detect_dependencies(
        self, operation: OperationInfo, spec: dict, known_resources: set[str],
    ) -> list[Dependency]:
        """Walk links in the current operation's responses and emit dependencies."""
        ...

    def detect_outputs(self, operation: OperationInfo, spec: dict) -> list[Output]:
        """Links declare consumption, not production. Always returns empty."""
        return []
```

#### 2. `matches()` logic

Check for the presence of `spec.get("openapi")` and verify the version string starts with `"3."`. Swagger 2.0 specs use a `"swagger"` key instead and do not support links. Return `False` for any non-3.x spec.

#### 3. `detect_dependencies()` algorithm

Walk the spec structure to find links for the current operation:

1. Look up the current operation in `spec["paths"]` using `operation.path` and `operation.method`
2. For each response code in the operation's `responses`, check for a `links` object
3. For each named link in `links`:
   a. Resolve the target operation via `operationId` or `operationRef`
   b. Parse runtime expressions from the link's `parameters` map
   c. Emit a `Dependency` for each successfully parsed parameter mapping

**Target resolution details:**

- For `operationId`: scan all paths/methods in the spec to find the operation with matching `operationId`. Extract the target resource from the path (e.g., `/users/{userId}` yields resource `users`). If no match found, log warning and skip.
- For `operationRef` starting with `#`: parse as a JSON Pointer into the spec document. Use RFC 6901 unescaping (`~1` to `/`, `~0` to `~`). Resolve to the target path/method. If resolution fails, log warning and skip.
- For `operationRef` starting with `http://` or `https://` (or any scheme): log a warning about SSRF protection and skip entirely. Do not attempt to fetch.

**Dependency construction:**

For each successfully parsed link parameter, emit:

```python
Dependency(
    field=parameter_name,       # The target operation's parameter name
    target_resource=resource,   # Extracted from target operation's path
    target_operation=method,    # HTTP method of target operation
    fact_ref=f"facts://{service}/{resource}#{source_field}",
    confidence=1.0,
    source="link_deps",
    lineage_type="explicit",
)
```

#### 4. Runtime expression parser

Implement a two-stage parser as a module-level function or static method:

**Stage 1 -- Outer structure (regex):** Match the expression against patterns:

- `$response.body#/<json_pointer>` -- body field reference
- `$request.path.<param_name>` -- path parameter
- `$request.query.<param_name>` -- query parameter
- `$response.header.<header_name>` -- response header
- `$request.body#/<json_pointer>` -- request body field (less common but valid)

Use a single regex with named groups to classify the expression type and extract the relevant portion.

**Stage 2 -- JSON Pointer (RFC 6901):** For `body#/...` expressions:

1. Split the pointer at `/` to get path segments
2. Unescape each segment: replace `~1` with `/`, then `~0` with `~` (order matters)
3. Return the dot-joined field path (e.g., `/data/user/id` becomes `data.user.id`)

If the expression cannot be parsed by either stage, log a warning with the raw expression text and return `None`. The caller must check for `None` and skip emitting a dependency for that parameter.

#### 5. Priority and registry integration

Set `priority = 100` -- higher than all existing adapters:

- `olm_deps`: priority 95
- `rbac_deps`: priority 70
- `generic_odg`: priority 50

The registry's `_discover_python()` method skips files listed in its `skip` set. The current skip list is: `{"__init__", "base", "registry", "merge", "yaml_adapter", "body_fk", "path_deps", "target_inference", "output_detection"}`. The file `link_deps.py` is not in this list, so it will be auto-discovered. No changes to `registry.py` are needed.

However, note that auto-discovery uses duck-typing: it checks for `name`, `priority`, `matches`, `detect_dependencies`, and `detect_outputs` attributes. The `LinkDepsAdapter` class must have all five.

### Edge cases to handle

1. **Empty links object:** `links: {}` -- iterate produces nothing, return empty list
2. **Link with no parameters:** A link can have a `requestBody` expression instead of `parameters`. For this implementation, only `parameters` are parsed. `requestBody` links are logged and skipped.
3. **Response codes:** Links can appear under any response code (200, 201, 301, etc.). Walk all response codes, not just 2xx.
4. **Operation paths with special characters:** When building `operationRef` JSON Pointers, path segments containing `/` are escaped as `~1`. The parser must handle this correctly in both directions.

### What this section does NOT cover

- Adding `DetectionSource` enum to `base.py` -- that is Section 01 (data model)
- Modifying existing adapter priorities -- this adapter slots in above existing ones
- Envelope detection -- that is Section 06
- Registry changes -- auto-discovery handles everything

---

## Implementation Notes (actual)

### Files created
- `platform-tools/idi/idi/generation/dep_adapters/link_deps.py` (~230 LOC)
- `platform-tools/idi/tests/generation/rest/test_link_deps.py` (~310 LOC)

### Test results
- **24 tests pass** (5 matching, 5 resolution, 8 expression parsing, 4 emission, 2 registration)
- **948 total tests pass** (full suite, 0 regressions)

### Deviations from plan
- Plan called for 15 tests; implementation has 24 for more thorough coverage of edge cases
- `conftest.py` and `__init__.py` were pre-existing from sections 01-04
- `DetectionSource.OPENAPI_LINK` was available from Section 01 (no fallback string needed)
- `ParsedExpression` dataclass added as structured return type for the runtime expression parser (plan left return type open)

### Known limitations (deferred)
- Link-level `$ref` (e.g., `$ref: '#/components/links/GetUser'`) not dereferenced — requires spec pre-processing
- Root body pointer `$response.body#/` not matched — safe skip with warning
- Hint links (operationId with no parameters) emit zero dependencies — per plan scope

---

## Verification checklist

After implementation, verify:

1. All 24 tests in `test_link_deps.py` pass
2. `LinkDepsAdapter` is auto-discovered by `DepAdapterRegistry` (instantiate a registry and check adapter list)
3. Running `cd /Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi && uv run pytest tests/generation/rest/test_link_deps.py` succeeds
4. Running the full test suite (`uv run pytest`) shows no regressions in existing CRD tests
5. A spec without links produces zero dependencies from this adapter
6. A spec with an external `operationRef` URL produces a warning log and zero dependencies for that link
7. An unparseable runtime expression never emits at confidence 1.0
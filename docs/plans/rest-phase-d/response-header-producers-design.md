# Response Header Producers Design (#21)

## Problem Statement

The current pipeline (after Phase C) detects producers only from response body fields. Several important dependency patterns exist exclusively in response headers:

| Header | Pattern | Dependency Type |
|--------|---------|-----------------|
| `Location` (201) | POST creates resource, returns URI | POST → GET |
| `ETag` (200) | GET returns version, PUT requires `If-Match` | GET → PUT |
| `X-Request-Id` | Correlation across operations | Request tracing |
| Custom headers | Declared in `responses.headers` | Spec-specific |

### Missed Dependencies in Benchmark Specs

**Vault:** POST `/auth/{mount}/login` returns auth tokens in response body (already detected). No header-based dependencies missed because Vault uses body-only responses.

**Authentik:** POST `/api/v3/flows/executor/` returns `Location` header for redirect flows. This POST→GET dependency is currently missed. Authentik also returns `X-Request-Id` on all responses.

## Proposed Approach

### Header Detection Algorithm

Two sources of header information:

**1. Spec-declared headers** (high confidence):
```yaml
responses:
  '201':
    headers:
      Location:
        schema:
          type: string
```
Parse `responses.{code}.headers.{name}` from the OpenAPI operation. These are explicit and reliable.

**2. Well-known headers** (medium confidence):
- `Location` on 201 responses: semantically defined by HTTP/1.1 RFC 7231
- `ETag` on 200 responses: defined by RFC 7232
- Inferred even when not declared in the spec

### Location Header Parsing

1. Extract `Location` header schema from 201 response (or assume string for well-known)
2. Match Location URI pattern against spec's path templates using RFC 6570 parser (Section 02, #9)
3. If match found: emit dependency from POST operation to matched GET operation
4. The path parameter extracted from the URI match becomes the consumed field

Example:
```
POST /users → 201 Location: /users/{id}
  → Dependency: POST /users → GET /users/{id}
  → Consumed field: id
  → Confidence: 0.95 (spec-declared) or 0.85 (inferred)
```

### ETag/If-Match Dependency

When GET response declares `ETag` header AND PUT/PATCH on same path accepts `If-Match` parameter:

```
GET /users/{id} → 200 ETag: "abc123"
PUT /users/{id} requires If-Match header
  → Dependency: GET /users/{id} → PUT /users/{id}
  → Consumed field: ETag → If-Match
  → Confidence: 0.90 (spec-declared) or 0.80 (inferred)
```

### X- Custom Headers

Custom headers have non-standardized semantics:
- Spec-declared: confidence 0.70 (the spec author intentionally declared the header)
- Inferred: **skip entirely** (too speculative without semantic understanding)

## Confidence Model

| Header | Declared in spec | Inferred |
|--------|:---:|:---:|
| Location (201) | 0.95 | 0.85 |
| ETag | 0.90 | 0.80 |
| X-Request-Id | 0.70 | skip |
| Other X- | 0.70 | skip |

All confidence values meet the project-wide 0.70 minimum threshold.

## Integration Point

Extends `dep_adapters/output_detection.py` with a new function:

```python
def detect_header_outputs(op_info: OperationInfo) -> list[Output]:
    """Detect dependency-producing response headers."""
    ...
```

Results merge into the same `Output` list as body-derived producers. The `Output` dataclass gains an optional `source_location` field:

```python
@dataclass
class Output:
    field: str
    fact_ref: str
    source: str
    priority: int
    source_location: str = "body"  # "body" or "header"
```

## Dependencies

- **Section 10 (Response Tree Walk):** Integration into `output_detection.py`
- **Section 02 (RFC 6570 Parser):** Location URI matching against path templates

## Risk Analysis

- **False positives on 201 without Location:** Some APIs return 201 for creation but don't use Location headers. Mitigation: only infer Location on 201 responses, not 200/204.
- **ETag false positives:** Some APIs use ETag for caching only, not optimistic concurrency. Mitigation: only emit GET→PUT dependency when If-Match is explicitly in PUT's parameters.

## Feasibility Verdict

**Implement.** Spec-declared headers are low risk (explicit signal). Inferred headers for Location/ETag are medium risk but well-defined by HTTP standards. Gate inferred path behind `--infer-headers` flag.

## Estimated Scope

- ~90 LOC for header detection
- ~40 LOC for Location URI matching
- ~30 LOC for `output_detection.py` integration
- Optional: ~10 LOC for `source_location` field on `Output` in `base.py`

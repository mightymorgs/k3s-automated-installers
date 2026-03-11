# Security-Aware Dependency Ordering Design (#22)

## Problem Statement

After Phase C, the pipeline has no awareness of authentication flows. The topological sort from Section 11 orders operations based on data dependencies (FK relationships), but authentication is a prerequisite for almost every operation. Without security-aware ordering, the first operation in the sorted sequence might be a protected endpoint that fails because no auth token has been obtained.

### Benchmark Spec Analysis

| Spec | Has securitySchemes | Operations with security | Token URL in spec |
|------|:---:|:---:|:---:|
| Vault | Yes (token) | ~95% | Yes (`/auth/token/create`) |
| Authentik | Yes (OAuth2, token) | ~98% | Yes (`/api/v3/flows/executor/`) |
| Sonarr | Yes (apiKey) | 100% | No (external provisioning) |
| Cloudflare | Yes (apiKey, bearer) | 100% | No (external dashboard) |

Only Vault and Authentik have internal token-producing operations. Sonarr and Cloudflare use externally provisioned API keys — no in-spec dependency exists.

## Proposed Approach

### Security Scheme Parsing

OpenAPI specs declare security schemes in `components.securitySchemes`. The algorithm processes each scheme type differently:

**OAuth2 flows:**
1. Extract `tokenUrl` from `flows.clientCredentials.tokenUrl` or `flows.authorizationCode.tokenUrl`
2. Match `tokenUrl` against spec's path templates
3. If matched: the matching operation is the token producer
4. If external URL: log note, no edge emitted

**API key schemes:**
1. Check if any operation produces the key field name in its response body
2. Typically external (API keys provisioned via web dashboard) — low confidence
3. Only emit edge if a spec operation explicitly produces the key field

**HTTP bearer schemes:**
1. Similar to OAuth2: look for operations returning `token` or `access_token` in response
2. Match against response output fields from the existing detection pipeline

### External vs. Internal Auth

**Critical decision:** When `tokenUrl` does not match any path in the spec, the auth dependency is external. The detector must **not emit an edge** — doing so would create a false dependency pointing to a non-existent operation.

Detection:
```python
def _is_internal_token_url(token_url: str, spec_paths: dict) -> bool:
    """Check if token URL matches a path in this spec."""
    parsed = urlparse(token_url)
    path = parsed.path
    return any(
        path_matches_template(path, template)
        for template in spec_paths
    )
```

### Edge Emission

For each operation with a `security` requirement:
- If the security scheme has an identified internal token producer:
  - Emit dependency: protected operation → token producer
  - `target_operation`: token-producing operation's operationId
  - `lineage_type`: "explicit" (security requirements are declared)
  - `detection_source`: `DetectionSource.SECURITY_SCHEME` (new enum member)
  - `confidence`: per model below

### Global vs. Operation-Level Security

OpenAPI supports both:
```yaml
# Global (applies to all unless overridden)
security:
  - oauth2: [read]

# Operation-level (overrides global)
paths:
  /public:
    get:
      security: []  # No auth required
```

Implementation: resolve effective security per operation by checking operation-level first, falling back to global.

## Confidence Model

| Scheme Type | Token URL in spec | Token URL external | No token URL |
|-------------|:---:|:---:|:---:|
| OAuth2 | 0.95 | skip | skip |
| API key | 0.80 | N/A | 0.70 |
| HTTP bearer | 0.85 | skip | 0.75 |

All values meet the 0.70 minimum threshold. External token URLs are skipped entirely (no edge emitted) to prevent false positives.

## Integration Point

New file: `dep_adapters/security_deps.py` implementing the `DepAdapter` protocol:

```python
class SecurityDepAdapter:
    priority = 85  # Just below link_deps (90) and annotation_deps (95)

    def matches(self, op_info: OperationInfo, spec: dict) -> bool:
        return "securitySchemes" in spec.get("components", {})

    def detect_dependencies(self, op_info, spec, known) -> list[Dependency]:
        ...

    def detect_outputs(self, op_info, spec, known) -> list[Output]:
        return []  # Security schemes don't produce outputs
```

Also: add `DetectionSource.SECURITY_SCHEME` to the enum in `base.py`.

## Performance Consideration

Security scheme parsing is O(S * O) where S = number of schemes, O = number of operations. For typical specs (1-3 schemes, 50-500 operations), this is negligible (<1ms).

## Dependencies

- **Section 11 (Topo Sort):** Ordering integration — security edges feed into the dependency graph
- **Section 01 (Data Model):** `DetectionSource` enum for new `SECURITY_SCHEME` member

## Risk Analysis

- **Over-connection:** If global security applies to all operations, every operation gets an edge to the token producer. This creates a star graph that may dominate the topology. Mitigation: the topo sort handles this naturally — the token operation goes to tier 0.
- **External auth false positives:** Most API keys and many OAuth2 flows are external. The `_is_internal_token_url()` check prevents false edges.
- **OAuth2 flow complexity:** Authorization code flow involves browser redirects that cannot be automated. Only `clientCredentials` and `password` flows are fully automatable.

## Feasibility Verdict

**Implement for OAuth2 flows where tokenUrl matches an internal path.** This is well-defined and low-risk. **Defer API key inference** — most API keys are provisioned externally, not via API calls. The OAuth2 path covers the highest-value use case (Vault, Authentik).

## Estimated Scope

- ~130 LOC for `dep_adapters/security_deps.py`
- ~5 LOC for `DetectionSource.SECURITY_SCHEME` in `base.py`

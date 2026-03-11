# Progressive Resource Definition Design (#23)

## Problem Statement

The current pipeline identifies resources primarily from schema/component names. When schema names diverge from path-derived resource names, FK matching breaks:

- Path `/api/v1/members` uses schema `TeamMember` → path says "members", schema says "team-member"
- Path `/organizations/{orgId}/repos` uses schema `Repository` → path says "repos", schema says "repository"
- Field `member_id` should match "members" resource but `TeamMember` schema yields "team-member"

Schema normalization (Section 02, #6) handles suffix stripping (`UserResponseDTO` → `User`) but not fundamental naming divergence.

### Benchmark Spec Analysis

| Spec | Path-schema agreement | Divergent cases |
|------|:---:|:---:|
| Vault | High | Backend type vs path (`kv_v2` vs `/secret/data/`) — handled by VaultAdapter |
| Authentik | High | Minor: `PatchedFlowRequest` → `flow` (handled by normalization) |
| Sonarr | Medium | `EpisodeResource` → `episodes` path (handled by suffix stripping) |
| Cloudflare | High | Resources derived from paths, not schemas |

Current naming divergence is manageable with existing normalization. Progressive resource definition would help most for specs not yet in the benchmark suite.

## Proposed Approach

### Two-Pass Algorithm

**Pass 1 — Path Segment Analysis (low risk):**

1. For each path template, extract resource name from last non-parameter segment:
   - `/users/{id}` → `users`
   - `/organizations/{orgId}/repos/{repoId}` → `repos`
2. Singularize: `users` → `user`, `repos` → `repo`
3. Build path-resource map: `{"/users/{id}": "user"}`
4. Record nesting: `repo` is sub-resource of `organization`

```python
def extract_path_resources(spec: dict) -> dict[str, ResourceDefinition]:
    resources = {}
    for path_template in spec.get("paths", {}):
        segments = [s for s in path_template.split("/") if s and not s.startswith("{")]
        if segments:
            name = singularize(segments[-1])
            parent = singularize(segments[-2]) if len(segments) >= 2 else None
            resources[name] = ResourceDefinition(
                canonical_name=name,
                schema_names=[],
                path_templates=[path_template],
                parent_resource=parent,
            )
    return resources
```

**Pass 2 — Schema Merge (higher risk, deferred):**

1. Apply schema normalization (#6): `UserResponseDTO` → `User`
2. Case-insensitive match against path-derived names: `User` → `user`
3. For unmatched schemas used as request/response body: adopt path-derived name
4. Remaining unmatched schemas: standalone (embedded objects, not top-level resources)

### Data Structure

```python
@dataclass
class ResourceDefinition:
    canonical_name: str          # Path-derived, singularized
    schema_names: list[str]      # Normalized schema names mapped to this resource
    path_templates: list[str]    # All path templates for this resource
    parent_resource: str | None  # Sub-resource relationship
```

### Conflict Resolution

When path-derived and schema-derived names disagree:
- **Path-derived name wins** for FK matching (paths are canonical REST identity)
- **Schema-derived name kept as alias** for producer matching
- Both names recorded in `resource_aliases` map consulted during target inference

### Fuzzy Matching Boundaries

**Acceptable matches:**
- Case-insensitive exact after singularization: `User` ↔ `user`
- Substring where longer name has known suffix/prefix: `TeamMember` contains `Member` → `member`

**Rejected (too speculative):**
- Levenshtein distance (e.g., `order` matching `border`)
- Semantic similarity (e.g., `employee` matching `worker`)
- Abbreviation expansion (e.g., `org` matching `organization`)

This strict boundary prevents false resource merges that could create phantom FK relationships.

## Integration Point

The resource definition pass runs **early in the pipeline**, after spec loading but before dependency detection:

```python
# In cli.py, after create_context():
resource_defs = extract_path_resources(ctx.schema)
# Pass to detect() calls
deps, outputs = registry.detect(op, spec, known_resources, resource_defs=resource_defs)
```

### Backward Compatibility

The `DepAdapter` protocol currently accepts `known_resources: set[str]`. To maintain backward compatibility:

```python
def detect_dependencies(
    self,
    op_info: OperationInfo,
    spec: dict,
    known_resources: set[str] | dict[str, ResourceDefinition],
) -> list[Dependency]:
    # Accept both: set is a view of canonical names
    if isinstance(known_resources, dict):
        canonical_names = set(known_resources.keys())
        aliases = known_resources
    else:
        canonical_names = known_resources
        aliases = None
    ...
```

## Confidence Model

Resource merging itself does not produce edges — it improves accuracy of existing edge detection:

| Match type | Confidence adjustment |
|------------|:---:|
| FK via canonical name | No change (existing confidence) |
| FK via alias | -0.05 (alias is one step removed) |

Both remain above the 0.70 minimum threshold for any edge that was above threshold before aliasing.

## Dependencies

- **Section 10 (Response Tree Walk):** Schema-to-operation mapping
- **Section 02 (Schema Normalization):** Schema name cleanup
- **Section 10 (ReadOnly Diff):** Resource identity from PUT vs GET comparison

## Risk Analysis

- **False merges:** Two distinct resources with similar names merged incorrectly (e.g., `user` and `admin-user`). Mitigation: strict fuzzy matching boundaries, path-wins-on-conflict rule.
- **Sub-resource confusion:** `/organizations/{orgId}/repos` — is `repos` a standalone resource or always scoped to `organization`? Pass 1 records the parent relationship but doesn't enforce it during FK matching. This is intentional — FK matching should find cross-scope references.
- **Singularization errors:** English pluralization is irregular (`indices` vs `indexes`, `matrices`). Mitigation: use a well-tested singularization library or maintain a small exception list.

## Feasibility Verdict

**Implement Pass 1 (path segment analysis) unconditionally.** It is simple (~80 LOC), low-risk, and improves resource identification for all specs.

**Defer Pass 2 (schema merge with fuzzy matching)** until benchmarks show Pass 1 alone is insufficient. The fuzzy matching introduces false merge risk that must be validated carefully against real specs.

## Estimated Scope

- Pass 1: ~80 LOC (`generation/resource_discovery.py`)
- Pass 2: ~120 LOC (deferred)
- Integration: ~40 LOC (`dep_adapters/base.py`, `target_inference.py`, `body_fk.py`)

# EM Clustering for CRUD Grouping (#19)

## Problem Statement

After Phases A-C, CRUD grouping uses path template matching (e.g., `/users/{id}` groups with `/users`). This works well for REST-conformant APIs but fails for:

- **Action-oriented endpoints:** `/api/v1/createUser`, `/api/v1/deleteUser` — no shared path template
- **Flat URL structures:** `/api/execute?action=CreateUser` — resource identity is in parameters, not paths
- **Inconsistent path patterns:** `/members/{id}` vs `/team/members/list` — same resource, different structure

Phase C benchmarks show path-based grouping succeeds for 4 of 5 benchmark specs (vault, authentik, sonarr, cloudflare). Only AWS Query-style APIs consistently fail — but those use the dedicated `AwsQueryAdapter` with `action_to_resource()`.

## Proposed Approach

### Input Representation

Each operation becomes a binary feature vector encoding parameter presence:

```
Operation: POST /users
  Parameters: [name=1, email=1, group_id=1, password=0, api_key=0, ...]
```

Sources of parameters:
- Path parameters (from URI template)
- Query parameters
- Header parameters (excluding standard headers: Authorization, Content-Type)
- Top-level request body properties

### Algorithm Comparison

| Approach | Pros | Cons |
|----------|------|------|
| **Jaccard similarity + hierarchical clustering** | No dependencies, deterministic, interpretable | Manual threshold selection |
| **GMM (sklearn)** | Automatic component count via BIC, soft assignments | +30MB dependency, non-deterministic |
| **DBSCAN** | No cluster count needed | Epsilon sensitivity, poor with varying density |

**Recommendation:** Jaccard similarity as default. The algorithm:

1. Compute pairwise Jaccard similarity between all operations' parameter sets
2. Build agglomerative clusters using average linkage
3. Cut dendrogram at threshold 0.6 (operations sharing >60% of parameters are grouped)
4. Merge Jaccard clusters with path-based groups (path match wins on conflict)

### sklearn Dependency Analysis

sklearn adds ~30MB. For a CLI tool focused on infrastructure automation, this is disproportionate. The Jaccard approach achieves comparable accuracy for the target use case without the dependency. sklearn can be an optional extra: `pip install idi[clustering]`.

## Integration Point

Clustering output feeds into the CRUD grouping step in `cli.py`:

```python
# Current: path-based only
groups = group_operations_by_path(operations)

# With clustering fallback:
groups = group_operations_by_path(operations)
if len(groups) < expected_resource_count and clustering_enabled:
    cluster_groups = cluster_operations_by_params(operations)
    groups = merge_groups(groups, cluster_groups)  # path wins conflicts
```

Trigger: only run if `--clustering` flag is passed or if path-based grouping produces suspiciously few groups (< 3 groups from > 20 operations).

## Confidence Model

| Cluster quality | Confidence |
|:---:|:---:|
| Tight (all members > 0.9 Jaccard) | 0.85 |
| Moderate (members 0.7-0.9) | 0.70 |
| Loose (members < 0.7) | Skip (leave ungrouped) |

## Risk Analysis

- **False merges:** Two unrelated operations sharing common parameter names (e.g., `page`, `limit`) could be incorrectly grouped. Mitigation: exclude pagination/filtering params from feature vectors.
- **Performance:** Jaccard similarity is O(n^2) for n operations. For typical specs (50-500 ops), this completes in <100ms.
- **Maintenance:** Simple algorithm, easy to debug and tune threshold.

## Feasibility Verdict

**Defer.** Phase C benchmarks show path-based CRUD grouping succeeds for all REST-conformant benchmark specs. AWS Query APIs already use `action_to_resource()`. The clustering fallback would help only for unusual API designs not yet in the benchmark suite. Prototype the Jaccard approach if a concrete failing spec is identified.

## Estimated Scope

- ~120 LOC for Jaccard approach (`dep_adapters/clustering.py`)
- ~180 LOC for GMM approach (optional sklearn path)
- ~40 LOC for integration into `cli.py` CRUD grouping

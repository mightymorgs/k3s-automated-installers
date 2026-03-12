Good, I now have a clear sense of the format and level of detail expected. Now I have all the context needed to write section 14.

# Section 14: Phase D Design Documents

## Overview

This section produces five focused design documents for Tier 3 improvement items (#19 through #23). These items require significant architectural decisions and depend on Phase C results to demonstrate the effectiveness of the generic detection approach before committing to implementation. **No code is produced in this section** -- the deliverables are design specifications with key decisions, feasibility analysis, dependency mapping, and enough detail that a future implementer can proceed without ambiguity.

**Depends on:** Section 13 (Phase C adapter slimming must be complete; results from Phases A-C inform feasibility assessments)
**Blocks:** Nothing (this is the final section)

## Implementation Results

All 5 design documents created in `docs/plans/rest-phase-d/`:

| Document | File | Verdict |
|----------|------|---------|
| EM Clustering | `em-clustering-design.md` | Defer (path-based grouping sufficient for benchmarks) |
| Link Injection | `link-injection-design.md` | Implement (round-trip validation justifies effort) |
| Response Header Producers | `response-header-producers-design.md` | Implement (spec-declared headers low risk) |
| Security-Aware Ordering | `security-aware-ordering-design.md` | Implement OAuth2 only (defer API key inference) |
| Progressive Resource Def | `progressive-resource-definition-design.md` | Implement Pass 1 only (defer fuzzy schema merge) |

All confidence values verified >= 0.70 project minimum. Designs reference Phase C results:
- Total vendor LOC 1059 → 413 (61% reduction)
- Vault pipeline parity verified (edge count >= baseline)
- 1225 tests passing across full suite

### Deliverables

| Document | File | Plan Item |
|----------|------|-----------|
| EM Clustering Design | `docs/plans/rest-phase-d/em-clustering-design.md` | #19 |
| Link Injection Design | `docs/plans/rest-phase-d/link-injection-design.md` | #20 |
| Response Header Producers Design | `docs/plans/rest-phase-d/response-header-producers-design.md` | #21 |
| Security-Aware Ordering Design | `docs/plans/rest-phase-d/security-aware-ordering-design.md` | #22 |
| Progressive Resource Definition Design | `docs/plans/rest-phase-d/progressive-resource-definition-design.md` | #23 |

---

## Tests

There are no automated tests for this section. The TDD plan explicitly marks this section as "N/A (design documents only)." Validation is performed through design review, not code execution.

---

## Background

### Why Design-First

The Phase D items sit at the frontier of what schema-based heuristic detection can achieve. Each one either introduces a new dependency (sklearn for #19), creates a feedback loop (link injection for #20), or extends detection to signals outside the schema body (headers for #21, security schemes for #22). Implementing any of these without a clear design risks wasted effort if Phase C results show the simpler approaches are sufficient.

### Pipeline Context

After Phases A-C, the REST pipeline in `platform-tools/idi/idi/generation/` has the following structure relevant to Phase D:

- **`dep_adapters/base.py`**: `Dependency` dataclass with `confidence`, `source`, `lineage_type`, `detection_source` fields. `Output` dataclass with `field`, `fact_ref`, `source`, `priority`. `DepAdapter` protocol with `matches()`, `detect_dependencies()`, `detect_outputs()`.
- **`dep_adapters/output_detection.py`**: Response field output detection with method priority (POST=3, PUT=2, PATCH=1). ID field precedence list. After Phase C: full response tree walk to depth 5, readOnly field detection, PUT-vs-GET set difference.
- **`dep_adapters/link_deps.py`** (from Section 05): OpenAPI links parser. Confidence 1.0 for explicit links. Two-stage runtime expression parser.
- **`dep_adapters/topo_sort.py`** (from Section 11): Tarjan's SCC + Kahn's topological sort. Cycle-breaking. Early termination fallback.
- **`dep_adapters/target_inference.py`**: FK suffix matching, credential exclusion regex.
- **`adapters/envelope_detector.py`** (from Section 06): Generic envelope unwrapping with 4 patterns.
- **`dep_adapters/body_fk.py`**: Nested FK detection and nested object producer resolution.

### Success Criteria for Design Documents

Each design document must address:

1. **Problem statement**: What gap exists after Phases A-C
2. **Proposed approach**: Algorithm, data flow, integration point
3. **Dependencies**: What Phase A-C components it builds on
4. **Confidence model**: What confidence scores the new detector would emit and why
5. **Risk analysis**: False positive potential, performance, maintainability
6. **Feasibility verdict**: Implement / defer / reject, with rationale tied to Phase C results
7. **Estimated scope**: Approximate LOC, files to create/modify

---

## Design Document 1: EM Clustering for CRUD Grouping (#19)

**File:** `docs/plans/rest-phase-d/em-clustering-design.md`

### Content Requirements

This document designs a Gaussian Mixture Model (GMM) clustering approach to group API operations by shared parameters. Operations sharing the same path/query parameter set likely operate on the same resource type. This improves CRUD grouping accuracy for readOnly diff (#14 from Section 10) and producer-consumer matching.

The document must cover these specific topics:

**Problem statement.** After Phase C, CRUD grouping uses path template matching (e.g., `/users/{id}` groups with `/users`). This works well for REST-conformant APIs but fails for APIs with inconsistent path patterns, action-oriented endpoints (e.g., `/api/v1/createUser`, `/api/v1/deleteUser`), or flat URL structures where the resource identity is only visible in shared parameter names.

**Input representation.** Describe the one-hot encoding of parameter names per operation. Each operation becomes a binary feature vector where 1 indicates the operation accepts that parameter. Include treatment of path parameters (extracted from URI template), query parameters, header parameters, and body-level properties (top-level keys of the request body schema).

**Clustering algorithm.** Compare three approaches with explicit trade-offs:
- Gaussian Mixture Model (sklearn.mixture.GaussianMixture) -- automatic component count via BIC/AIC, soft cluster assignments, handles overlapping clusters
- Hierarchical clustering on parameter Jaccard similarity -- no sklearn dependency, deterministic, interpretable dendrograms, but requires manual threshold selection for cutting the dendrogram
- DBSCAN on parameter overlap -- no need to specify cluster count, but sensitive to epsilon parameter selection

**sklearn dependency analysis.** sklearn adds approximately 30MB to the installation. Analyze whether the accuracy gain justifies this for a CLI tool. Recommend the Jaccard similarity approach as the default, with sklearn as an optional extra (`pip install idi[clustering]`) for users who need it.

**Integration point.** The clustering output feeds into the CRUD grouping step that currently uses path template matching. The document must specify how clustered operations replace or augment the existing path-based grouping, and what happens when clustering disagrees with path matching (path match should win -- higher confidence).

**When to use.** Define the trigger condition: only run clustering if path-based CRUD grouping produces fewer than N groups (threshold to be determined from benchmarks) or if a `--clustering` flag is explicitly passed. Clustering should not run by default due to its computational cost and the fact that path-based grouping is sufficient for most well-designed APIs.

**Confidence model.** Cluster membership probability from GMM maps to confidence. Tight clusters (all members > 0.9 probability) get confidence 0.85 for inferred CRUD relationships. Loose clusters (members 0.7-0.9) get confidence 0.7. Members below 0.7 probability are left ungrouped.

**Feasibility verdict.** Defer unless Phase C benchmarks show that path-based CRUD grouping fails for more than 1 of the 5 benchmark specs. The Jaccard similarity fallback should be prototyped first.

**Estimated scope.** ~120 LOC for Jaccard approach, ~180 LOC for GMM approach, plus ~40 LOC for integration into the existing CRUD grouping logic. One new file: `dep_adapters/clustering.py`.

---

## Design Document 2: Link Injection (#20)

**File:** `docs/plans/rest-phase-d/link-injection-design.md`

### Content Requirements

This document designs the reverse of the links parser from Section 05: instead of consuming OpenAPI `links` objects, this feature produces them by injecting inferred dependency edges back into the OpenAPI spec as standard `links` objects.

The document must cover these specific topics:

**Problem statement.** After the pipeline infers dependency edges, there is no way to validate inference accuracy against specs that already have links (round-trip testing), enrich specs for downstream tools (Schemathesis stateful testing, Dredd, Prism), or give users a human-readable view of the inferred graph in a format they already understand.

**Output format.** The injected links must be valid OpenAPI 3.0 `links` objects. Each inferred edge `(source_operation, source_field) -> (target_operation, target_param)` becomes:

```yaml
responses:
  '200':
    links:
      InferredLink_{target_operationId}:
        operationId: {target_operationId}
        parameters:
          {target_param}: '$response.body#/{source_field}'
        x-idi-confidence: 0.85
        x-idi-detection-source: "fk_suffix"
```

The `x-idi-confidence` and `x-idi-detection-source` extensions provide provenance. The link name prefix `InferredLink_` distinguishes injected links from author-declared links.

**Round-trip validation.** Describe the validation flow: (1) parse existing links with link_deps.py, (2) run inference pipeline, (3) compare inferred edges to parsed links, (4) report precision/recall. This is the primary use case -- it validates the inference pipeline against ground truth.

**Conflict resolution.** When a response already has author-declared links, inferred links must not overwrite them. The injection should add new links alongside existing ones. If an inferred link duplicates an existing one (same operationId + same parameter mapping), skip it and log a confirmation that inference matched ground truth.

**Spec mutation vs. copy.** The injector must never modify the original spec dict in place. It should produce a deep copy with injected links. This preserves the immutable-spec invariant used throughout the pipeline.

**Integration point.** Link injection runs as a post-processing step after the full pipeline completes, not as a DepAdapter. It takes the final list of `Dependency` objects and the original spec, and produces an enriched spec. New file: `generation/link_injector.py`.

**Dependency.** Requires Section 05 (link_deps.py) for the parser that validates round-trip correctness. Requires Section 01 (DetectionSource enum) for the `x-idi-detection-source` extension value.

**Confidence model.** Injected links carry the confidence of the underlying inferred edge. No additional confidence adjustment -- the link is a faithful representation of the inference.

**Feasibility verdict.** Implement after Phase C. Low risk, moderate value. The round-trip validation use case alone justifies the effort.

**Estimated scope.** ~100 LOC for injection logic, ~60 LOC for round-trip validation report. One new file: `generation/link_injector.py`. Modifications to the CLI (`cli.py`) to add a `--inject-links` flag.

---

## Design Document 3: Response Header Producers (#21)

**File:** `docs/plans/rest-phase-d/response-header-producers-design.md`

### Content Requirements

This document designs detection of dependency-producing response headers. Certain HTTP response headers carry values that downstream operations consume as inputs, creating dependency edges that the current pipeline misses entirely because it only examines response bodies.

The document must cover these specific topics:

**Problem statement.** The current pipeline (after Phase C) detects producers only from response body fields. Several important dependency patterns exist exclusively in response headers:
- `Location` header from 201 Created responses: contains the URI of the newly created resource. A `POST /users` returning `Location: /users/42` declares a producer of `/users/{id}` -- a POST-to-GET dependency.
- `ETag` header: version identifier for conditional updates. `GET /users/42` returns `ETag: "abc"`, which must be passed as `If-Match: "abc"` to `PUT /users/42`. This is a GET-to-PUT dependency.
- `X-Request-Id`: correlation identifier linking request/response pairs across operations.
- Custom headers declared in `responses.headers` in the OpenAPI spec.

**Header detection algorithm.** Two sources of header information:
1. **Spec-declared headers:** OpenAPI responses can declare headers via `responses.{code}.headers.{name}`. These are explicit and high-confidence.
2. **Well-known headers:** `Location` on 201 responses and `ETag` on 200 responses are semantically defined by HTTP standards even when not declared in the spec. These can be inferred.

**Location header parsing.** The `Location` header value is a URI. To create a dependency edge, the URI must be matched against the spec's path templates. The algorithm:
1. Extract the `Location` header schema from the 201 response (or assume string type for well-known).
2. Match the Location URI pattern against all path templates in the spec using the same RFC 6570 parser from Section 02 (#9).
3. If a match is found, emit a dependency from the POST operation to the matched GET operation, with the path parameter as the consumed field.
4. Confidence: 0.95 for spec-declared `Location` header, 0.85 for inferred (not declared but 201 response).

**ETag/If-Match dependency.** When a GET response declares an `ETag` header and a PUT/PATCH on the same resource path accepts an `If-Match` header (in parameters), emit a GET-to-PUT dependency. Confidence: 0.9 for spec-declared, 0.8 for inferred.

**X- headers.** Custom headers (X-Request-Id, X-Total-Count, etc.) are lower confidence because their semantics are not standardized. Confidence: 0.7 for spec-declared custom headers, skip inferred custom headers entirely (too speculative).

**Integration point.** This extends `output_detection.py` with a new `detect_header_outputs()` function that runs alongside the existing `detect_outputs()`. The results merge into the same `Output` list. The `Output` dataclass may need a `source_location` field (default "body", new value "header") to distinguish header-sourced producers.

**Confidence model summary.**

| Header | Declared in spec | Inferred | Source |
|--------|:---:|:---:|--------|
| Location (201) | 0.95 | 0.85 | HTTP standard |
| ETag | 0.90 | 0.80 | HTTP standard |
| X-Request-Id | 0.70 | skip | Convention only |
| Other X- | 0.70 | skip | Convention only |

**Dependency.** Requires Section 10 (response tree walk in output_detection.py) for integration. Requires Section 02 (#9, RFC 6570 parser) for Location URI matching.

**Feasibility verdict.** Implement. Low risk for spec-declared headers (explicit signal). Medium risk for inferred headers (may produce false positives on APIs that return 201 without Location). The spec-declared path is safe; the inferred path should be gated behind a `--infer-headers` flag.

**Estimated scope.** ~90 LOC for header detection, ~40 LOC for Location URI matching. Modifications to `output_detection.py` (~30 LOC) and `base.py` (optional `source_location` field on `Output`).

---

## Design Document 4: Security-Aware Dependency Ordering (#22)

**File:** `docs/plans/rest-phase-d/security-aware-ordering-design.md`

### Content Requirements

This document designs automatic detection of authentication dependencies. If an operation requires a security scheme (OAuth2 token, API key), and another operation in the spec produces that credential (e.g., `POST /auth/token`), a dependency edge should be emitted so that authentication operations execute before protected endpoints.

The document must cover these specific topics:

**Problem statement.** After Phase C, the pipeline has no awareness of authentication flows. The topological sort from Section 11 orders operations based on data dependencies (FK relationships), but authentication is a prerequisite for almost every operation. Without security-aware ordering, the first operation in the sorted sequence might be a protected endpoint that fails because no auth token has been obtained.

**Security scheme parsing.** OpenAPI specs declare security schemes in `components.securitySchemes`:

```yaml
components:
  securitySchemes:
    oauth2:
      type: oauth2
      flows:
        clientCredentials:
          tokenUrl: https://auth.example.com/token
        authorizationCode:
          authorizationUrl: https://auth.example.com/authorize
          tokenUrl: https://auth.example.com/token
    apiKey:
      type: apiKey
      in: header
      name: X-API-Key
    bearerAuth:
      type: http
      scheme: bearer
```

Operations reference these via the `security` field:

```yaml
paths:
  /users:
    get:
      security:
        - oauth2: [read:users]
```

**Token-producing operation detection.** For OAuth2 schemes, the `tokenUrl` is the producer. The algorithm:
1. Extract all `securitySchemes` from the spec.
2. For OAuth2 schemes: match the `tokenUrl` against the spec's path templates. If matched, the matching operation is the token producer.
3. For API key schemes: search for operations that produce the API key field name in their response body (using the existing output detection pipeline).
4. For HTTP bearer: similar to OAuth2 -- look for operations returning a `token` or `access_token` field.

**External vs. internal auth.** Many APIs have external authentication (the token URL points outside the spec). When the `tokenUrl` does not match any path in the spec, log a note and do not emit an edge -- the auth dependency is external to this API. This is critical to avoid false edges.

**Edge emission.** For each operation with a `security` requirement:
- If the security scheme has an identified internal token-producing operation, emit a dependency edge from the protected operation to the token producer.
- The dependency's `target_operation` is the token-producing operation.
- `lineage_type`: "explicit" (security requirements are declared, not inferred).
- `detection_source`: a new `DetectionSource.SECURITY_SCHEME` enum member.

**Confidence model.**

| Scheme Type | Token URL in spec | Token URL external | No token URL |
|-------------|:---:|:---:|:---:|
| OAuth2 | 0.95 | skip | skip |
| API key | 0.80 | N/A | 0.70 |
| HTTP bearer | 0.85 | skip | 0.75 |

**Global vs. operation-level security.** OpenAPI specs can declare security at the top level (applies to all operations) or at the operation level (overrides top-level). The implementation must handle both. If global security is declared, every operation without an explicit override inherits it -- every such operation gets a dependency on the token producer.

**Performance consideration.** Security scheme parsing is O(S * O) where S is the number of security schemes and O is the number of operations. For typical specs (1-3 schemes, 50-500 operations), this is negligible.

**Integration point.** New file: `dep_adapters/security_deps.py` implementing the `DepAdapter` protocol. Priority: high (just below link_deps.py and annotation_deps.py). `matches()` returns True if the spec has `components.securitySchemes`.

**Dependency.** Requires Section 11 (topo_sort.py) for ordering integration. Requires Section 01 (DetectionSource enum) for the new enum member.

**Feasibility verdict.** Implement for OAuth2 flows where tokenUrl matches an internal path. Defer API key inference (too speculative -- most API keys are provisioned externally, not via API calls). The OAuth2 path is well-defined and low-risk.

**Estimated scope.** ~130 LOC for security scheme parsing and edge emission. One new file: `dep_adapters/security_deps.py`. Minor modification to `base.py` to add `DetectionSource.SECURITY_SCHEME`.

---

## Design Document 5: Progressive Resource Definition (#23)

**File:** `docs/plans/rest-phase-d/progressive-resource-definition-design.md`

### Content Requirements

This document designs a two-pass resource discovery mechanism that improves resource identification for specs where schema names do not match resource names. This is common in auto-generated specs, legacy APIs, and APIs where the URL structure and schema naming follow different conventions.

The document must cover these specific topics:

**Problem statement.** The current pipeline identifies resources primarily from schema/component names in the spec. When schema names use suffixes like `UserResponseDTO` or prefixes like `CreateUserRequest`, the schema normalization from Section 02 (#6) helps. But some specs have more fundamental mismatches: the path `/api/v1/members` might use a schema named `TeamMember`, or the path `/organizations/{orgId}/repos` might use `Repository`. Path-based resource identity and schema-based resource identity diverge, leading to missed FK matches because the producer (schema-derived) and consumer (path-derived) use different names for the same resource.

**Two-pass algorithm.**

Pass 1 -- Path segment analysis:
1. For each path template in the spec, extract the resource name from the last non-parameter segment: `/users/{id}` yields `users`, `/organizations/{orgId}/repos/{repoId}` yields `repos`.
2. Singularize the extracted name to get the canonical resource name: `users` becomes `user`, `repos` becomes `repo`.
3. Build a path-resource map: `{"/users/{id}": "user", "/organizations/{orgId}/repos/{repoId}": "repo"}`.
4. Record the nesting hierarchy: `repo` is a sub-resource of `organization`.

Pass 2 -- Schema merge:
1. For each component schema, apply the existing schema normalization (#6 from Section 02): `UserResponseDTO` becomes `User`, `TeamMember` stays `TeamMember`.
2. Match normalized schema names to path-derived resource names using case-insensitive comparison and singularization: `User` matches `user`, `Repository` matches `repo` only if a fuzzy match threshold is met.
3. For unmatched schemas, check if the schema is used as the request/response body of any operation. If so, adopt the path-derived resource name for that schema.
4. For remaining unmatched schemas, keep them as standalone resource definitions (they may represent embedded objects, not top-level resources).

**Conflict resolution.** When path-derived and schema-derived names disagree:
- Path-derived name wins for FK matching (paths are the canonical resource identity in REST).
- Schema-derived name is kept as an alias for producer matching.
- Both names are recorded in a `resource_aliases` map that the FK matcher consults during target inference.

**Resource alias map.** The data structure:

```python
@dataclass
class ResourceDefinition:
    canonical_name: str          # Path-derived, singularized
    schema_names: list[str]      # Normalized schema names that map to this resource
    path_templates: list[str]    # All path templates for this resource
    parent_resource: str | None  # Sub-resource relationship
```

This map is constructed once per spec and passed to `target_inference.py` and `body_fk.py` for FK resolution. When a field like `member_id` fails to match a resource named `user`, the alias map reveals that `member` is an alias for `user` (because the `/members` path uses the `User` schema).

**Fuzzy matching boundaries.** The design must explicitly define the limits of fuzzy matching to avoid false resource merges. Acceptable matches:
- Case-insensitive exact match after singularization: `User` matches `user`
- Substring match where one name contains the other and the longer name has a known suffix/prefix: `TeamMember` contains `Member` which singularizes to `member`

Unacceptable matches (too speculative):
- Levenshtein distance-based matching (e.g., `order` matching `border`)
- Semantic similarity (e.g., `employee` matching `worker`)

**Integration point.** The resource definition pass runs early in the pipeline, after spec loading but before dependency detection. The `ResourceDefinition` map replaces the current `known_resources: set[str]` parameter passed to `detect_dependencies()`. This is a breaking change to the `DepAdapter` protocol -- the document must specify how to maintain backward compatibility (accept both `set[str]` and `dict[str, ResourceDefinition]`, with the set being a view of canonical names).

**Dependency.** Requires Section 10 (response tree walk, #13) for accurate schema-to-operation mapping. Requires Section 10 (#14, readOnly diff) for resource identity from PUT vs GET comparison. Requires Section 02 (#6, schema normalization) for schema name cleanup.

**Confidence model.** Resource merging itself does not produce edges -- it improves the accuracy of existing edge detection. The confidence impact is indirect:
- FK matches via canonical name: existing confidence (unchanged)
- FK matches via alias: confidence reduced by 0.05 (alias match is one step removed from direct match)

**Feasibility verdict.** Implement Pass 1 (path segment analysis) unconditionally -- it is simple, low-risk, and improves resource identification for all specs. Defer Pass 2 (schema merge with fuzzy matching) until benchmarks show that Pass 1 alone is insufficient. The fuzzy matching introduces false merge risk that must be validated carefully.

**Estimated scope.** Pass 1: ~80 LOC. Pass 2: ~120 LOC. Integration into target_inference.py and body_fk.py: ~40 LOC. One new file: `generation/resource_discovery.py`. Modifications to `dep_adapters/base.py` (`OperationInfo` or `DepAdapter` protocol to accept resource definitions).

---

## Implementation Checklist

Since this section produces design documents rather than code, the implementation checklist is structured around document creation and review:

1. Create directory `docs/plans/rest-phase-d/` if it does not exist.
2. Write `em-clustering-design.md` covering all topics listed in Design Document 1 above. Ensure the feasibility verdict references actual Phase C benchmark results (edge counts, CRUD grouping accuracy on each benchmark spec).
3. Write `link-injection-design.md` covering all topics listed in Design Document 2 above. Include a concrete round-trip validation example using a spec that has existing links.
4. Write `response-header-producers-design.md` covering all topics listed in Design Document 3 above. Include examples from at least 2 benchmark specs showing where header-based dependencies are currently missed.
5. Write `security-aware-ordering-design.md` covering all topics listed in Design Document 4 above. Include analysis of how many benchmark specs have `securitySchemes` and what percentage of their operations have `security` requirements.
6. Write `progressive-resource-definition-design.md` covering all topics listed in Design Document 5 above. Include analysis of path-vs-schema naming divergence across benchmark specs.
7. Review all five documents for internal consistency: confidence scores must not conflict with the project-wide precision-over-recall constraint (minimum 0.7 to emit, ground-truth at 0.95+).
8. Verify that no design document proposes adding a dependency edge below confidence 0.7.

---

## Cross-Section Dependencies

This section depends on the following completed sections:

- **Section 01 (Data Model):** `DetectionSource` enum with its string-valued members. Design documents reference `DetectionSource.SECURITY_SCHEME` (new member proposed in Document 4).
- **Section 02 (Phase A Preprocessing):** Schema normalization (#6) and RFC 6570 URI template parser (#9). Documents 3 and 5 reference these.
- **Section 05 (Links Parser):** `link_deps.py` implementing OpenAPI links parsing. Document 2 depends on this for round-trip validation.
- **Section 10 (Response Walk / ReadOnly):** Full response tree walk and readOnly detection. Documents 3, 4, and 5 reference these capabilities.
- **Section 11 (Topo Sort):** `topo_sort.py` with Tarjan's SCC + Kahn's sort. Document 4 integrates with this.
- **Section 13 (Phase C Adapter Slimming):** Benchmark results from Phase C inform all feasibility verdicts. The documents must reference actual edge counts and accuracy metrics from Phase C testing.
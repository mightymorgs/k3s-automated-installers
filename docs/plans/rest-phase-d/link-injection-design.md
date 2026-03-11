# Link Injection Design (#20)

## Problem Statement

After the pipeline infers dependency edges, there is no way to:

1. **Validate inference accuracy** against specs that already have OpenAPI `links` (round-trip testing)
2. **Enrich specs** for downstream tools (Schemathesis stateful testing, Dredd, Prism)
3. **Give users a human-readable view** of the inferred graph in a standard format

## Proposed Approach

### Output Format

Each inferred edge becomes a valid OpenAPI 3.0 `links` object:

```yaml
responses:
  '200':
    links:
      InferredLink_getUser:
        operationId: getUser
        parameters:
          user_id: '$response.body#/id'
        x-idi-confidence: 0.85
        x-idi-detection-source: "fk_suffix"
```

- `InferredLink_` prefix distinguishes injected from author-declared links
- `x-idi-confidence` carries the underlying edge confidence
- `x-idi-detection-source` provides provenance from `DetectionSource` enum

### Spec Mutation vs. Copy

The injector **never modifies the original spec** in place. It produces a deep copy with injected links, preserving the immutable-spec invariant used throughout the pipeline.

### Conflict Resolution

When a response already has author-declared links:
- Inferred links are **added alongside** existing ones (never overwrite)
- If an inferred link duplicates an existing link (same operationId + same parameter mapping), skip it and log a confirmation that inference matched ground truth
- The link name includes a counter to avoid collisions: `InferredLink_getUser_1`, `InferredLink_getUser_2`

### Round-Trip Validation

The primary use case — validating inference accuracy against ground truth:

1. Parse existing links with `link_deps.py` (Section 05) → declared edges
2. Run inference pipeline → inferred edges
3. Compare: for each declared edge, check if inference found it
4. Report precision (inferred edges that match declared) and recall (declared edges found by inference)

```
Round-Trip Validation Report:
  Declared links: 12
  Inferred links: 45
  Matched: 10 (83% recall of declared links)
  Extra inferred: 35 (potentially valid, not declared by author)
  Missed: 2 (declared links not found by inference)
```

## Integration Point

Link injection runs as a **post-processing step** after the full pipeline completes:

```python
# In cli.py or as standalone command
from idi.generation.link_injector import inject_links

enriched_spec = inject_links(
    spec=original_spec,
    dependencies=all_deps,  # List[Dependency] from pipeline
    operations=all_operations,
)
```

New file: `generation/link_injector.py`
CLI flag: `--inject-links` to enable, `--inject-links-output path.json` for output file

## Dependencies

- **Section 05 (Links Parser):** `link_deps.py` for round-trip validation
- **Section 01 (Data Model):** `DetectionSource` enum for `x-idi-detection-source` extension

## Confidence Model

Injected links carry the confidence of the underlying inferred edge directly. No additional adjustment — the link is a faithful representation of the inference.

## Risk Analysis

- **False positives in injected links:** If the inference pipeline has FPs, they propagate to injected links. Mitigation: the `x-idi-confidence` extension lets consumers filter by threshold.
- **Spec compatibility:** Some OpenAPI tools may not understand `x-idi-*` extensions. This is harmless — extensions are ignored by compliant tools per the spec.
- **Large output:** Specs with many operations may produce hundreds of injected links. Mitigation: optional `--min-confidence` flag to filter.

## Feasibility Verdict

**Implement after Phase C.** Low risk, moderate value. The round-trip validation use case alone justifies the effort. The enriched spec output is a bonus for downstream tool integration.

## Estimated Scope

- ~100 LOC for injection logic (`generation/link_injector.py`)
- ~60 LOC for round-trip validation report
- ~20 LOC for CLI integration (`cli.py` flag)

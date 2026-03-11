Good -- no existing tests for the audit script. Now I have all the context I need. Let me generate the section content.

# Section 13: Audit Baseline Correction

## Overview

This section modifies the `edge_detection_audit.py` script to distinguish between **actionable** and **non-actionable** expected references. Currently, all expected refs are treated equally in coverage calculations, including `UNKNOWN_KIND` targets from ref_tuple detection (method 4). These refs represent reference tuples where the target Kind cannot be resolved from the schema (no `kind` enum, or the enum values are not registered Kinds). Since the pipeline *cannot* resolve these targets without external data, counting them as gaps inflates the miss rate and obscures the coverage picture for refs the pipeline can actually address.

The fix adds `actionable: bool` and `non_actionable_reason: str` fields to `ExpectedRef`, marks `UNKNOWN_KIND` targets as non-actionable, and updates the report to show two coverage columns: **Actionable Coverage** (refs with known target Kinds) and **Total Ref Coverage** (all refs including non-actionable).

**No dependencies on other sections.** This section can be implemented in parallel with any other section.

## File Paths

- **Modified:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/scripts/edge_detection_audit.py`
- **Created:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/test_audit_baseline.py`

## Background: Current State

The audit script lives at `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/scripts/edge_detection_audit.py`. It:

1. Discovers CRD services by scanning `catalog/skills/crd/` and matching to spec files in `catalog/specs/`.
2. Walks every CRD schema with unlimited depth, applying 6 detection methods to identify expected references.
3. Loads detected refs from generated skill JSON files.
4. Compares expected vs detected, computing root causes for gaps.
5. Generates a markdown report with summary table, root cause categories, missing edges, and prioritized fix list.

The `ExpectedRef` dataclass currently has these fields:

```python
@dataclass
class ExpectedRef:
    service: str
    kind: str
    field_path: str
    field_name: str
    expected_target: str
    detection_method: str
    depth: int
    confidence: str
    parent_path: str = ""
    has_excluded_sibling_kind: bool = False
```

When method 4 (ref_tuple) finds a reference tuple but cannot resolve the target Kind (no `kind` enum or values not in `KNOWN_KINDS`), it sets `expected_target = "UNKNOWN_KIND"`. These show up as `REF_TUPLE_UNRESOLVABLE` in root cause analysis. In the current audit report, ArgoCD has 45 of 79 missing edges categorized as `REF_TUPLE_UNRESOLVABLE` -- these are all `UNKNOWN_KIND` targets. They inflate ArgoCD's miss count from ~34 to 79, dragging the service down to 53.5% coverage when the actionable coverage is actually much higher.

## Tests First

Create the file `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/test_audit_baseline.py`.

These tests import directly from the audit script and validate the new behavior without requiring actual catalog data on disk.

```python
"""Tests for audit baseline correction — actionable vs non-actionable refs.

Validates that:
- UNKNOWN_KIND refs are marked actionable=False with correct reason
- Known-Kind refs remain actionable=True
- Audit output shows dual metrics: Actionable Coverage and Total Ref Coverage
- REF_TUPLE_UNRESOLVABLE refs don't inflate the actionable gap count
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add scripts/ to sys.path so we can import the audit module directly
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from edge_detection_audit import ExpectedRef, generate_report


# --- Fixtures ---

def _make_expected_ref(
    *,
    service: str = "test-svc",
    kind: str = "TestKind",
    field_path: str = "spec.ref",
    field_name: str = "ref",
    expected_target: str = "Secret",
    detection_method: str = "suffix_pattern",
    depth: int = 2,
    confidence: str = "high",
    actionable: bool = True,
    non_actionable_reason: str = "",
) -> ExpectedRef:
    """Helper to construct ExpectedRef with new fields."""
    return ExpectedRef(
        service=service,
        kind=kind,
        field_path=field_path,
        field_name=field_name,
        expected_target=expected_target,
        detection_method=detection_method,
        depth=depth,
        confidence=confidence,
        actionable=actionable,
        non_actionable_reason=non_actionable_reason,
    )


# --- Test: UNKNOWN_KIND refs marked actionable=False ---

def test_unknown_kind_refs_marked_non_actionable():
    """UNKNOWN_KIND target from ref_tuple should have actionable=False."""
    ref = _make_expected_ref(
        expected_target="UNKNOWN_KIND",
        detection_method="ref_tuple",
        actionable=False,
        non_actionable_reason="ref_tuple_no_kind_enum",
    )
    assert ref.actionable is False
    assert ref.non_actionable_reason == "ref_tuple_no_kind_enum"


def test_known_kind_refs_remain_actionable():
    """Refs with concrete target Kinds should have actionable=True (default)."""
    ref = _make_expected_ref(expected_target="Secret")
    assert ref.actionable is True
    assert ref.non_actionable_reason == ""


def test_default_actionable_is_true():
    """The default value for actionable should be True."""
    ref = ExpectedRef(
        service="s", kind="K", field_path="spec.x", field_name="x",
        expected_target="ConfigMap", detection_method="suffix_pattern",
        depth=1, confidence="high",
    )
    assert ref.actionable is True
    assert ref.non_actionable_reason == ""


# --- Test: Audit report contains dual metrics ---

def test_report_contains_actionable_coverage_column():
    """The summary table should have an 'Actionable' column."""
    expected = [
        _make_expected_ref(field_path="spec.secretRef", expected_target="Secret"),
        _make_expected_ref(
            field_path="spec.targetRef",
            expected_target="UNKNOWN_KIND",
            detection_method="ref_tuple",
            actionable=False,
            non_actionable_reason="ref_tuple_no_kind_enum",
        ),
    ]
    detected = {}  # No detected refs — both will be "missing"
    # Build missing edges for the non-detected refs
    from edge_detection_audit import MissingEdge
    missing = [
        MissingEdge(
            service="test-svc", kind="TestKind",
            field_path="spec.secretRef", field_name="secretRef",
            expected_target="Secret", detection_method="suffix_pattern",
            depth=2, root_cause="test", root_cause_category="DETECTOR_MISS",
            suggested_detector="test", suggested_fix="test",
        ),
        MissingEdge(
            service="test-svc", kind="TestKind",
            field_path="spec.targetRef", field_name="targetRef",
            expected_target="UNKNOWN_KIND", detection_method="ref_tuple",
            depth=2, root_cause="test", root_cause_category="REF_TUPLE_UNRESOLVABLE",
            suggested_detector="test", suggested_fix="test",
        ),
    ]
    report = generate_report(expected, detected, missing)
    # The report should contain both "Actionable" and "Total" in the header row
    assert "Actionable" in report
    assert "Total" in report


def test_report_actionable_rate_excludes_unknown_kind():
    """Actionable coverage rate should not count UNKNOWN_KIND refs in its denominator."""
    # 1 actionable ref (Secret, matched), 1 non-actionable (UNKNOWN_KIND, missing)
    actionable_ref = _make_expected_ref(
        field_path="spec.secretRef", expected_target="Secret",
    )
    non_actionable_ref = _make_expected_ref(
        field_path="spec.targetRef",
        expected_target="UNKNOWN_KIND",
        detection_method="ref_tuple",
        actionable=False,
        non_actionable_reason="ref_tuple_no_kind_enum",
    )
    expected = [actionable_ref, non_actionable_ref]
    # The actionable ref IS detected
    from edge_detection_audit import DetectedRef
    detected = {
        "TestKind": [DetectedRef(
            kind="TestKind", field_path="spec.secretRef",
            target_kind="Secret", detection_source="ref_detector:detect_ref",
            confidence=0.9,
        )]
    }
    # Only the non-actionable one is "missing"
    from edge_detection_audit import MissingEdge
    missing = [
        MissingEdge(
            service="test-svc", kind="TestKind",
            field_path="spec.targetRef", field_name="targetRef",
            expected_target="UNKNOWN_KIND", detection_method="ref_tuple",
            depth=2, root_cause="unresolvable", root_cause_category="REF_TUPLE_UNRESOLVABLE",
            suggested_detector="N/A", suggested_fix="N/A",
        ),
    ]
    report = generate_report(expected, detected, missing)
    # Actionable rate should be 100% (1/1 actionable matched)
    # Total rate should be 50% (1/2 total matched)
    assert "100.0%" in report
    assert "50.0%" in report


# --- Test: extract_expected_refs marks UNKNOWN_KIND correctly ---

def test_extract_expected_refs_marks_unknown_kind():
    """When ref_tuple produces UNKNOWN_KIND, the ExpectedRef should be non-actionable.

    This tests the extract_expected_refs function with a minimal schema
    containing a ref tuple with no kind enum.
    """
    from edge_detection_audit import extract_expected_refs

    # Minimal spec with one Kind having a ref tuple with no kind enum
    spec = {
        "components": {
            "schemas": {
                "MyResource": {
                    "properties": {
                        "spec": {
                            "type": "object",
                            "properties": {
                                "targetRef": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "namespace": {"type": "string"},
                                        "kind": {"type": "string"},
                                        "apiGroup": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }
    refs = extract_expected_refs("test-svc", spec)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.expected_target == "UNKNOWN_KIND"
    assert ref.actionable is False
    assert ref.non_actionable_reason == "ref_tuple_no_kind_enum"


def test_extract_expected_refs_known_kind_is_actionable():
    """When ref_tuple resolves a known Kind from enum, the ExpectedRef should be actionable."""
    from edge_detection_audit import extract_expected_refs, KNOWN_KINDS

    # Pick a known kind for the enum value
    known_kind = "Secret"
    assert known_kind in KNOWN_KINDS

    spec = {
        "components": {
            "schemas": {
                "MyResource": {
                    "properties": {
                        "spec": {
                            "type": "object",
                            "properties": {
                                "targetRef": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "namespace": {"type": "string"},
                                        "kind": {
                                            "type": "string",
                                            "enum": [known_kind],
                                        },
                                        "apiGroup": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }
    refs = extract_expected_refs("test-svc", spec)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.expected_target == known_kind
    assert ref.actionable is True
    assert ref.non_actionable_reason == ""
```

## Implementation Details

### 1. Add `actionable` and `non_actionable_reason` to `ExpectedRef`

In `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/scripts/edge_detection_audit.py`, modify the `ExpectedRef` dataclass (currently at line 117):

```python
@dataclass
class ExpectedRef:
    service: str
    kind: str
    field_path: str
    field_name: str
    expected_target: str
    detection_method: str
    depth: int
    confidence: str
    parent_path: str = ""
    has_excluded_sibling_kind: bool = False
    actionable: bool = True                  # NEW
    non_actionable_reason: str = ""          # NEW
```

Both fields have defaults, so all existing code that constructs `ExpectedRef` continues to work unchanged (they default to `actionable=True`).

### 2. Mark UNKNOWN_KIND refs as non-actionable in `extract_expected_refs`

In the `extract_expected_refs` function, locate the method 4 (ref_tuple) block. Currently at approximately line 465, the code does:

```python
target_str = tuple_target or "UNKNOWN_KIND"
results.append(ExpectedRef(
    service=service, kind=kind, field_path=fpath,
    field_name=fname, expected_target=target_str,
    detection_method="ref_tuple", depth=fdepth,
    confidence="high" if tuple_target else "medium",
    parent_path=parent_path,
))
```

Change this to pass the new fields when the target is unresolvable:

```python
target_str = tuple_target or "UNKNOWN_KIND"
is_actionable = tuple_target is not None
results.append(ExpectedRef(
    service=service, kind=kind, field_path=fpath,
    field_name=fname, expected_target=target_str,
    detection_method="ref_tuple", depth=fdepth,
    confidence="high" if tuple_target else "medium",
    parent_path=parent_path,
    actionable=is_actionable,
    non_actionable_reason="" if is_actionable else "ref_tuple_no_kind_enum",
))
```

This is the **only** place in the current codebase that produces `UNKNOWN_KIND` targets. All other detection methods (suffix_pattern, kind_name_pattern, secret_key_selector, parent_kind_name, description_ref) resolve to concrete Kind names.

### 3. Update `generate_report` to show dual metrics

The summary table (section 1 of the report) currently has columns: `Service | Kinds | Expected Refs | Detected | Missing | Rate`. Change this to include both actionable and total coverage.

The new table header:

```
| Service | Kinds | Expected | Actionable | Detected | Missing | Actionable Rate | Total Rate |
```

For each service row:
- **Expected**: total expected refs (same as before)
- **Actionable**: count of expected refs where `actionable is True`
- **Detected**: matched count (same as before)
- **Missing**: total missing count (same as before)
- **Actionable Rate**: `(actionable_matched / actionable_expected) * 100` -- where `actionable_matched` counts matched refs that are actionable
- **Total Rate**: `(total_matched / total_expected) * 100` -- same calculation as current `Rate`

Implementation approach in `generate_report` (around line 750):

For each service, compute:
- `svc_actionable = [r for r in svc_expected if r.actionable]`
- `svc_actionable_missing = [m for m in svc_missing if not any(r.actionable is False and r.field_path == m.field_path and r.kind == m.kind for r in svc_expected)]` -- but more practically, count the missing edges whose corresponding `ExpectedRef` was actionable

A cleaner approach: build a set of `(kind, field_path)` keys for non-actionable expected refs. When counting actionable missing, exclude missing edges whose `(kind, field_path)` is in the non-actionable set.

```python
# Build non-actionable set for filtering
non_actionable_keys: set[tuple[str, str]] = {
    (r.kind, r.field_path) for r in expected if not r.actionable
}

# In the per-service loop:
svc_actionable_expected = [r for r in svc_expected if r.actionable]
svc_actionable_missing = [
    m for m in svc_missing
    if (m.kind, m.field_path) not in non_actionable_keys
]
actionable_matched = len(svc_actionable_expected) - len(svc_actionable_missing)
actionable_rate = (actionable_matched / len(svc_actionable_expected) * 100) if svc_actionable_expected else 0
```

### 4. Update PIPELINE_MAX_DEPTH reference if needed

The current script has `PIPELINE_MAX_DEPTH = 8` at line 97. When section-10 (depth decay) lands and raises the pipeline's max_depth to 12, this constant should be updated to match. However, since section-13 has no dependency on section-10, leave it at 8 for now. The audit script's own walking is unlimited-depth regardless; this constant is only used for root cause analysis ("field at depth X > max_depth Y").

### 5. No changes to `run_audit` matching logic

The `run_audit` function's matching logic (comparing expected vs detected via `(kind, field_path)` keys) does not change. Non-actionable refs that are unmatched still appear in the `missing` list. The only difference is in **reporting**: the new dual columns let readers see the distinction.

### 6. Update the TOTAL row

The TOTAL row at the bottom of the summary table should also show dual rates:

```python
total_actionable = [r for r in expected if r.actionable]
total_actionable_missing = [
    m for m in missing
    if (m.kind, m.field_path) not in non_actionable_keys
]
total_actionable_matched = len(total_actionable) - len(total_actionable_missing)
total_actionable_rate = (total_actionable_matched / len(total_actionable) * 100) if total_actionable else 0
total_rate = (total_matched / len(expected) * 100) if expected else 0
```

## Verification

After implementation, run:

```bash
cd /Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi
uv run pytest tests/generation/crd/test_audit_baseline.py -v
```

All 7 tests should pass. Then run the full CRD test suite to confirm no regressions:

```bash
uv run pytest tests/generation/crd/ -v
```

Optionally, run the audit script itself to see the new dual-column report:

```bash
cd /Users/morgan/GitRepo/k3s-automated-installers
python3 platform-tools/idi/scripts/edge_detection_audit.py
```

The expected impact on the report: ArgoCD's **Actionable Rate** should jump from 53.5% to approximately 72% (removing ~45 `UNKNOWN_KIND` refs from the actionable denominator), while **Total Rate** stays at 53.5%. The overall TOTAL actionable rate should rise from 92.2% to approximately 95%+.

## Implementation Notes

- **Code review fix applied:** `non_actionable_keys` set uses `(service, kind, field_path)` 3-tuple (not just `(kind, field_path)`) to prevent cross-service bleed when different services define the same Kind name.
- **Test file:** 247 lines (7 tests), all passing.
- **No regressions:** Full CRD test suite (1063 tests) passes.

## Summary of Changes (Actual)

| Change | Location | Lines |
|--------|----------|:---:|
| Add `actionable: bool = True` field to `ExpectedRef` | `edge_detection_audit.py` line ~129 | 1 |
| Add `non_actionable_reason: str = ""` field to `ExpectedRef` | `edge_detection_audit.py` line ~130 | 1 |
| Set `actionable=False` for UNKNOWN_KIND in method 4 | `edge_detection_audit.py` line ~467 | 4 |
| Dual-column summary table in `generate_report` (service-scoped keys) | `edge_detection_audit.py` lines ~755-796 | ~40 |
| New test file | `tests/generation/crd/test_audit_baseline.py` | 247 |
Now I have all the necessary context. Let me produce the section content.

# Section 09: Credential Suppression

## Overview

Add a credential exclusion suppression rule to `ref_detector.py` that prevents string-typed credential value fields (password, token, apiKey, clientSecret, bearerToken, etc.) from being falsely classified as Kind references. This is critical because the new fuzzy_resolve mechanism (section-05/06) will match credential fields that happen to share names with known Kinds or plurals (e.g., `token` matching a Token Kind, `secret` matching Secret). String credential fields hold opaque values, not resource names, and emitting edges for them creates false dependencies in the topological sort.

**Precision > Recall constraint:** A false edge from a credential field creates a phantom cycle in Kahn's algorithm, deadlocking deployment. Suppressing a credential field that happens to be a legitimate reference is recoverable via the semantic field map (section-07) or structural detectors -- but a false positive is not.

**No dependencies on other sections.** This section is fully parallelizable (Batch 1). The credential rule is appended to the existing `_SUPPRESSION_RULE_LIST` in `ref_detector.py`, which already contains 3 rules.

## File Paths

- **Modified:** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/crd/ref_detector.py`
- **Modified (tests):** `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/test_suppress_false_positives.py`

## Tests (Write First)

Add a new test class to the existing `test_suppress_false_positives.py` file. The tests follow the same patterns already established in that file: use the `_make_field()` and `_make_cf()` helpers, call `suppress_false_positives()`, and assert on the result's `role`, `confidence`, and `detection_source`.

### Test class: `TestRule4CredentialExclusion`

Located in `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/tests/generation/crd/test_suppress_false_positives.py`.

```python
class TestRule4CredentialExclusion:
    """Rule 4: credential value fields on string-typed leaves are suppressed."""

    def test_password_string_field_suppressed(self):
        """'password' string field -> suppressed."""
        field = _make_field("password", schema={"type": "string"})
        cf = _make_cf(field_path="spec.password", target_kind="Password")
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"
        assert results[0].confidence == 0.1
        assert "credential_value_field" in results[0].detection_source

    def test_client_secret_string_field_suppressed(self):
        """'clientSecret' string field -> suppressed."""
        field = _make_field("clientSecret", schema={"type": "string"})
        cf = _make_cf(field_path="spec.clientSecret", target_kind="Secret")
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"
        assert "credential_value_field" in results[0].detection_source

    def test_bearer_token_string_field_suppressed(self):
        """'bearerToken' string field -> suppressed."""
        field = _make_field("bearerToken", schema={"type": "string"})
        cf = _make_cf(field_path="spec.bearerToken", target_kind="Token")
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"

    def test_access_key_id_string_field_suppressed(self):
        """'accessKeyId' string field -> suppressed."""
        field = _make_field("accessKeyId", schema={"type": "string"})
        cf = _make_cf(field_path="spec.accessKeyId")
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"

    def test_api_key_string_field_suppressed(self):
        """'apiKey' string field -> suppressed."""
        field = _make_field("apiKey", schema={"type": "string"})
        cf = _make_cf(field_path="spec.apiKey")
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"

    def test_client_secret_ref_object_not_suppressed(self):
        """'clientSecretRef' object field -> NOT suppressed (object type references a resource)."""
        field = _make_field("clientSecretRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
            },
        })
        cf = _make_cf(
            field_path="spec.clientSecretRef",
            target_kind="Secret",
            field_type="object",
        )
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "input_ref"

    def test_token_secret_ref_object_not_suppressed(self):
        """'tokenSecretRef' object field -> NOT suppressed (object type)."""
        field = _make_field("tokenSecretRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "key": {"type": "string"},
            },
        })
        cf = _make_cf(
            field_path="spec.tokenSecretRef",
            target_kind="Secret",
            field_type="object",
        )
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "input_ref"
```

### Key test design decisions

1. **String-only guard:** The rule ONLY suppresses `type: string` fields. Object-typed fields like `clientSecretRef` and `tokenSecretRef` are legitimate structural references to Kubernetes Secrets (they contain `name`/`namespace`/`key` sub-fields). The tests explicitly verify this distinction.

2. **Rule name:** The suppression rule is named `"credential_value_field"` to distinguish it from the existing 3 rules. This name appears in the `detection_source` string as `"suppressed:{original}:credential_value_field"`.

3. **The tests use the same `_make_field` and `_make_cf` helpers** already defined at the top of `test_suppress_false_positives.py`. No new helpers are needed.

## Implementation

### Step 1: Add the credential value regex constant

In `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/idi/generation/crd/ref_detector.py`, add a compiled regex pattern near the other constants at module level. This regex is derived from the OWASP-based pattern already used in the REST pipeline (`dep_adapters/target_inference.py` line 40-44) but adapted for CRD CamelCase field naming conventions:

```python
_CREDENTIAL_VALUE_RE: re.Pattern = re.compile(
    r"(?i)^("
    r"password|passwd|"
    r"client[_-]?secret|"
    r"access[_-]?token|refresh[_-]?token|bearer[_-]?token|id[_-]?token|"
    r"token|"
    r"api[_-]?key|apikey|"
    r"secret[_-]?key|"
    r"access[_-]?key[_-]?id|secret[_-]?access[_-]?key|"
    r"authorization"
    r")$"
)
```

Key points about the regex:
- Case-insensitive (`(?i)`) to handle both `password` and `Password`.
- Anchored (`^...$`) to match the full field name, not a substring. This prevents false suppression of fields like `passwordSecretRef` (which would be an object field anyway, guarded by the type check) or `tokenBucketRef`.
- Uses `[_-]?` separators for compound names (`clientSecret`, `client_secret`, `client-secret`) since CRD field names may use any convention.
- Does NOT match `Ref`-suffixed fields (`secretRef`, `tokenRef`) -- those are structural references, not credential values. The anchored regex ensures `bearerTokenRef` does not match because `Ref` is appended.

### Step 2: Add the suppression rule predicate function

Add the new predicate function before the `_SUPPRESSION_RULE_LIST` definition:

```python
def _rule_credential_value_field(
    field: WalkedField,
    classification: ClassifiedField,
) -> bool:
    """Rule 4: Suppress string credential value fields.

    String fields whose name matches credential patterns (password, token,
    apiKey, clientSecret, bearerToken, etc.) hold opaque values, not
    resource names. Object-typed fields are exempt -- those are typically
    SecretKeySelector-shaped refs (e.g., tokenSecretRef).
    """
    if field.schema.get("type") != "string":
        return False
    return bool(_CREDENTIAL_VALUE_RE.match(field.name))
```

### Step 3: Register the rule in `_SUPPRESSION_RULE_LIST`

Append the new rule tuple to the existing list:

```python
_SUPPRESSION_RULE_LIST: list[tuple[Any, str]] = [
    (_rule_target_kind_not_at_word_boundary, "target_kind_not_at_word_boundary"),
    (_rule_kind_collision_no_structural_context, "kind_collision_no_structural_context"),
    (_rule_nested_metadata_self_reference, "nested_metadata_self_reference"),
    (_rule_credential_value_field, "credential_value_field"),  # NEW
]
```

The rule is appended at the end (position 4). Rule ordering matters because "first matching rule wins" in `suppress_false_positives()`. Credential fields may also match earlier rules (e.g., Rule 1 might fire if `target_kind` is not a word boundary token in the field name). Placing the credential rule last means it only fires as a safety net when the earlier rules did not already suppress the classification. This is correct: if an earlier rule already catches a credential field, the suppression still happens with the more specific rule name. If none of the earlier rules fire (e.g., the field name happens to contain the target kind as a valid token), the credential rule provides the final guard.

### How the suppression works at runtime

The `suppress_false_positives()` function is already called as the final step of `classify_walked_field()` (line ~1754 in the current code). When it runs:

1. For each `ClassifiedField` in the input list, it iterates through `_SUPPRESSION_RULE_LIST`.
2. If `_rule_credential_value_field(field, classification)` returns `True`:
   - The classification's `role` is changed to `"config_field"`.
   - Its `confidence` is set to `0.1` (below the 0.7 emission floor).
   - Its `detection_source` is updated to `"suppressed:{original_source}:credential_value_field"`.
3. The item remains in the output list (it is downgraded, not removed), preserving audit trail visibility.

No changes are needed to `suppress_false_positives()` itself -- the existing loop handles the new rule automatically.

### Credential field names covered

The regex covers these CRD field names commonly found across enterprise CRD schemas (cert-manager, external-secrets, Strimzi, Istio):

| Field Name | Suppressed? | Rationale |
|---|---|---|
| `password` | Yes | Opaque credential value |
| `clientSecret` | Yes | OAuth client secret value |
| `bearerToken` | Yes | Auth token value |
| `accessToken` | Yes | OAuth access token value |
| `refreshToken` | Yes | OAuth refresh token value |
| `idToken` | Yes | OIDC ID token value |
| `apiKey` | Yes | API key value |
| `accessKeyId` | Yes | AWS-style access key ID |
| `secretAccessKey` | Yes | AWS-style secret key |
| `secretKey` | Yes | Generic secret key value |
| `authorization` | Yes | HTTP Authorization header value |
| `clientSecretRef` | **No** | Object ref to a Secret (has `name`/`key` sub-fields) |
| `tokenSecretRef` | **No** | Object ref to a Secret |
| `passwordSecretRef` | **No** | Object ref to a Secret |
| `secretName` | **No** | String reference to a Secret resource name |
| `tokenBucketRef` | **No** | Not matched by anchored regex |

The critical distinction is: fields ending in `Ref`, `Name`, or `Key` that reference resource names are NOT matched because the regex is anchored and those suffixes change the full field name. Fields like `secretName` reference a Secret by name (legitimate ref), while `clientSecret` holds the actual secret value (not a ref).

## Verification

Run from `/Users/morgan/GitRepo/k3s-automated-installers/platform-tools/idi/`:

```bash
uv run pytest tests/generation/crd/test_suppress_false_positives.py -v
```

Expected: All existing tests pass unchanged (the new rule does not interfere with existing suppression behavior), plus all new `TestRule4CredentialExclusion` tests pass.

To verify no regressions across the full CRD test suite:

```bash
uv run pytest tests/generation/crd/ -v
```

## Implementation Notes

### Deviations from plan

- **Tests `test_access_key_id` and `test_api_key`:** Plan used default `target_kind="Secret"`, but Rule 1 (`target_kind_not_at_word_boundary`) preempted Rule 4. Fixed by using `target_kind="Access"` and `target_kind="Key"` respectively so Rule 4 is actually exercised. Added `detection_source` assertions.

### Additional tests added (code review)

- `test_secret_name_not_suppressed` — confirms `secretName` passes through (string reference, not credential)
- `test_refresh_token_string_field_suppressed` — verifies `refreshToken` suppression
- `test_secret_access_key_string_field_suppressed` — verifies `secretAccessKey` suppression
- `test_credential_field_without_type_not_suppressed` — confirms `password` with `schema={}` is NOT suppressed

### Final test count

- 35 tests in `test_suppress_false_positives.py` (was 24 before this section)
- 1029 tests in full CRD suite, all passing
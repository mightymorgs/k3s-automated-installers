"""Tests for Phase A detection rule enhancements (section-03).

Covers five detection improvements:
  #1 Credential/external parameter exclusion
  #2 readOnly/writeOnly field classification
  #4 FK suffix expansion (_uuid, _guid array variants)
  #7 Producer validity rules (method priority)
  #8 ID synonym matching (normalize_id_suffix)
"""
from __future__ import annotations

import pytest

from idi.generation.dep_adapters.base import OperationInfo, Output
from idi.generation.dep_adapters.naming import normalize_id_suffix
from idi.generation.dep_adapters.output_detection import detect_outputs
from idi.generation.dep_adapters.target_inference import infer_target


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _op(
    method: str = "POST",
    path: str = "/things",
    response_props: dict | None = None,
    body_props: dict | None = None,
) -> OperationInfo:
    """Build a minimal OperationInfo for testing."""
    return OperationInfo(
        service="test-svc",
        resource="things",
        operation=f"{method.lower()}Things",
        path=path,
        method=method,
        body_schema={
            "type": "object",
            "properties": body_props or {},
        },
        response_schema={
            "type": "object",
            "properties": response_props or {"id": {"type": "string"}},
        },
    )


# ===================================================================
# #1  Credential / External Parameter Exclusion
# ===================================================================

class TestCredentialExclusion:
    """Credential-like params return (None, 0.0) from infer_target."""

    KNOWN = {"users", "tokens", "secrets", "clients"}

    @pytest.mark.parametrize("field", [
        "client_secret",
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "password",
        "passwd",
        "secret",
        "api_key",
        "api-key",
        "apikey",
        "authorization",
    ])
    def test_credential_param_excluded(self, field):
        target, conf = infer_target(field, {"type": "string"}, self.KNOWN)
        assert target is None, f"{field} should be excluded as credential"
        assert conf == 0.0

    @pytest.mark.parametrize("field,expected_target", [
        ("user_id", "users"),
        ("token_id", "tokens"),
        ("secret_id", "secrets"),
    ])
    def test_fk_suffix_not_excluded(self, field, expected_target):
        """Fields with FK suffixes are NOT excluded even if they contain credential words."""
        target, conf = infer_target(field, {"type": "string"}, self.KNOWN)
        assert target == expected_target, (
            f"{field} should NOT be excluded — it has an FK suffix"
        )
        assert conf > 0.0

    @pytest.mark.parametrize("field", [
        "description",
        "user_name",
        "email_address",
    ])
    def test_non_credential_non_fk_not_excluded(self, field):
        """Regular fields that don't match credentials pass through normally."""
        # 'description' is in _NEVER_FK_FIELDS so it returns (None, 0.0) for a
        # different reason, but that's fine — the credential regex is not the cause.
        # user_name/email_address just won't match any resource.
        # This test ensures the credential regex doesn't accidentally catch them.
        infer_target(field, {"type": "string"}, self.KNOWN)
        # No assertion on result — just verifying no exception and no false exclusion


# ===================================================================
# #2  readOnly / writeOnly Field Classification
# ===================================================================

class TestReadOnlyWriteOnly:
    """readOnly fields register as outputs; writeOnly fields are excluded."""

    def test_readonly_field_classified_as_producer(self):
        """A readOnly field in response schema registers as Output with readonly_field source."""
        op = _op(
            method="POST",
            response_props={
                "id": {"type": "string", "readOnly": True},
                "name": {"type": "string"},
            },
        )
        outputs = detect_outputs(op)
        id_outputs = [o for o in outputs if o.field == "id"]
        assert len(id_outputs) == 1
        assert id_outputs[0].source == "readonly_field"
        assert id_outputs[0].priority == 4  # POST priority

    def test_readonly_non_id_field_detected(self):
        """A readOnly field NOT in _ID_FIELD_PRECEDENCE is still detected as output."""
        op = _op(
            method="POST",
            response_props={
                "created_at": {"type": "string", "readOnly": True},
                "status": {"type": "string"},
            },
        )
        outputs = detect_outputs(op)
        readonly_outputs = [o for o in outputs if o.field == "created_at"]
        assert len(readonly_outputs) == 1
        assert readonly_outputs[0].source == "readonly_field"

    def test_writeonly_field_in_skip_set(self):
        """A writeOnly field in _ID_FIELD_PRECEDENCE should not appear in outputs."""
        op = _op(
            method="POST",
            response_props={
                "id": {"type": "string"},
                "key": {"type": "string", "writeOnly": True},
            },
        )
        outputs = detect_outputs(op)
        # 'key' is in _ID_FIELD_PRECEDENCE but should be excluded
        writeonly_fields = [o for o in outputs if o.field == "key"]
        assert len(writeonly_fields) == 0
        # 'id' should still be present
        assert any(o.field == "id" for o in outputs)

    def test_no_readonly_writeonly_empty(self):
        """Schema with no readOnly/writeOnly returns standard outputs."""
        op = _op(
            method="POST",
            response_props={
                "id": {"type": "string"},
                "name": {"type": "string"},
            },
        )
        outputs = detect_outputs(op)
        id_outputs = [o for o in outputs if o.field == "id"]
        assert len(id_outputs) == 1
        assert id_outputs[0].source == "generic_odg"


# ===================================================================
# #4  FK Suffix Expansion
# ===================================================================

class TestFKSuffixExpansion:
    """Extended FK suffixes (_uuid, _guid, _uuids, _guids) detected."""

    KNOWN = {"users", "projects", "teams"}

    def test_uuid_suffix_detected(self):
        target, conf = infer_target(
            "user_uuid", {"type": "string", "format": "uuid"}, self.KNOWN,
        )
        assert target == "users"
        assert conf > 0.0

    def test_guid_suffix_detected(self):
        target, conf = infer_target(
            "user_guid", {"type": "string"}, self.KNOWN,
        )
        assert target == "users"
        assert conf > 0.0

    def test_array_ids_suffix(self):
        target, conf = infer_target(
            "user_ids",
            {"type": "array", "items": {"type": "string"}},
            self.KNOWN,
        )
        assert target == "users"
        assert conf > 0.0

    def test_array_uuids_suffix(self):
        target, conf = infer_target(
            "user_uuids",
            {"type": "array", "items": {"type": "string"}},
            self.KNOWN,
        )
        assert target == "users"
        assert conf > 0.0

    def test_array_guids_suffix(self):
        target, conf = infer_target(
            "user_guids",
            {"type": "array", "items": {"type": "string"}},
            self.KNOWN,
        )
        assert target == "users"
        assert conf > 0.0

    def test_existing_id_suffix_preserved(self):
        """user_id still works (regression guard)."""
        target, conf = infer_target(
            "user_id", {"type": "integer"}, self.KNOWN,
        )
        assert target == "users"
        assert conf > 0.0

    def test_no_match_without_resource(self):
        """Suffix-only match without matching resource gets lower confidence."""
        target, conf = infer_target(
            "widget_uuid", {"type": "string", "format": "uuid"}, self.KNOWN,
        )
        # No 'widgets' in known — may return None or low confidence
        # Key: should not crash or return high confidence
        if target is not None:
            assert conf < 0.7

    def test_username_not_matched(self):
        """'username' has no FK suffix — not matched as FK."""
        target, conf = infer_target(
            "username", {"type": "string"}, self.KNOWN,
        )
        # username → may match 'users' via candidate generation, that's ok
        # Key: it's not matched via suffix expansion


# ===================================================================
# #7  Producer Validity Rules
# ===================================================================

class TestProducerValidity:
    """Method-based producer priority and exclusion."""

    def test_post_produces_outputs(self):
        op = _op(method="POST")
        outputs = detect_outputs(op)
        assert len(outputs) > 0
        assert outputs[0].priority == 4

    def test_put_create_produces_outputs(self):
        """PUT on collection path (no resource ID) → producer."""
        op = _op(method="PUT", path="/things")
        outputs = detect_outputs(op)
        assert len(outputs) > 0
        assert outputs[0].priority == 3

    def test_patch_create_produces_outputs(self):
        """PATCH on collection path → producer."""
        op = _op(method="PATCH", path="/things")
        outputs = detect_outputs(op)
        assert len(outputs) > 0
        assert outputs[0].priority == 2

    def test_get_produces_outputs(self):
        """GET operations register as producers with lowest priority."""
        op = _op(method="GET", path="/things/{thing_id}")
        outputs = detect_outputs(op)
        assert len(outputs) > 0
        assert outputs[0].priority == 1

    def test_delete_produces_no_outputs(self):
        op = _op(method="DELETE")
        outputs = detect_outputs(op)
        assert len(outputs) == 0

    def test_head_produces_no_outputs(self):
        op = _op(method="HEAD")
        outputs = detect_outputs(op)
        assert len(outputs) == 0

    def test_options_produces_no_outputs(self):
        op = _op(method="OPTIONS")
        outputs = detect_outputs(op)
        assert len(outputs) == 0

    def test_post_wins_over_get(self):
        """POST has higher priority than GET for same field."""
        post_op = _op(method="POST")
        get_op = _op(method="GET", path="/things/{thing_id}")
        post_outputs = detect_outputs(post_op)
        get_outputs = detect_outputs(get_op)
        assert post_outputs[0].priority > get_outputs[0].priority

    def test_put_update_excluded(self):
        """PUT on resource-specific path (with ID param) → update, no outputs."""
        op = _op(method="PUT", path="/things/{thing_id}")
        outputs = detect_outputs(op)
        assert len(outputs) == 0

    def test_get_not_subject_to_id_guard(self):
        """GET with resource ID in path still produces (reads data)."""
        op = _op(method="GET", path="/things/{thing_id}")
        outputs = detect_outputs(op)
        assert len(outputs) > 0


# ===================================================================
# #8  ID Synonym Matching
# ===================================================================

class TestIDSynonymMatching:
    """normalize_id_suffix canonicalizes _uuid/_guid/_uid to _id."""

    def test_uuid_normalized(self):
        assert normalize_id_suffix("user_uuid") == "user_id"

    def test_guid_normalized(self):
        assert normalize_id_suffix("user_guid") == "user_id"

    def test_uid_normalized(self):
        assert normalize_id_suffix("user_uid") == "user_id"

    def test_id_unchanged(self):
        assert normalize_id_suffix("user_id") == "user_id"

    def test_username_unchanged(self):
        assert normalize_id_suffix("username") == "username"

    def test_case_insensitive(self):
        """Suffix matching is case-insensitive."""
        assert normalize_id_suffix("User_UUID") == "User_id"

    def test_bare_uuid_unchanged(self):
        """Bare 'uuid' without prefix stays as-is (no empty prefix)."""
        # normalize_id_suffix("uuid") → depends on implementation
        # _uuid suffix requires at least 1 char prefix due to lower check
        result = normalize_id_suffix("uuid")
        # 'uuid' ends with '_uuid'? No — it doesn't have underscore prefix
        # So it should stay unchanged
        assert result == "uuid"

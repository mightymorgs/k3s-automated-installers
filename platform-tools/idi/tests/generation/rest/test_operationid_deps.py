"""Tests for operationId convention mining adapter (section-10)."""
from __future__ import annotations

import pytest

from idi.generation.dep_adapters.base import Dependency, OperationInfo
from idi.generation.dep_adapters.operationid_deps import (
    OperationIdDepAdapter,
    _extract_targets,
    _split_words,
)


def _make_op(path: str = "/groups", method: str = "post",
             resource: str = "groups") -> OperationInfo:
    return OperationInfo(
        service="test",
        resource=resource,
        operation=f"{resource}/create",
        path=path,
        method=method,
        body_schema={},
        response_schema={},
    )


def _make_spec(path: str, method: str, operation_id: str | None) -> dict:
    op: dict = {}
    if operation_id is not None:
        op["operationId"] = operation_id
    return {"paths": {path: {method.lower(): op}}}


class TestSplitWords:
    """CamelCase/PascalCase/snake_case/kebab splitting."""

    def test_camel_case(self):
        assert _split_words("createGroupForUser") == ["create", "group", "for", "user"]

    def test_pascal_case(self):
        assert _split_words("AddUserToGroup") == ["add", "user", "to", "group"]

    def test_snake_case(self):
        assert _split_words("list_orders_by_customer") == ["list", "orders", "by", "customer"]

    def test_kebab_case(self):
        assert _split_words("get-user-groups") == ["get", "user", "groups"]

    def test_consecutive_uppercase(self):
        assert _split_words("getHTTPResponse") == ["get", "http", "response"]

    def test_single_word(self):
        assert _split_words("list") == ["list"]

    def test_empty(self):
        assert _split_words("") == []


class TestExtractTargets:
    """Preposition-based resource extraction."""

    def test_for_pattern(self):
        assert _extract_targets(["create", "group", "for", "user"]) == ["user"]

    def test_by_pattern(self):
        assert _extract_targets(["list", "orders", "by", "customer"]) == ["customer"]

    def test_to_pattern(self):
        assert _extract_targets(["add", "user", "to", "group"]) == ["user", "group"]

    def test_no_preposition(self):
        assert _extract_targets(["list", "users"]) == []

    def test_preposition_at_end(self):
        """Preposition with no following words yields nothing."""
        assert _extract_targets(["search", "for"]) == []

    def test_multi_word_target(self):
        """Words after preposition are joined as single resource."""
        targets = _extract_targets(["get", "items", "for", "shopping", "cart"])
        assert targets == ["shoppingcart"]


class TestOperationIdDepAdapter:
    """End-to-end adapter tests."""

    def setup_method(self):
        self.adapter = OperationIdDepAdapter()

    def test_create_group_for_user(self):
        """'createGroupForUser' → dep on 'users' resource."""
        op = _make_op(path="/groups", method="post", resource="groups")
        spec = _make_spec("/groups", "post", "createGroupForUser")
        known = {"users", "groups", "roles"}
        deps = self.adapter.detect_dependencies(op, spec, known)
        assert len(deps) == 1
        assert deps[0].target_resource == "users"
        assert deps[0].confidence == 0.5
        assert deps[0].source == "generic_odg:operationid"

    def test_add_user_to_group(self):
        """'addUserToGroup' → dep on resources that exist in known_resources."""
        op = _make_op(path="/group-members", method="post", resource="group-members")
        spec = _make_spec("/group-members", "post", "addUserToGroup")
        known = {"users", "groups", "group-members"}
        deps = self.adapter.detect_dependencies(op, spec, known)
        targets = {d.target_resource for d in deps}
        assert "users" in targets or "groups" in targets
        for d in deps:
            assert d.confidence == 0.5

    def test_list_orders_by_customer(self):
        """'listOrdersByCustomer' → dep on 'customers'."""
        op = _make_op(path="/orders", method="get", resource="orders")
        spec = _make_spec("/orders", "get", "listOrdersByCustomer")
        known = {"orders", "customers", "products"}
        deps = self.adapter.detect_dependencies(op, spec, known)
        assert len(deps) == 1
        assert deps[0].target_resource == "customers"

    def test_list_users_no_dep(self):
        """'listUsers' → no cross-resource dependency."""
        op = _make_op(path="/users", method="get", resource="users")
        spec = _make_spec("/users", "get", "listUsers")
        known = {"users", "groups"}
        deps = self.adapter.detect_dependencies(op, spec, known)
        assert deps == []

    def test_delete_user_no_dep(self):
        """'deleteUser' → no cross-resource dependency."""
        op = _make_op(path="/users/{id}", method="delete", resource="users")
        spec = _make_spec("/users/{id}", "delete", "deleteUser")
        known = {"users", "groups"}
        deps = self.adapter.detect_dependencies(op, spec, known)
        assert deps == []

    def test_no_pattern_no_dep(self):
        """'frobnicateWidget' → no recognized pattern → empty."""
        op = _make_op(path="/widgets", method="post", resource="widgets")
        spec = _make_spec("/widgets", "post", "frobnicateWidget")
        known = {"widgets", "gadgets"}
        deps = self.adapter.detect_dependencies(op, spec, known)
        assert deps == []

    def test_none_operation_id(self):
        """None operationId → empty list."""
        op = _make_op(path="/users", method="get", resource="users")
        spec = _make_spec("/users", "get", None)
        known = {"users"}
        deps = self.adapter.detect_dependencies(op, spec, known)
        assert deps == []

    def test_empty_operation_id(self):
        """Empty string operationId → empty list."""
        op = _make_op(path="/users", method="get", resource="users")
        spec = _make_spec("/users", "get", "")
        known = {"users"}
        deps = self.adapter.detect_dependencies(op, spec, known)
        assert deps == []

    def test_phantom_target_rejected(self):
        """Matched resource must exist in known_resources."""
        op = _make_op(path="/orders", method="post", resource="orders")
        spec = _make_spec("/orders", "post", "createOrderForCustomer")
        known = {"orders"}  # "customers" NOT in known
        deps = self.adapter.detect_dependencies(op, spec, known)
        assert deps == []

    def test_confidence_capped_at_half(self):
        """Confidence must be exactly 0.5."""
        op = _make_op(path="/groups", method="post", resource="groups")
        spec = _make_spec("/groups", "post", "createGroupForUser")
        known = {"users", "groups"}
        deps = self.adapter.detect_dependencies(op, spec, known)
        for d in deps:
            assert d.confidence == 0.5

    def test_source_string(self):
        """Source must be 'generic_odg:operationid'."""
        op = _make_op(path="/groups", method="post", resource="groups")
        spec = _make_spec("/groups", "post", "createGroupForUser")
        known = {"users", "groups"}
        deps = self.adapter.detect_dependencies(op, spec, known)
        for d in deps:
            assert d.source == "generic_odg:operationid"

    def test_matches_all_specs(self):
        """Universal adapter — matches returns True."""
        assert self.adapter.matches({}, "any-service") is True
        assert self.adapter.matches({"openapi": "3.0.0"}, "test") is True

    def test_priority_below_generic(self):
        """Priority lower than generic_odg (50), links (100), annotations (92)."""
        assert self.adapter.priority < 50
        assert self.adapter.priority < 100
        assert self.adapter.priority < 92

    def test_detect_outputs_empty(self):
        """operationId mining produces no outputs."""
        op = _make_op()
        spec = _make_spec("/groups", "post", "createGroupForUser")
        assert self.adapter.detect_outputs(op, spec) == []

    def test_self_resource_not_emitted(self):
        """Don't emit dep to current resource (self-ref)."""
        op = _make_op(path="/users", method="post", resource="users")
        spec = _make_spec("/users", "post", "createUserForUser")
        known = {"users", "groups"}
        deps = self.adapter.detect_dependencies(op, spec, known)
        # Should not include a dep targeting "users" (self)
        assert all(d.target_resource != "users" for d in deps)

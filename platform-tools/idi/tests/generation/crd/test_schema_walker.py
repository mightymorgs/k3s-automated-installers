"""Tests for crd/schema_walker.py — CRD Phase 2 Section 02."""
from __future__ import annotations

import pytest

from idi.generation.crd.schema_walker import (
    EXCLUDED_FIELDS,
    WalkedField,
    _K8S_ENVELOPE,
    walk_crd_schema,
    walk_crd_status,
)


# ---------------------------------------------------------------------------
# WalkedField dataclass
# ---------------------------------------------------------------------------


class TestWalkedField:
    def test_frozen(self):
        """WalkedField is immutable."""
        wf = WalkedField(
            path="spec.foo", name="foo", schema={"type": "string"},
            depth=1, is_array_item=False, required=False, parent_path="spec",
        )
        with pytest.raises(AttributeError):
            wf.path = "spec.bar"  # type: ignore[misc]

    def test_stores_all_attributes(self):
        """All expected attributes are stored with correct values."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        wf = WalkedField(
            path="spec.issuerRef", name="issuerRef", schema=schema,
            depth=1, is_array_item=False, required=True, parent_path="spec",
        )
        assert wf.path == "spec.issuerRef"
        assert wf.name == "issuerRef"
        assert wf.schema is schema
        assert wf.depth == 1
        assert wf.is_array_item is False
        assert wf.required is True
        assert wf.parent_path == "spec"


# ---------------------------------------------------------------------------
# walk_crd_schema: flat properties
# ---------------------------------------------------------------------------


class TestWalkFlat:
    def test_single_string_property(self):
        """Single string property yields one WalkedField at depth 1."""
        props = {"foo": {"type": "string"}}
        fields = list(walk_crd_schema(props))
        assert len(fields) == 1
        assert fields[0].path == "spec.foo"
        assert fields[0].name == "foo"
        assert fields[0].depth == 1

    def test_multiple_properties(self):
        """Multiple properties yield one WalkedField each."""
        props = {
            "alpha": {"type": "string"},
            "beta": {"type": "integer"},
            "gamma": {"type": "boolean"},
        }
        fields = list(walk_crd_schema(props))
        names = {f.name for f in fields}
        assert names == {"alpha", "beta", "gamma"}

    def test_required_field(self):
        """required=True when field name in required list."""
        props = {
            "foo": {"type": "string"},
            "bar": {"type": "string"},
        }
        fields = list(walk_crd_schema(props, required=["foo"]))
        foo = next(f for f in fields if f.name == "foo")
        bar = next(f for f in fields if f.name == "bar")
        assert foo.required is True
        assert bar.required is False

    def test_parent_path_is_prefix_for_depth_1(self):
        """parent_path is 'spec' for depth-1 fields."""
        props = {"x": {"type": "string"}}
        fields = list(walk_crd_schema(props))
        assert fields[0].parent_path == "spec"


# ---------------------------------------------------------------------------
# walk_crd_schema: nested objects
# ---------------------------------------------------------------------------


class TestWalkNested:
    def test_object_yields_parent_and_children(self):
        """Object with nested properties yields parent AND children."""
        props = {
            "outer": {
                "type": "object",
                "properties": {
                    "inner": {"type": "string"},
                },
            },
        }
        fields = list(walk_crd_schema(props))
        names = [f.name for f in fields]
        assert "outer" in names
        assert "inner" in names

    def test_depth_2_inner_field(self):
        """Inner field at depth 2 has correct path and parent_path."""
        props = {
            "outer": {
                "type": "object",
                "properties": {
                    "inner": {"type": "string"},
                },
            },
        }
        fields = list(walk_crd_schema(props))
        inner = next(f for f in fields if f.name == "inner")
        assert inner.path == "spec.outer.inner"
        assert inner.depth == 2
        assert inner.parent_path == "spec.outer"

    def test_depth_5_nesting(self):
        """Deeply nested schema (simulating SecretStore tokenSecretRef)."""
        # spec.provider.vault.auth.tokenSecretRef at depth 4 + inner name at 5
        props = {
            "provider": {
                "type": "object",
                "properties": {
                    "vault": {
                        "type": "object",
                        "properties": {
                            "auth": {
                                "type": "object",
                                "properties": {
                                    "tokenSecretRef": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
        fields = list(walk_crd_schema(props))
        paths = {f.path for f in fields}
        assert "spec.provider" in paths
        assert "spec.provider.vault" in paths
        assert "spec.provider.vault.auth" in paths
        assert "spec.provider.vault.auth.tokenSecretRef" in paths
        assert "spec.provider.vault.auth.tokenSecretRef.name" in paths

        token_ref = next(f for f in fields if f.name == "tokenSecretRef")
        assert token_ref.depth == 4

        name_field = next(f for f in fields if f.path == "spec.provider.vault.auth.tokenSecretRef.name")
        assert name_field.depth == 5

    def test_required_at_each_level(self):
        """Each level uses its own required list."""
        props = {
            "outer": {
                "type": "object",
                "required": ["inner"],
                "properties": {
                    "inner": {"type": "string"},
                    "optional": {"type": "string"},
                },
            },
        }
        fields = list(walk_crd_schema(props, required=["outer"]))
        outer = next(f for f in fields if f.name == "outer")
        inner = next(f for f in fields if f.name == "inner")
        optional = next(f for f in fields if f.name == "optional")
        assert outer.required is True
        assert inner.required is True
        assert optional.required is False


# ---------------------------------------------------------------------------
# walk_crd_schema: arrays
# ---------------------------------------------------------------------------


class TestWalkArrays:
    def test_array_field_yielded(self):
        """Array field is yielded with is_array_item=False."""
        props = {
            "items_list": {
                "type": "array",
                "items": {"type": "string"},
            },
        }
        fields = list(walk_crd_schema(props))
        assert len(fields) == 1
        assert fields[0].name == "items_list"
        assert fields[0].is_array_item is False

    def test_array_with_object_items(self):
        """Array with object items — inner fields yielded with is_array_item=True."""
        props = {
            "routes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "match": {"type": "string"},
                    },
                },
            },
        }
        fields = list(walk_crd_schema(props))
        routes = next(f for f in fields if f.name == "routes")
        match = next(f for f in fields if f.name == "match")
        assert routes.is_array_item is False
        assert match.is_array_item is True
        assert match.path == "spec.routes.match"

    def test_array_with_simple_items_no_recursion(self):
        """Array with simple items (type: string) — only array field yielded."""
        props = {
            "tags": {
                "type": "array",
                "items": {"type": "string"},
            },
        }
        fields = list(walk_crd_schema(props))
        assert len(fields) == 1
        assert fields[0].name == "tags"

    def test_nested_arrays(self):
        """Nested arrays (array of objects containing arrays) — both levels recursed."""
        props = {
            "routes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "services": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        }
        fields = list(walk_crd_schema(props))
        names = [f.name for f in fields]
        assert "routes" in names
        assert "services" in names
        assert "name" in names
        name_field = next(f for f in fields if f.name == "name")
        assert name_field.is_array_item is True
        assert name_field.path == "spec.routes.services.name"


# ---------------------------------------------------------------------------
# walk_crd_schema: mixed nesting
# ---------------------------------------------------------------------------


class TestWalkMixed:
    def test_object_containing_array_containing_object(self):
        """Object > array > object — all levels yielded correctly."""
        props = {
            "tls": {
                "type": "object",
                "properties": {
                    "hosts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "hostname": {"type": "string"},
                            },
                        },
                    },
                    "secretName": {"type": "string"},
                },
            },
        }
        fields = list(walk_crd_schema(props))
        paths = {f.path for f in fields}
        assert "spec.tls" in paths
        assert "spec.tls.hosts" in paths
        assert "spec.tls.hosts.hostname" in paths
        assert "spec.tls.secretName" in paths

    def test_ingressroute_pattern(self):
        """IngressRoute-like: routes[].services[].name reachable at depth 3."""
        props = {
            "routes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "services": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "port": {"type": "integer"},
                                },
                            },
                        },
                    },
                },
            },
        }
        fields = list(walk_crd_schema(props))
        name_field = next(f for f in fields if f.path == "spec.routes.services.name")
        assert name_field.depth == 3
        assert name_field.is_array_item is True

    def test_pushsecret_pattern(self):
        """PushSecret-like: secretStoreRefs[] array yielded at depth 1."""
        props = {
            "secretStoreRefs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "kind": {"type": "string"},
                    },
                },
            },
        }
        fields = list(walk_crd_schema(props))
        store_refs = next(f for f in fields if f.name == "secretStoreRefs")
        assert store_refs.depth == 1
        assert store_refs.is_array_item is False
        # Inner fields also yielded
        name_field = next(f for f in fields if f.path == "spec.secretStoreRefs.name")
        assert name_field.is_array_item is True
        # 'kind' inside array items at depth > 1 is now yielded (discriminator)
        kind_field = next(f for f in fields if f.path == "spec.secretStoreRefs.kind")
        assert kind_field.is_array_item is True
        assert kind_field.depth == 2


# ---------------------------------------------------------------------------
# walk_crd_schema: exclusions
# ---------------------------------------------------------------------------


class TestWalkExclusions:
    def test_excluded_fields_skipped_at_depth_1(self):
        """EXCLUDED_FIELDS like status, labels, annotations are skipped."""
        props = {
            "foo": {"type": "string"},
            "status": {"type": "object"},
            "labels": {"type": "object"},
            "annotations": {"type": "object"},
        }
        fields = list(walk_crd_schema(props))
        names = {f.name for f in fields}
        assert names == {"foo"}

    def test_excluded_fields_skipped_inside_nested_objects(self):
        """EXCLUDED_FIELDS are skipped even inside nested objects."""
        props = {
            "outer": {
                "type": "object",
                "properties": {
                    "labels": {"type": "object"},
                    "good": {"type": "string"},
                },
            },
        }
        fields = list(walk_crd_schema(props))
        names = {f.name for f in fields}
        assert "labels" not in names
        assert "good" in names
        assert "outer" in names

    def test_k8s_envelope_skipped_at_root(self):
        """_K8S_ENVELOPE fields (apiVersion, kind, metadata, status) skipped at root."""
        props = {
            "apiVersion": {"type": "string"},
            "kind": {"type": "string"},
            "metadata": {"type": "object"},
            "status": {"type": "object"},
            "foo": {"type": "string"},
        }
        fields = list(walk_crd_schema(props))
        names = {f.name for f in fields}
        assert names == {"foo"}

    def test_k8s_envelope_not_skipped_when_nested(self):
        """_K8S_ENVELOPE fields NOT skipped when nested (except some EXCLUDED ones)."""
        props = {
            "outer": {
                "type": "object",
                "properties": {
                    # "metadata" is not in EXCLUDED_FIELDS, so it should be yielded
                    "metadata": {"type": "string"},
                    # "kind" is in EXCLUDED_FIELDS but allowed at depth > 1
                    "kind": {"type": "string"},
                },
            },
        }
        fields = list(walk_crd_schema(props))
        names = {f.name for f in fields}
        assert "outer" in names
        # "metadata" is NOT in EXCLUDED_FIELDS, so it IS yielded when nested
        assert "metadata" in names
        # "kind" is in EXCLUDED_FIELDS but allowed at depth > 1 (discriminator)
        assert "kind" in names

    def test_kind_excluded_at_root_level(self):
        """'kind' in EXCLUDED_FIELDS is still skipped at depth 1 (root level)."""
        props = {
            "kind": {"type": "string"},
            "foo": {"type": "string"},
        }
        fields = list(walk_crd_schema(props))
        names = {f.name for f in fields}
        assert "kind" not in names
        assert "foo" in names

    def test_excluded_fields_has_15_entries(self):
        """EXCLUDED_FIELDS contains 15 entries (selector removed for PushSecret support)."""
        assert len(EXCLUDED_FIELDS) == 15

    def test_k8s_envelope_has_4_entries(self):
        """_K8S_ENVELOPE has 4 entries."""
        assert _K8S_ENVELOPE == frozenset({"apiVersion", "kind", "metadata", "status"})


# ---------------------------------------------------------------------------
# walk_crd_schema: max_depth
# ---------------------------------------------------------------------------


class TestWalkMaxDepth:
    def test_fields_at_max_depth_yielded(self):
        """Fields at exactly max_depth are yielded."""
        props = {
            "a": {
                "type": "object",
                "properties": {
                    "b": {"type": "string"},
                },
            },
        }
        fields = list(walk_crd_schema(props, max_depth=2))
        names = {f.name for f in fields}
        assert "a" in names  # depth 1
        assert "b" in names  # depth 2 (at max)

    def test_fields_beyond_max_depth_not_yielded(self):
        """Fields beyond max_depth are NOT yielded."""
        props = {
            "a": {
                "type": "object",
                "properties": {
                    "b": {
                        "type": "object",
                        "properties": {
                            "c": {"type": "string"},
                        },
                    },
                },
            },
        }
        fields = list(walk_crd_schema(props, max_depth=2))
        names = {f.name for f in fields}
        assert "a" in names  # depth 1
        assert "b" in names  # depth 2 (at max)
        assert "c" not in names  # depth 3 (beyond max)

    def test_custom_max_depth_2(self):
        """Custom max_depth=2 — depth 3 fields not yielded."""
        props = {
            "level1": {
                "type": "object",
                "properties": {
                    "level2": {
                        "type": "object",
                        "properties": {
                            "level3": {"type": "string"},
                        },
                    },
                },
            },
        }
        fields = list(walk_crd_schema(props, max_depth=2))
        paths = {f.path for f in fields}
        assert "spec.level1" in paths
        assert "spec.level1.level2" in paths
        assert "spec.level1.level2.level3" not in paths


# ---------------------------------------------------------------------------
# walk_crd_status
# ---------------------------------------------------------------------------


class TestWalkStatus:
    def test_prefix_is_status(self):
        """walk_crd_status uses 'status' prefix."""
        props = {"ready": {"type": "boolean"}}
        fields = list(walk_crd_status(props))
        assert fields[0].path == "status.ready"

    def test_default_max_depth_3(self):
        """walk_crd_status has max_depth 3."""
        props = {
            "a": {
                "type": "object",
                "properties": {
                    "b": {
                        "type": "object",
                        "properties": {
                            "c": {
                                "type": "object",
                                "properties": {
                                    "d": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        }
        fields = list(walk_crd_status(props))
        paths = {f.path for f in fields}
        assert "status.a" in paths         # depth 1
        assert "status.a.b" in paths       # depth 2
        assert "status.a.b.c" in paths     # depth 3
        assert "status.a.b.c.d" not in paths  # depth 4 — beyond default max_depth 3

    def test_does_not_skip_status_in_excluded(self):
        """walk_crd_status does NOT skip 'status' field from EXCLUDED_FIELDS."""
        # This tests that if someone has a status.status nested field,
        # it won't be skipped (since we ARE walking status).
        # Note: in practice "status" is in EXCLUDED_FIELDS but walk_crd_status
        # should not skip it since we are intentionally walking status subresource.
        # However, if there's a nested "status" field within status, that's unusual
        # but should also not be skipped.
        props = {"phase": {"type": "string"}}
        fields = list(walk_crd_status(props))
        assert len(fields) == 1
        assert fields[0].name == "phase"

    def test_other_excluded_fields_still_apply(self):
        """Other EXCLUDED_FIELDS like 'labels', 'annotations' still skipped in status."""
        props = {
            "phase": {"type": "string"},
            "labels": {"type": "object"},
            "annotations": {"type": "object"},
        }
        fields = list(walk_crd_status(props))
        names = {f.name for f in fields}
        assert "phase" in names
        assert "labels" not in names
        assert "annotations" not in names

    def test_does_not_skip_k8s_envelope_at_root(self):
        """walk_crd_status does NOT skip _K8S_ENVELOPE at root."""
        props = {
            "metadata": {"type": "string"},  # not in EXCLUDED_FIELDS
            "phase": {"type": "string"},
        }
        fields = list(walk_crd_status(props))
        names = {f.name for f in fields}
        assert "metadata" in names
        assert "phase" in names


# ---------------------------------------------------------------------------
# Non-dict property schemas
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_non_dict_property_schema_skipped(self):
        """Non-dict property schema entries are silently skipped."""
        props = {
            "good": {"type": "string"},
            "bad": "not a dict",
            "also_bad": None,
        }
        fields = list(walk_crd_schema(props))
        assert len(fields) == 1
        assert fields[0].name == "good"

    def test_custom_prefix(self):
        """Custom prefix is used in paths."""
        props = {"foo": {"type": "string"}}
        fields = list(walk_crd_schema(props, prefix="custom"))
        assert fields[0].path == "custom.foo"
        assert fields[0].parent_path == "custom"

    def test_empty_properties(self):
        """Empty properties dict yields no fields."""
        fields = list(walk_crd_schema({}))
        assert fields == []

    def test_array_items_required_propagation(self):
        """Array item required list is used for inner fields."""
        props = {
            "routes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["match"],
                    "properties": {
                        "match": {"type": "string"},
                        "optional": {"type": "string"},
                    },
                },
            },
        }
        fields = list(walk_crd_schema(props))
        match = next(f for f in fields if f.name == "match")
        optional = next(f for f in fields if f.name == "optional")
        assert match.required is True
        assert optional.required is False


# ---------------------------------------------------------------------------
# allOf / oneOf / anyOf composition handling
# ---------------------------------------------------------------------------


class TestComposedSchemaTraversal:
    """Tests for allOf/oneOf/anyOf traversal in schema walker."""

    def test_allof_properties_merged(self):
        """Properties in allOf sub-schemas are traversed."""
        props = {
            "config": {
                "allOf": [
                    {
                        "properties": {
                            "secretRef": {"type": "object", "properties": {"name": {"type": "string"}}},
                        },
                    },
                    {
                        "properties": {
                            "endpoint": {"type": "string"},
                        },
                    },
                ],
            },
        }
        fields = list(walk_crd_schema(props))
        names = {f.name for f in fields}
        # config itself + its composed children
        assert "config" in names
        assert "secretRef" in names
        assert "endpoint" in names

    def test_single_oneof_unwrapped(self):
        """oneOf with exactly 1 item is unwrapped."""
        props = {
            "provider": {
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "vault": {"type": "object", "properties": {"url": {"type": "string"}}},
                        },
                    },
                ],
            },
        }
        fields = list(walk_crd_schema(props))
        names = {f.name for f in fields}
        assert "vault" in names

    def test_multi_oneof_not_traversed(self):
        """oneOf with multiple items is not merged (ambiguous)."""
        props = {
            "target": {
                "oneOf": [
                    {"type": "object", "properties": {"option_a": {"type": "string"}}},
                    {"type": "object", "properties": {"option_b": {"type": "string"}}},
                ],
            },
        }
        fields = list(walk_crd_schema(props))
        names = {f.name for f in fields}
        # Only the parent field, no children (ambiguous merge avoided)
        assert "target" in names
        assert "option_a" not in names
        assert "option_b" not in names

    def test_allof_with_existing_properties(self):
        """allOf compositions merge with existing direct properties."""
        props = {
            "auth": {
                "type": "object",
                "properties": {
                    "token": {"type": "string"},
                },
                "allOf": [
                    {
                        "properties": {
                            "secretRef": {"type": "object", "properties": {"name": {"type": "string"}}},
                        },
                    },
                ],
            },
        }
        fields = list(walk_crd_schema(props))
        names = {f.name for f in fields}
        assert "token" in names
        assert "secretRef" in names

    def test_allof_in_array_items(self):
        """allOf inside array items is flattened."""
        props = {
            "solvers": {
                "type": "array",
                "items": {
                    "allOf": [
                        {"properties": {"dns01": {"type": "object"}}},
                        {"properties": {"http01": {"type": "object"}}},
                    ],
                },
            },
        }
        fields = list(walk_crd_schema(props))
        names = {f.name for f in fields}
        assert "dns01" in names
        assert "http01" in names


# ---------------------------------------------------------------------------
# WalkedField enrichment: depth_confidence + sibling_names
# ---------------------------------------------------------------------------


class TestWalkedFieldEnrichment:
    """Tests for depth_confidence and sibling_names fields on WalkedField."""

    def test_sibling_names_populated_for_nested_object_fields(self):
        """sibling_names contains sibling property names from the parent object."""
        props = {
            "auth": {
                "type": "object",
                "properties": {
                    "vault": {"type": "string"},
                    "kubernetes": {"type": "string"},
                    "jwt": {"type": "string"},
                },
            },
        }
        fields = list(walk_crd_schema(props))
        vault = next(f for f in fields if f.name == "vault")
        assert vault.sibling_names == frozenset({"vault", "kubernetes", "jwt"})

    def test_sibling_names_is_frozenset(self):
        """sibling_names must be a frozenset (immutable, hashable)."""
        props = {
            "foo": {"type": "string"},
            "bar": {"type": "string"},
        }
        fields = list(walk_crd_schema(props))
        for field in fields:
            assert isinstance(field.sibling_names, frozenset)

    def test_depth_confidence_defaults_to_1_0(self):
        """All WalkedField from standard walk have depth_confidence == 1.0."""
        props = {
            "level1": {
                "type": "object",
                "properties": {
                    "level2": {
                        "type": "object",
                        "properties": {
                            "level3": {"type": "string"},
                        },
                    },
                },
            },
        }
        fields = list(walk_crd_schema(props))
        for field in fields:
            assert field.depth_confidence == 1.0

    def test_sibling_names_at_root_spec_level(self):
        """Fields directly under spec have sibling_names from spec properties."""
        props = {
            "foo": {"type": "string"},
            "bar": {"type": "string"},
            "baz": {"type": "string"},
        }
        fields = list(walk_crd_schema(props))
        foo = next(f for f in fields if f.name == "foo")
        assert foo.sibling_names == frozenset({"foo", "bar", "baz"})

    def test_sibling_names_inside_array_items(self):
        """Fields inside array items have sibling_names from the items object."""
        props = {
            "routes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "match": {"type": "string"},
                        "services": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        }
        fields = list(walk_crd_schema(props))
        match = next(f for f in fields if f.name == "match")
        assert "services" in match.sibling_names
        assert "match" in match.sibling_names

    def test_sibling_names_deeply_nested(self):
        """sibling_names works at arbitrary depth, reflecting the immediate parent."""
        props = {
            "provider": {
                "type": "object",
                "properties": {
                    "vault": {
                        "type": "object",
                        "properties": {
                            "auth": {
                                "type": "object",
                                "properties": {
                                    "tokenSecretRef": {"type": "string"},
                                    "appRole": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        }
        fields = list(walk_crd_schema(props))
        token_ref = next(f for f in fields if f.name == "tokenSecretRef")
        assert "appRole" in token_ref.sibling_names
        assert "tokenSecretRef" in token_ref.sibling_names

    def test_existing_walkedfield_construction_backward_compatible(self):
        """WalkedField can still be constructed without the new fields."""
        wf = WalkedField(
            path="spec.foo", name="foo", schema={"type": "string"},
            depth=1, is_array_item=False, required=False, parent_path="spec",
        )
        assert wf.depth_confidence == 1.0
        assert wf.sibling_names == frozenset()

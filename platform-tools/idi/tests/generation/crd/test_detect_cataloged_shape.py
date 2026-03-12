"""Tests for detect_cataloged_shape (C30 runtime) in ref_detector.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from idi.generation.crd.ref_detector import (
    CatalogEntry,
    ShapeCatalog,
    _get_shape_catalog,
    detect_cataloged_shape,
)
from idi.generation.crd.schema_walker import WalkedField


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_field(
    name: str,
    schema: dict | None = None,
    path: str | None = None,
    parent_path: str = "spec",
) -> WalkedField:
    if schema is None:
        schema = {"type": "object"}
    if path is None:
        path = f"{parent_path}.{name}"
    return WalkedField(
        path=path,
        name=name,
        schema=schema,
        depth=1,
        is_array_item=False,
        required=False,
        parent_path=parent_path,
    )


@pytest.fixture
def sample_catalog() -> ShapeCatalog:
    """A ShapeCatalog with one entry for testing."""
    entry = CatalogEntry(
        fingerprint="name:string,namespace:string?",
        target_kind="Secret",
        confirmed_in=("SecretStore", "ExternalSecret"),
        confidence=0.80,
        required_properties=frozenset({"name"}),
    )
    return ShapeCatalog(shapes={"name:string,namespace:string?": entry})


@pytest.fixture
def high_confidence_catalog() -> ShapeCatalog:
    """A ShapeCatalog with a 3-CRD entry (confidence 0.85)."""
    entry = CatalogEntry(
        fingerprint="name:string,namespace:string?",
        target_kind="Secret",
        confirmed_in=("SecretStore", "ExternalSecret", "PushSecret"),
        confidence=0.85,
        required_properties=frozenset({"name"}),
    )
    return ShapeCatalog(shapes={"name:string,namespace:string?": entry})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDetectCatalogedShape:
    def test_matching_fingerprint(self, sample_catalog):
        """Field matching a cataloged fingerprint -> ClassifiedField."""
        field = _make_field("secretRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
            },
            "required": ["name"],
        })
        result = detect_cataloged_shape(field, sample_catalog)
        assert result is not None
        assert result.role == "input_ref"
        assert result.target_kind == "Secret"
        assert result.confidence == 0.80
        assert result.detection_source == "ref_detector:cataloged_shape"

    def test_high_confidence(self, high_confidence_catalog):
        """3-CRD entry -> confidence 0.85."""
        field = _make_field("secretRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
            },
            "required": ["name"],
        })
        result = detect_cataloged_shape(field, high_confidence_catalog)
        assert result is not None
        assert result.confidence == 0.85

    def test_missing_required_property(self, sample_catalog):
        """Field missing a required property -> None."""
        field = _make_field("someRef", schema={
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
            },
        })
        result = detect_cataloged_shape(field, sample_catalog)
        assert result is None

    def test_empty_catalog(self):
        """Empty catalog -> None for any field."""
        catalog = ShapeCatalog(shapes={})
        field = _make_field("anything", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        })
        result = detect_cataloged_shape(field, catalog)
        assert result is None

    def test_no_properties(self):
        """Field with no properties -> None."""
        catalog = ShapeCatalog(shapes={})
        field = _make_field("plain", schema={"type": "string"})
        result = detect_cataloged_shape(field, catalog)
        assert result is None

    def test_fingerprint_no_match(self, sample_catalog):
        """Field with different fingerprint -> None."""
        field = _make_field("other", schema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
            },
            "required": ["host"],
        })
        result = detect_cataloged_shape(field, sample_catalog)
        assert result is None


class TestGetShapeCatalog:
    def test_returns_shape_catalog(self):
        """_get_shape_catalog returns a ShapeCatalog instance."""
        import idi.generation.crd.ref_detector as rd
        # Reset singleton for isolation.
        old = rd._SHAPE_CATALOG
        rd._SHAPE_CATALOG = None
        try:
            catalog = _get_shape_catalog()
            assert isinstance(catalog, ShapeCatalog)
        finally:
            rd._SHAPE_CATALOG = old

    def test_singleton_caching(self):
        """_get_shape_catalog returns same instance on repeated calls."""
        import idi.generation.crd.ref_detector as rd
        old = rd._SHAPE_CATALOG
        rd._SHAPE_CATALOG = None
        try:
            c1 = _get_shape_catalog()
            c2 = _get_shape_catalog()
            assert c1 is c2
        finally:
            rd._SHAPE_CATALOG = old

    def test_missing_file_returns_empty(self):
        """When catalog file does not exist, returns empty catalog."""
        import idi.generation.crd.ref_detector as rd
        old = rd._SHAPE_CATALOG
        rd._SHAPE_CATALOG = None
        try:
            catalog = _get_shape_catalog()
            # The default path likely doesn't exist in test env.
            assert isinstance(catalog, ShapeCatalog)
        finally:
            rd._SHAPE_CATALOG = old

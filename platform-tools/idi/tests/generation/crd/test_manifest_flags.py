"""Tests for ManifestFlags dataclass — CRD Phase 3 Section 01."""
from __future__ import annotations

from idi.generation.crd.ref_detector import ManifestFlags


class TestManifestFlagsDefaults:
    def test_defaults_all_false(self):
        """ManifestFlags defaults to all-false/empty."""
        flags = ManifestFlags()
        assert flags.accepts_arbitrary_resources is False
        assert flags.passthrough_detection_source == ""
        assert flags.passthrough_field_path == ""

    def test_mutable(self):
        """ManifestFlags fields can be set."""
        flags = ManifestFlags()
        flags.accepts_arbitrary_resources = True
        flags.passthrough_detection_source = "ref_detector:passthrough_manifest"
        flags.passthrough_field_path = "spec.resources"
        assert flags.accepts_arbitrary_resources is True
        assert flags.passthrough_detection_source == "ref_detector:passthrough_manifest"
        assert flags.passthrough_field_path == "spec.resources"

    def test_init_with_values(self):
        """ManifestFlags can be initialized with specific values."""
        flags = ManifestFlags(
            accepts_arbitrary_resources=True,
            passthrough_detection_source="test",
            passthrough_field_path="spec.x",
        )
        assert flags.accepts_arbitrary_resources is True
        assert flags.passthrough_detection_source == "test"
        assert flags.passthrough_field_path == "spec.x"

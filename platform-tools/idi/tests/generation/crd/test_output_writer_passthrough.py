"""Tests for output_writer accepts_arbitrary_resources — CRD Phase 3 Section 05."""
from __future__ import annotations

from idi.generation.crd.output_writer import build_decomposed_skill


def _crd_info():
    return {
        "kind": "Application",
        "group": "argoproj.io",
        "version": "v1alpha1",
        "plural": "applications",
        "scope": "Namespaced",
        "service": "argocd",
        "description": "ArgoCD Application",
    }


class TestOutputWriterPassthrough:
    def test_flag_true_in_manifest(self):
        """accepts_arbitrary_resources=True -> manifest has the key."""
        skill = build_decomposed_skill(
            _crd_info(), fields=[], status_conditions=["Ready"],
            accepts_arbitrary_resources=True,
        )
        assert skill["manifest"]["accepts_arbitrary_resources"] is True

    def test_flag_false_omits_key(self):
        """accepts_arbitrary_resources=False -> key not in manifest."""
        skill = build_decomposed_skill(
            _crd_info(), fields=[], status_conditions=["Ready"],
            accepts_arbitrary_resources=False,
        )
        assert "accepts_arbitrary_resources" not in skill["manifest"]

    def test_flag_default_omits_key(self):
        """Default (no parameter) -> key not in manifest."""
        skill = build_decomposed_skill(
            _crd_info(), fields=[], status_conditions=["Ready"],
        )
        assert "accepts_arbitrary_resources" not in skill["manifest"]

    def test_flag_true_preserves_other_fields(self):
        """accepts_arbitrary_resources=True still has all standard fields."""
        skill = build_decomposed_skill(
            _crd_info(), fields=[], status_conditions=["Ready"],
            accepts_arbitrary_resources=True,
        )
        manifest = skill["manifest"]
        assert manifest["kind"] == "Application"
        assert manifest["group"] == "argoproj.io"
        assert manifest["schema_version"] == "2.0"
        assert manifest["service"] == "argocd"

"""Tests for detection_source and confidence in output serialization."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from idi.generation.context import GeneratorContext
from idi.generation.dep_adapters.base import DetectionSource
from idi.generation.output_writer import emit_resource


def _make_ctx(tmp_dir: Path) -> GeneratorContext:
    """Create a minimal GeneratorContext for output tests."""
    return GeneratorContext(
        api_name="test-svc",
        style="rest",
        schema={"openapi": "3.0.0", "info": {"title": "Test"}, "paths": {}},
        adapter=None,
        output_dir=tmp_dir,
    )


class TestOutputInstrumentation:
    def test_detection_source_and_confidence_in_output(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        resource_info = {
            "resource": "widgets",
            "description": "Test resource",
            "field_refs": [],
            "operations": [
                {
                    "op_info": {
                        "operation": "create",
                        "method": "POST",
                        "endpoint": "/widgets",
                        "description": "Create widget",
                    },
                    "params": {"request_fields": [], "response_fields": []},
                    "depends_on": [
                        {
                            "path": "test-svc/gadgets/create",
                            "source": "generic_odg:body",
                            "field": "gadget_id",
                            "type": "unknown",
                            "fact_ref": "facts://test-svc/gadgets#id",
                            "lineage_type": "copy",
                            "detection_source": DetectionSource.FK_SUFFIX.value,
                            "confidence": 0.75,
                        },
                    ],
                    "outputs": {},
                    "idempotent": False,
                    "field_refs_map": {},
                    "check_with": None,
                },
            ],
        }
        emit_resource(ctx, tmp_path, resource_info)

        op_file = tmp_path / "widgets" / "operations" / "create.json"
        assert op_file.exists()
        op_data = json.loads(op_file.read_text())
        deps = op_data.get("depends_on", [])
        assert len(deps) == 1
        dep = deps[0]
        assert dep["detection_source"] == "rest:fk_suffix"
        assert dep["confidence"] == 0.75

    def test_output_works_without_detection_source(self, tmp_path):
        """Backward compat: deps without the new keys still work."""
        ctx = _make_ctx(tmp_path)
        resource_info = {
            "resource": "widgets",
            "description": "Test",
            "field_refs": [],
            "operations": [
                {
                    "op_info": {
                        "operation": "create",
                        "method": "POST",
                        "endpoint": "/widgets",
                        "description": "Create widget",
                    },
                    "params": {"request_fields": [], "response_fields": []},
                    "depends_on": [
                        {
                            "path": "test-svc/gadgets/create",
                            "source": "generic_odg:body",
                            "field": "gadget_id",
                            "type": "unknown",
                            "fact_ref": None,
                            "lineage_type": "copy",
                            # No detection_source or confidence keys
                        },
                    ],
                    "outputs": {},
                    "idempotent": False,
                    "field_refs_map": {},
                    "check_with": None,
                },
            ],
        }
        emit_resource(ctx, tmp_path, resource_info)

        op_file = tmp_path / "widgets" / "operations" / "create.json"
        assert op_file.exists()
        op_data = json.loads(op_file.read_text())
        deps = op_data.get("depends_on", [])
        assert len(deps) == 1
        # Should not have detection_source or confidence
        assert "detection_source" not in deps[0]
        assert "confidence" not in deps[0]

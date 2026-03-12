"""Tests for detection_source and confidence in output JSON."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from idi.generation.context import GeneratorContext
from idi.generation.output_writer import emit_resource


def _make_ctx(tmp_path: Path) -> GeneratorContext:
    """Build a minimal GeneratorContext for output_writer tests."""
    return GeneratorContext(
        schema={},
        output_dir=tmp_path,
        api_name="testsvc",
        style="rest",
        adapter=None,
    )


class TestOutputInstrumentation:
    """detection_source and confidence appear in output JSON."""

    def test_depends_on_includes_detection_source(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        resource_info = {
            "resource": "widget",
            "description": "",
            "operations": [
                {
                    "op_info": {
                        "resource": "widget",
                        "operation": "create",
                        "method": "POST",
                        "endpoint": "/widgets",
                        "path": "/widgets",
                    },
                    "params": {"request_fields": []},
                    "depends_on": [
                        {
                            "path": "testsvc/gadget/create",
                            "field": "gadget_id",
                            "source": "generic_odg:body",
                            "fact_ref": "facts://testsvc/gadget#id",
                            "lineage_type": "copy",
                            "discriminator_value": None,
                            "detection_source": "rest:fk_suffix",
                            "confidence": 0.75,
                        }
                    ],
                    "outputs": {},
                    "idempotent": False,
                    "field_refs_map": {},
                    "check_with": None,
                }
            ],
            "field_refs": [],
        }
        emit_resource(ctx, tmp_path, resource_info)

        op_file = tmp_path / "widget" / "operations" / "create.json"
        op_data = json.loads(op_file.read_text())
        dep = op_data["depends_on"][0]

        assert "detection_source" in dep
        assert dep["detection_source"] == "rest:fk_suffix"

    def test_depends_on_includes_confidence(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        resource_info = {
            "resource": "widget",
            "description": "",
            "operations": [
                {
                    "op_info": {
                        "resource": "widget",
                        "operation": "create",
                        "method": "POST",
                        "endpoint": "/widgets",
                        "path": "/widgets",
                    },
                    "params": {"request_fields": []},
                    "depends_on": [
                        {
                            "path": "testsvc/gadget/create",
                            "field": "gadget_id",
                            "source": "generic_odg:body",
                            "fact_ref": None,
                            "lineage_type": "copy",
                            "discriminator_value": None,
                            "detection_source": "rest:default",
                            "confidence": 0.42,
                        }
                    ],
                    "outputs": {},
                    "idempotent": False,
                    "field_refs_map": {},
                    "check_with": None,
                }
            ],
            "field_refs": [],
        }
        emit_resource(ctx, tmp_path, resource_info)

        op_file = tmp_path / "widget" / "operations" / "create.json"
        op_data = json.loads(op_file.read_text())
        dep = op_data["depends_on"][0]

        assert "confidence" in dep
        assert dep["confidence"] == 0.42

    def test_existing_fields_preserved(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        resource_info = {
            "resource": "widget",
            "description": "",
            "operations": [
                {
                    "op_info": {
                        "resource": "widget",
                        "operation": "create",
                        "method": "POST",
                        "endpoint": "/widgets",
                        "path": "/widgets",
                    },
                    "params": {"request_fields": []},
                    "depends_on": [
                        {
                            "path": "testsvc/gadget/create",
                            "field": "gadget_id",
                            "source": "generic_odg:body",
                            "fact_ref": "facts://testsvc/gadget#id",
                            "lineage_type": "copy",
                            "discriminator_value": None,
                            "detection_source": "rest:fk_suffix",
                            "confidence": 0.5,
                        }
                    ],
                    "outputs": {},
                    "idempotent": False,
                    "field_refs_map": {},
                    "check_with": None,
                }
            ],
            "field_refs": [],
        }
        emit_resource(ctx, tmp_path, resource_info)

        op_file = tmp_path / "widget" / "operations" / "create.json"
        op_data = json.loads(op_file.read_text())
        dep = op_data["depends_on"][0]

        assert dep["path"] == "testsvc/gadget/create"
        assert dep["field"] == "gadget_id"
        assert dep["source"] == "generic_odg:body"
        assert dep["fact_ref"] == "facts://testsvc/gadget#id"
        assert dep["lineage_type"] == "copy"

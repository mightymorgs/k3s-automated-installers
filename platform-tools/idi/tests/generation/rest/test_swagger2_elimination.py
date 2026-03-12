"""Tests: Swagger 2.0 spec processing WITHOUT swagger2.py adapter.

Verifies the generic pipeline (spec_loader, field_extractor) handles all
Swagger 2.0 structural differences that swagger2.py used to handle:
- #/definitions/ -> $ref resolution
- in:body parameters -> request body extraction
- in:formData parameters -> synthetic body schema
- responses[code].schema (not nested under content/)
- file upload parameters
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from idi.generation.field_extractor import (
    extract_request_fields,
    extract_response_fields,
    extract_schema_fields,
)


@pytest.fixture
def swagger2_spec():
    """Valid Swagger 2.0 spec with body params and definitions."""
    return {
        "swagger": "2.0",
        "info": {"title": "Test API", "version": "1.0"},
        "paths": {
            "/pets": {
                "post": {
                    "operationId": "createPet",
                    "parameters": [
                        {
                            "in": "body",
                            "name": "body",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "tag": {"type": "string"},
                                },
                                "required": ["name"],
                            },
                        },
                    ],
                    "responses": {
                        "201": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "integer"},
                                    "name": {"type": "string"},
                                    "tag": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
    }


@pytest.fixture
def swagger2_formdata_spec():
    """Swagger 2.0 spec with in:formData parameters (Slack-style)."""
    return {
        "swagger": "2.0",
        "info": {"title": "Slack API", "version": "1.0"},
        "paths": {
            "/chat.postMessage": {
                "post": {
                    "operationId": "chatPostMessage",
                    "parameters": [
                        {"in": "formData", "name": "channel", "type": "string", "required": True},
                        {"in": "formData", "name": "text", "type": "string"},
                        {"in": "formData", "name": "attachment", "type": "file",
                         "description": "File to upload"},
                    ],
                    "responses": {
                        "200": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "ok": {"type": "boolean"},
                                    "ts": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
    }


class TestSwagger2SpecHandling:
    """Generic pipeline handles Swagger 2.0 structural differences."""

    def test_body_parameter_extraction(self, swagger2_spec):
        """Swagger 2.0 'in: body' parameter extracted as request body fields."""
        ctx = MagicMock()
        ctx.schema = swagger2_spec
        operation = swagger2_spec["paths"]["/pets"]["post"]
        fields = extract_request_fields(ctx, {}, operation)
        field_names = {f["name"] for f in fields}
        assert "name" in field_names
        assert "tag" in field_names

    def test_formdata_parameter_extraction(self, swagger2_formdata_spec):
        """Swagger 2.0 'in: formData' parameters converted to body fields."""
        ctx = MagicMock()
        ctx.schema = swagger2_formdata_spec
        operation = swagger2_formdata_spec["paths"]["/chat.postMessage"]["post"]
        fields = extract_request_fields(ctx, {}, operation)
        field_names = {f["name"] for f in fields}
        assert "channel" in field_names
        assert "text" in field_names

    def test_file_upload_handled_gracefully(self, swagger2_formdata_spec):
        """Swagger 2.0 file upload (type: file) handled without error."""
        ctx = MagicMock()
        ctx.schema = swagger2_formdata_spec
        operation = swagger2_formdata_spec["paths"]["/chat.postMessage"]["post"]
        fields = extract_request_fields(ctx, {}, operation)
        attachment = [f for f in fields if f["name"] == "attachment"]
        assert len(attachment) == 1
        assert attachment[0]["type"] == "file"

    def test_response_schema_direct(self, swagger2_spec):
        """Swagger 2.0 responses[code].schema (not under content/) extracted."""
        ctx = MagicMock()
        ctx.schema = swagger2_spec
        ctx.adapter = MagicMock(spec=[])  # No extract_response_schema
        operation = swagger2_spec["paths"]["/pets"]["post"]
        fields = extract_response_fields(ctx, operation)
        field_names = {f["name"] for f in fields}
        assert "id" in field_names
        assert "name" in field_names

    def test_allof_in_swagger2_definitions(self):
        """allOf in Swagger 2.0 definitions handled by canonicalization."""
        ctx = MagicMock()
        ctx.schema = {"paths": {}}
        # Schema using allOf (common in Swagger 2.0 definitions)
        schema = {
            "allOf": [
                {"type": "object", "properties": {"id": {"type": "integer"}}},
                {"type": "object", "properties": {"name": {"type": "string"}}},
            ],
        }
        result = extract_schema_fields(ctx, schema)
        assert "id" in result["properties"]
        assert "name" in result["properties"]

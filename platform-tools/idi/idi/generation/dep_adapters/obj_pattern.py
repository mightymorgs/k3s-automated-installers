"""Structural adapter: Django REST Framework _obj field pattern.

Priority: 85 (structural signal, DRF-specific).
"""
from __future__ import annotations

from typing import Any

from idi.generation.dep_adapters.base import Dependency, OperationInfo, Output

_OBJ_ID_FIELDS = {"pk", "id", "uuid", "uid", "guid"}


class ObjPatternAdapter:
    name = "obj_pattern"
    priority = 85

    def matches(self, spec: dict[str, Any], service_name: str) -> bool:
        count = 0
        for path_methods in spec.get("paths", {}).values():
            if not isinstance(path_methods, dict):
                continue
            for method_data in path_methods.values():
                if not isinstance(method_data, dict):
                    continue
                body = (method_data.get("requestBody", {})
                        .get("content", {}).get("application/json", {})
                        .get("schema", {}))
                for fn in body.get("properties", {}):
                    if fn.endswith("_obj"):
                        count += 1
                        if count >= 5:
                            return True
        return False

    def detect_dependencies(
        self, operation: OperationInfo, spec: dict, known_resources: set[str],
    ) -> list[Dependency]:
        body = operation.body_schema
        if not body or "properties" not in body:
            return []
        results: list[Dependency] = []
        for fn, fs in body.get("properties", {}).items():
            if not fn.endswith("_obj") or not isinstance(fs, dict):
                continue
            if fs.get("type") != "object":
                continue
            if not (_OBJ_ID_FIELDS & set(fs.get("properties", {}))):
                continue
            results.append(Dependency(
                field=fn[:-4], target_resource=fn[:-4],
                confidence=0.9, source="obj_pattern",
            ))
        return results

    def detect_outputs(self, operation: OperationInfo, spec: dict) -> list[Output]:
        return []

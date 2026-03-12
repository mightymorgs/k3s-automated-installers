"""Dependency adapter registry: discovery + detect orchestration."""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from idi.generation.dep_adapters.base import (
    DepAdapter,
    Dependency,
    OperationInfo,
    Output,
)
from idi.generation.dep_adapters.merge import filter_by_confidence, filter_self_refs, merge_deps, merge_outputs

logger = logging.getLogger(__name__)


class DepAdapterRegistry:
    """Discovers adapters, runs matching ones, merges results."""

    def __init__(self, adapter_dirs: list[Path] | None = None) -> None:
        self._adapters: list[DepAdapter] = []
        self._yaml_names: set[str] = set()

        if adapter_dirs is None:
            adapter_dirs = [Path(__file__).parent]

        for d in adapter_dirs:
            self._discover_python(d)
            gen = d / "generated"
            if gen.is_dir():
                self._discover_yaml(gen)

        self._adapters.sort(key=lambda a: -a.priority)

    def _discover_python(self, directory: Path) -> None:
        skip = {"__init__", "base", "registry", "merge", "yaml_adapter",
                "body_fk", "path_deps", "target_inference", "output_detection"}
        for py in sorted(directory.glob("*.py")):
            if py.stem in skip:
                continue
            mod_name = f"idi.generation.dep_adapters.{py.stem}"
            try:
                mod = importlib.import_module(mod_name)
            except Exception:
                logger.warning("Could not import dep adapter: %s", mod_name)
                continue
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if (isinstance(obj, type) and hasattr(obj, "name")
                        and hasattr(obj, "priority") and hasattr(obj, "matches")
                        and hasattr(obj, "detect_dependencies")
                        and hasattr(obj, "detect_outputs")):
                    try:
                        self._adapters.append(obj())
                    except Exception:
                        logger.warning("Could not instantiate: %s.%s", mod_name, attr)

    def _discover_yaml(self, directory: Path) -> None:
        try:
            from idi.generation.dep_adapters.yaml_adapter import YamlDepAdapter
        except ImportError:
            return
        for yf in sorted(directory.glob("*.yaml")):
            try:
                adapter = YamlDepAdapter.from_file(yf)
                self._adapters.append(adapter)
                self._yaml_names.add(adapter.name.lower())
            except Exception:
                logger.warning("Could not load YAML adapter: %s", yf)

    def get_adapters_for(self, spec: dict, service: str) -> list[DepAdapter]:
        matching = [a for a in self._adapters if a.matches(spec, service)]
        if service.lower() in self._yaml_names:
            if not any(a.name.lower() == service.lower() for a in matching):
                logger.warning("YAML adapter '%s' exists but did not match spec", service)
        return matching

    def detect(
        self, operation: OperationInfo, spec: dict, known_resources: set[str],
    ) -> tuple[list[Dependency], list[Output]]:
        adapters = self.get_adapters_for(spec, operation.service)
        all_deps: list[Dependency] = []
        all_outputs: list[Output] = []
        for adapter in adapters:
            try:
                all_deps.extend(adapter.detect_dependencies(operation, spec, known_resources))
            except Exception:
                logger.warning("Adapter %s raised in detect_dependencies", adapter.name)
            try:
                all_outputs.extend(adapter.detect_outputs(operation, spec))
            except Exception:
                logger.warning("Adapter %s raised in detect_outputs", adapter.name)
        deps = merge_deps(all_deps)
        deps = filter_self_refs(deps, operation.resource, operation.method)
        deps = filter_by_confidence(deps)
        # Suppress body/operationid deps whose target is already covered by a
        # path dep. Path skeleton is authoritative; weaker sources are fenced.
        _FENCED_SOURCES = {"generic_odg:body", "generic_odg:operationid"}
        path_targets = {d.target_resource for d in deps if d.source == "generic_odg:path"}
        if path_targets:
            deps = [
                d for d in deps
                if d.source not in _FENCED_SOURCES or d.target_resource not in path_targets
            ]
        outputs = merge_outputs(all_outputs)
        return deps, outputs

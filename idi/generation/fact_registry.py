"""Fact registry using canonical FactRef model.

Maps facts to their producing skills with alias resolution.
Looking up by 'id' finds 'pk' (both canonicalize to 'id').
"""
from pathlib import Path
from typing import Dict, List, Optional
import yaml

from idi.generation.fact_model import FactRef, ProducedFact, FactGraph, from_legacy


class FactRegistry:
    """Registry mapping facts to their producing skills.

    Supports alias resolution: looking up by 'id' finds 'pk'.
    Uses FactGraph internally for canonical lookup.
    """

    def __init__(self):
        self._graph = FactGraph()
        self._by_service: Dict[str, Dict[str, ProducedFact]] = {}

    def register_output(
        self,
        service: str,
        resource: str,
        field: str,
        skill_path: str,
        operation: str
    ) -> None:
        """Register a fact as produced by a skill.

        Args:
            service: Service name (e.g., 'authentik')
            resource: Resource name (e.g., 'providers-oauth2')
            field: Field name (e.g., 'pk', 'id', 'name')
            skill_path: Path to the skill file
            operation: Operation type (e.g., 'create', 'retrieve')
        """
        ref = FactRef(service=service, resource=resource, field=field)
        produced = ProducedFact(
            ref=ref,
            skill_path=skill_path,
            response_field=field,
            operation=operation
        )
        self._graph.add_produced(produced)

        # Also track by service for legacy export and service queries
        if service not in self._by_service:
            self._by_service[service] = {}
        key = f"{resource}.{field}"
        self._by_service[service][key] = produced

    def find_producer(self, ref: FactRef) -> Optional[ProducedFact]:
        """Find the skill that produces a fact (with alias resolution).

        Prefers 'create' operations when multiple producers exist.

        Args:
            ref: The fact reference to look up

        Returns:
            ProducedFact if found, None otherwise
        """
        return self._graph.get_producer(ref)

    def find_all_producers(self, ref: FactRef) -> List[ProducedFact]:
        """Find all skills that produce a fact.

        Args:
            ref: The fact reference to look up

        Returns:
            List of all producers (may be empty)
        """
        return self._graph.find_producers(ref)

    def get_facts_for_service(self, service: str) -> List[ProducedFact]:
        """Get all facts registered for a service.

        Args:
            service: Service name

        Returns:
            List of ProducedFact objects for the service
        """
        if service not in self._by_service:
            return []
        return list(self._by_service[service].values())

    def to_legacy_format(self) -> Dict[str, Dict[str, str]]:
        """Export to legacy {service: {key: path}} format.

        Used for backwards compatibility with existing code.

        Returns:
            Dict mapping service -> {resource.field: skill_path}
        """
        legacy: Dict[str, Dict[str, str]] = {}
        for service, facts in self._by_service.items():
            legacy[service] = {}
            for key, produced in facts.items():
                legacy[service][key] = produced.skill_path
        return legacy

    @classmethod
    def build_from_directory(cls, skills_dir: Path) -> "FactRegistry":
        """Build registry by scanning skills directory.

        Parses YAML frontmatter from skill files and extracts
        output facts from 'create' operations.

        Args:
            skills_dir: Root directory containing skill files

        Returns:
            Populated FactRegistry
        """
        registry = cls()

        for skill_path in skills_dir.rglob("*.md"):
            frontmatter = cls._parse_frontmatter(skill_path)
            if not frontmatter:
                continue

            api = frontmatter.get("api", {})
            service = api.get("service")
            resource = api.get("resource")
            operation = api.get("operation", "")

            # Only index create operations as fact producers
            if not service or not resource or operation != "create":
                continue

            outputs = frontmatter.get("outputs", {})
            facts = outputs.get("facts", [])
            rel_path = str(skill_path.relative_to(skills_dir))

            for fact in facts:
                try:
                    ref = from_legacy(fact)
                    registry.register_output(
                        service=ref.service,
                        resource=ref.resource,
                        field=ref.field,
                        skill_path=rel_path,
                        operation=operation
                    )
                except Exception:
                    # Skip malformed fact entries
                    continue

        return registry

    @staticmethod
    def _parse_frontmatter(skill_path: Path) -> Optional[Dict]:
        """Parse YAML frontmatter from skill file.

        Args:
            skill_path: Path to skill markdown file

        Returns:
            Parsed frontmatter dict, or None if parsing fails
        """
        try:
            content = skill_path.read_text()
            if not content.startswith("---"):
                return None
            parts = content.split("---", 2)
            if len(parts) < 3:
                return None
            return yaml.safe_load(parts[1])
        except Exception:
            return None

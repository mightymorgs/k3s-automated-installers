"""Canonical fact model with URI-based references.

Facts are identified by URIs: facts://service/resource#field

Examples:
    facts://authentik/providers-oauth2#id
    facts://cloudflare/zones#name
    facts://sonarr/qualityprofile#id
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set, Tuple
import re

# --- Field alias groups ---
# Each group maps a canonical field name to all known aliases.
# When a field matches ANY alias in a group, it canonicalizes to the group key.
FIELD_ALIAS_GROUPS: Dict[str, FrozenSet[str]] = {
    "id": frozenset({"id", "pk", "uuid", "guid", "uid"}),
    "created_at": frozenset({"created_at", "created", "timestamp", "date_created"}),
    "name": frozenset({"name", "title", "label", "display_name"}),
    "owner": frozenset({"owner", "owner_id", "creator", "created_by"}),
}

# Flat reverse lookup: alias → canonical field name.
_ALIAS_TO_CANONICAL: Dict[str, str] = {}
for _canonical, _aliases in FIELD_ALIAS_GROUPS.items():
    for _alias in _aliases:
        _ALIAS_TO_CANONICAL[_alias] = _canonical

# Backwards-compatible: the ID alias set used by ingest + resolve.
ID_ALIASES: Set[str] = set(FIELD_ALIAS_GROUPS["id"])


def canonicalize_field(field_name: str) -> str:
    """Resolve a field name to its canonical form via alias groups.

    Args:
        field_name: Raw field name (e.g. ``'pk'``, ``'created'``).

    Returns:
        Canonical field name (e.g. ``'id'``, ``'created_at'``).
        Returns the input lowercased if no alias matches.
    """
    return _ALIAS_TO_CANONICAL.get(field_name.lower(), field_name.lower())


# --- Lineage type classification ---

class LineageType(str, Enum):
    """Classifies the nature of a dependency edge.

    Inspired by DataHub's FineGrainedLineage types.  Helps Kahn's sort
    prioritize hard deps and enables impact analysis.
    """
    COPY = "copy"
    """Hard dependency: the exact value is needed (e.g. provider PK)."""

    TRANSFORM = "transform"
    """Soft dependency: the value is used to derive/compute something."""

    REFERENCE = "reference"
    """Informational: could use an alternative (e.g. optional policy)."""

# URI pattern: facts://service/resource#field
FACT_URI_PATTERN = re.compile(
    r"^facts://(?P<service>[a-z0-9_-]+)/(?P<resource>[a-z0-9_-]+)#(?P<field>[a-z0-9_]+)$",
    re.IGNORECASE
)


class InvalidFactUri(ValueError):
    """Raised when a fact URI cannot be parsed."""
    pass


@dataclass(frozen=True)
class FactRef:
    """Canonical reference to a fact produced or consumed by a skill.

    Attributes:
        service: Service name (e.g., 'authentik', 'cloudflare')
        resource: Resource name (e.g., 'providers-oauth2', 'zones')
        field: Original field name (e.g., 'pk', 'uuid', 'name')
        canonical_field: Normalized field name (aliases resolved)
    """
    service: str
    resource: str
    field: str
    canonical_field: str = field(init=False)

    def __post_init__(self):
        # Resolve aliases via alias groups (pk → id, created → created_at, etc.)
        object.__setattr__(self, 'canonical_field', canonicalize_field(self.field))

    def to_uri(self) -> str:
        """Serialize to canonical URI format."""
        return f"facts://{self.service}/{self.resource}#{self.field}"

    def to_legacy(self) -> str:
        """Serialize to legacy dot-notation format for backwards compatibility."""
        return f"facts.{self.service}.{self.resource}.{self.field}"

    def matches_canonical(self, other: "FactRef") -> bool:
        """Check if two FactRefs have the same canonical identity.

        Two facts match canonically if they refer to the same service,
        resource, and canonical field (after alias resolution).
        """
        return (
            self.service == other.service and
            self.resource == other.resource and
            self.canonical_field == other.canonical_field
        )

    def __hash__(self):
        return hash((self.service, self.resource, self.field))

    def __eq__(self, other):
        if not isinstance(other, FactRef):
            return False
        return (
            self.service == other.service and
            self.resource == other.resource and
            self.field == other.field
        )


def parse_fact_uri(uri: str) -> FactRef:
    """Parse a fact URI into a FactRef.

    Args:
        uri: URI in format facts://service/resource#field

    Returns:
        FactRef instance

    Raises:
        InvalidFactUri: If URI format is invalid
    """
    match = FACT_URI_PATTERN.match(uri)
    if not match:
        raise InvalidFactUri(f"Invalid fact URI: {uri}")

    return FactRef(
        service=match.group("service").lower(),
        resource=match.group("resource").lower(),
        field=match.group("field").lower(),
    )


def from_legacy(legacy: str) -> FactRef:
    """Convert legacy dot-notation to FactRef.

    Args:
        legacy: String like 'facts.authentik.providers-oauth2.id'

    Returns:
        FactRef instance
    """
    parts = legacy.split(".")

    # Strip 'facts.' prefix if present
    if parts[0] == "facts":
        parts = parts[1:]

    if len(parts) < 3:
        raise InvalidFactUri(f"Invalid legacy fact: {legacy}")

    service = parts[0].lower()
    resource = parts[1].lower()
    field = parts[2].lower()

    return FactRef(service=service, resource=resource, field=field)


# --- Field Normalization ---

def camel_to_snake(name: str) -> str:
    """Convert camelCase or PascalCase to snake_case.

    Inserts underscore before uppercase letters that follow lowercase or digits.
    Examples:
        qualityProfileId -> quality_profile_id
        OAuth2Provider -> oauth2_provider
    """
    result = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    return result.lower()


def normalize_field(field: str) -> str:
    """Normalize a field name to canonical form.

    1. Convert camelCase to snake_case
    2. Lowercase
    """
    return camel_to_snake(field).lower()


def strip_id_suffix(field: str) -> str:
    """Strip ID-related suffixes from a field name.

    Used to match 'tunnel_id' to 'tunnel' resource.
    """
    normalized = normalize_field(field)
    for suffix in ("_id", "_pk", "_uuid", "_guid", "_uid", "_key", "_ref"):
        if normalized.endswith(suffix):
            return normalized[:-len(suffix)]
    return normalized


class AliasRegistry:
    """Registry for service-specific field aliases.

    Allows custom mappings like cloudflare/cfd-tunnel -> tunnel.
    """

    def __init__(self):
        self._aliases: Dict[Tuple[str, str], str] = {}
        self._reverse: Dict[Tuple[str, str], str] = {}

    def register(self, service: str, alias: str, canonical: str) -> None:
        """Register an alias mapping.

        Args:
            service: Service name
            alias: The alias (e.g., 'cfd-tunnel')
            canonical: The canonical name (e.g., 'tunnel')
        """
        key = (service.lower(), alias.lower())
        self._aliases[key] = canonical.lower()
        # Also register reverse for bidirectional lookup
        reverse_key = (service.lower(), canonical.lower())
        self._reverse[reverse_key] = alias.lower()

    def resolve(self, service: str, name: str) -> str:
        """Resolve a name to its canonical form.

        If no alias registered, returns the name unchanged.
        """
        key = (service.lower(), name.lower())
        return self._aliases.get(key, name.lower())

    def get_alias(self, service: str, canonical: str) -> str:
        """Get the alias for a canonical name.

        If no alias registered, returns the canonical name unchanged.
        """
        key = (service.lower(), canonical.lower())
        return self._reverse.get(key, canonical.lower())


# Global alias registry with built-in mappings
DEFAULT_ALIASES = AliasRegistry()

# Cloudflare mappings
DEFAULT_ALIASES.register("cloudflare", "cfd-tunnel", "tunnel")
DEFAULT_ALIASES.register("cloudflare", "cfd-tunnel-config", "tunnel-config")


# --- Provenance Model ---

@dataclass
class ProducedFact:
    """A fact produced (output) by a skill operation.

    Attributes:
        ref: The canonical fact reference
        skill_path: Path to the skill that produces this fact
        response_field: Field name in the API response
        operation: Operation type (create, retrieve, list, etc.)
    """
    ref: FactRef
    skill_path: str
    response_field: str
    operation: str


@dataclass
class RequiredFact:
    """A fact required (input) by a skill operation.

    Attributes:
        ref: The canonical fact reference
        skill_path: Path to the skill that requires this fact
        request_field: Field name in the API request
        required: Whether this is a required vs optional input
    """
    ref: FactRef
    skill_path: str
    request_field: str
    required: bool = True


class FactGraph:
    """Graph of fact production and consumption relationships.

    Enables queries like:
    - "Which skill produces this fact?"
    - "Which skills require this fact?"
    - "What's the dependency chain to produce this fact?"
    """

    def __init__(self):
        # Map from canonical (service, resource, canonical_field) -> list of producers
        self._producers: Dict[tuple, List[ProducedFact]] = {}
        # Map from canonical key -> list of consumers
        self._consumers: Dict[tuple, List[RequiredFact]] = {}

    def _canonical_key(self, ref: FactRef) -> tuple:
        """Create canonical lookup key from FactRef."""
        return (ref.service, ref.resource, ref.canonical_field)

    def add_produced(self, fact: ProducedFact) -> None:
        """Register a fact as produced by a skill."""
        key = self._canonical_key(fact.ref)
        if key not in self._producers:
            self._producers[key] = []
        self._producers[key].append(fact)

    def add_required(self, fact: RequiredFact) -> None:
        """Register a fact as required by a skill."""
        key = self._canonical_key(fact.ref)
        if key not in self._consumers:
            self._consumers[key] = []
        self._consumers[key].append(fact)

    def find_producers(self, ref: FactRef) -> List[ProducedFact]:
        """Find all skills that produce a given fact."""
        key = self._canonical_key(ref)
        return self._producers.get(key, [])

    def find_consumers(self, ref: FactRef) -> List[RequiredFact]:
        """Find all skills that require a given fact."""
        key = self._canonical_key(ref)
        return self._consumers.get(key, [])

    def get_producer(self, ref: FactRef) -> Optional[ProducedFact]:
        """Get the primary producer for a fact (prefers 'create' operations)."""
        producers = self.find_producers(ref)
        if not producers:
            return None

        # Prefer create operations as authoritative source
        for p in producers:
            if p.operation == "create":
                return p
        return producers[0]

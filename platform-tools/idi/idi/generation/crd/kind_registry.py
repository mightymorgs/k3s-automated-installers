"""Unified Kind registry for CRD field classification.

Replaces 6 hardcoded dictionaries spread across 4 files with a single
auto-populated registry. Supports runtime registration from CRD specs,
CamelCase-aware longest-match field lookup, and multi-group tie-breaking.

Zero internal imports from the idi package -- leaf module.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KindEntry:
    """A registered Kubernetes resource Kind."""

    kind: str       # e.g., "Secret"
    plural: str     # e.g., "secrets"
    group: str      # e.g., "core"
    is_core: bool   # True for bootstrap resources


# Well-known compound patterns that cannot be derived from generic suffix matching.
# Only SecretKeyRef and ConfigMapKeyRef are standard K8s compound patterns.
# A generic {Kind}KeyRef suffix would cause false positives (e.g., serviceKeyRef).
_WELL_KNOWN_COMPOUND: dict[str, tuple[str, str, str]] = {
    "secretkeyref": ("Secret", "secrets", "core"),
    "configmapkeyref": ("ConfigMap", "configmaps", "core"),
}

# Short-name aliases: shortened field name fragments that map to a longer
# registered Kind. These are checked when the dynamic suffix matching fails.
# "store" -> SecretStore is the only known case (external-secrets ecosystem).
_SHORT_NAME_ALIASES: dict[str, str] = {
    "store": "SecretStore",
}


class KindRegistry:
    """Unified registry for Kubernetes resource Kind-to-plural mappings.

    Bootstrap resources (18 core + 2 aliases) are loaded at init time.
    Additional CRD Kinds are registered at runtime via register() or
    register_from_crd(). All lookups use a single sorted data structure
    for O(n) longest-match semantics.
    """

    def __init__(self) -> None:
        """Initialize with core K8s resources."""
        self._kind_to_entries: dict[str, list[KindEntry]] = {}
        self._plural_to_kind: dict[str, str] = {}
        self._sorted_entries: list[KindEntry] = []
        self._load_core_resources()

    def _load_core_resources(self) -> None:
        """Register the 18 core K8s resources + 2 aliases."""
        core = [
            ("Secret", "secrets", "core"),
            ("ConfigMap", "configmaps", "core"),
            ("Service", "services", "core"),
            ("ServiceAccount", "serviceaccounts", "core"),
            ("PersistentVolumeClaim", "persistentvolumeclaims", "core"),
            ("PersistentVolume", "persistentvolumes", "core"),
            ("Namespace", "namespaces", "core"),
            ("Node", "nodes", "core"),
            ("Pod", "pods", "core"),
            ("Endpoint", "endpoints", "core"),
            ("Deployment", "deployments", "apps"),
            ("StatefulSet", "statefulsets", "apps"),
            ("DaemonSet", "daemonsets", "apps"),
            ("Job", "jobs", "batch"),
            ("CronJob", "cronjobs", "batch"),
            ("Ingress", "ingresses", "networking.k8s.io"),
            ("IngressClass", "ingressclasses", "networking.k8s.io"),
            ("StorageClass", "storageclasses", "storage.k8s.io"),
            # Aliases for non-standard field names.
            ("Claim", "persistentvolumeclaims", "core"),
            ("Volume", "persistentvolumes", "core"),
        ]
        for kind, plural, group in core:
            self.register(kind, plural, group, is_core=True)

    def register(
        self,
        kind: str,
        plural: str,
        group: str = "",
        is_core: bool = False,
    ) -> None:
        """Register a Kind with its plural form and optional API group.

        Appends to existing entries if the same Kind is registered with a
        different group. Rebuilds the sorted entry list after each call.
        """
        entry = KindEntry(kind=kind, plural=plural, group=group, is_core=is_core)

        entries = self._kind_to_entries.setdefault(kind, [])
        # Avoid duplicates.
        if entry not in entries:
            entries.append(entry)

        # Update plural -> kind mapping (first-registered wins).
        if plural not in self._plural_to_kind:
            self._plural_to_kind[plural] = kind

        self._rebuild_sorted()

    def _rebuild_sorted(self) -> None:
        """Rebuild _sorted_entries sorted by len(kind) descending."""
        all_entries: list[KindEntry] = []
        for entries in self._kind_to_entries.values():
            all_entries.extend(entries)
        # Deduplicate (same entry from multiple register calls).
        seen: set[tuple[str, str, str]] = set()
        unique: list[KindEntry] = []
        for e in all_entries:
            key = (e.kind, e.plural, e.group)
            if key not in seen:
                seen.add(key)
                unique.append(e)
        self._sorted_entries = sorted(unique, key=lambda e: len(e.kind), reverse=True)

    def register_from_crd(self, crd_spec: dict) -> None:
        """Auto-register from CRD spec sub-dict.

        Expects: {"group": "...", "names": {"kind": "...", "plural": "..."}}.
        Silently skips if kind or plural is missing.
        """
        names = crd_spec.get("names", {})
        kind = names.get("kind")
        plural = names.get("plural")
        group = crd_spec.get("group", "")
        if not kind or not plural:
            return
        self.register(kind, plural, group)

    def is_ref_field(
        self,
        field_name: str,
        current_group: str = "",
    ) -> tuple[bool, str | None, str | None, str | None]:
        """Check if field_name is a reference to a known Kind.

        Returns (is_ref, target_kind, target_plural, target_group).

        Uses CamelCase-aware longest-match-first. The current_group
        parameter breaks ties when a Kind exists in multiple API groups.

        If ambiguous (multiple groups, none matching current_group),
        returns (False, None, None, None) -- precision > recall.
        """
        if not field_name:
            return (False, None, None, None)

        lower_name = field_name.lower()

        # 1. Well-known compounds (checked first, highest priority).
        for compound_key, (wk_kind, wk_plural, wk_group) in _WELL_KNOWN_COMPOUND.items():
            if lower_name == compound_key or lower_name.endswith(compound_key):
                return (True, wk_kind, wk_plural, wk_group)

        # 2. Dynamic suffix matching — iterate sorted entries (longest Kind first).
        for entry in self._sorted_entries:
            kind = entry.kind
            kind_lower = kind.lower()

            # Check suffixes: {Kind}Ref and {Kind}Name.
            matched = False
            for suffix in ("Ref", "Name"):
                # Case-sensitive PascalCase match.
                target_suffix = kind + suffix
                if field_name.endswith(target_suffix):
                    prefix_len = len(field_name) - len(target_suffix)
                    if self._check_boundary(field_name, prefix_len):
                        matched = True
                        break

                # Lowercase match (for fully-lowercase field names).
                # Handles both exact ("secretref") and prefixed ("localsecretref").
                target_lower = kind_lower + suffix.lower()
                if lower_name.endswith(target_lower):
                    matched = True
                    break

            if matched:
                return self._resolve_entry(kind, current_group)

        # 3. Short-name alias fallback.
        # Check if the field base (before Ref/Name suffix) matches a short alias.
        for suffix_lower in ("ref", "name"):
            if lower_name.endswith(suffix_lower):
                base = lower_name[: -len(suffix_lower)]
                if base in _SHORT_NAME_ALIASES:
                    alias_kind = _SHORT_NAME_ALIASES[base]
                    if alias_kind in self._kind_to_entries:
                        return self._resolve_entry(alias_kind, current_group)

        return (False, None, None, None)

    @staticmethod
    def _check_boundary(field_name: str, prefix_len: int) -> bool:
        """Verify CamelCase word boundary before the Kind token.

        A boundary exists if:
        - prefix_len == 0 (Kind starts at beginning of field name), OR
        - The character before the Kind token is lowercase (camelCase transition).
        """
        if prefix_len == 0:
            return True
        char_before = field_name[prefix_len - 1]
        return char_before.islower()

    def _resolve_entry(
        self,
        kind: str,
        current_group: str,
    ) -> tuple[bool, str | None, str | None, str | None]:
        """Resolve a matched Kind to a specific entry, handling multi-group.

        Returns (True, kind, plural, group) or (False, None, None, None)
        if ambiguous.
        """
        entries = self._kind_to_entries.get(kind, [])
        if not entries:
            return (False, None, None, None)

        if len(entries) == 1:
            e = entries[0]
            return (True, e.kind, e.plural, e.group)

        # Multi-group tie-breaking.
        # 1. Prefer entry matching current_group.
        if current_group:
            for e in entries:
                if e.group == current_group:
                    return (True, e.kind, e.plural, e.group)

        # 2. Prefer core entries.
        core_entries = [e for e in entries if e.is_core]
        if len(core_entries) == 1:
            e = core_entries[0]
            return (True, e.kind, e.plural, e.group)

        # 3. Ambiguous -- suppress edge (precision > recall).
        return (False, None, None, None)

    def kind_to_plural(self, kind: str) -> str | None:
        """Return plural for a Kind. Returns None if not registered."""
        entries = self._kind_to_entries.get(kind, [])
        if entries:
            return entries[0].plural
        return None

    def plural_to_kind(self, plural: str) -> str | None:
        """Return Kind for a plural. Returns None if not registered."""
        return self._plural_to_kind.get(plural)

    def group_for_kind(self, kind: str) -> str | None:
        """Return group for a Kind. Returns None if not registered."""
        entries = self._kind_to_entries.get(kind, [])
        if entries:
            return entries[0].group
        return None

    def all_kinds(self) -> set[str]:
        """All registered Kind names."""
        return set(self._kind_to_entries.keys())

    def all_plurals(self) -> set[str]:
        """All registered plural names."""
        return set(self._plural_to_kind.keys())

    def core_plurals(self) -> set[str]:
        """Only bootstrap (is_core=True) resource plurals."""
        result: set[str] = set()
        for entries in self._kind_to_entries.values():
            for e in entries:
                if e.is_core:
                    result.add(e.plural)
        return result

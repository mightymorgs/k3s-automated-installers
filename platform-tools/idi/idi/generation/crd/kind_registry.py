"""Unified Kind registry for CRD field classification.

Replaces 6 hardcoded dictionaries spread across 4 files with a single
auto-populated registry. Supports runtime registration from CRD specs,
CamelCase-aware longest-match field lookup, and multi-group tie-breaking.

Zero internal imports from the idi package -- leaf module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class KindEntry:
    """A registered Kubernetes resource Kind."""

    kind: str       # e.g., "Secret"
    plural: str     # e.g., "secrets"
    group: str      # e.g., "core"
    is_core: bool   # True for bootstrap resources
    service: str = ""  # Service that owns this Kind; "" for core K8s resources


@dataclass(frozen=True)
class KindCandidate:
    """A candidate Kind match from fuzzy resolution."""

    kind: str
    api_group: str | None
    score: float
    match_type: str  # "plural_exact" | "suffix_unique" | "camel_tail" | "bare_kind"


_FUZZY_DENYLIST: frozenset[str] = frozenset({
    "role", "service", "policy", "type", "mode", "strategy",
    "provider", "status", "class", "event", "rule", "group", "user",
})

_INFRASTRUCTURE_PREFIXES: frozenset[str] = frozenset({
    "backend", "upstream", "target", "peer", "source", "default",
})

_CORROBORATING_SIBLINGS: frozenset[str] = frozenset({
    "namespace", "kind", "apiGroup", "apiVersion", "group",
})

_REF_SUFFIXES: tuple[str, ...] = ("Ref", "Name", "Key")


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
        self._plural_to_entries: dict[str, list[KindEntry]] = {}
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
        service: str = "",
    ) -> None:
        """Register a Kind with its plural form, optional API group, and owning service.

        Appends to existing entries if the same Kind is registered with a
        different group. Rebuilds the sorted entry list after each call.
        """
        entry = KindEntry(kind=kind, plural=plural, group=group, is_core=is_core, service=service)

        entries = self._kind_to_entries.setdefault(kind, [])
        # Avoid duplicates.
        if entry not in entries:
            entries.append(entry)

        # Update plural -> entries mapping (append, no longer first-wins).
        plural_list = self._plural_to_entries.setdefault(plural, [])
        if entry not in plural_list:
            plural_list.append(entry)

        self._rebuild_sorted()

    def _rebuild_sorted(self) -> None:
        """Rebuild _sorted_entries sorted by len(kind) descending."""
        all_entries: list[KindEntry] = []
        for entries in self._kind_to_entries.values():
            all_entries.extend(entries)
        # Deduplicate (same entry from multiple register calls).
        seen: set[tuple[str, str, str, str]] = set()
        unique: list[KindEntry] = []
        for e in all_entries:
            key = (e.kind, e.plural, e.group, e.service)
            if key not in seen:
                seen.add(key)
                unique.append(e)
        self._sorted_entries = sorted(unique, key=lambda e: len(e.kind), reverse=True)

    def register_from_crd(self, crd_spec: dict, service: str = "") -> None:
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
        self.register(kind, plural, group, service=service)

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
        entries = self._plural_to_entries.get(plural, [])
        if entries:
            return entries[0].kind
        return None

    def group_for_kind(self, kind: str) -> str | None:
        """Return group for a Kind. Returns None if not registered."""
        entries = self._kind_to_entries.get(kind, [])
        if entries:
            return entries[0].group
        return None

    def kinds_for_group(self, group: str) -> set[str]:
        """Return all distinct Kind names registered for a given API group."""
        result: set[str] = set()
        for kind_name, entries in self._kind_to_entries.items():
            for e in entries:
                if e.group == group:
                    result.add(kind_name)
        return result

    def groups_for_kind(self, kind: str) -> list[str]:
        """Return all groups that contain this Kind name."""
        entries = self._kind_to_entries.get(kind, [])
        return [e.group for e in entries]

    def all_kinds(self) -> set[str]:
        """All registered Kind names."""
        return set(self._kind_to_entries.keys())

    def all_plurals(self) -> set[str]:
        """All registered plural names."""
        return set(self._plural_to_entries.keys())

    def core_plurals(self) -> set[str]:
        """Only bootstrap (is_core=True) resource plurals."""
        result: set[str] = set()
        for entries in self._kind_to_entries.values():
            for e in entries:
                if e.is_core:
                    result.add(e.plural)
        return result

    # ------------------------------------------------------------------
    # Fuzzy resolution (section-05)
    # ------------------------------------------------------------------

    def fuzzy_resolve(
        self,
        field_name: str,
        *,
        scope_service: str | None = None,
        require_unique: bool = True,
        sibling_names: frozenset[str] = frozenset(),
    ) -> list[KindCandidate]:
        """Resolve field name to candidate Kind(s) via 4 lexical heuristics.

        Resolution order (highest confidence first):
        1. Exact plural match (0.80)
        2. Suffix match against Kind endings (0.75)
        3. CamelCase tail segment (0.65 with infra prefix, 0.50 without)
        4. Exact lowercase Kind match (0.55)

        Cross-service penalty: If a candidate's service differs from scope_service
        (and is not a core resource), multiply confidence by 0.7.

        High-risk noun denylist: Common nouns that happen to match Kind names
        are rejected unless corroborated by structural siblings.

        Returns candidates sorted by score descending. Typically 0 or 1 results.
        """
        clean_name = field_name.rstrip("[]")
        if len(clean_name) < 2:
            return []

        normalized = clean_name.lower()

        # Try heuristics in confidence order; first match wins.
        candidates = (
            self._fuzzy_try_plural(normalized, scope_service, require_unique)
            or self._fuzzy_try_suffix(clean_name, scope_service)
            or self._fuzzy_try_camel_tail(clean_name, scope_service)
            or self._fuzzy_try_bare_kind(clean_name, scope_service)
        )

        if not candidates:
            return []

        # Denylist gate: strip ref suffix, check field base against denylist.
        # For simple (non-compound) field names, also check the resolved Kind
        # to catch plural forms like "services" -> Service -> "service".
        base_for_deny = clean_name.lower()
        for suffix in _REF_SUFFIXES:
            if base_for_deny.endswith(suffix.lower()):
                base_for_deny = base_for_deny[: -len(suffix)]
                break

        is_denylisted = base_for_deny in _FUZZY_DENYLIST

        if not is_denylisted:
            # Only apply Kind-level denylist for simple field names (1 segment,
            # or 2 segments where the last is a ref suffix). Compound names like
            # "backendServices" have structural context and should not be blocked.
            segments = self._decompose_camel_case(clean_name)
            is_simple = len(segments) <= 1 or (
                len(segments) == 2 and segments[-1] in _REF_SUFFIXES
            )
            if is_simple:
                is_denylisted = candidates[0].kind.lower() in _FUZZY_DENYLIST

        if is_denylisted:
            if not sibling_names.intersection(_CORROBORATING_SIBLINGS):
                return []

        return candidates

    def _fuzzy_try_plural(
        self,
        normalized: str,
        scope_service: str | None,
        require_unique: bool,
    ) -> list[KindCandidate]:
        """Heuristic 1: exact plural match (confidence 0.80)."""
        entries = self._plural_to_entries.get(normalized, [])
        if not entries:
            return []

        if require_unique:
            services = {e.service for e in entries if e.service != ""}
            if len(services) > 1:
                return []

        entry = self._pick_best_entry(entries, scope_service)
        score = self._apply_cross_service_penalty(entry, 0.80, scope_service)
        return [KindCandidate(
            kind=entry.kind, api_group=entry.group,
            score=score, match_type="plural_exact",
        )]

    def _fuzzy_try_suffix(
        self, field_name: str, scope_service: str | None,
    ) -> list[KindCandidate]:
        """Heuristic 2: suffix match against Kind endings (confidence 0.75).

        Strip Ref/Name/Key suffix, require base >= 4 chars,
        Kind must be strictly longer than base (proper suffix).
        """
        bases: list[str] = []
        for suffix in _REF_SUFFIXES:
            if field_name.endswith(suffix):
                base = field_name[: -len(suffix)]
                if len(base) >= 4:
                    bases.append(base)
        # Also try raw name.
        if len(field_name) >= 4:
            bases.append(field_name)

        for base in bases:
            base_lower = base.lower()
            matched_kinds: dict[str, KindEntry] = {}
            for entry in self._sorted_entries:
                kind_lower = entry.kind.lower()
                if kind_lower.endswith(base_lower) and len(entry.kind) > len(base):
                    if entry.kind not in matched_kinds:
                        matched_kinds[entry.kind] = entry

            if len(matched_kinds) == 1:
                entry = next(iter(matched_kinds.values()))
                # If multiple entries for same kind, pick best.
                all_entries = self._kind_to_entries.get(entry.kind, [entry])
                entry = self._pick_best_entry(all_entries, scope_service)
                score = self._apply_cross_service_penalty(entry, 0.75, scope_service)
                return [KindCandidate(
                    kind=entry.kind, api_group=entry.group,
                    score=score, match_type="suffix_unique",
                )]

        return []

    def _fuzzy_try_camel_tail(
        self, field_name: str, scope_service: str | None,
    ) -> list[KindCandidate]:
        """Heuristic 3: CamelCase tail segment (confidence 0.65/0.50)."""
        segments = self._decompose_camel_case(field_name)
        if len(segments) < 2:
            return []

        tail_idx = len(segments) - 1
        if segments[tail_idx] in _REF_SUFFIXES:
            tail_idx -= 1
            if tail_idx < 0:
                return []

        tail = segments[tail_idx]
        prefix_idx = tail_idx - 1
        prefix = segments[prefix_idx] if prefix_idx >= 0 else ""

        # Resolve tail to a Kind (exact, case-insensitive, then plural).
        # Uniqueness guard: must resolve to exactly one distinct Kind name.
        target_entry: KindEntry | None = None
        tail_lower = tail.lower()

        if tail in self._kind_to_entries:
            entries = self._kind_to_entries[tail]
            target_entry = self._pick_best_entry(entries, scope_service)
        else:
            # Case-insensitive Kind name lookup — must be unique.
            matched_kinds: list[str] = [
                k for k in self._kind_to_entries if k.lower() == tail_lower
            ]
            if len(matched_kinds) == 1:
                entries = self._kind_to_entries[matched_kinds[0]]
                target_entry = self._pick_best_entry(entries, scope_service)
            elif not matched_kinds:
                # Plural lookup — check uniqueness across Kind names.
                if tail_lower in self._plural_to_entries:
                    entries = self._plural_to_entries[tail_lower]
                    unique_kinds = {e.kind for e in entries}
                    if len(unique_kinds) == 1:
                        target_entry = self._pick_best_entry(entries, scope_service)

        if target_entry is None:
            return []

        raw_score = 0.65 if prefix.lower() in _INFRASTRUCTURE_PREFIXES else 0.50
        score = self._apply_cross_service_penalty(target_entry, raw_score, scope_service)
        return [KindCandidate(
            kind=target_entry.kind, api_group=target_entry.group,
            score=score, match_type="camel_tail",
        )]

    def _fuzzy_try_bare_kind(
        self, field_name: str, scope_service: str | None,
    ) -> list[KindCandidate]:
        """Heuristic 4: exact lowercase Kind match (confidence 0.55).

        Score 0.55 is deliberately below the 0.7 emission threshold.
        The caller (detect_fuzzy_kind_name) multiplies by depth_confidence,
        so only top-level fields with strong structural signals can reach 0.7.
        The outer denylist gate handles high-risk nouns; non-denylisted
        bare matches rely on the threshold as the precision guard.
        """
        field_lower = field_name.lower()
        for kind, entries in self._kind_to_entries.items():
            if kind.lower() == field_lower:
                entry = self._pick_best_entry(entries, scope_service)
                score = self._apply_cross_service_penalty(entry, 0.55, scope_service)
                return [KindCandidate(
                    kind=entry.kind, api_group=entry.group,
                    score=score, match_type="bare_kind",
                )]
        return []

    def _pick_best_entry(
        self, entries: list[KindEntry], scope_service: str | None,
    ) -> KindEntry:
        """Select best entry: prefer same-service, then core, then first."""
        if len(entries) == 1:
            return entries[0]
        if scope_service:
            for e in entries:
                if e.service == scope_service:
                    return e
        for e in entries:
            if e.service == "" or e.is_core:
                return e
        return entries[0]

    def _apply_cross_service_penalty(
        self, entry: KindEntry, raw_score: float, scope_service: str | None,
    ) -> float:
        """Apply 0.7 multiplier for cross-service matches. Core kinds exempt."""
        if scope_service is None:
            return raw_score
        if entry.service == "" or entry.service == scope_service:
            return raw_score
        return raw_score * 0.7

    @staticmethod
    def _decompose_camel_case(name: str) -> list[str]:
        """Split a camelCase or PascalCase name into segments.

        'backendServices' -> ['backend', 'Services']
        'peerConfigRef' -> ['peer', 'Config', 'Ref']
        'gateways' -> ['gateways']
        'bgpV2Peers' -> ['bgp', 'V', '2', 'Peers']

        Note: Consecutive uppercase letters are split individually
        (e.g., 'HTTPSGateway' -> ['H','T','T','P','S','Gateway']).
        This is acceptable because the tail segment is still correct.
        """
        return re.findall(r"[A-Z][a-z]*|[a-z]+|[0-9]+", name)

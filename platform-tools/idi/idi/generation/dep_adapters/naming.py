"""Naming convention detection and word splitting.

Ported from RESTler ``ApiResourceTypes.fs:13-170``.  Each name component
can have its own convention (e.g., ``the-accounts/{the_account_id}`` —
container uses hyphens, parameter uses underscores).

RestTestGen-style Porter stemming added for cross-morphological matching
(``NormalizedParameterName.java`` in SeUniVr/RestTestGen).
"""
from __future__ import annotations

import enum
import re

import inflect
from nltk.stem import PorterStemmer

_engine = inflect.engine()
_stemmer = PorterStemmer()


class Convention(enum.Enum):
    CAMEL = "camel"
    PASCAL = "pascal"
    SNAKE = "snake"
    KEBAB = "kebab"


# RESTler: RegexSplitMap — convention-specific splitting patterns.
_SPLIT_PATTERNS: dict[Convention, re.Pattern] = {
    Convention.CAMEL: re.compile(r"(?<=[a-z0-9])(?=[A-Z])"),
    Convention.PASCAL: re.compile(r"(?<=[a-z0-9])(?=[A-Z])"),
    Convention.SNAKE: re.compile(r"_"),
    Convention.KEBAB: re.compile(r"-"),
}

_NORMALIZED_SEP = "__"


def detect_convention(name: str) -> Convention:
    """Auto-detect naming convention from a string.

    RESTler: ``getConvention`` in ``ApiResourceTypes.fs:151``.
    """
    if not name:
        return Convention.CAMEL
    has_upper = any(c.isupper() for c in name)
    has_lower = any(c.islower() for c in name)
    has_underscores = "_" in name
    has_hyphens = "-" in name

    if has_upper and has_lower:
        return Convention.PASCAL if name[0].isupper() else Convention.CAMEL
    if has_underscores:
        return Convention.SNAKE
    if has_hyphens:
        return Convention.KEBAB
    return Convention.CAMEL


def split_words(name: str, convention: Convention | None = None) -> list[str]:
    """Split a name into words by its naming convention.

    RESTler: ``getTypeWords`` in ``ApiResourceTypes.fs:171``.
    """
    if not name:
        return []
    if convention is None:
        convention = detect_convention(name)
    pattern = _SPLIT_PATTERNS[convention]
    return [w for w in pattern.split(name) if w]


def normalize(name: str) -> str:
    """Normalize a name: split by convention → lowercase → join with ``__``.

    RESTler: ``candidateTypeNames = getCandidateTypeNames() |> List.map (fun x -> x.ToLower())``
    """
    words = split_words(name)
    return _NORMALIZED_SEP.join(w.lower() for w in words)


def singularize(name: str) -> str:
    """Singularize a name.  Wraps inflect (Python equivalent of Pluralize.NET.Core)."""
    result = _engine.singular_noun(name)
    return result if result else name


def stem(name: str) -> str:
    """Porter-stem a name (RestTestGen-style).

    Splits by convention, stems each token, re-joins with ``__``.
    Ported from ``NormalizedParameterName.computeNormalizedName()``
    in SeUniVr/RestTestGen.
    """
    words = split_words(name)
    if not words:
        return name.lower()
    return _NORMALIZED_SEP.join(_stemmer.stem(w.lower()) for w in words)


def stem_token(word: str) -> str:
    """Porter-stem a single token."""
    return _stemmer.stem(word.lower())


# ---------------------------------------------------------------------------
# ID synonym normalization (#8)
# ---------------------------------------------------------------------------

_ID_SYNONYMS: tuple[str, ...] = ("_uuid", "_guid", "_uid")


def normalize_id_suffix(name: str) -> str:
    """Canonicalize ID-like suffixes to _id for producer-consumer matching.

    Converts _uuid, _guid, _uid suffixes to _id.
    Leaves non-ID-like names unchanged.
    """
    lower = name.lower()
    for synonym in _ID_SYNONYMS:
        if lower.endswith(synonym):
            return name[: len(name) - len(synonym)] + "_id"
    return name

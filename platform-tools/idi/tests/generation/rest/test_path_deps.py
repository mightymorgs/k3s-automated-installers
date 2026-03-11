"""Tests for underscore/hyphen path normalization in _match_segment (section-04)."""
from idi.generation.dep_adapters.path_deps import _match_segment


class TestMatchSegmentNormalization:
    """Underscore-to-hyphen normalization in _match_segment."""

    def test_underscore_to_hyphen_exact_match(self):
        assert _match_segment("tag_protections", {"tag-protections"}) == "tag-protections"

    def test_underscore_to_hyphen_multi_word(self):
        assert _match_segment("user_groups", {"user-groups"}) == "user-groups"

    def test_no_underscore_unchanged(self):
        assert _match_segment("groups", {"groups"}) == "groups"

    def test_triple_segment_underscore(self):
        assert _match_segment("api_v3_series", {"api-v3-series"}) == "api-v3-series"

    def test_already_hyphenated_still_matches(self):
        """If segment already uses hyphens, normalization is a no-op."""
        assert _match_segment("tag-protections", {"tag-protections"}) == "tag-protections"

    def test_no_match_returns_none(self):
        assert _match_segment("nonexistent_resource", {"something-else"}) is None

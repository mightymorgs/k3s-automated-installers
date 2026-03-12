"""Tests for RFC 6570 URI template parser (#9)."""
from idi.generation.path_extractor import parse_rfc6570_template


class TestRFC6570Parser:
    def test_simple_path_param(self):
        result = parse_rfc6570_template("/users/{id}")
        assert len(result) == 1
        assert result[0]["name"] == "id"
        assert result[0]["location"] == "path"
        assert result[0]["required"] is True

    def test_reserved_expansion(self):
        result = parse_rfc6570_template("/{+param}")
        params = {p["name"]: p for p in result}
        assert params["param"]["location"] == "path"
        assert params["param"]["required"] is True

    def test_fragment_expansion(self):
        result = parse_rfc6570_template("/{#param}")
        params = {p["name"]: p for p in result}
        assert params["param"]["location"] == "path"
        assert params["param"]["required"] is False

    def test_path_segment_expansion(self):
        result = parse_rfc6570_template("{/param}")
        params = {p["name"]: p for p in result}
        assert params["param"]["location"] == "path"
        assert params["param"]["required"] is True

    def test_semicolon_expansion(self):
        result = parse_rfc6570_template("{;param}")
        params = {p["name"]: p for p in result}
        assert params["param"]["location"] == "path"
        assert params["param"]["required"] is False

    def test_query_expansion_multiple_params(self):
        result = parse_rfc6570_template("/users{?filter,sort}")
        params = {p["name"]: p for p in result}
        assert len(params) == 2
        assert params["filter"]["location"] == "query"
        assert params["filter"]["required"] is False
        assert params["sort"]["location"] == "query"
        assert params["sort"]["required"] is False

    def test_query_continuation(self):
        result = parse_rfc6570_template("{&param}")
        params = {p["name"]: p for p in result}
        assert params["param"]["location"] == "query"
        assert params["param"]["required"] is False

    def test_mixed_template(self):
        result = parse_rfc6570_template("/users/{id}{?filter,sort}")
        params = {p["name"]: p for p in result}
        assert len(params) == 3
        assert params["id"]["location"] == "path"
        assert params["id"]["required"] is True
        assert params["filter"]["location"] == "query"
        assert params["sort"]["location"] == "query"

    def test_explode_modifier_stripped(self):
        result = parse_rfc6570_template("{?list*}")
        assert result[0]["name"] == "list"

    def test_maxlen_modifier_stripped(self):
        result = parse_rfc6570_template("{param:3}")
        assert result[0]["name"] == "param"

    def test_no_templates(self):
        result = parse_rfc6570_template("/users/list")
        assert result == []

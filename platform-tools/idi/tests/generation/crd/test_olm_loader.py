"""Tests for OLM CSV loader — CRD Phase 4 Section 01."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from idi.generation.crd.olm_loader import (
    GVKRef,
    extract_gvk_dependencies,
    fetch_olm_csv,
)

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase4"


# ---------------------------------------------------------------------------
# GVKRef dataclass
# ---------------------------------------------------------------------------


class TestGVKRef:
    def test_frozen(self):
        """GVKRef is immutable."""
        ref = GVKRef(kind="Certificate", group="cert-manager.io", version="v1", plural="certificates")
        with pytest.raises(AttributeError):
            ref.kind = "Other"  # type: ignore[misc]

    def test_stores_fields(self):
        ref = GVKRef(kind="Certificate", group="cert-manager.io", version="v1", plural="certificates")
        assert ref.kind == "Certificate"
        assert ref.group == "cert-manager.io"
        assert ref.version == "v1"
        assert ref.plural == "certificates"

    def test_equality(self):
        a = GVKRef(kind="Certificate", group="cert-manager.io", version="v1", plural="certificates")
        b = GVKRef(kind="Certificate", group="cert-manager.io", version="v1", plural="certificates")
        assert a == b


# ---------------------------------------------------------------------------
# extract_gvk_dependencies()
# ---------------------------------------------------------------------------


class TestExtractGvkDependencies:
    def test_valid_csv(self):
        """Valid CSV returns correct owned and required GVKRef lists."""
        csv = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [
                        {"name": "certificates.cert-manager.io", "kind": "Certificate", "version": "v1"},
                    ],
                    "required": [
                        {"name": "secrets.core", "kind": "Secret", "version": "v1"},
                    ],
                },
            },
        }
        owned, required = extract_gvk_dependencies(csv)
        assert len(owned) == 1
        assert owned[0].kind == "Certificate"
        assert owned[0].group == "cert-manager.io"
        assert owned[0].plural == "certificates"
        assert len(required) == 1
        assert required[0].kind == "Secret"

    def test_group_extraction(self):
        """Group extracted after first dot."""
        csv = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [
                        {"name": "orders.acme.cert-manager.io", "kind": "Order", "version": "v1"},
                    ],
                    "required": [],
                },
            },
        }
        owned, _ = extract_gvk_dependencies(csv)
        assert owned[0].group == "acme.cert-manager.io"
        assert owned[0].plural == "orders"

    def test_name_no_dot_skipped(self):
        """Entry with name lacking a dot is skipped."""
        csv = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [
                        {"name": "badname", "kind": "Bad", "version": "v1"},
                    ],
                    "required": [],
                },
            },
        }
        owned, required = extract_gvk_dependencies(csv)
        assert owned == []

    def test_missing_kind_skipped(self):
        """Entry missing 'kind' is skipped."""
        csv = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [
                        {"name": "things.example.io", "version": "v1"},
                    ],
                    "required": [],
                },
            },
        }
        owned, _ = extract_gvk_dependencies(csv)
        assert owned == []

    def test_missing_name_skipped(self):
        """Entry missing 'name' is skipped."""
        csv = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [
                        {"kind": "Thing", "version": "v1"},
                    ],
                    "required": [],
                },
            },
        }
        owned, _ = extract_gvk_dependencies(csv)
        assert owned == []

    def test_required_null(self):
        """required=null returns empty list."""
        csv = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [],
                    "required": None,
                },
            },
        }
        owned, required = extract_gvk_dependencies(csv)
        assert required == []

    def test_owned_null(self):
        """owned=null returns empty list."""
        csv = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": None,
                    "required": [],
                },
            },
        }
        owned, required = extract_gvk_dependencies(csv)
        assert owned == []

    def test_missing_crd_section(self):
        """Missing customresourcedefinitions returns ([], [])."""
        csv = {"spec": {}}
        owned, required = extract_gvk_dependencies(csv)
        assert owned == []
        assert required == []

    def test_empty_lists(self):
        """Empty owned and required return ([], [])."""
        csv = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [],
                    "required": [],
                },
            },
        }
        owned, required = extract_gvk_dependencies(csv)
        assert owned == []
        assert required == []

    def test_version_default_empty(self):
        """Missing version defaults to empty string."""
        csv = {
            "spec": {
                "customresourcedefinitions": {
                    "owned": [
                        {"name": "things.example.io", "kind": "Thing"},
                    ],
                    "required": [],
                },
            },
        }
        owned, _ = extract_gvk_dependencies(csv)
        assert owned[0].version == ""


# ---------------------------------------------------------------------------
# fetch_olm_csv() — mocked HTTP
# ---------------------------------------------------------------------------


def _mock_urlopen_response(data: bytes, status: int = 200):
    """Create a mock response for urlopen."""
    resp = MagicMock()
    resp.read.return_value = data
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestFetchOlmCsv:
    def test_successful_fetch(self, tmp_path):
        """Successful fetch writes cache file and returns parsed dict."""
        payload = {"spec": {"customresourcedefinitions": {"owned": [], "required": []}}}
        raw = json.dumps(payload).encode()

        with patch("idi.generation.crd.olm_loader.urlopen") as mock_open:
            mock_open.return_value = _mock_urlopen_response(raw)
            result = fetch_olm_csv("test-op", cache_dir=str(tmp_path / "olm"))

        assert result is not None
        assert result["spec"]["customresourcedefinitions"]["owned"] == []
        # Verify cache file was written.
        cache_file = tmp_path / "olm" / "test-op" / "csv.yaml"
        assert cache_file.exists()

    def test_cache_directory_created(self, tmp_path):
        """Cache directory created if not exists."""
        payload = {"spec": {}}
        raw = json.dumps(payload).encode()

        cache_dir = tmp_path / "deep" / "nested" / "olm"
        with patch("idi.generation.crd.olm_loader.urlopen") as mock_open:
            mock_open.return_value = _mock_urlopen_response(raw)
            fetch_olm_csv("test-op", cache_dir=str(cache_dir))

        assert (cache_dir / "test-op" / "csv.yaml").exists()

    def test_cache_hit_no_http(self, tmp_path):
        """Cache hit returns data without HTTP call."""
        import yaml
        cache_dir = tmp_path / "olm"
        cache_file = cache_dir / "test-op" / "csv.yaml"
        cache_file.parent.mkdir(parents=True)
        expected = {"spec": {"cached": True}}
        cache_file.write_text(yaml.dump(expected), encoding="utf-8")

        with patch("idi.generation.crd.olm_loader.urlopen") as mock_open:
            result = fetch_olm_csv("test-op", cache_dir=str(cache_dir))

        mock_open.assert_not_called()
        assert result == expected

    def test_http_404_returns_none(self, tmp_path):
        """HTTP 404 returns None."""
        with patch("idi.generation.crd.olm_loader.urlopen") as mock_open:
            mock_open.side_effect = HTTPError(
                "http://example.com", 404, "Not Found", {}, None,
            )
            result = fetch_olm_csv("missing-op", cache_dir=str(tmp_path / "olm"))

        assert result is None

    def test_fallback_name_tried(self, tmp_path):
        """Fallback '{service}-operator' tried on 404 for primary name."""
        payload = {"spec": {"found": True}}
        raw = json.dumps(payload).encode()

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise HTTPError("http://example.com", 404, "Not Found", {}, None)
            return _mock_urlopen_response(raw)

        with patch("idi.generation.crd.olm_loader.urlopen", side_effect=side_effect):
            result = fetch_olm_csv("myservice", cache_dir=str(tmp_path / "olm"))

        assert result is not None
        assert result["spec"]["found"] is True
        assert call_count == 2

    def test_fallback_also_404_returns_none(self, tmp_path):
        """Both primary and fallback 404 -> None."""
        with patch("idi.generation.crd.olm_loader.urlopen") as mock_open:
            mock_open.side_effect = HTTPError(
                "http://example.com", 404, "Not Found", {}, None,
            )
            result = fetch_olm_csv("missing", cache_dir=str(tmp_path / "olm"))

        assert result is None

    def test_malformed_json_returns_none(self, tmp_path):
        """Malformed JSON response returns None."""
        with patch("idi.generation.crd.olm_loader.urlopen") as mock_open:
            mock_open.return_value = _mock_urlopen_response(b"not json{{{")
            result = fetch_olm_csv("bad", cache_dir=str(tmp_path / "olm"))

        assert result is None

    def test_path_traversal_sanitized(self, tmp_path):
        """Operator name with '..' sanitized — slashes stripped, path stays under cache_dir."""
        payload = {"spec": {}}
        raw = json.dumps(payload).encode()

        with patch("idi.generation.crd.olm_loader.urlopen") as mock_open:
            mock_open.return_value = _mock_urlopen_response(raw)
            result = fetch_olm_csv("../../etc/passwd", cache_dir=str(tmp_path / "olm"))

        # Key invariant: no cache file should escape the cache_dir.
        cache_dir_resolved = (tmp_path / "olm").resolve()
        if result is not None:
            for p in cache_dir_resolved.rglob("csv.yaml"):
                assert str(p.resolve()).startswith(str(cache_dir_resolved))

    def test_timeout_returns_none(self, tmp_path):
        """Timeout after retries returns None."""
        with patch("idi.generation.crd.olm_loader.urlopen") as mock_open:
            mock_open.side_effect = TimeoutError("timed out")
            with patch("idi.generation.crd.olm_loader.time.sleep"):
                result = fetch_olm_csv("slow-op", cache_dir=str(tmp_path / "olm"))

        assert result is None

    def test_http_500_retries(self, tmp_path):
        """HTTP 500 retries and eventually returns None."""
        with patch("idi.generation.crd.olm_loader.urlopen") as mock_open:
            mock_open.side_effect = HTTPError(
                "http://example.com", 500, "Server Error", {}, None,
            )
            with patch("idi.generation.crd.olm_loader.time.sleep"):
                result = fetch_olm_csv("failing", cache_dir=str(tmp_path / "olm"))

        assert result is None


# ---------------------------------------------------------------------------
# Golden fixture tests
# ---------------------------------------------------------------------------


class TestGoldenFixtures:
    def test_cert_manager_golden(self):
        """Real cert-manager response parses correctly."""
        fixture_path = _FIXTURES_DIR / "olm_cert_manager.json"
        csv = json.loads(fixture_path.read_text(encoding="utf-8"))
        owned, required = extract_gvk_dependencies(csv)

        assert len(owned) == 6
        kinds = {g.kind for g in owned}
        assert "Certificate" in kinds
        assert "Issuer" in kinds
        assert "ClusterIssuer" in kinds
        assert "Order" in kinds

        # cert-manager has no required deps.
        assert required == []

        # Verify group extraction for nested group.
        order = next(g for g in owned if g.kind == "Order")
        assert order.group == "acme.cert-manager.io"
        assert order.plural == "orders"

    def test_external_secrets_golden(self):
        """Real external-secrets response parses correctly."""
        fixture_path = _FIXTURES_DIR / "olm_external_secrets.json"
        csv = json.loads(fixture_path.read_text(encoding="utf-8"))
        owned, required = extract_gvk_dependencies(csv)

        assert len(owned) == 5
        kinds = {g.kind for g in owned}
        assert "ExternalSecret" in kinds
        assert "SecretStore" in kinds

        # ESO requires cert-manager.
        assert len(required) == 1
        assert required[0].kind == "Certificate"
        assert required[0].group == "cert-manager.io"

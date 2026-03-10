"""Tests for split_camel_case — CRD Phase 3 Section 07."""
from __future__ import annotations

from idi.generation.crd.ref_detector import split_camel_case


class TestSplitCamelCase:
    def test_refresh_interval(self):
        assert split_camel_case("refreshInterval") == ["refresh", "Interval"]

    def test_ca_bundle_secret_name(self):
        assert split_camel_case("caBundleSecretName") == ["ca", "Bundle", "Secret", "Name"]

    def test_secret_ref(self):
        assert split_camel_case("secretRef") == ["secret", "Ref"]

    def test_metadata(self):
        assert split_camel_case("metadata") == ["metadata"]

    def test_server_url(self):
        assert split_camel_case("serverURL") == ["server", "URL"]

    def test_server_tls_config(self):
        assert split_camel_case("serverTLSConfig") == ["server", "TLS", "Config"]

    def test_empty_string(self):
        assert split_camel_case("") == [""]

    def test_single_upper(self):
        assert split_camel_case("X") == ["X"]

    def test_all_lower(self):
        assert split_camel_case("abc") == ["abc"]

    def test_https_connection(self):
        assert split_camel_case("HTTPSConnection") == ["HTTPS", "Connection"]

    def test_pascal_case(self):
        assert split_camel_case("SecretStore") == ["Secret", "Store"]

    def test_preferred_during_scheduling(self):
        tokens = split_camel_case("preferredDuringSchedulingIgnoredDuringExecution")
        assert tokens == ["preferred", "During", "Scheduling", "Ignored", "During", "Execution"]

"""Tests for ALM label-based edge detection — Section 02."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.olm_loader import GVKRef
from idi.generation.crd.topo_sort import DependencyEdge
from idi.generation.dep_adapters.olm_deps import OlmDepAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry_with_strimzi() -> KindRegistry:
    """Registry with Strimzi CRDs pre-registered."""
    reg = KindRegistry()
    reg.register("Kafka", "kafkas", "kafka.strimzi.io", service="strimzi")
    reg.register("KafkaTopic", "kafkatopics", "kafka.strimzi.io", service="strimzi")
    reg.register("KafkaUser", "kafkausers", "kafka.strimzi.io", service="strimzi")
    reg.register("KafkaConnect", "kafkaconnects", "kafka.strimzi.io", service="strimzi")
    reg.register("KafkaConnector", "kafkaconnectors", "kafka.strimzi.io", service="strimzi")
    return reg


def _make_strimzi_owned() -> list[GVKRef]:
    """OLM owned GVKs for Strimzi."""
    return [
        GVKRef(kind="Kafka", group="kafka.strimzi.io", version="v1beta2", plural="kafkas"),
        GVKRef(kind="KafkaTopic", group="kafka.strimzi.io", version="v1beta2", plural="kafkatopics"),
        GVKRef(kind="KafkaUser", group="kafka.strimzi.io", version="v1beta2", plural="kafkausers"),
        GVKRef(kind="KafkaConnect", group="kafka.strimzi.io", version="v1beta2", plural="kafkaconnects"),
        GVKRef(kind="KafkaConnector", group="kafka.strimzi.io", version="v1beta2", plural="kafkaconnectors"),
    ]


def _make_examples_with_label(
    child_kind: str, child_name: str, label_key: str, label_value: str,
    parent_kind: str, parent_name: str,
    api_version: str = "kafka.strimzi.io/v1beta2",
) -> list[dict]:
    """Build a minimal 2-example set: parent + child with one label."""
    return [
        {"apiVersion": api_version, "kind": parent_kind,
         "metadata": {"name": parent_name}, "spec": {}},
        {"apiVersion": api_version, "kind": child_kind,
         "metadata": {"name": child_name, "labels": {label_key: label_value}},
         "spec": {}},
    ]


def _extract(adapter: OlmDepAdapter, examples: list[dict],
             owned: list[GVKRef] | None = None,
             registry: KindRegistry | None = None) -> list[DependencyEdge]:
    """Call _extract_alm_label_edges with defaults."""
    return adapter._extract_alm_label_edges(
        examples,
        owned or _make_strimzi_owned(),
        registry or _make_registry_with_strimzi(),
    )


# ---------------------------------------------------------------------------
# Pre-filter tests
# ---------------------------------------------------------------------------


class TestPreFilter:
    """Label key namespace denylist pre-filter."""

    @pytest.mark.parametrize("prefix", [
        "app.kubernetes.io/", "helm.sh/", "kubernetes.io/",
        "k8s.io/", "meta.helm.sh/", "argocd.argoproj.io/",
    ])
    def test_denylist_prefix_rejected(self, prefix):
        """Labels with denylist prefixes are rejected."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", f"{prefix}instance", "production-cluster",
            "Kafka", "production-cluster",
        )
        edges = _extract(adapter, examples)
        assert edges == []

    def test_operator_domain_passes(self):
        """strimzi.io/cluster passes pre-filter."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "strimzi.io/cluster", "production-cluster",
            "Kafka", "production-cluster",
        )
        edges = _extract(adapter, examples)
        assert len(edges) == 1


# ---------------------------------------------------------------------------
# Gate 1: Exact Unique Name Cross-Link
# ---------------------------------------------------------------------------


class TestGate1NameCrossLink:
    """Gate 1: label value must match exactly one example name."""

    def test_exact_match_resolves(self):
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "strimzi.io/cluster", "production-cluster",
            "Kafka", "production-cluster",
        )
        edges = _extract(adapter, examples)
        assert len(edges) == 1
        assert edges[0].target_gk == "kafka.strimzi.io/Kafka"
        assert edges[0].source_gk == "kafka.strimzi.io/KafkaTopic"

    def test_zero_matches_drops(self):
        """Label value matching no example name → no edge."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "strimzi.io/cluster", "nonexistent",
            "Kafka", "production-cluster",
        )
        edges = _extract(adapter, examples)
        assert edges == []

    def test_ambiguous_matches_drops(self):
        """Two examples with same name, different kinds → ambiguous → no edge."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = [
            {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "Kafka",
             "metadata": {"name": "shared-name"}, "spec": {}},
            {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "KafkaConnect",
             "metadata": {"name": "shared-name"}, "spec": {}},
            {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "KafkaTopic",
             "metadata": {"name": "orders-topic",
                          "labels": {"strimzi.io/cluster": "shared-name"}},
             "spec": {}},
        ]
        edges = _extract(adapter, examples)
        assert edges == []

    def test_self_loop_drops(self):
        """Parent Kind == child Kind (self-loop) → no edge."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "Kafka", "kafka-b", "strimzi.io/cluster", "kafka-a",
            "Kafka", "kafka-a",
        )
        edges = _extract(adapter, examples)
        assert edges == []


# ---------------------------------------------------------------------------
# Gate 2: Label Key Domain Match
# ---------------------------------------------------------------------------


class TestGate2DomainMatch:
    """Gate 2: label key domain must match an OLM-owned API group."""

    def test_exact_domain_match(self):
        """Exact match: strimzi.io label domain, strimzi.io in owned groups."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        owned = [GVKRef(kind="Kafka", group="strimzi.io", version="v1", plural="kafkas"),
                 GVKRef(kind="KafkaTopic", group="strimzi.io", version="v1", plural="kafkatopics")]
        reg = KindRegistry()
        reg.register("Kafka", "kafkas", "strimzi.io", service="strimzi")
        reg.register("KafkaTopic", "kafkatopics", "strimzi.io", service="strimzi")
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "strimzi.io/cluster", "production-cluster",
            "Kafka", "production-cluster", api_version="strimzi.io/v1",
        )
        edges = adapter._extract_alm_label_edges(examples, owned, reg)
        assert len(edges) == 1

    def test_dns_suffix_match(self):
        """DNS suffix: strimzi.io label domain matches kafka.strimzi.io group."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "strimzi.io/cluster", "production-cluster",
            "Kafka", "production-cluster",
        )
        edges = _extract(adapter, examples)
        assert len(edges) == 1

    def test_reverse_suffix_match(self):
        """Reverse suffix: postgres-operator.crunchydata.com domain, crunchydata.com group."""
        reg = KindRegistry()
        reg.register("PostgresCluster", "postgresclusters", "crunchydata.com", service="pgo")
        reg.register("PGBackup", "pgbackups", "crunchydata.com", service="pgo")
        owned = [
            GVKRef(kind="PostgresCluster", group="crunchydata.com", version="v1", plural="postgresclusters"),
            GVKRef(kind="PGBackup", group="crunchydata.com", version="v1", plural="pgbackups"),
        ]
        examples = _make_examples_with_label(
            "PGBackup", "daily-backup",
            "postgres-operator.crunchydata.com/cluster", "prod-db",
            "PostgresCluster", "prod-db",
            api_version="crunchydata.com/v1",
        )
        adapter = OlmDepAdapter(registry=reg)
        edges = adapter._extract_alm_label_edges(examples, owned, reg)
        assert len(edges) == 1

    def test_bare_key_drops(self):
        """Key without '/' (bare key like 'cluster') drops."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = [
            {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "Kafka",
             "metadata": {"name": "production-cluster"}, "spec": {}},
            {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "KafkaTopic",
             "metadata": {"name": "orders-topic",
                          "labels": {"cluster": "production-cluster"}},
             "spec": {}},
        ]
        edges = _extract(adapter, examples)
        assert edges == []

    def test_unrelated_domain_drops(self):
        """Unrelated domain (acme.io) with strimzi.io owned groups drops."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "acme.io/cluster", "production-cluster",
            "Kafka", "production-cluster",
        )
        edges = _extract(adapter, examples)
        assert edges == []


# ---------------------------------------------------------------------------
# Gate 3: Generic Value Denylist
# ---------------------------------------------------------------------------


class TestGate3GenericValue:
    """Gate 3: label value must not be a generic example name."""

    @pytest.mark.parametrize("value", [
        "my-cluster", "example", "default", "sample", "test",
        "test-instance", "cluster-example", "example-db",
        "My-Cluster", "EXAMPLE",
    ])
    def test_generic_value_drops(self, value):
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "strimzi.io/cluster", value,
            "Kafka", value,
        )
        edges = _extract(adapter, examples)
        assert edges == [], f"Expected DROP for generic value '{value}'"

    @pytest.mark.parametrize("value", [
        "kafka-production", "strimzi-cluster-1", "production-cluster",
        "orders-db", "payment-service",
    ])
    def test_non_generic_value_passes(self, value):
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "strimzi.io/cluster", value,
            "Kafka", value,
        )
        edges = _extract(adapter, examples)
        assert len(edges) == 1, f"Expected PASS for non-generic value '{value}'"


# ---------------------------------------------------------------------------
# Gate 4: Generic Key Segment
# ---------------------------------------------------------------------------


class TestGate4GenericKeySegment:
    """Gate 4: label key name segment must not be a generic grouping term."""

    @pytest.mark.parametrize("segment", [
        "instance", "managed-by", "part-of", "component", "name", "app", "tier",
    ])
    def test_generic_key_segment_drops(self, segment):
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", f"strimzi.io/{segment}", "production-cluster",
            "Kafka", "production-cluster",
        )
        edges = _extract(adapter, examples)
        assert edges == [], f"Expected DROP for generic key segment '{segment}'"

    @pytest.mark.parametrize("segment", ["cluster", "connect", "leader"])
    def test_non_generic_key_segment_passes(self, segment):
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", f"strimzi.io/{segment}", "production-cluster",
            "Kafka", "production-cluster",
        )
        edges = _extract(adapter, examples)
        assert len(edges) == 1, f"Expected PASS for key segment '{segment}'"


# ---------------------------------------------------------------------------
# Gate 5: Target Kind Validation
# ---------------------------------------------------------------------------


class TestGate5TargetValidation:
    """Gate 5: target Kind must be in OLM owned + KindRegistry."""

    def test_owned_and_registered_passes(self):
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "strimzi.io/cluster", "production-cluster",
            "Kafka", "production-cluster",
        )
        edges = _extract(adapter, examples)
        assert len(edges) == 1

    def test_not_in_owned_drops(self):
        """Parent Kind not in owned set → DROP."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        # Use owned list that does NOT include Kafka
        owned = [GVKRef(kind="KafkaTopic", group="kafka.strimzi.io", version="v1beta2", plural="kafkatopics")]
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "strimzi.io/cluster", "production-cluster",
            "Kafka", "production-cluster",
        )
        edges = adapter._extract_alm_label_edges(examples, owned, _make_registry_with_strimzi())
        assert edges == []

    def test_not_in_registry_drops(self):
        """Parent Kind not in KindRegistry → DROP."""
        empty_reg = KindRegistry()  # No CRDs registered (only core K8s)
        adapter = OlmDepAdapter(registry=empty_reg)
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "strimzi.io/cluster", "production-cluster",
            "Kafka", "production-cluster",
        )
        edges = adapter._extract_alm_label_edges(examples, _make_strimzi_owned(), empty_reg)
        assert edges == []


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    """Integration tests for the full gate pipeline."""

    def test_strimzi_like_non_generic_names(self):
        """Strimzi-like examples with non-generic names produce correct edges."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = [
            {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "Kafka",
             "metadata": {"name": "production-cluster"}, "spec": {}},
            {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "KafkaTopic",
             "metadata": {"name": "orders-topic",
                          "labels": {"strimzi.io/cluster": "production-cluster"}},
             "spec": {}},
            {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "KafkaUser",
             "metadata": {"name": "orders-user",
                          "labels": {"strimzi.io/cluster": "production-cluster"}},
             "spec": {}},
            {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "KafkaConnect",
             "metadata": {"name": "debezium-connect"}, "spec": {}},
            {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "KafkaConnector",
             "metadata": {"name": "pg-connector",
                          "labels": {"strimzi.io/cluster": "debezium-connect"}},
             "spec": {}},
        ]
        edges = _extract(adapter, examples)
        edge_pairs = {(e.source_gk, e.target_gk) for e in edges}
        assert ("kafka.strimzi.io/KafkaTopic", "kafka.strimzi.io/Kafka") in edge_pairs
        assert ("kafka.strimzi.io/KafkaUser", "kafka.strimzi.io/Kafka") in edge_pairs
        assert ("kafka.strimzi.io/KafkaConnector", "kafka.strimzi.io/KafkaConnect") in edge_pairs
        assert len(edges) == 3

    def test_grouping_labels_produce_zero_edges(self):
        """Operator with only grouping labels (instance) → zero edges."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "strimzi.io/instance", "production-cluster",
            "Kafka", "production-cluster",
        )
        edges = _extract(adapter, examples)
        assert edges == []

    def test_generic_names_produce_zero_edges(self):
        """Operator with generic names (my-cluster) → zero edges."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "my-topic", "strimzi.io/cluster", "my-cluster",
            "Kafka", "my-cluster",
        )
        edges = _extract(adapter, examples)
        assert edges == []

    def test_dedup_multiple_labels_same_parent(self):
        """Multiple labels pointing to same parent → one edge."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = [
            {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "Kafka",
             "metadata": {"name": "production-cluster"}, "spec": {}},
            {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "KafkaTopic",
             "metadata": {"name": "orders-topic",
                          "labels": {"strimzi.io/cluster": "production-cluster",
                                     "strimzi.io/leader": "production-cluster"}},
             "spec": {}},
        ]
        edges = _extract(adapter, examples)
        assert len(edges) == 1

    def test_edge_attributes(self):
        """Emitted edges have correct detection_source, edge_type, confidence."""
        adapter = OlmDepAdapter(registry=_make_registry_with_strimzi())
        examples = _make_examples_with_label(
            "KafkaTopic", "orders-topic", "strimzi.io/cluster", "production-cluster",
            "Kafka", "production-cluster",
        )
        edges = _extract(adapter, examples)
        assert len(edges) == 1
        e = edges[0]
        assert e.detection_source == "olm_deps:alm_label"
        assert e.edge_type == "hard"
        assert e.confidence == 0.90
        assert "strimzi.io/cluster" in e.source_field

    def test_detect_alm_label_edges_public_method(self):
        """Public detect_alm_label_edges method returns DependencyEdge list."""
        reg = _make_registry_with_strimzi()
        adapter = OlmDepAdapter(registry=reg)
        csv = {
            "metadata": {
                "annotations": {
                    "alm-examples": json.dumps([
                        {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "Kafka",
                         "metadata": {"name": "production-cluster"}, "spec": {}},
                        {"apiVersion": "kafka.strimzi.io/v1beta2", "kind": "KafkaTopic",
                         "metadata": {"name": "orders-topic",
                                      "labels": {"strimzi.io/cluster": "production-cluster"}},
                         "spec": {}},
                    ]),
                },
            },
            "spec": {
                "customresourcedefinitions": {
                    "owned": [
                        {"name": "kafkas.kafka.strimzi.io", "kind": "Kafka", "version": "v1beta2"},
                        {"name": "kafkatopics.kafka.strimzi.io", "kind": "KafkaTopic", "version": "v1beta2"},
                    ],
                    "required": [],
                },
            },
        }
        with patch("idi.generation.dep_adapters.olm_deps.fetch_olm_csv", return_value=csv):
            edges = adapter.detect_alm_label_edges("strimzi", reg)

        assert len(edges) == 1
        assert isinstance(edges[0], DependencyEdge)

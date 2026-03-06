"""Detect secrets in manifests and generate PushSecret CRD templates."""


def detect_secret_fields(manifests: list[dict]) -> dict[str, list[str]]:
    """Detect secret fields from K8s Secret manifests. Returns {secret_name: [field_names]}."""
    result: dict[str, list[str]] = {}
    for doc in manifests:
        if doc.get("kind") != "Secret":
            continue
        name = doc.get("metadata", {}).get("name", "")
        if not name:
            continue
        fields = list(doc.get("data", {}).keys()) + list(doc.get("stringData", {}).keys())
        if fields:
            result[name] = fields
    return result


def generate_pushsecret_template(
    app_name: str, secret_fields: dict[str, list[str]]
) -> str:
    """Generate a PushSecret CRD J2 template for pushing K8s secrets to Vault."""
    if not secret_fields:
        return ""

    lines = [
        "{# Auto-generated PushSecret CRD template.",
        f"   Pushes {app_name} K8s Secrets to Vault KV for BWS extraction. #}}",
    ]

    for secret_name, fields in secret_fields.items():
        lines.extend([
            "---",
            "apiVersion: external-secrets.io/v1alpha1",
            "kind: PushSecret",
            "metadata:",
            f"  name: push-{secret_name}",
            "  namespace: {{ app_namespace }}",
            "  labels:",
            "    app.kubernetes.io/name: {{ app_name }}",
            "    app.kubernetes.io/managed-by: idi-ansible",
            "spec:",
            "  secretStoreRefs:",
            "    - name: vault-push",
            "      kind: ClusterSecretStore",
            f"  selector:",
            f"    secret:",
            f"      name: {secret_name}",
            "  data:",
        ])
        for field_name in fields:
            lines.extend([
                f"    - match:",
                f"      secretKey: {field_name}",
                f"      remoteRef:",
                f"        remoteKey: kv/data/{app_name}/{secret_name}",
                f"        property: {field_name}",
            ])

    return "\n".join(lines) + "\n"

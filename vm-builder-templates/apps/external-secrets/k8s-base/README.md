# External Secrets Operator - Kubernetes Secrets Synchronization

External Secrets Operator (ESO) synchronizes secrets from external secret management systems (Vault, AWS Secrets Manager, Bitwarden Secrets) into Kubernetes Secrets.

## Overview

**Purpose**: Integrate external secret providers with Kubernetes native Secret resources

**Namespace**: `external-secrets-system`

**Components**:
- Controller: Watches ExternalSecret CRDs and syncs secrets
- Webhook: Validates ExternalSecret and SecretStore resources
- Cert Controller: Manages TLS certificates for webhook

## Installation

### Prerequisites
- K3s cluster running
- kubectl configured
- Helm 3.x (recommended installation method)
- Secret providers configured (Vault, Bitwarden Secrets)

### Deployment Methods

**Option 1: Helm (Recommended)**
```bash
# Add External Secrets Operator Helm repository
helm repo add external-secrets https://charts.external-secrets.io
helm repo update

# Install External Secrets Operator
helm install external-secrets external-secrets/external-secrets \
  --namespace external-secrets-system \
  --create-namespace \
  --set installCRDs=true

# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=external-secrets -n external-secrets-system --timeout=300s
```

**Option 2: Kustomize (Future - when base/ is populated)**
```bash
kubectl apply -k apps/external-secrets/k8s-base/
```

**Option 3: Ansible Orchestration**
```bash
ansible-playbook ansible/playbooks/orchestration/deploy-golden-master.yml
```

### Verify Installation

```bash
# Check ESO pods
kubectl get pods -n external-secrets-system

# Verify CRDs are installed
kubectl get crd | grep external-secrets

# Expected CRDs:
# - externalsecrets.external-secrets.io
# - secretstores.external-secrets.io
# - clustersecretstores.external-secrets.io
```

## Configuration

### SecretStore vs ClusterSecretStore

**SecretStore** (namespace-scoped):
- References secrets in the same namespace
- Used for tenant-specific secret backends

**ClusterSecretStore** (cluster-scoped):
- References secrets from any namespace
- Used for shared secret backends (recommended for Vault and BWS)

### Vault Integration

Create `ClusterSecretStore` for Vault:

```yaml
# File: vault-cluster-secret-store.yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: vault-backend
spec:
  provider:
    vault:
      # Vault server address (in-cluster)
      server: "http://vault.vault.svc.cluster.local:8200"

      # Path to KV v2 secrets engine
      path: "secret"

      # KV secrets engine version
      version: "v2"

      # Authentication method
      auth:
        # Use Kubernetes service account authentication
        kubernetes:
          # Path where Kubernetes auth is mounted in Vault
          mountPath: "kubernetes"

          # Vault role to use
          role: "external-secrets"

          # Service account for authentication
          serviceAccountRef:
            name: "external-secrets"
            namespace: "external-secrets-system"
```

**Setup Vault Role**:
```bash
# Enable Kubernetes auth in Vault
kubectl exec -n vault vault-0 -- vault auth enable kubernetes

# Configure Kubernetes auth
kubectl exec -n vault vault-0 -- vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc:443"

# Create policy for ESO
kubectl exec -n vault vault-0 -- vault policy write external-secrets - <<EOF
path "secret/data/*" {
  capabilities = ["read", "list"]
}
EOF

# Create role for ESO
kubectl exec -n vault vault-0 -- vault write auth/kubernetes/role/external-secrets \
  bound_service_account_names=external-secrets \
  bound_service_account_namespaces=external-secrets-system \
  policies=external-secrets \
  ttl=24h
```

### Bitwarden Secrets Manager Integration

Create `ClusterSecretStore` for BWS:

```yaml
# File: bws-cluster-secret-store.yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: bitwarden-secrets
spec:
  provider:
    bitwardensecretsmanager:
      # Bitwarden Secrets Manager API URL
      apiURL: "https://api.bitwarden.com"

      # Organization ID
      organizationID: "<your-org-id>"

      # Access token reference (stored in K8s Secret)
      auth:
        secretRef:
          credentials:
            name: bws-access-token
            namespace: external-secrets-system
            key: token
---
# Secret containing BWS access token
apiVersion: v1
kind: Secret
metadata:
  name: bws-access-token
  namespace: external-secrets-system
type: Opaque
stringData:
  token: "<bws-access-token>"
```

**Get BWS Access Token**:
```bash
# Login to Bitwarden Secrets Manager
bws login

# Create service account and get token
# Store token in K8s Secret as shown above
```

## Usage

### Creating ExternalSecrets

**Example 1: Sync from Vault**
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: sonarr-api-key
  namespace: media-stack
spec:
  # Refresh interval (how often to check for changes)
  refreshInterval: 15m

  # Reference to SecretStore
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore

  # Target Kubernetes Secret
  target:
    name: sonarr-api-key
    creationPolicy: Owner

  # Data to sync
  data:
    - secretKey: api_key
      remoteRef:
        key: apps/media-stack/sonarr
        property: api_key
```

**Example 2: Sync from Bitwarden Secrets**
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: database-credentials
  namespace: media-stack
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: bitwarden-secrets
    kind: ClusterSecretStore
  target:
    name: postgres-credentials
  data:
    - secretKey: username
      remoteRef:
        key: <bws-secret-id>
        property: username
    - secretKey: password
      remoteRef:
        key: <bws-secret-id>
        property: password
```

**Example 3: Sync Entire Secret**
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-config
  namespace: media-stack
spec:
  refreshInterval: 30m
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: app-config-secret
  dataFrom:
    - extract:
        key: apps/media-stack/config
```

### Using Secrets in Pods

Once ExternalSecret creates the Kubernetes Secret, reference it normally:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sonarr
  namespace: media-stack
spec:
  template:
    spec:
      containers:
        - name: sonarr
          image: lscr.io/linuxserver/sonarr:latest
          env:
            - name: API_KEY
              valueFrom:
                secretKeyRef:
                  name: sonarr-api-key  # Created by ExternalSecret
                  key: api_key
```

## Monitoring

```bash
# Check ESO pods
kubectl get pods -n external-secrets-system

# List all ExternalSecrets
kubectl get externalsecret -A

# Check ExternalSecret status
kubectl describe externalsecret <name> -n <namespace>

# View ESO controller logs
kubectl logs -n external-secrets-system -l app.kubernetes.io/name=external-secrets

# Check SecretStore status
kubectl get clustersecretstore
kubectl describe clustersecretstore vault-backend
```

**ExternalSecret Status Conditions**:
- **Ready**: Secret successfully synced
- **SecretSynced**: Data fetched from provider
- **SecretStoreReady**: SecretStore connection successful

## Troubleshooting

### ExternalSecret Not Syncing

```bash
# Check ExternalSecret status
kubectl describe externalsecret <name> -n <namespace>

# Look for errors in status conditions:
# - SecretStoreNotFound: SecretStore doesn't exist
# - SecretStoreNotReady: Provider connection failed
# - SecretNotFound: Secret doesn't exist in provider

# Check ESO logs
kubectl logs -n external-secrets-system -l app.kubernetes.io/name=external-secrets --tail=100
```

### Vault Authentication Failures

```bash
# Verify service account exists
kubectl get sa external-secrets -n external-secrets-system

# Check Vault role configuration
kubectl exec -n vault vault-0 -- vault read auth/kubernetes/role/external-secrets

# Test Kubernetes auth from ESO pod
kubectl exec -n external-secrets-system deployment/external-secrets -- \
  vault login -method=kubernetes role=external-secrets
```

### Bitwarden Secrets Connection Issues

```bash
# Verify BWS access token secret
kubectl get secret bws-access-token -n external-secrets-system

# Check ClusterSecretStore status
kubectl describe clustersecretstore bitwarden-secrets

# Test BWS connectivity manually
bws secret list --organization-id <org-id>
```

### Secret Not Updated

**Problem**: Secret exists but values are outdated

**Solution**:
```bash
# Force refresh by annotating ExternalSecret
kubectl annotate externalsecret <name> -n <namespace> \
  force-sync=$(date +%s) --overwrite

# Or delete and recreate ExternalSecret
kubectl delete externalsecret <name> -n <namespace>
kubectl apply -f <externalsecret-manifest>
```

## Secret Rotation

ESO automatically refreshes secrets based on `refreshInterval`:

```yaml
spec:
  refreshInterval: 15m  # Check for changes every 15 minutes
```

**Manual Rotation**:
1. Update secret in Vault/BWS
2. Wait for `refreshInterval` or force sync (see above)
3. Restart pods to pick up new secret values

**Automatic Pod Restart** (using Reloader):
```bash
# Install Reloader (watches Secrets and restarts Deployments)
helm repo add stakater https://stakater.github.io/stakater-charts
helm install reloader stakater/reloader -n external-secrets-system

# Annotate Deployment to enable auto-restart
kubectl annotate deployment sonarr -n media-stack \
  secret.reloader.stakater.com/reload="sonarr-api-key"
```

## Best Practices

1. **Use ClusterSecretStore**: Share secret providers across namespaces
2. **Set Reasonable Refresh Intervals**: Balance freshness vs. API load
3. **Use RBAC**: Restrict ExternalSecret creation to authorized users
4. **Monitor Sync Status**: Alert on failed secret syncs
5. **Version Secrets**: Use Vault KV v2 for versioning and rollback
6. **Audit Access**: Enable audit logging in Vault
7. **Rotate Credentials**: Regularly rotate BWS and Vault tokens

## Security Considerations

- **Provider Credentials**: Store BWS tokens and Vault tokens securely
- **RBAC**: Use Kubernetes RBAC to control ExternalSecret creation
- **Network Policies**: Restrict ESO pod access to secret providers
- **Secret Scope**: Use SecretStore for tenant isolation
- **Immutable Secrets**: Use `immutable: true` for sensitive secrets
- **Audit Logging**: Monitor secret access in Vault

## Related Documentation

- [External Secrets Operator Docs](https://external-secrets.io/latest/)
- [Vault Provider](https://external-secrets.io/latest/provider/hashicorp-vault/)
- [Bitwarden Secrets Manager Provider](https://external-secrets.io/latest/provider/bitwarden-secrets-manager/)
- [apps/vault/k8s-base/README.md](../../vault/k8s-base/README.md) - Vault setup
- [BWS_PLAYBOOK_PATTERN.md](../../../docs/BWS_PLAYBOOK_PATTERN.md) - Secrets workflow

## Future Enhancements

- PushSecret for syncing K8s Secrets to external providers
- Generator integration for password/key generation
- Webhook for secret change notifications
- Multi-provider failover (Vault primary, BWS fallback)
- Secret validation and templating
- Integration with cert-manager for TLS certificates

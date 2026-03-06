# HashiCorp Vault - Golden Master Component

## Overview

HashiCorp Vault is deployed as the **first Golden Master component** and provides centralized secrets management for the K3s cluster. Vault acts as the bridge between Bitwarden Secrets Manager (BWS) and Kubernetes applications.

## Architecture

```
┌─────────────────────┐
│ Bitwarden Secrets   │
│ Manager (BWS)       │
└──────────┬──────────┘
           │
           │ (Ansible sync)
           ▼
┌─────────────────────┐
│ HashiCorp Vault     │
│ (K3s StatefulSet)   │
└──────────┬──────────┘
           │
           │ (ESO pulls)
           ▼
┌─────────────────────┐
│ External Secrets    │
│ Operator (ESO)      │
└──────────┬──────────┘
           │
           │ (creates)
           ▼
┌─────────────────────┐
│ K8s Secrets         │
│ (Applications)      │
└─────────────────────┘
```

## Components

### Namespace
- **Name**: `vault`
- **Purpose**: Isolates Vault components

### StatefulSet
- **Name**: `vault`
- **Replicas**: 1 (single-node for homelab)
- **Image**: `hashicorp/vault:1.18`
- **Storage**: 10Gi Longhorn PVC
- **Backend**: File storage at `/vault/data`

### Services
1. **vault** (Headless)
   - API: `8200/TCP`
   - Cluster: `8201/TCP`
   - DNS: `vault.vault.svc.cluster.local`

2. **vault-ui** (ClusterIP)
   - HTTP: `8200/TCP`
   - For port-forwarding to access UI

### ConfigMap
- **Name**: `vault-config`
- **Contains**: Vault HCL configuration
  - Listener on `0.0.0.0:8200` (HTTP)
  - File storage backend
  - UI enabled

## Deployment

### Prerequisites
1. K3s cluster running
2. Longhorn storage installed
3. BWS CLI installed and configured
4. VAULT_ADDR and VAULT_TOKEN environment variables

### Deploy via Ansible

```bash
# Deploy Vault server
ansible-playbook apps/vault/install/01-deploy-server.yml

# Sync secrets from BWS
ansible-playbook apps/vault/config/02-sync-from-bws.yml
```

### Deploy via kubectl (for testing)

```bash
# Apply all manifests
kubectl apply -k apps/vault/k8s-base/

# Wait for pod to be ready
kubectl wait --for=condition=ready pod/vault-0 -n vault --timeout=300s
```

## Initialization and Unsealing

### First-Time Initialization

On first deployment, Vault must be initialized:

```bash
# Exec into the pod
kubectl exec -it vault-0 -n vault -- sh

# Initialize Vault (generates unseal keys and root token)
vault operator init -key-shares=5 -key-threshold=3

# Save the output - these are critical!
# Unseal Keys: 5 keys (need 3 to unseal)
# Root Token: For administrative access
```

The Ansible playbook `01-deploy-server.yml` automates this and stores keys in BWS.

### Unsealing

Vault starts in a sealed state. Unseal with 3 of the 5 keys:

```bash
# Manual unseal
vault operator unseal <key1>
vault operator unseal <key2>
vault operator unseal <key3>

# Check seal status
vault status
```

The Ansible playbook handles automatic unsealing by retrieving keys from BWS.

## Accessing Vault

### Via Port-Forward (UI)

```bash
# Forward port 8200
kubectl port-forward -n vault svc/vault-ui 8200:8200

# Open browser
http://localhost:8200
```

### Via CLI (from pod)

```bash
# Exec into pod
kubectl exec -it vault-0 -n vault -- sh

# Set address (already set via env var)
export VAULT_ADDR=http://127.0.0.1:8200

# Login with root token
vault login <root-token>

# List secrets engines
vault secrets list

# Read a secret (KV v2)
vault kv get secret/homelab/staging/media-stack/nfs_server_ip
```

### Via API

```bash
# Check health
curl http://vault.vault.svc.cluster.local:8200/v1/sys/health

# Read secret (requires token)
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  http://vault.vault.svc.cluster.local:8200/v1/secret/data/path/to/secret
```

## Secrets Sync Pattern

Secrets flow from BWS to Vault to K8s:

1. **Source**: Secrets stored in BWS
2. **Sync**: Ansible playbook reads from BWS, writes to Vault
3. **Path**: `secret/data/{client}/{environment}/{app}/{key}`
   - Example: `secret/data/homelab/staging/media-stack/nfs_server_ip`
4. **Consumption**: External Secrets Operator (ESO) reads from Vault
5. **K8s Secret**: ESO creates native K8s Secret for application

## Secret Path Convention

```
secret/data/{client}/{environment}/{app}/{key}
```

Examples:
- `secret/data/homelab/staging/media-stack/nfs_server_ip`
- `secret/data/homelab/staging/media-stack/nfs_media_path`
- `secret/data/homelab/production/argocd/admin_password`

## Vault Policies

Policies control access to secrets:

```hcl
# Example: media-stack policy
path "secret/data/homelab/*/media-stack/*" {
  capabilities = ["read", "list"]
}
```

Created by `02-sync-from-bws.yml` playbook.

## Verification

```bash
# Check pod status
kubectl get pods -n vault

# Check PVC
kubectl get pvc -n vault

# Check services
kubectl get svc -n vault

# Check seal status
kubectl exec -n vault vault-0 -- vault status

# Check secrets engine
kubectl exec -n vault vault-0 -- vault secrets list
```

Expected output:
- Pod: `vault-0` Running
- PVC: `data-vault-0` Bound, 10Gi, longhorn
- Seal Status: Unsealed
- Initialized: true

## Troubleshooting

### Pod CrashLoopBackOff

Check logs:
```bash
kubectl logs -n vault vault-0
```

Common causes:
- PVC not bound (Longhorn not ready)
- Config syntax error in ConfigMap
- Permissions issue with `/vault/data`

### Vault Sealed After Restart

Vault seals on restart. Re-unseal:
```bash
# Via playbook (recommended)
ansible-playbook apps/vault/install/01-deploy-server.yml

# Or manually
kubectl exec -n vault vault-0 -- vault operator unseal <key>
```

### Cannot Write Secrets

Check:
- Root token valid
- KV v2 engine enabled at `secret/`
- Path follows convention
- Proper JSON format for KV v2

### UI Not Accessible

```bash
# Verify port-forward
kubectl port-forward -n vault svc/vault-ui 8200:8200

# Check service
kubectl get svc -n vault vault-ui

# Verify UI enabled in config
kubectl get cm -n vault vault-config -o yaml
```

## Maintenance

### Backup

Backup Vault data volume:
```bash
# Backup PVC using Longhorn snapshot
kubectl annotate pvc data-vault-0 -n vault backup.longhorn.io/create="true"
```

### Upgrade Vault Version

1. Update image tag in `vault-server-statefulset.yaml`
2. Apply changes:
   ```bash
   kubectl apply -f apps/vault/k8s-base/vault-server-statefulset.yaml
   ```
3. Vault will perform rolling update
4. Unseal after upgrade

### Rotate Root Token

```bash
vault token create -policy=root
vault token revoke <old-token>
# Update BWS with new token
```

## Integration with Other Components

### External Secrets Operator (ESO)

ESO will be configured to read from Vault:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: vault-backend
spec:
  provider:
    vault:
      server: "http://vault.vault.svc.cluster.local:8200"
      path: "secret"
      version: "v2"
```

### ArgoCD

ArgoCD can use Vault for secrets via ESO or Vault plugin.

### AWX

AWX can retrieve secrets from Vault for playbook credentials.

## Security Considerations

1. **TLS Disabled**: Currently HTTP-only for internal cluster use
   - Consider enabling TLS for production
2. **Root Token**: Store securely in BWS, rotate regularly
3. **Unseal Keys**: Never commit to Git, store in BWS
4. **Policies**: Use least-privilege access
5. **Audit Logging**: Enable for compliance (future)

## References

- [Vault Documentation](https://www.vaultproject.io/docs)
- [Vault on Kubernetes](https://www.vaultproject.io/docs/platform/k8s)
- [Architecture Docs](../../../docs/ARCHITECTURE.md#golden-master-pattern)

# ArgoCD GitOps Platform

ArgoCD is the **primary deployment method** for applications in the media-stack Golden Master. It provides declarative, GitOps-based continuous deployment by monitoring Git repositories and automatically syncing Kubernetes resources.

## Architecture

ArgoCD monitors the `k8s/applications/` directory for `Application` manifests. When you commit a new Application manifest to Git, ArgoCD automatically:

1. Detects the change via Git polling or webhooks
2. Fetches the target manifests from the specified path
3. Applies them to the cluster
4. Monitors health and sync status
5. Self-heals if resources drift from desired state

## Directory Structure

```
apps/argocd/
├── k8s-base/
│   ├── namespace.yaml                 # ArgoCD namespace
│   ├── argocd-install.yaml           # Reference to official install manifest
│   ├── argocd-server-service.yaml    # NodePort service for UI access
│   ├── argocd-repo-secret.yaml       # Placeholder for GitHub SSH credentials
│   ├── kustomization.yaml            # Kustomize configuration
│   └── README.md                     # This file
├── install/
│   └── 01-install-server.yml         # Install ArgoCD server
└── config/
    └── 02-configure-repo.yml         # Configure GitHub repository access
```

## Deployment

### Prerequisites

- K3s cluster running
- Bitwarden Secrets Manager (BWS) configured with SSH deploy key
- Ansible inventory with `inventory.ssh.keypair.private_key_b64`

### Installation

Run the atomic playbooks in order:

```bash
# 1. Install ArgoCD server
ansible-playbook apps/argocd/install/01-install-server.yml

# 2. Configure GitHub repository
ansible-playbook apps/argocd/config/02-configure-repo.yml
```

## Accessing ArgoCD UI

### Option 1: NodePort (Default)

ArgoCD UI is exposed on NodePort 30280 (HTTP):

```bash
# Access via node IP
http://<node-ip>:30280

# Or port-forward from local machine
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Then visit: https://localhost:8080
```

### Option 2: Ingress (via Traefik)

Create an IngressRoute for ArgoCD:

```yaml
apiVersion: traefik.containo.us/v1alpha1
kind: IngressRoute
metadata:
  name: argocd-server
  namespace: argocd
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`argocd.example.com`)
      kind: Rule
      services:
        - name: argocd-server
          port: 443
  tls:
    certResolver: letsencrypt
```

### Login Credentials

**Username**: `admin`

**Password**: Retrieved from Kubernetes Secret (stored in BWS by playbook)

```bash
# Get password from K8s
kubectl get secret argocd-initial-admin-secret -n argocd \
  -o jsonpath='{.data.password}' | base64 -d

# Or retrieve from BWS (stored by playbook)
# Key: argocd/admin_password
```

## Creating Applications

### Directory for Application Manifests

All ArgoCD Application manifests should be placed in:

```
k8s/applications/
```

ArgoCD monitors this directory and automatically deploys any Application resources.

### Example Application Manifest

See `k8s/applications/example-app.yaml` for a complete example.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: media-stack
  namespace: argocd
spec:
  project: default

  # Source: Where to get the manifests
  source:
    repoURL: https://github.com/mightymorgs/media-stack
    targetRevision: main
    path: k8s/media-stack/base

  # Destination: Where to deploy
  destination:
    server: https://kubernetes.default.svc
    namespace: media-stack

  # Sync policy: Automated with self-heal
  syncPolicy:
    automated:
      prune: true       # Delete resources not in Git
      selfHeal: true    # Revert manual changes
      allowEmpty: false # Prevent empty sync
    syncOptions:
      - CreateNamespace=true
```

### Auto-Sync Configuration

Applications are configured with:

- **Auto-sync**: Enabled - changes in Git are automatically deployed
- **Self-heal**: Enabled - manual changes to cluster are reverted
- **Prune**: Enabled - resources removed from Git are deleted from cluster

### Creating a New Application

1. Create an Application manifest in `k8s/applications/`:

```bash
cat > k8s/applications/my-app.yaml <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/mightymorgs/media-stack
    targetRevision: main
    path: k8s/my-app/base
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
EOF
```

2. Commit and push to Git:

```bash
git add k8s/applications/my-app.yaml
git commit -m "feat: add ArgoCD application for my-app"
git push
```

3. ArgoCD will automatically detect and deploy the application

4. Monitor in UI or CLI:

```bash
# Install ArgoCD CLI
curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd
rm argocd-linux-amd64

# Login
argocd login <node-ip>:30280 --username admin --password <password>

# List applications
argocd app list

# Get application details
argocd app get my-app

# Sync manually (if not auto-sync)
argocd app sync my-app
```

## Repository Configuration

ArgoCD is configured to access the GitHub repository via SSH:

- **Repository**: `git@github.com:mightymorgs/media-stack.git`
- **Authentication**: SSH private key from BWS
- **Secret Name**: `media-stack-repo` in `argocd` namespace

The repository credentials are managed by:

- **Template**: `apps/argocd/templates/repo-secret.yaml.j2`
- **Playbook**: `apps/argocd/config/02-configure-repo.yml`

## AppProject Configuration

ArgoCD uses Projects to group applications and define access controls:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: media-stack
  namespace: argocd
spec:
  description: Media Stack Applications

  # Source repositories allowed
  sourceRepos:
    - 'https://github.com/mightymorgs/media-stack'
    - 'git@github.com:mightymorgs/media-stack.git'

  # Destination clusters and namespaces
  destinations:
    - namespace: '*'
      server: https://kubernetes.default.svc

  # Cluster resources allowed
  clusterResourceWhitelist:
    - group: '*'
      kind: '*'
```

## Verification

### Check ArgoCD Pods

```bash
kubectl get pods -n argocd
```

Expected pods:
- `argocd-application-controller-*`
- `argocd-applicationset-controller-*`
- `argocd-dex-server-*`
- `argocd-notifications-controller-*`
- `argocd-redis-*`
- `argocd-repo-server-*`
- `argocd-server-*`

### Check Repository Connection

```bash
# Via UI: Settings → Repositories
# Via CLI:
argocd repo list
```

### Test Application Deployment

Deploy the example application:

```bash
kubectl apply -f k8s/applications/example-app.yaml

# Watch sync status
argocd app get example-app --watch
```

## Troubleshooting

### ArgoCD Server Not Starting

```bash
# Check logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server

# Check events
kubectl get events -n argocd --sort-by='.lastTimestamp'
```

### Repository Connection Failed

```bash
# Verify secret exists
kubectl get secret media-stack-repo -n argocd

# Check secret contents (SSH key should be present)
kubectl get secret media-stack-repo -n argocd -o yaml

# Test SSH connection manually
ssh -T git@github.com
```

### Application Out of Sync

```bash
# View sync status
argocd app get <app-name>

# View differences
argocd app diff <app-name>

# Force sync
argocd app sync <app-name> --force

# Refresh (re-fetch from Git)
argocd app get <app-name> --refresh
```

### Self-Heal Not Working

Check the Application manifest has:

```yaml
syncPolicy:
  automated:
    selfHeal: true
```

Self-heal only works for automated sync policies.

## References

- [ArgoCD Official Documentation](https://argo-cd.readthedocs.io/)
- [ArgoCD GitHub Repository](https://github.com/argoproj/argo-cd)
- [GitOps Principles](https://opengitops.dev/)
- [Media Stack Architecture](../../../docs/ARCHITECTURE.md)
- [Coding Standards](../../../docs/CODING_STANDARDS.md)

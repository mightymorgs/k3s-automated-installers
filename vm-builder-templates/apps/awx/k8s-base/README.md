# AWX - Ansible Automation Platform

AWX is the open-source upstream project for Red Hat Ansible Automation Platform. It provides a web-based UI, REST API, and task engine for managing and executing Ansible playbooks at scale.

## Overview

**Purpose**: Workflow orchestration and job scheduling for infrastructure automation

**Namespace**: `awx`

**Components**:
- AWX Web: Web UI and REST API server
- AWX Task: Ansible job execution engine
- AWX EE (Execution Environments): Containerized Ansible runtime
- PostgreSQL: Database backend (managed by AWX Operator)
- Redis: Task queue and caching

## Installation

### Prerequisites
- K3s cluster running
- Longhorn storage class (for PostgreSQL PVC)
- kubectl configured
- Kustomize 3.0+ (for operator installation)

### Deployment Methods

**Option 1: AWX Operator (Recommended)**

Step 1: Install AWX Operator
```bash
# Set AWX Operator version
export AWX_OPERATOR_VERSION=2.10.0

# Create namespace
kubectl create namespace awx

# Install AWX Operator
kubectl apply -k "https://github.com/ansible/awx-operator/releases/download/${AWX_OPERATOR_VERSION}/awx-operator.yaml"

# Wait for operator to be ready
kubectl wait --for=condition=ready pod -l control-plane=controller-manager -n awx --timeout=300s
```

Step 2: Deploy AWX Instance
```bash
# Create AWX instance manifest
cat <<EOF | kubectl apply -f -
apiVersion: awx.ansible.com/v1beta1
kind: AWX
metadata:
  name: awx
  namespace: awx
spec:
  service_type: ClusterIP
  ingress_type: none
  postgres_storage_class: longhorn
  postgres_storage_requirements:
    requests:
      storage: 8Gi
  projects_persistence: true
  projects_storage_class: longhorn
  projects_storage_size: 8Gi
  web_replicas: 1
  task_replicas: 1
EOF

# Wait for AWX to be ready (can take 5-10 minutes)
kubectl wait --for=condition=ready awx/awx -n awx --timeout=600s
```

**Option 2: Kustomize (Future - when base/ is populated)**
```bash
kubectl apply -k apps/awx/k8s-base/
```

**Option 3: Ansible Orchestration**
```bash
ansible-playbook ansible/playbooks/orchestration/deploy-golden-master.yml
```

### Initial Setup

```bash
# Get AWX admin password
kubectl get secret awx-admin-password -n awx -o jsonpath="{.data.password}" | base64 -d

# Port forward to access UI
kubectl port-forward svc/awx-service -n awx 8080:80

# Access UI: http://localhost:8080
# Username: admin
# Password: (from command above)
```

## Configuration

### Ingress (Traefik)

Expose AWX UI via Traefik:
```yaml
# File: awx-ingressroute.yaml
apiVersion: traefik.containo.us/v1alpha1
kind: IngressRoute
metadata:
  name: awx
  namespace: awx
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`awx.local.mightymorgs.com`)
      kind: Rule
      services:
        - name: awx-service
          port: 80
  tls:
    certResolver: default
```

### Project Configuration

Add this Git repository as a project source:

1. Navigate to **Resources → Projects**
2. Click **Add**
3. Configure:
   - Name: `media-stack-repo`
   - Organization: `Default`
   - Source Control Type: `Git`
   - Source Control URL: `https://github.com/mightymorgs/media-stack.git`
   - Source Control Branch/Tag/Commit: `main`
   - Update on Launch: Yes

### Inventory Configuration

Create inventory for K3s cluster:

1. Navigate to **Resources → Inventories**
2. Click **Add → Inventory**
3. Configure:
   - Name: `k3s-cluster`
   - Organization: `Default`
4. Add **Hosts**:
   - Name: `localhost`
   - Variables:
     ```yaml
     ansible_connection: local
     ansible_python_interpreter: /usr/bin/python3
     ```

### Credential Configuration

Add credentials for external services:

**Bitwarden Secrets Manager**:
1. Navigate to **Resources → Credentials**
2. Click **Add**
3. Type: `Custom Credential Type` (create BWS type first)
4. Store `BWS_ACCESS_TOKEN`

**Vault Token**:
1. Type: `HashiCorp Vault Secret Lookup`
2. Store Vault address and token

**GitHub SSH Key** (for private repos):
1. Type: `Source Control`
2. Upload deploy key from Bitwarden Secrets

### Job Template Configuration

Create job templates for common workflows:

**Example: Deploy Media Stack**
1. Navigate to **Resources → Templates**
2. Click **Add → Job Template**
3. Configure:
   - Name: `Deploy Media Stack`
   - Job Type: `Run`
   - Inventory: `k3s-cluster`
   - Project: `media-stack-repo`
   - Playbook: `ansible/playbooks/orchestration/deploy-media-stack-single-node.yml`
   - Credentials: `BWS Access Token`, `Vault Token`
   - Extra Variables:
     ```yaml
     deployment_environment: production
     enable_monitoring: true
     ```
   - Options:
     - Enable Privilege Escalation: No (K8s API doesn't require sudo)
     - Enable Concurrent Jobs: No

## Usage

### Running Job Templates

**Via UI**:
1. Navigate to **Resources → Templates**
2. Click **Launch** on desired template
3. Optionally override variables
4. Monitor job output in real-time

**Via API** (curl):
```bash
# Get API token
AWX_TOKEN=$(curl -s -X POST http://awx.local.mightymorgs.com/api/v2/tokens/ \
  -u admin:password \
  -H "Content-Type: application/json" \
  | jq -r '.token')

# Launch job template
curl -X POST http://awx.local.mightymorgs.com/api/v2/job_templates/5/launch/ \
  -H "Authorization: Bearer $AWX_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"extra_vars": "{\"deployment_environment\": \"production\"}"}'
```

**Via CLI** (awxkit or ansible-tower-cli):
```bash
# Install awxkit
pip install awxkit

# Configure
export TOWER_HOST=http://awx.local.mightymorgs.com
export TOWER_USERNAME=admin
export TOWER_PASSWORD=<password>

# Launch job
awx job_templates launch --name="Deploy Media Stack"
```

### Workflow Templates

Chain multiple job templates:

1. Navigate to **Resources → Templates**
2. Click **Add → Workflow Template**
3. Configure workflow:
   - Name: `Full Golden Master Deployment`
   - Workflow:
     ```
     Deploy Vault → Deploy ESO → Deploy ArgoCD → Deploy AWX → Deploy Apps
     ```
   - Add success/failure handlers for each step

## Monitoring

```bash
# Check AWX pods
kubectl get pods -n awx

# View AWX instance status
kubectl get awx -n awx

# Check AWX logs (web)
kubectl logs -n awx -l app.kubernetes.io/name=awx-web

# Check AWX logs (task)
kubectl logs -n awx -l app.kubernetes.io/name=awx-task

# Check PostgreSQL logs
kubectl logs -n awx -l app.kubernetes.io/name=postgres
```

**UI Monitoring**:
- Dashboard: Real-time job statistics
- Jobs: View running/completed job output
- Activity Stream: Audit log of all changes

## Troubleshooting

### AWX Instance Not Ready

```bash
# Check AWX resource status
kubectl describe awx awx -n awx

# Check operator logs
kubectl logs -n awx -l control-plane=controller-manager

# Check AWX pods
kubectl get pods -n awx

# If stuck in pending, check PVC status
kubectl get pvc -n awx
```

### Job Execution Failures

**Problem**: Jobs fail with "Connection refused" to K8s API

**Solution**: Ensure kubectl is configured in Execution Environment
```bash
# Check job logs for errors
# Verify KUBECONFIG is set in job template extra vars
# Add credential for K8s authentication
```

**Problem**: Jobs fail with "Module not found"

**Solution**: Use custom Execution Environment with required collections
```dockerfile
# Build custom EE with kubernetes.core collection
# See: https://ansible.readthedocs.io/en/latest/execution_environments/
```

### Database Connection Issues

```bash
# Check PostgreSQL pod
kubectl get pods -n awx -l app.kubernetes.io/name=postgres

# Check database connectivity
kubectl exec -it -n awx deployment/awx-web -- awx-manage check_db

# Restart AWX pods if needed
kubectl rollout restart deployment/awx-web -n awx
kubectl rollout restart deployment/awx-task -n awx
```

## Execution Environments

AWX uses containerized execution environments (EE) instead of traditional virtualenvs.

### Default EE
AWX ships with `quay.io/ansible/awx-ee:latest` which includes:
- Ansible Core 2.15+
- Common Ansible collections
- Python 3.11

### Custom EE (Future)

Create custom EE with required collections:

```yaml
# execution-environment.yml
version: 3
dependencies:
  galaxy: requirements.yml
  python: requirements.txt
  system: bindep.txt

images:
  base_image:
    name: quay.io/ansible/ansible-runner:latest

additional_build_steps:
  prepend_base:
    - RUN pip3 install kubernetes
  append_final:
    - RUN ansible-galaxy collection install kubernetes.core
```

Build and push:
```bash
ansible-builder build -t ghcr.io/mightymorgs/awx-ee:latest
podman push ghcr.io/mightymorgs/awx-ee:latest
```

Configure in AWX:
1. **Administration → Execution Environments**
2. Add custom EE image

## Security Best Practices

1. **Use RBAC**: Create Organizations and Teams for multi-tenancy
2. **Credential Isolation**: Use credential types with input/output mappings
3. **Enable SSO**: Integrate with Authentik (future)
4. **Audit Logging**: Enable Activity Stream for compliance
5. **Network Policies**: Restrict AWX pod communication
6. **Secret Management**: Store credentials in Vault, not AWX database
7. **Least Privilege**: Create service accounts with minimal K8s permissions

## Related Documentation

- [AWX Official Docs](https://ansible.readthedocs.io/projects/awx/en/latest/)
- [AWX Operator GitHub](https://github.com/ansible/awx-operator)
- [Ansible Execution Environments](https://ansible.readthedocs.io/en/latest/execution_environments/)
- [ARCHITECTURE.md](../../../docs/ARCHITECTURE.md) - System architecture
- [PLAYBOOK_STRUCTURE.md](../../../docs/PLAYBOOK_STRUCTURE.md) - Playbook organization

## Future Enhancements

- SSO integration with Authentik
- Custom Execution Environment with all required collections
- Webhook receivers for Git push events
- Notification integration (Slack, email, PagerDuty)
- Multi-cluster inventory with dynamic sources
- Workflow templates for complex deployments
- RBAC policies for multi-tenant access

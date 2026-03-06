# Golden Master Template

Reference app template encoding all enforced patterns for IDI infrastructure playbooks. Every new app should be created by copying this skeleton and replacing placeholder values.

This is a **skeleton** -- placeholder values like `{{ app_name }}` are not deployable. The golden master exists to document the canonical structure and to serve as the validation baseline for molecule tests.

**Source documents:**
- [Design](../../../docs/plans/2026-03-04-golden-master-design.md)
- [Pattern Comparison](../../../docs/plans/2026-03-04-golden-master-pattern-comparison.md)
- [Votes](../../../docs/plans/2026-03-04-golden-master-votes.md)
- [Phase 3 fixes memory](../../../memory/phase3-fixes-session.md)

---

## Directory Structure

```
apps/_golden-master/
├── install/
│   ├── 01-deploy.yml              # Canonical J2-template install playbook
│   ├── 01-apply-kustomize.yml     # Canonical kustomize install playbook (alternative)
│   └── 02-verify.yml              # Canonical verification playbook
├── config/
│   └── 02-configure-api.yml       # Canonical Phase 4 config playbook
├── templates/
│   ├── 00-namespace.yaml.j2       # Namespace (always kubectl apply)
│   ├── 10-secrets.yaml.j2         # K8s Secret (always kubectl apply)
│   ├── 20-pushsecret.yaml.j2      # PushSecret -> Vault KV (always kubectl apply)
│   ├── 30-pvc.yaml.j2             # PVC (always kubectl apply)
│   ├── 40-statefulset.yaml.j2     # Workload (kubectl_action)
│   ├── 50-service.yaml.j2         # Service + NodePort (kubectl_action)
│   └── 60-ingressroute.yaml.j2    # IngressRoute (kubectl_action)
└── README.md                      # This file
```

---

## Numeric-Prefix Convention

The rendered manifest filename encodes both **apply class** and **ordering**. This is the single most important convention in the golden master.

| Prefix | Resource | Apply Method | Rationale |
|--------|----------|-------------|-----------|
| `00-` | Namespace | always `kubectl apply` | Must exist before all other resources |
| `10-` | Secrets | always `kubectl apply` | Never `replace --force` -- avoids transient deletion |
| `20-` | PushSecret | always `kubectl apply` | CRD, no benefit from force-replace |
| `30-` | PVC | always `kubectl apply` | `pvc-protection` finalizer deadlocks on force-delete |
| `40-` | StatefulSet / Deployment | `kubectl {{ kubectl_action }}` | Force-replace restarts pods (intended in full mode) |
| `50-` | Service | `kubectl {{ kubectl_action }}` | Force-replace resets ClusterIP/NodePort |
| `60-` | IngressRoute | `kubectl {{ kubectl_action }}` | Force-replace refreshes routing |

### Classification Rule

```
prefix < 40  -->  always kubectl apply (protected resources)
prefix >= 40 -->  kubectl {{ kubectl_action }} (workload resources)
```

**Filesystem sort IS the apply order.** No ordered list variables, no per-app metadata, no globs to accidentally match wrong files.

### Implementation in Playbooks

```yaml
- name: Apply protected resources (prefix < 40, always kubectl apply)
  ansible.builtin.command:
    cmd: kubectl apply -f {{ item.path }}
  loop: "{{ manifest_files.files | sort(attribute='path') }}"
  when: item.path | basename is regex('^[0-3]')

- name: Apply workload resources (prefix >= 40, uses kubectl_action)
  ansible.builtin.command:
    cmd: kubectl {{ workload_action | default(kubectl_action) }} -f {{ item.path }}
  loop: "{{ manifest_files.files | sort(attribute='path') }}"
  when: item.path | basename is regex('^[4-9]')
```

---

## Reconcile / Rebuild Mode Contract

The `kubectl_action` variable controls whether workload resources get `apply` (reconcile mode) or `replace --force` (rebuild/full mode). Protected resources are **always** applied safely regardless of mode.

| Resource | Reconcile (`apply`) | Rebuild (`replace --force`) |
|----------|--------------------|-----------------------------|
| Namespace | create if missing, never delete | create if missing, never delete |
| Secrets | apply (preserve existing) | apply (preserve existing) |
| PushSecret | apply | apply |
| PVC | skip if Bound | skip if Bound |
| CRDs / RBAC | apply | apply |
| StatefulSet | apply (rolling update) | replace --force |
| Deployment | apply (rolling update) | replace --force |
| Service | apply | replace --force |
| IngressRoute | apply | replace --force |

Secrets and PVCs are protected in **both** modes. "Rebuild" means "force-restart pods and recreate services", not "nuke everything including data."

---

## Enforced Patterns (8 Critical Rules from Phase 3 Fixes)

These 8 patterns were discovered through production failures. Every install playbook must implement them.

### 1. Namespace First

Namespace must be created before any manifest apply. Uses `kubectl create --dry-run=client | apply` for idempotency.

```yaml
- name: Ensure namespace exists
  ansible.builtin.shell: |
    kubectl create namespace {{ app_namespace }} --dry-run=client -o yaml | kubectl apply -f -
```

### 2. Secret Split Apply

Secrets (prefix < 40) must never go through `replace --force`. The numeric-prefix convention enforces this structurally -- files matching `^[0-3]` always use `kubectl apply`.

### 3. Secret Preservation (Idempotency)

Apps that generate secrets must check for existing values before generating new ones. Per-field preservation, not all-or-nothing.

```yaml
- name: Check for existing secret field
  ansible.builtin.command: >-
    kubectl get secret {{ app_name }}-credentials -n {{ app_namespace }}
    -o jsonpath='{.data.{{ item.k8s_key }}}'
  register: existing_secret
  failed_when: false

- name: Preserve existing value
  ansible.builtin.set_fact:
    "{{ item.field_name }}": "{{ existing_secret.stdout | b64decode }}"
  when: existing_secret.rc == 0 and existing_secret.stdout | length > 0

- name: Generate only if missing
  ansible.builtin.set_fact:
    "{{ item.field_name }}": "{{ lookup('password', '/dev/null length=32 chars=ascii_letters,digits') }}"
  when: lookup('vars', item.field_name, default='') | length == 0
```

### 4. Non-Empty Secret Guard

Never apply a secret with an empty value. Fail loudly instead.

```yaml
- name: Guard against empty secret value
  ansible.builtin.fail:
    msg: "Refusing to apply secret -- {{ item.field_name }} is empty"
  when: lookup('vars', item.field_name, default='') | length == 0
```

### 5. Two-Step Pod Wait

`kubectl wait` fails with "no matching resources" if no pod exists yet. Always pre-check pod existence.

```yaml
- name: Wait for at least one pod to exist
  ansible.builtin.command: >-
    kubectl -n {{ app_namespace }} get pods -l app.kubernetes.io/name={{ app_name }}
    -o jsonpath='{.items[0].metadata.name}'
  retries: 6
  delay: 10
  until: pod_exists.rc == 0 and pod_exists.stdout != ''

- name: Wait for pod to be ready
  ansible.builtin.command: >-
    kubectl -n {{ app_namespace }} wait --for=condition=ready pod
    -l app.kubernetes.io/name={{ app_name }} --timeout=600s
  retries: 3
  delay: 10
  until: wait_result.rc == 0
```

### 6. Namespace Labels

Every namespace gets `app.kubernetes.io/name` and `app.kubernetes.io/part-of` labels.

```yaml
- name: Label namespace
  ansible.builtin.command: >-
    kubectl label namespace {{ app_namespace }}
    app.kubernetes.io/name={{ app_name }}
    app.kubernetes.io/part-of=golden-master
    --overwrite
```

### 7. StatefulSet PVC Safety Gate

If a StatefulSet has `volumeClaimTemplates` and existing PVCs are Bound, downgrade `kubectl_action` to `apply` to prevent data loss. An explicit `danger_full_replace: true` overrides the gate.

### 8. Consistent Namespace Variable

Always use `app_namespace`, never `{app}_namespace` (e.g., never `vault_namespace`, `grafana_namespace`).

---

## Voted Improvements (15 Total: 8 HIGH + 7 MEDIUM)

### HIGH Priority (eliminates a class of failures)

| # | Improvement | Source | Failure Class Eliminated |
|---|-------------|--------|--------------------------|
| 1 | Numeric-prefix canonical filenames | Cat 3/9 | Secrets/PVCs deleted by `replace --force`; ordering bugs |
| 2 | Reconcile/rebuild mode contract | Cross-cutting | Implicit/accidental destructive behaviour |
| 3 | Non-empty guard on secrets | Cat 4 | Credential wipe on extraction failure |
| 4 | Per-field preservation for multi-field secrets | Cat 4 | Full credential rotation on partial failure |
| 5 | Non-empty extraction guard | Cat 10 | Empty secret overwrite from failed sed |
| 6 | Pre-check pod existence before `kubectl wait` | Cat 5 | "No matching resources" crash |
| 7 | Eliminate contradictory `ignore_errors` patterns | Cat 7 | Green pipelines with broken apps |
| 8 | Full mode safety gate with claimTemplates detection | Cat 11 | Data loss / deadlock in full rebuild |

### MEDIUM Priority (correctness/robustness gain)

| # | Improvement | Source | Benefit |
|---|-------------|--------|---------|
| 9 | Mandatory namespace labels | Cat 1 | Consistent resource ownership |
| 10 | Tool auto-detection in exec probes | Cat 6 | Works across Alpine and non-Alpine images |
| 11 | Optional health response validation | Cat 6 | Catches 200-with-error-body edge cases |
| 12 | Structured state writeback on failure | Cat 7 | Diagnostics without log archaeology |
| 13 | Multi-field naming contract for PushSecrets | Cat 8 | Consistent naming, no structural refactoring later |
| 14 | File existence + non-empty pre-check for sed | Cat 10 | Guards against zero-byte config files |
| 15 | Select Ready pod in discovery | Cat 12 | Stable selection during rollouts |

---

## Architectural Review Additions (8)

These were added after the initial 15 improvements, based on architectural review of the golden master design.

| # | Addition | Where Applied | Purpose |
|---|----------|---------------|---------|
| 1 | Resource kind classifier safety net | Install playbook | Defence-in-depth beyond numeric prefixes -- detect protected resource kinds (Secret, PVC, Namespace, CRD, PushSecret) and refuse `replace --force` even if prefixes are wrong |
| 2 | Ready pod selection | Verify playbook | Select pods with `ready==true` container status, not just `phase=Running` |
| 3 | Health probe timeouts | Verify playbook | `--max-time` / `--timeout` flags on curl/wget to prevent hung probes |
| 4 | Dry-run server validation | Install playbook | `kubectl apply --dry-run=server` before real apply to catch schema errors early |
| 5 | Negative molecule tests | Molecule scenario | Verify safety mechanisms work (empty guard fires, PVC gate exists, protected prefix enforced) |
| 6 | Global timeout constants | Install/verify playbooks | `app_start_timeout_seconds`, `retry_interval_seconds`, `health_probe_timeout_seconds` instead of magic numbers |
| 7 | Secret drift detection | Install playbook | Hash comparison of existing vs rendered secrets, warn-but-preserve |
| 8 | Safe pod count check | Install playbook | Use `-o json \| jq '.items \| length'` not `.items[0]` indexing to avoid errors on empty pod lists |

---

## Secret Naming Contract

All credential-related resources follow a strict naming convention.

| Resource | Name Pattern | Example |
|----------|-------------|---------|
| K8s Secret | `{{ app_name }}-credentials` | `grafana-credentials` |
| PushSecret | `{{ app_name }}-push` | `grafana-push` |
| Vault remote key | `apps/data/{{ app_name }}/{{ field }}` | `apps/data/grafana/admin_password` |

**Exceptions:** Operator-managed apps (argocd, awx) where the operator dictates the secret name. Use the `secret_name` variable to override.

All secrets should be **multi-field capable** from day one, even if starting with a single credential. This avoids structural refactoring when a second credential is added.

---

## PushSecret Convention

Every app with credentials must have a `pushsecret.yaml.j2` template. The PushSecret pushes credentials from the K8s Secret to Vault KV for the ESO credential pipeline.

```
K8s Secret --> PushSecret CRD --> Vault KV --> sync-app-state.sh --> BWS
```

Template structure:

```yaml
apiVersion: external-secrets.io/v1alpha1
kind: PushSecret
metadata:
  name: {{ app_name }}-push
  namespace: {{ app_namespace }}
spec:
  secretStoreRefs:
    - name: vault-backend
      kind: ClusterSecretStore
  selector:
    secret:
      name: {{ app_name }}-credentials
  data:
    - match:
        secretKey: FIELD_NAME
        remoteRef:
          remoteKey: apps/data/{{ app_name }}/field_name
          property: value
```

---

## Verify Playbook Patterns

### Health Probe Auto-Detection

Use a self-selecting wrapper so probes work across Alpine (wget) and non-Alpine (curl) images:

```yaml
/bin/sh -c "command -v curl >/dev/null
&& curl -sf --max-time {{ health_probe_timeout_seconds }} http://127.0.0.1:{{ container_port }}{{ health_path }}
|| wget -q -O - --timeout={{ health_probe_timeout_seconds }} http://127.0.0.1:{{ container_port }}{{ health_path }}"
```

### Error Handling Rules

- **NEVER** use `ignore_errors: true` on health checks
- **NEVER** use `failed_when: false` on health checks
- **ALWAYS** use `retries:` + `until:` for retry tolerance
- **ALWAYS** use `failed_when: rc != 0` for hard failure after retries
- Use `block/rescue` for structured failure diagnostics

### Optional Response Validation

Set `health_response_pattern` to a regex for body inspection:

```yaml
vars:
  health_response_pattern: '"status"\s*:\s*"ok"'
```

---

## Config Playbook Patterns (Phase 4)

### Cardinal Rule

Phase 4/5 playbooks are **pure consumers** of BWS extra-vars. No `kubectl exec` or `curl` to discover values that BWS already has. No `| default('hardcoded-value')` for BWS-sourced vars.

### Dynamic Pod Discovery

Never hardcode pod names like `app-0`. Always use label-based lookup:

```yaml
- name: Get ready pod name
  ansible.builtin.command: >-
    kubectl -n {{ app_namespace }} get pods -l app.kubernetes.io/name={{ app_name }}
    --field-selector=status.phase=Running
    -o jsonpath='{.items[0].metadata.name}'
  register: app_pod
  retries: 3
  delay: 5
  until: app_pod.rc == 0 and app_pod.stdout != ''
```

### Variable Conventions

- Use `app_namespace`, never `{app}_namespace`
- No `KUBECONFIG` environment blocks (rely on default kubeconfig)
- All vars come from Phase 4 extra-vars via `-e @/tmp/bws-app-state.json`
- Namespace vars use plain literals as defaults: `app_namespace: "appname"` (Phase 4 extra-vars override when provided)

---

## Credential Extraction Patterns

For apps that generate credentials at runtime (Pattern B apps like sonarr, radarr, etc.):

### File Check Guard

Always check both existence AND non-empty content:

```yaml
- name: Wait for config file with content
  ansible.builtin.command: >-
    kubectl exec {{ pod }} -- /bin/sh -c "test -f {{ path }} && test -s {{ path }}"
  retries: 12
  delay: 10
  until: config_check.rc == 0
```

### Extraction Guard

Never overwrite the destination secret if extraction output is empty:

```yaml
- name: Guard against empty extraction
  ansible.builtin.fail:
    msg: "Credential extraction returned empty for {{ app_name }}"
  when: extracted_value.stdout | length == 0
```

### Post-Extraction Secret Creation

Use `--dry-run=client | apply` for idempotent secret creation after extraction:

```yaml
- name: Create credentials K8s Secret
  ansible.builtin.shell: >-
    kubectl create secret generic {{ app_name }}-credentials
    --from-literal={{ field }}={{ extracted_value.stdout }}
    -n {{ app_namespace }}
    --dry-run=client -o yaml | kubectl apply -f -
  no_log: true
```

---

## Global Timeout Constants

Use named variables instead of magic numbers for all timeouts:

```yaml
vars:
  app_start_timeout_seconds: 600
  retry_interval_seconds: 10
  health_probe_timeout_seconds: 5
```

Usage:

```yaml
retries: "{{ (app_start_timeout_seconds / retry_interval_seconds) | int }}"
delay: "{{ retry_interval_seconds }}"
```

---

## Best-Practice Reference Apps

For real-world examples of specific patterns:

| Pattern | Best Example App |
|---------|-----------------|
| Secret split-apply | `apps/neo4j/`, `apps/langfuse/` |
| Secret preservation | `apps/grafana/`, `apps/authentik/` |
| Multi-field secrets + PushSecret | `apps/langfuse/` (3 fields) |
| Health check with retries | `apps/grafana/`, `apps/jellyfin/` |
| PVC protection | `apps/claudebox/` |
| Namespace labeling | `apps/authentik/`, `apps/grafana/` |
| Full credential pipeline | `apps/langfuse/` |
| Dynamic pod discovery | `apps/sonarr/`, `apps/radarr/` |

---

## Creating a New App

1. Copy `apps/_golden-master/` to `apps/new-app/`
2. Replace all placeholder values (`app_name`, `app_namespace`, ports, images, credentials)
3. Remove sections that don't apply (e.g., credential extraction if no runtime secrets)
4. Run molecule validation: `ansible-playbook molecule/golden-master/converge.yml`
5. Add the app to `registry.json` via the registry generator

---

## Exclusions

The `_golden-master` directory is excluded from:

- `registry.json` generation (underscore prefix convention)
- Phase 3/4/5 workflow app discovery
- BWS inventory (no inventory entry exists)

The underscore prefix ensures filesystem-level exclusion from any glob pattern matching `apps/*/install/*.yml`.

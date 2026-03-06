#!/usr/bin/env bash
# generate-tier2-scenarios.sh — Create Tier 2 Molecule scenarios for all apps with install playbooks.
# Each scenario uses the shared Kind lifecycle playbooks and per-app fixture configs.
#
# Usage:
#   ./molecule/generate-tier2-scenarios.sh
#
# Run from the ansible/ directory, or the script will cd there automatically.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APPS_DIR="$(cd "$SCRIPT_DIR/../../apps" && pwd)"
TEMPLATES_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
REGISTRY="$TEMPLATES_DIR/registry.json"

# ── Namespace lookup ──────────────────────────────────────────────────────────
# Primary: registry.json (authoritative). Fallback: grep the deploy playbook.
lookup_namespace() {
  local app="$1"
  local playbook="$2"
  local ns=""

  # Try registry.json first
  if [ -f "$REGISTRY" ]; then
    ns=$(python3 -c "
import json, sys
with open('$REGISTRY') as f:
    r = json.load(f)
print(r.get('apps',{}).get('$app',{}).get('namespace',''))
" 2>/dev/null || true)
  fi

  # Fallback: grep playbook for *_namespace or app_namespace vars
  if [ -z "$ns" ]; then
    ns=$(grep -E '^\s+(app_namespace|'"$(echo "$app" | tr '-' '_')"'_namespace|storage_namespace|media_namespace): ' "$playbook" 2>/dev/null \
      | head -1 \
      | sed 's/.*: *"\{0,1\}\([^"]*\)"\{0,1\}.*/\1/' \
      | tr -d ' ' || true)
  fi

  # Fallback: metadata comment
  if [ -z "$ns" ]; then
    ns=$(grep -E '^#\s+namespace:' "$playbook" 2>/dev/null \
      | head -1 \
      | sed 's/.*: *"\{0,1\}\([^"]*\)"\{0,1\}.*/\1/' \
      | tr -d ' ' || true)
  fi

  # Last resort
  echo "${ns:-default}"
}

# ── Generate scenarios ────────────────────────────────────────────────────────
COUNT=0

for APP_DIR in "$APPS_DIR"/*/; do
  APP=$(basename "$APP_DIR")
  INSTALL_DIR="$APP_DIR/install"

  # Skip apps without install playbooks
  [ -d "$INSTALL_DIR" ] || continue
  DEPLOY_PLAYBOOK=$(find "$INSTALL_DIR" -name '01-*.yml' 2>/dev/null | head -1)
  [ -n "$DEPLOY_PLAYBOOK" ] || continue

  SCENARIO_DIR="$SCRIPT_DIR/install-${APP}"
  mkdir -p "$SCENARIO_DIR"

  NAMESPACE=$(lookup_namespace "$APP" "$DEPLOY_PLAYBOOK")
  DEPLOY_BASENAME=$(basename "$DEPLOY_PLAYBOOK")
  REL_PLAYBOOK="../../../apps/${APP}/install/${DEPLOY_BASENAME}"

  # ── molecule.yml ──────────────────────────────────────────────────────────
  cat > "$SCENARIO_DIR/molecule.yml" <<YAML
---
dependency:
  name: galaxy
  options:
    requirements-file: molecule/requirements.yml
driver:
  name: default
  options:
    managed: false
platforms:
  - name: localhost
provisioner:
  name: ansible
  config_options:
    defaults:
      gathering: explicit
  options:
    extra-vars: "@../fixtures/per-app/config-${APP}.json"
  env:
    KUBECONFIG: /tmp/molecule-kubeconfig
  inventory:
    hosts:
      all:
        hosts:
          localhost:
            ansible_connection: local
            target_hosts: localhost
            install_mode: rebuild
            kubectl_action: apply
scenario:
  create_sequence:
    - create
    - prepare
  converge_sequence:
    - converge
  destroy_sequence:
    - destroy
  test_sequence:
    - dependency
    - create
    - prepare
    - converge
    - idempotence
    - verify
    - destroy
verifier:
  name: ansible
YAML

  # ── converge.yml ──────────────────────────────────────────────────────────
  cat > "$SCENARIO_DIR/converge.yml" <<YAML
---
- name: "Create Kind cluster"
  ansible.builtin.import_playbook: ../shared/create-kind.yml

- name: "Prepare namespaces"
  ansible.builtin.import_playbook: ../shared/prepare-namespaces.yml

- name: "Ensure ${APP} namespace"
  hosts: localhost
  gather_facts: false
  environment:
    KUBECONFIG: /tmp/molecule-kubeconfig
  tasks:
    - name: Create ${APP} namespace
      ansible.builtin.shell: >-
        kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -
      changed_when: false

- name: "Deploy ${APP}"
  ansible.builtin.import_playbook: ${REL_PLAYBOOK}
YAML

  # ── verify.yml ────────────────────────────────────────────────────────────
  cat > "$SCENARIO_DIR/verify.yml" <<YAML
---
- name: "Verify ${APP} deployment"
  hosts: localhost
  gather_facts: false
  environment:
    KUBECONFIG: /tmp/molecule-kubeconfig
  vars:
    app_name: "${APP}"
    app_namespace: "${NAMESPACE}"
  tasks:
    - name: Check namespace exists
      ansible.builtin.command: kubectl get namespace {{ app_namespace }}
      register: ns_check
      changed_when: false

    - name: Check pods are running
      ansible.builtin.command: >-
        kubectl -n {{ app_namespace }} get pods -l app={{ app_name }}
        -o jsonpath='{.items[*].status.phase}'
      register: pod_status
      changed_when: false
      failed_when: false

    - name: Verify pod status
      ansible.builtin.assert:
        that:
          - "'Running' in pod_status.stdout or 'Pending' in pod_status.stdout"
        fail_msg: "No running pods found for {{ app_name }} in {{ app_namespace }}: {{ pod_status.stdout }}"
      when: pod_status.stdout | length > 0

    - name: Check services exist
      ansible.builtin.command: >-
        kubectl -n {{ app_namespace }} get svc -l app={{ app_name }}
        -o jsonpath='{.items[*].metadata.name}'
      register: svc_check
      changed_when: false
      failed_when: false

    - name: Report deployment status
      ansible.builtin.debug:
        msg: |
          App: {{ app_name }}
          Namespace: {{ app_namespace }}
          Pods: {{ pod_status.stdout | default('none') }}
          Services: {{ svc_check.stdout | default('none') }}
YAML

  COUNT=$((COUNT + 1))
  echo "  Created scenario: install-${APP}"
done

echo ""
echo "Generated ${COUNT} Tier 2 scenarios."
echo "Run: molecule test -s install-<app>"

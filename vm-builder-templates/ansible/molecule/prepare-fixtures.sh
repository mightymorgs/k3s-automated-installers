#!/usr/bin/env bash
# prepare-fixtures.sh — Download BWS cache and generate per-app Molecule fixtures.
# Replicates Phase 4's variable extraction so Molecule tests use real data.
#
# Usage:
#   ./molecule/prepare-fixtures.sh                              # default inventory key
#   ./molecule/prepare-fixtures.sh "inventory/my-custom-key"    # custom key
#
# Requires: BWS_ACCESS_TOKEN env var, bws CLI, jq

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURES_DIR="$SCRIPT_DIR/fixtures"
PER_APP_DIR="$FIXTURES_DIR/per-app"
ANSIBLE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$ANSIBLE_DIR/../../.." && pwd)"

INVENTORY_KEY="${1:-inventory/homelab-k3s-master-prod-mediastack-libvirt-latest}"

# ── Validate prerequisites ──────────────────────────────────────────────────
if [ -z "${BWS_ACCESS_TOKEN:-}" ]; then
  echo "ERROR: BWS_ACCESS_TOKEN not set"
  exit 1
fi

if ! command -v bws &>/dev/null; then
  echo "ERROR: bws CLI not found"
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo "ERROR: jq not found"
  exit 1
fi

mkdir -p "$PER_APP_DIR"

# ── Step 1: Download BWS inventory ──────────────────────────────────────────
echo "==> Downloading BWS inventory: $INVENTORY_KEY"
BWS_CACHE=$(bws secret list --output json)
SECRET_ID=$(echo "$BWS_CACHE" | jq -r --arg k "$INVENTORY_KEY" '.[] | select(.key==$k) | .id' | head -n1)

if [ -z "$SECRET_ID" ]; then
  echo "ERROR: Secret '$INVENTORY_KEY' not found in BWS"
  exit 1
fi

sleep 1  # Rate limit
INVENTORY=$(bws secret get "$SECRET_ID" --output json | jq -r '.value')
echo "$INVENTORY" > "$FIXTURES_DIR/bws-inventory.json"
echo "    Saved to fixtures/bws-inventory.json ($(echo "$INVENTORY" | jq 'keys | length') top-level keys)"

# ── Step 2: Build cross-app state JSON ──────────────────────────────────────
# This is the EXACT same jq as phase4-dynamic.yml lines 198-239
echo "==> Building cross-app state JSON"
VM_HOSTNAME=$(echo "$INVENTORY" | jq -r '.identity.hostname // "molecule-test"')

CROSS_APP_STATE=$(echo "$INVENTORY" | jq --arg vm_hostname "$VM_HOSTNAME" '
  ([._state.apps // {} | to_entries[] |
    select(.value | type == "object") |
    . as $app | ($app.key | gsub("-"; "_")) as $norm_key |
    (
      (select(.value.api_key != null and (.value.api_key | length) > 0) |
       {key: ($norm_key + "_api_key"), value: $app.value.api_key}),
      (select(.value.admin_password != null and (.value.admin_password | length) > 0) |
       {key: ($norm_key + "_admin_password"), value: $app.value.admin_password}),
      (select(.value.root_token != null and (.value.root_token | length) > 0) |
       {key: ($norm_key + "_root_token"), value: $app.value.root_token}),
      (select(.value.admin_token != null and (.value.admin_token | length) > 0) |
       {key: ($norm_key + "_admin_token"), value: $app.value.admin_token}),
      (select(.value.url != null and (.value.url | length) > 0) |
       {key: ($norm_key + "_url"), value: $app.value.url}),
      (select(.value.nodeport != null) |
       {key: ($norm_key + "_nodeport"), value: (.value.nodeport | tostring)}),
      (select(.value.pod_name != null and (.value.pod_name | length) > 0) |
       {key: ($norm_key + "_pod_name"), value: $app.value.pod_name}),
      (select(.value.namespace != null and (.value.namespace | length) > 0) |
       {key: ($norm_key + "_namespace"), value: $app.value.namespace}),
      (select(.value.service_name != null and (.value.service_name | length) > 0) |
       {key: ($norm_key + "_service_name"), value: $app.value.service_name}),
      (select(.value.service_port != null) |
       {key: ($norm_key + "_service_port"), value: (.value.service_port | tostring)}),
      (select(.value.websecure_port != null) |
       {key: ($norm_key + "_websecure_port"), value: (.value.websecure_port | tostring)})
    )
   ] | from_entries) +
  (if ._state.vault.root_token then {vault_root_token: ._state.vault.root_token} else {} end) +
  (if ._state.vault.unseal_key then {vault_unseal_key: ._state.vault.unseal_key} else {} end) +
  (if ._state.vault.initialized then {vault_initialized: ._state.vault.initialized} else {} end) +
  (if ._state.k3s.pod_cidr then {k3s_pod_cidr: ._state.k3s.pod_cidr} else {} end) +
  (if ._state.k3s.service_cidr then {k3s_service_cidr: ._state.k3s.service_cidr} else {} end) +
  (if .ingress.domain then {domain: .ingress.domain, ingress_domain: .ingress.domain} else {} end) +
  {vm_hostname: $vm_hostname, inventory_secret_name: "'"$INVENTORY_KEY"'"}
')

echo "$CROSS_APP_STATE" > "$FIXTURES_DIR/cross-app-state.json"
KEY_COUNT=$(echo "$CROSS_APP_STATE" | jq 'keys | length')
echo "    Cross-app state: $KEY_COUNT keys"

# ── Step 3: Build per-app config JSONs ──────────────────────────────────────
# Same merge logic as phase4-dynamic.yml lines 254-272
echo "==> Building per-app config JSONs"
REGISTRY_PATH="$REPO_ROOT/vm-builder/vm-builder-templates/registry.json"

if [ ! -f "$REGISTRY_PATH" ]; then
  echo "WARN: registry.json not found at $REGISTRY_PATH — using BWS _config only"
  REGISTRY='{}'
else
  REGISTRY=$(cat "$REGISTRY_PATH")
fi

APP_COUNT=0
for APP_DIR in "$REPO_ROOT"/vm-builder/vm-builder-templates/apps/*/; do
  APP=$(basename "$APP_DIR")

  # Layer 1: App-specific template config from BWS _config
  APP_CONFIG=$(echo "$INVENTORY" | jq -c --arg app "$APP" '._config[$app] // .apps.config[$app] // {}')

  if [ "$APP_CONFIG" = "{}" ] || [ "$APP_CONFIG" = "null" ]; then
    # Seed from registry defaults
    APP_CONFIG=$(echo "$REGISTRY" | jq -c --arg app "$APP" '
      .apps[$app].variables // {} |
      to_entries | map({key: .key, value: .value.default}) | from_entries')
  else
    # Sanitize: remove stale Jinja2 expressions
    APP_CONFIG=$(echo "$APP_CONFIG" | jq -c 'with_entries(select(.value | tostring | test("\\{\\{") | not))')
  fi

  # Layer 2: Merge cross-app state
  MERGED=$(jq -s '.[0] * .[1]' <(echo "$APP_CONFIG") "$FIXTURES_DIR/cross-app-state.json")
  echo "$MERGED" > "$PER_APP_DIR/config-${APP}.json"
  APP_COUNT=$((APP_COUNT + 1))
done

echo "    Generated $APP_COUNT per-app config JSONs in fixtures/per-app/"
echo ""
echo "==> Done. Fixtures ready for Molecule."

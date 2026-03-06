#!/usr/bin/env bash
# sync-app-state.sh — Collect cluster state + credentials for one app
#
# Outputs a JSON blob to /tmp/state-{app_id}.json containing:
#   - status, url, namespace, service_name, service_port, nodeport, pod_name
#   - installed_at timestamp
#   - Platform-specific fields (traefik websecure_port, authentik cluster_ip)
#   - Extracted credentials from K8s Secrets (registry-driven or legacy fallback)
#
# Does NOT do BWS read-modify-write — outputs JSON to /tmp/state-{app_id}.json.
# The caller (typically write_app_to_inventory in bws-helpers.sh) handles BWS writes.
#
# Usage: sync-app-state.sh <app_id> <registry_json_path>
#
# Called by:
#   - Phase 3 install-all-apps: per-app subshell, immediately after successful install
#   - Future: runtime debounce controller (async, on Vault KV changes)

set -euo pipefail

APP="$1"
REGISTRY_JSON="${2:-vm-builder/vm-builder-templates/registry.json}"

REGISTRY=$(cat "$REGISTRY_JSON")
NAMESPACE=$(echo "$REGISTRY" | jq -r --arg app "$APP" '.apps[$app].namespace // "default"')

# ── 1. Cluster state from registry.json ──────────────────────────
# Prefer registry.json metadata for nodeport/service info (authoritative source)
NODEPORT=$(echo "$REGISTRY" | jq -r --arg app "$APP" '.apps[$app].nodeport // null')
SERVICE_NAME=$(echo "$REGISTRY" | jq -r --arg app "$APP" '.apps[$app].ingress.service_name // $app')
SERVICE_PORT=$(echo "$REGISTRY" | jq -r --arg app "$APP" '.apps[$app].ingress.service_port // .apps[$app].port // 80')

# Build URL: NodePort (reachable from host) or ClusterIP fallback
if [ "$NODEPORT" != "null" ] && [ -n "$NODEPORT" ]; then
  APP_URL="http://127.0.0.1:${NODEPORT}"
else
  APP_URL="http://${SERVICE_NAME}.${NAMESPACE}.svc:${SERVICE_PORT}"
fi

# ── 2. Discover pod name (try common label selectors) ────────────
POD_NAME=""
for selector in "app=$APP" "app.kubernetes.io/name=$APP" "app.kubernetes.io/instance=$APP"; do
  POD_NAME=$(kubectl get pod -n "$NAMESPACE" -l "$selector" --no-headers \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [ -n "$POD_NAME" ]; then break; fi
done

# ── 3. Build base state JSON ────────────────────────────────────
APP_STATE=$(jq -n \
  --arg status "installed" \
  --arg url "$APP_URL" \
  --arg nodeport "$NODEPORT" \
  --arg namespace "$NAMESPACE" \
  --arg service_name "$SERVICE_NAME" \
  --arg service_port "$SERVICE_PORT" \
  --arg pod_name "$POD_NAME" \
  '{status: $status, url: $url, namespace: $namespace,
    service_name: $service_name, service_port: $service_port,
    installed_at: (now | strftime("%Y-%m-%dT%H:%M:%SZ"))}
    + (if $nodeport != "null" and $nodeport != "" then {nodeport: ($nodeport | tonumber)} else {} end)
    + (if $pod_name != "" then {pod_name: $pod_name} else {} end)')

# ── 4. Platform-specific state ──────────────────────────────────
if [ "$APP" = "traefik" ]; then
  WEBSECURE_PORT=$(kubectl get svc traefik -n "$NAMESPACE" \
    -o jsonpath='{.spec.ports[?(@.name=="websecure")].port}' 2>/dev/null || echo "")
  if [ -n "$WEBSECURE_PORT" ]; then
    APP_STATE=$(echo "$APP_STATE" | jq --arg p "$WEBSECURE_PORT" '.websecure_port = ($p | tonumber)')
  fi
fi
if [ "$APP" = "authentik" ]; then
  CLUSTER_IP=$(kubectl get svc "$SERVICE_NAME" -n "$NAMESPACE" \
    -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "")
  if [ -n "$CLUSTER_IP" ]; then
    APP_STATE=$(echo "$APP_STATE" | jq --arg ip "$CLUSTER_IP" '.cluster_ip = $ip')
  fi
fi

# ── 5. Extract credentials from K8s Secrets ─────────────────────
# Prefer registry.json credentials metadata (fully generic, no hardcoded apps).
# Fall back to legacy case block until all apps have credentials in registry.json.
CRED_META=$(echo "$REGISTRY" | jq -c --arg app "$APP" '.apps[$app].credentials // {}')

if [ "$CRED_META" != '{}' ]; then
  # Registry-driven: read secret_name + fields mapping from registry.json
  SECRET_NAME=$(echo "$CRED_META" | jq -r '.secret_name // empty')
  if [ -n "$SECRET_NAME" ]; then
    CRED_JSON=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" \
      -o json 2>/dev/null || echo "")
    if [ -n "$CRED_JSON" ]; then
      # Map K8s Secret keys to BWS field names using credentials.fields
      FIELDS_PATCH=$(echo "$CRED_META" | jq -c --argjson secret "$CRED_JSON" '
        .fields // {} | to_entries | map(
          select($secret.data[.key] != null) |
          {key: .value.bws_field,
           value: ($secret.data[.key] | @base64d)}
        ) | from_entries')
      if [ "$FIELDS_PATCH" != '{}' ]; then
        APP_STATE=$(echo "$APP_STATE" | jq --argjson creds "$FIELDS_PATCH" '. + $creds')
        # Mask credential values in Actions log
        for field in $(echo "$FIELDS_PATCH" | jq -r 'values[]'); do
          echo "::add-mask::${field}"
        done
        echo "  $APP: extracted credentials from K8s Secret (registry-driven)"
      fi
    fi
  fi
else
  # Legacy fallback: hardcoded mapping for Pattern A apps
  K8S_SECRET="" K8S_KEY="" BWS_FIELD=""
  case "$APP" in
    grafana)  K8S_SECRET="grafana-secrets";             K8S_KEY="GF_SECURITY_ADMIN_PASSWORD"; BWS_FIELD="admin_password" ;;
    argocd)   K8S_SECRET="argocd-initial-admin-secret";  K8S_KEY="password";                   BWS_FIELD="admin_password" ;;
    awx)      K8S_SECRET="awx-admin-password";           K8S_KEY="password";                   BWS_FIELD="admin_password" ;;
    neo4j)    K8S_SECRET="neo4j-auth";                   K8S_KEY="NEO4J_AUTH";                 BWS_FIELD="admin_password" ;;
    elastic)  K8S_SECRET="elasticsearch-credentials";    K8S_KEY="password";                   BWS_FIELD="admin_password" ;;
    langfuse) K8S_SECRET="langfuse-config";              K8S_KEY="NEXTAUTH_SECRET";            BWS_FIELD="admin_password" ;;
  esac

  if [ -n "$K8S_SECRET" ]; then
    CRED_VALUE=$(kubectl get secret "$K8S_SECRET" -n "$NAMESPACE" \
      -o jsonpath="{.data['$K8S_KEY']}" 2>/dev/null | base64 -d 2>/dev/null || true)
    if [ -n "$CRED_VALUE" ]; then
      echo "::add-mask::$CRED_VALUE"
      APP_STATE=$(echo "$APP_STATE" | jq --arg field "$BWS_FIELD" --arg val "$CRED_VALUE" '.[$field] = $val')
      echo "  $APP: extracted $BWS_FIELD from K8s Secret (legacy)"
    fi
  fi
fi

# ── 6. Write output ─────────────────────────────────────────────
echo "$APP_STATE" > "/tmp/state-${APP}.json"
echo "  $APP: state collected (ns=$NAMESPACE, url=$APP_URL)"

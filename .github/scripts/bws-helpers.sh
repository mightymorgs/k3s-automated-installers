#!/usr/bin/env bash
# Shared BWS helper functions for GitHub Actions workflows.
# Requires: /tmp/bws_secrets.json (created by setup-bws action)
# Usage: source "$GITHUB_WORKSPACE/.github/scripts/bws-helpers.sh"
set -euo pipefail

BWS_CACHE="${BWS_CACHE:-/tmp/bws_secrets.json}"

# Look up a BWS secret ID by key from the cached secret list
id_for() {
  jq -r --arg k "$1" '.[] | select(.key==$k) | .id' "$BWS_CACHE" | head -n1
}

# Fetch a BWS secret value by ID (with rate-limit-friendly delay)
get_val() {
  sleep 1
  bws secret get "$1" --output json | jq -r '.value'
}

# ── Per-app BWS inventory write with retry ──────────────────────
# Merges one app's _config + _state into the shared inventory secret.
# Uses flock to serialize concurrent writes from parallel subshells,
# with exponential backoff + jitter for BWS API rate limits.
#
# Usage: write_app_to_inventory <app_name> <secret_id>
# Expects: /tmp/state-{app}.json  (from sync-app-state.sh)
#           /tmp/app-config-{app}.json (from Step 3 pre-extract)
BWS_LOCK="/tmp/bws-write.lock"

write_app_to_inventory() {
  local APP="$1"
  local SECRET_ID="$2"
  local MAX_RETRIES=5

  local STATE_FILE="/tmp/state-${APP}.json"
  local CONFIG_FILE="/tmp/app-config-${APP}.json"

  if [ ! -f "$STATE_FILE" ]; then
    echo "[$APP] BWS write: no state file, skipping"
    return 0
  fi

  local STATE CONFIG
  STATE=$(cat "$STATE_FILE")
  CONFIG=$(cat "$CONFIG_FILE" 2>/dev/null || echo '{}')

  local attempt=0
  while [ $attempt -lt $MAX_RETRIES ]; do
    attempt=$((attempt + 1))

    # Exponential backoff + jitter on retries (avoid thundering herd)
    if [ $attempt -gt 1 ]; then
      local BACKOFF=$(( (1 << attempt) + RANDOM % 4 ))
      echo "[$APP] BWS write: retry $attempt in ${BACKOFF}s..."
      sleep "$BACKOFF"
    fi

    # flock serializes writes — only one subshell touches BWS at a time.
    # The flock subshell does read-merge-write atomically.
    if (
      flock -w 120 200 || exit 1

      # Read current inventory (1 BWS API call)
      sleep 1
      INVENTORY=$(bws secret get "$SECRET_ID" --output json | jq -r '.value')

      # Merge this app's state + full config
      INVENTORY=$(echo "$INVENTORY" | jq -c \
        --arg app "$APP" \
        --argjson state "$STATE" \
        --argjson cfg "$CONFIG" '
        ._state.apps[$app] = (._state.apps[$app] // {} | . * $state) |
        ._state.apps.installed |= (. // [] | if index($app) then . else . + [$app] end) |
        if ($cfg | length) > 0 then ._config[$app] = (._config[$app] // {} | . * $cfg) else . end
      ')

      SIZE=$(echo "$INVENTORY" | wc -c | tr -d ' ')

      # Write back (1 BWS API call)
      sleep 1
      bws secret edit --value "$INVENTORY" "$SECRET_ID"
      echo "[$APP] BWS write: OK (attempt $attempt, ${SIZE} chars)"

    ) 200>"$BWS_LOCK"; then
      return 0
    fi

    echo "[$APP] BWS write: attempt $attempt failed"
  done

  echo "::warning::[$APP] BWS write FAILED after $MAX_RETRIES attempts"
  return 1
}

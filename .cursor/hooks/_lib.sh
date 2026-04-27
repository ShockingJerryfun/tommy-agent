#!/usr/bin/env bash
# Shared helpers for the Tommy autopilot hooks.
# Project hooks run with the project root as CWD, so paths are relative.

set -euo pipefail

STATE_FILE=".cursor/state/stages.json"
LOG_FILE=".cursor/logs/autopilot.log"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG_FILE"
}

iso_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

require_state() {
  if [[ ! -f "$STATE_FILE" ]]; then
    log "FATAL: state file missing at $STATE_FILE"
    return 1
  fi
}

# Atomic JSON edit: read STATE_FILE, pipe through jq, write back.
# Usage: edit_state [jq flags...] '<jq filter>'
# The trailing filter MUST be the last argument; everything before it is
# forwarded to jq verbatim (including --arg name value pairs).
edit_state() {
  local tmp
  tmp="$(mktemp "${TMPDIR:-/tmp}/tommy-stages.XXXXXX")"
  jq "$@" "$STATE_FILE" >"$tmp"
  mv "$tmp" "$STATE_FILE"
}

read_state() {
  jq "$@" "$STATE_FILE"
}

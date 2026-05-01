#!/usr/bin/env bash
# autopilot.sh — control plane for the Tommy SOTA rebuild autopilot.
#
# Subcommands:
#   status                 Print the current stage table.
#   complete <STAGE_ID>    Mark a stage completed (called by the agent).
#   block <STAGE_ID> <msg> Mark a stage blocked with a one-line reason.
#   unblock <STAGE_ID>     Move a blocked stage back to in_progress.
#   start <STAGE_ID>       Force a stage into in_progress (rare).
#   reset                  Set every stage back to pending.
#   enable | disable       Toggle the auto_continue flag.
#   next                   Print the id of the next pending/in_progress stage.
#   set-chain <file.json>  Atomically replace the active chain with the contents
#                          of the given JSON file (preserves audit log).

set -euo pipefail

# Resolve workspace root (the directory containing .cursor/) regardless of CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

# shellcheck source=./_lib.sh
source "$SCRIPT_DIR/_lib.sh"

require_state >/dev/null

cmd="${1:-status}"
shift || true

stage_exists() {
  local id="$1"
  read_state -e --arg id "$id" '.stages | map(.id) | index($id) // -1 | . >= 0' >/dev/null
}

set_status() {
  local id="$1" status="$2" reason="${3:-}"
  if ! stage_exists "$id"; then
    echo "unknown stage id: $id" >&2
    exit 1
  fi
  edit_state --arg id "$id" --arg status "$status" --arg reason "$reason" --arg now "$(iso_now)" \
    '(.stages[] | select(.id == $id) | .status) |= $status
     | (.stages[] | select(.id == $id) | .blocked_reason) |= $reason
     | .updated_at = $now'
  log "$id -> $status${reason:+ ($reason)}"
}

case "$cmd" in
  status)
    read_state -r '"auto_continue: " + (.auto_continue | tostring)'
    read_state -r '
      .stages[]
      | "  [" + .status + "] " + .id + "  " + .title
        + (if .blocked_reason != "" then "  -- BLOCKED: " + .blocked_reason else "" end)
    '
    ;;

  next)
    read_state -r '
      ([.stages[] | select(.status == "in_progress")] + [.stages[] | select(.status == "pending")])
      | (.[0] // {id:""}).id
    '
    ;;

  complete)
    id="${1:?usage: autopilot.sh complete <STAGE_ID>}"
    set_status "$id" "completed" ""
    echo "✔ marked $id completed."
    ;;

  block)
    id="${1:?usage: autopilot.sh block <STAGE_ID> <reason>}"
    shift
    reason="${*:-no reason given}"
    set_status "$id" "blocked" "$reason"
    echo "⏸ marked $id blocked: $reason"
    ;;

  unblock)
    id="${1:?usage: autopilot.sh unblock <STAGE_ID>}"
    set_status "$id" "in_progress" ""
    echo "▶ unblocked $id (now in_progress)."
    ;;

  start)
    id="${1:?usage: autopilot.sh start <STAGE_ID>}"
    set_status "$id" "in_progress" ""
    echo "▶ forced $id into in_progress."
    ;;

  reset)
    edit_state --arg now "$(iso_now)" \
      '.stages |= map(.status = "pending" | .blocked_reason = "")
       | .updated_at = $now'
    log "all stages reset to pending."
    echo "↺ all stages reset to pending."
    ;;

  enable)
    edit_state --arg now "$(iso_now)" '.auto_continue = true | .updated_at = $now'
    log "autopilot enabled."
    echo "▶ autopilot enabled."
    ;;

  disable)
    edit_state --arg now "$(iso_now)" '.auto_continue = false | .updated_at = $now'
    log "autopilot disabled."
    echo "■ autopilot disabled."
    ;;

  set-chain)
    src="${1:?usage: autopilot.sh set-chain <path-to-chain.json>}"
    if [[ ! -f "$src" ]]; then
      echo "chain file not found: $src" >&2
      exit 1
    fi
    if ! jq -e '.stages and (.stages | type == "array")' "$src" >/dev/null; then
      echo "chain file must have a top-level .stages array" >&2
      exit 1
    fi
    label="$(jq -r '.active_chain // "unnamed"' "$src")"
    count="$(jq -r '.stages | length' "$src")"
    tmp="$(mktemp "${TMPDIR:-/tmp}/tommy-stages.XXXXXX")"
    jq --arg now "$(iso_now)" '.updated_at = $now' "$src" >"$tmp"
    mv "$tmp" "$STATE_FILE"
    log "chain replaced: active_chain=$label stages=$count source=$src"
    echo "▶ chain '$label' loaded ($count stages)."
    ;;

  *)
    echo "unknown subcommand: $cmd" >&2
    echo "see: $0 status | complete | block | unblock | start | reset | enable | disable | next | set-chain" >&2
    exit 2
    ;;
esac

#!/usr/bin/env bash
# Cursor `stop` hook — chains the Tommy SOTA rebuild stage by stage.
#
# Reads stdin (JSON payload from Cursor — currently unused), inspects
# .cursor/state/stages.json, and if autopilot is enabled and an unfinished
# stage exists, returns a `followup_message` so the agent re-enters on the
# next stage automatically. `loop_limit` in hooks.json bounds the chain.

set -euo pipefail

# shellcheck source=./_lib.sh
source "$(dirname "$0")/_lib.sh"

# Drain stdin so Cursor isn't kept waiting (payload not needed yet).
cat >/dev/null || true

if ! require_state; then
  echo '{}'
  exit 0
fi

auto_continue="$(read_state -r '.auto_continue // false')"
if [[ "$auto_continue" != "true" ]]; then
  log "auto_continue is disabled — exiting without followup."
  echo '{}'
  exit 0
fi

# Surface a blocked stage instead of skipping it.
blocked_stage="$(read_state -r '[.stages[] | select(.status == "blocked")] | .[0] // empty')"
if [[ -n "$blocked_stage" ]]; then
  blocked_id="$(printf '%s' "$blocked_stage" | jq -r '.id')"
  blocked_reason="$(printf '%s' "$blocked_stage" | jq -r '.blocked_reason')"
  log "stage $blocked_id is blocked — autopilot pausing."
  jq -n --arg id "$blocked_id" --arg reason "$blocked_reason" \
    '{followup_message: ("Autopilot is paused: stage \($id) is blocked. Reason: \($reason). Resolve the blocker or run `.cursor/hooks/autopilot.sh unblock \($id)` then re-trigger autopilot. Do not start any new work.")}'
  exit 0
fi

# Prefer an in-progress stage (resume), else first pending stage.
next="$(read_state -c '
  ([.stages[] | select(.status == "in_progress")] + [.stages[] | select(.status == "pending")]) | .[0] // empty
')"

if [[ -z "$next" || "$next" == "null" ]]; then
  log "all stages completed — autopilot stopping."
  echo '{}'
  exit 0
fi

next_id="$(printf '%s' "$next" | jq -r '.id')"
next_title="$(printf '%s' "$next" | jq -r '.title')"
next_status="$(printf '%s' "$next" | jq -r '.status')"

if [[ "$next_status" == "pending" ]]; then
  edit_state --arg id "$next_id" --arg now "$(iso_now)" \
    '(.stages[] | select(.id == $id) | .status) |= "in_progress"
     | .updated_at = $now'
  log "advanced stage $next_id to in_progress."
fi

# Build the autopilot prompt. The agent reads this as if the user typed it.
read -r -d '' MSG <<EOF || true
[AUTOPILOT — STAGE ${next_id}]

You are now executing stage ${next_id} of the Tommy SOTA rebuild.

Stage scope (from the locked Architectural Blueprint):
  ${next_title}

Hard rules for this stage:
  1. Implement the stage end-to-end without asking for permission. Decisions in §13 of the blueprint are already final.
  2. Use Cursor's native file/edit/terminal tools — do not just emit Markdown.
  3. Preserve public API behavior unless the stage explicitly changes it. Tests must stay green; ruff must stay clean.
  4. Add or update tests for any new behavior introduced by this stage.
  5. When the stage is fully complete (code written, lints clean, tests green), run from the workspace root:
        ./.cursor/hooks/autopilot.sh complete ${next_id}
     This is the ONLY signal the autopilot uses to advance. Do not skip it.
  6. If you are genuinely blocked and cannot proceed, run:
        ./.cursor/hooks/autopilot.sh block ${next_id} "<one-line reason>"
     Then stop. The autopilot will pause until the user resolves it.
  7. After you call \`autopilot.sh complete\`, the next stage will be triggered automatically by the stop hook — finish your turn cleanly.

Re-read \`.cursor/rules/autopilot.mdc\` if you need the full protocol. Begin work on ${next_id} now.
EOF

jq -n --arg msg "$MSG" '{followup_message: $msg}'
log "emitted followup for stage $next_id."

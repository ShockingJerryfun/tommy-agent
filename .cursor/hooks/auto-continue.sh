#!/usr/bin/env bash
# Cursor `stop` hook — chains the active autopilot stage chain.
#
# Reads stdin (JSON payload from Cursor — currently unused), inspects
# .cursor/state/stages.json, and if autopilot is enabled and an unfinished
# stage exists, returns a `followup_message` so the agent re-enters on the
# next stage automatically. `loop_limit` in hooks.json bounds the chain.
#
# The prompt template is generic: it pulls .chain_label / .chain_doc and the
# per-stage .title + .scope + .acceptance from stages.json, so this single
# script supports arbitrary chains (current chain: Tommy UX Parity).

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
next_scope="$(printf '%s' "$next" | jq -r '.scope // ""')"
next_accept="$(printf '%s' "$next" | jq -r '.acceptance // ""')"
next_executor="$(printf '%s' "$next" | jq -r '.executor // "subagent"')"

chain_label="$(read_state -r '.chain_label // .active_chain // "unnamed-chain"')"
chain_doc="$(read_state -r '.chain_doc // ""')"

if [[ "$next_status" == "pending" ]]; then
  edit_state --arg id "$next_id" --arg now "$(iso_now)" \
    '(.stages[] | select(.id == $id) | .status) |= "in_progress"
     | .updated_at = $now'
  log "advanced stage $next_id to in_progress."
fi

# Per-stage executor contract: stages that need first-person tool work
# (e.g. driving a real browser via cursor-ide-browser MCP) should set
# executor=parent so the foreman doesn't blindly hand off to a subagent.
if [[ "$next_executor" == "parent" ]]; then
  read -r -d '' PROTOCOL <<'PARENT_PROTO' || true
Execution protocol (PARENT-EXECUTED stage):
  1. YOU execute this stage directly. Do NOT dispatch a generalPurpose
     subagent for the audit/verification work itself — that is the whole
     point of this stage. Use Cursor's native tools (Shell, Read, Write,
     StrReplace, ReadLints) and the cursor-ide-browser MCP for browser
     automation.
  2. You MAY dispatch a small focused subagent ONLY for narrowly scoped
     fix-ups discovered during the audit/verification. Never delegate the
     audit / browser screenshots themselves.
  3. When the acceptance criteria for this stage all hold, run from the
     workspace root:
        ./.cursor/hooks/autopilot.sh complete <STAGE_ID>
     This is the ONLY signal the autopilot uses to advance.
  4. If you genuinely cannot finish (env blocker, missing creds, platform
     bug), run:
        ./.cursor/hooks/autopilot.sh block <STAGE_ID> "<one-line reason>"
     and stop the turn so the user can intervene.
  5. Never call `autopilot.sh complete` for more than one stage per turn.
  6. After `complete`, end your turn cleanly — the stop hook will inject
     the next stage's prompt automatically.
PARENT_PROTO
else
  read -r -d '' PROTOCOL <<'SUB_PROTO' || true
Foreman / subagent protocol (REQUIRED):
  1. You are the FOREMAN for this stage, not the implementer. Dispatch a
     subagent via the Task tool with subagent_type=generalPurpose and
     model=gpt-5.5-medium. Pass the subagent the FULL stage scope, the
     acceptance criteria above, the file paths to start from, and a strict
     instruction to use Cursor's native edit/terminal tools (no Markdown-only
     diffs).
  2. The subagent must NOT call `autopilot.sh complete`. When the subagent
     returns, YOU verify: from `backend/` run `python -m pytest -x -q` and
     `python -m ruff check`; sample the diff for adherence to scope; check
     the stage-specific acceptance bullets. If a quality gate fails, resume
     the same subagent (Task with the agent id from its previous reply,
     resume=<id>) up to two more times with a precise fix list.
  3. When all gates pass, run from the workspace root:
        ./.cursor/hooks/autopilot.sh complete <STAGE_ID>
     This is the ONLY signal the autopilot uses to advance. Do not skip it,
     do not call it before the work is actually green, and do not call it for
     a stage you did not just verify.
  4. After three failed subagent attempts, run:
        ./.cursor/hooks/autopilot.sh block <STAGE_ID> "<one-line reason>"
     and stop the turn so the user can intervene.
  5. Never call `autopilot.sh complete` for more than one stage per turn.
  6. After `complete` end your turn cleanly — the stop hook will inject the
     next stage's prompt automatically.
SUB_PROTO
fi

PROTOCOL="${PROTOCOL//<STAGE_ID>/$next_id}"

# Build the autopilot prompt. The agent reads this as if the user typed it.
read -r -d '' MSG <<EOF || true
[AUTOPILOT — STAGE ${next_id}]

You are now executing stage ${next_id} of the chain: ${chain_label}.
Reference plan / blueprint: ${chain_doc:-"(see .cursor/state/stages.json)"}

Stage title:
  ${next_title}

Executor:
  ${next_executor}

Stage scope:
  ${next_scope}

Acceptance criteria for this stage:
  ${next_accept}

${PROTOCOL}

Re-read \`.cursor/rules/autopilot.mdc\` if you need the full protocol.
Begin work on ${next_id} now.
EOF

jq -n --arg msg "$MSG" '{followup_message: $msg}'
log "emitted followup for stage $next_id."

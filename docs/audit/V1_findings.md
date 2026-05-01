# V1 — Empirical Browser Audit (Tommy UX Polish chain)

Date: 2026-04-28. Auditor: parent agent (Cursor / Claude Opus 4.7) driving the
`cursor-ide-browser` MCP against a freshly-built local stack (backend uvicorn
on `127.0.0.1:8000`, Next dev on `127.0.0.1:3000`).

Reference reading:
- ChatGPT signed-out shell (chatgpt.com) was captured at
  `docs/audit/v1/chatgpt/01_signed_out.png` — the marketing surface only,
  the actual chat UI is gated behind login. Findings below reference my
  internal model of ChatGPT's chat surface (chat list left, single
  conversation column, no permanently-mounted right rail, hover-only
  message toolbar with ~14px icons, etc.) which is well-known UX.

Local-app screenshots:
- `docs/audit/v1/desktop/01_initial_load.png` — 1280×800 viewport, freshly
  loaded landing on an existing session.
- `docs/audit/v1/desktop/02_new_chat_empty.png` — empty new conversation.
- `docs/audit/v1/desktop/03_tool_call_complete.png` — full-page screenshot
  after `echo hello-tommy` triggered `run_shell_command` and the agent
  produced a final answer.
- `docs/audit/v1/desktop/04_assistant_post_tool.png` — toolbar hover state.
- `docs/audit/v1/mobile/01_broken_layout.png` — viewport requested 390×844;
  the rendered DOM shows BOTH the desktop sidebar AND the desktop right
  rail simultaneously visible, the central chat column squeezed to almost
  nothing.
- `docs/audit/v1/mobile/02_after_reload.png` — the same after a hard
  navigate.

DOM probes were captured via `browser_snapshot` and stored only inline
in this doc (not separate files) since their utility is one-shot.

---

## P0 — must fix before anything else

### 1. Desktop UI is a "developer dashboard", not a chat product

**Symptom**: every chat surface permanently shows five right-rail panels
stacked vertically: `Approvals`, `Memory`, `Skills`, `Run State`,
`Settings`. The chat column ends up taking ~45% of the viewport width.
ChatGPT shows ONE column for chat, period; metadata lives behind a single
button or in the message itself.

**Evidence**: `desktop/01_initial_load.png`, `desktop/02_new_chat_empty.png`.
Right rail visible in both.

**Fix direction**: collapse the right rail to a single closeable panel
(toggle from a header button or `⌘K`). Default closed. Surface
`Run State` inline next to streaming messages instead of in a permanent
panel. Move `Settings` into a slide-over modal.

**Files**: `frontend/components/agent-shell.tsx` lines 2135–2200,
`frontend/components/inspector-panel.tsx`, `frontend/components/settings-panel.tsx`.
Severity: P0.

---

### 2. Inspector panels are mounted up to 3× simultaneously (DOM duplication)

**Symptom**: on every page render the snapshot tree contains the same
content twice for `Approvals`, `Memory`, `Skills`, `Run State`, `Settings`
(refs `e40` vs `e54`, `e41` vs `e55`, `e46–e53` vs `e60–e67`). On mobile
the `MobileInspectorSheet` adds a third copy.

**Root cause**: `agent-shell.tsx` mounts two responsive aside containers:

```2136:2160:frontend/components/agent-shell.tsx
        <aside className="hidden min-h-0 overflow-y-auto pr-1 scrollbar-thin xl:flex xl:flex-col xl:gap-3">
          <ApprovalPanel ... />
          <MemoryPanel ... />
          <SkillPanel ... />
          <ReasoningPanel ... />
          <SettingsPanel ... />
        </aside>
```

```2161:2200:frontend/components/agent-shell.tsx
        <div className="hidden max-h-[42dvh] min-h-0 gap-3 overflow-y-auto pr-1 scrollbar-thin lg:col-span-2 lg:grid xl:hidden">
          <ApprovalPanel ... />
          <MemoryPanel ... />
          <SkillPanel ... />
          <ReasoningPanel ... />
          <SettingsPanel ... />
        </div>
```

Plus `<MobileInspectorSheet>` at line 2063 that ALSO mounts the same panels.
Tailwind's `hidden` only hides visually — both DOM trees are present.

**Impact**: a11y tree pollution (screen readers announce settings 2–3×),
duplicated state subscriptions and re-renders, hydration mismatch warnings
(see console capture).

**Fix direction**: introduce a single source-of-truth `useViewport()` hook
that returns `{ isMobile, isCompact, isDesktop }` and conditionally render
ONLY one of the three variants. Or extract a single `<RightRail panels />`
component and conditionally pass it to the right slot.

Severity: P0.

---

### 3. Mobile (≤768 px) viewport renders with desktop layout

**Symptom**: at 390×844 the chat column is essentially unreadable. The
sidebar (left, ~170 px) and the right rail (right, ~170 px) both remain
visible, the middle is a black void, the composer is off-screen.

**Evidence**: `mobile/01_broken_layout.png`.

**Root cause**: agent-shell uses
`flex-col md:grid md:grid-cols-1 lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[15rem_minmax(0,1fr)_20rem]`
plus `hidden lg:flex` on the desktop sidebar and `xl:hidden lg:grid` on
the secondary rail. At 390px the sidebar should be hidden, but the
rendered DOM shows it visible. The `<MobileInspectorSheet>` and
`<MobileSessionDrawer>` components also exist but the responsive collapse
isn't actually firing — the page at 390 looks the same as at 1280.

**Fix direction**: rebuild the layout from a mobile-first single column.
At ≥`lg` open the sidebar; at ≥`xl` open the rail. Use
`SessionMobileHeader` only on `<lg`. Verify with browser DevTools device
emulation on iPhone 12.

**Files**: `frontend/components/agent-shell.tsx` lines 2040–2210,
`frontend/components/session-sidebar.tsx` line 147,
`frontend/components/session-mobile-header.tsx`,
`frontend/components/mobile-session-drawer.tsx`,
`frontend/components/mobile-inspector-sheet.tsx`.
Severity: P0.

---

### 4. React hydration mismatch on every load

**Symptom**: Next.js DevTools console reports
`A tree hydrated but some attributes of the server rendered HTML didn't
match the client properties` repeatedly, citing `data-cursor-ref` flips
across `MemoryPanel`, `SkillPanel`, `ReasoningPanel`, `SettingsPanel`.

**Evidence**: console capture in this turn.

**Root cause**: dual-mount + the `data-cursor-ref` injection path emits
different refs on server vs client because the dual mount creates
duplicate keys. Closing #2 likely closes this.

Severity: P0.

---

### 5. Composer footer leaks dev-mode controls into ChatGPT-style UI

**Symptom**: every chat shows a footer row beneath the textarea with
`工作目录` (input), `命令范围` (combobox `restricted/unrestricted`), plus
the smaller "按 ⌘↵ 发送 · Tommy 可能出错" caption. ChatGPT keeps the
composer to a single textarea with attach + send + footer caption.

**Evidence**: visible in every desktop screenshot at the bottom edge.

**Fix direction**: move `工作目录` and `命令范围` into Settings. Keep the
caption. Add a slim "scope" badge (e.g. `🛡️ Restricted`) inside the
composer textarea border, click to switch. Optionally show working
directory only when at least one shell tool is invoked in the session.

**Files**: `frontend/components/chat-composer.tsx`.
Severity: P0.

---

### 6. Action toolbar is jarring — "always visible on mobile" yielded
   ChatGPT-incompatible bulk

**Symptom**: U1 enlarged action icons to `h-5 w-5` inside `min-w-11
min-h-11` buttons "for mobile compliance". On desktop they look childlike
next to the prose. On mobile they cover too much of the bubble.

**Reference**: ChatGPT uses `~14 px` (≈`h-3.5 w-3.5`) icons with subtle
hover-only treatment on desktop and a separate compact bottom toolbar on
mobile. There is no oversized 44 pt button overlay on the bubble.

**Fix direction**: revert icon size to `h-3.5 w-3.5` (or `h-4 w-4`)
inside `p-1.5` rounded buttons (≈ 28 px hit area on desktop). On mobile
keep the **same** icon size but place the toolbar below the bubble in a
horizontal row with `py-2 gap-2` so each button still receives ~40 px of
touch area through generous spacing rather than oversized pixels. Hide
on desktop until the message is hovered (`group-hover` opacity-0 → 1).

**Files**: `frontend/components/message-stream.tsx`,
`frontend/components/agent-shell.tsx` (`copyMessage` action area).
Severity: P0.

---

## P1 — visible regressions vs ChatGPT

### 7. Empty state has illustrative cards instead of clickable
   suggested-prompt cards

**Symptom**: empty new chat shows four feature cards (`工具调用`, `长期
记忆`, `流式推理`, `任务分解`) — they are decorative, not interactive.
ChatGPT shows clickable suggestion chips ("Suggest fall foliage day-trips
near Boston", "Help me prep a job interview", …) that fill the composer
when tapped.

**Fix direction**: add `frontend/components/empty-state.tsx` with the
greeting, a small model picker, and 4 suggestion chips (mix of generic +
agent-aware: "Run `ls -la` and explain", "Search for the latest LangGraph
release", "Summarize this PDF", "Brainstorm ideas").
Severity: P1.

---

### 8. Header reads "LangGraph Agent" / "LangGraph Workbench" — too
   technical for the chat surface

**Symptom**: the page header literally says `LangGraph Workbench` and the
session header says `LangGraph Agent`. ChatGPT just says `ChatGPT`.

**Fix direction**: rename to `Tommy` everywhere user-facing. Reserve
LangGraph branding for an "About" or developer panel.

**Files**: `frontend/components/agent-shell.tsx`,
`frontend/components/session-sidebar.tsx`.
Severity: P1.

---

### 9. The session sidebar shows raw session IDs ("会话 dede7e") and
   crowded preview text

**Symptom**: every session row shows `<title>` followed by a 2-line preview
of the last message. This makes the sidebar visually noisy and the rows
roughly twice as tall as ChatGPT's. ChatGPT shows just the title (one
line, ellipsis on overflow) and groups by recency.

**Fix direction**: reduce session row to a single line with hover preview
in a tooltip. Group by `Today / Last 7 days / Last 30 days / Older`
instead of `置顶 / 最近 / 已归档`.

**Files**: `frontend/components/session-sidebar.tsx`.
Severity: P1.

---

### 10. Tables overflow the chat column at 1280px viewport

**Symptom**: the GFM table in the demo conversation
(`desktop/01_initial_load.png`) extends edge-to-edge with no max-width
constraint, columns stretching wide.

**Fix direction**: wrap markdown tables in a `<div class="overflow-x-auto
my-4 rounded border border-slate-200 dark:border-slate-800">` with
`min-w-full` on the table; sticky header on long tables.

**Files**: `frontend/components/message-stream.tsx` (markdown components).
Severity: P1.

---

### 11. The assistant avatar is a dark circle with a faint icon — no
   gradient ring during streaming, no breathing pulse

**Symptom**: the avatar (small disk on the message left) is static; users
have no perceptual cue that the model is generating beyond the `正在
回答…` label.

**Fix direction**: add a `bg-clip-padding ring-1 ring-emerald-500/40
animate-pulse` wrapper while `isStreaming && message.id === streamingId`.
Severity: P1.

---

### 12. There is no inline "Stop generating" affordance below the
   streaming bubble

**Symptom**: stop is only available via the composer's send-button-turned-
stop. ChatGPT shows a "Stop generating" pill below the streaming
assistant message.

**Files**: `frontend/components/message-stream.tsx`.
Severity: P1.

---

### 13. Code block top-bar feels chunky vs ChatGPT

**Symptom**: language label + copy button + collapse button = ~32 px
vertical bar. ChatGPT uses a slim ~24 px translucent bar with just
language name (left) and a single icon-style copy button (right).

**Fix direction**: tighten the bar (`h-9 px-3 text-[11px]`), drop the
collapse button — replace with a "show all" inline link inside the body
when truncated; reduce border to `1px solid rgba(...)`.

**Files**: `frontend/components/code-block.tsx`.
Severity: P1.

---

### 14. Settings panel shows raw select boxes for model/style/theme
   without preview affordances

**Symptom**: the settings panel exposes radio-like row controls
(`模型 DeepSeek V4 Pro / DeepSeek Chat / DeepSeek Reasoner`,
`回复风格 平衡 简洁 详细`, `外观 跟随系统 浅色 深色`). They look
correct but get rendered twice (per #2). Also the labels lack visual
separation; the panel currently looks denser than ChatGPT's settings sheet.

**Fix direction**: rebuild as a slide-over modal triggered from a single
gear icon top-right. Use grouped sections with subtle dividers.
Severity: P1.

---

### 15. Memory / Skill / Approval panels have no zero-state empathy

**Symptom**: all three show "暂无…" empty states which are utilitarian.
Users encountering this for the first time get no hint about what the
panel does.

**Fix direction**: add a subdued one-line caption explaining each panel's
role and a "Learn more" link.
Severity: P2.

---

### 16. The action toolbar (`复制消息`, `编辑消息`, `重新生成`) appears
   on hover but disappears immediately when leaving the bubble — no grace
   period

**Symptom**: hovering the bubble shows the bar, mousing onto the bar
itself sometimes flashes (depends on layout) because the bar is outside
the bubble's hover zone.

**Fix direction**: wrap bubble + toolbar in a single `group` and use
`group-hover:opacity-100 transition-opacity duration-150`.
Severity: P2.

---

### 17. `工作目录` placeholder uses fullwidth slashes (`/path/to/your/
   project`) but the actual setting accepts only POSIX paths — no
   validation feedback

**Severity**: P2.

---

### 18. The "已归档 ( 0 )" sidebar button stays visible even when there are
   no archived sessions

**Severity**: P2.

---

## Backend / agent

### 19. Agent tool-loop continuity — REPRO STATUS: not reproduced in this
   audit

**What I tried**: created a fresh session, set `命令范围 = 不受限制`,
sent `"运行命令 echo hello-tommy 然后告诉我输出"`. The agent called
`run_shell_command`, received `{"stdout":"hello-tommy\n"...}`, and
produced a final answer `"搞定。输出是：hello-tommy 什么都没有，就是
一行 hello-tommy。干净利落。"`. See `desktop/03_tool_call_complete.png`.

**Conclusion**: the simple single-tool case works on DeepSeek V4 Pro.
The user-reported "agent stops after calling tools" likely surfaces in
one of: (a) multi-tool sequences, (b) approval-required tools where
approval times out / fails, (c) specific models (Reasoner?), (d) errors
in the SSE event stream that close the stream prematurely. V2 must
reproduce this with a deterministic case (e.g. ask for two consecutive
shell commands then a summary) and fix or rule out.

**Files to inspect**:
- `backend/app/agent_framework/graph/routing.py` — `route_after_critic`
  looks correct on paper.
- `backend/app/agent_framework/runtime/event_service.py` — verify the
  SSE pipeline keeps emitting after a `ToolMessage` event.
- `backend/app/agent_framework/runtime/run_steps.py`.
- `frontend/components/agent-shell.tsx` `subscribeRunEvents` — confirm
  it doesn't close the EventSource after the first tool result.

Severity: P0 (per user report) — must be reproduced + fixed in V2.

---

## Acceptance summary for V1

- [x] Local stack started (`uvicorn` 8000, Next 3000).
- [x] Desktop screenshots captured at 4 key states.
- [x] Mobile screenshot captured (P0 layout bug evidenced).
- [x] ChatGPT reference screenshot captured (signed-out only).
- [x] >= 15 numbered findings (delivered: 19).
- [x] Agent tool-loop reproduction attempt documented.
- [x] Backend tests + ruff still green prior to changes (carried over
      from U9 verification, 157 passed / ruff clean).

V2 will start with findings 1, 2, 3, 4, 5, 6, 19. The remaining items
land in V3 (mobile parity) and V4 (visual polish).

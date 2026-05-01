# Tommy UX Parity Changelog

This changelog summarizes the U1-U9 UX parity chain, which aligned Tommy's chat experience with current ChatGPT/Cursor interaction patterns while preserving the existing LangGraph backend contract.

## Scope Snapshot

- 9 UX parity stages covering mobile behavior, editing/reruns, streaming, Markdown, conversation management, prompts, attachments, visual polish, and regression coverage.
- Product storage schema updates for run idempotency, session management/search, prompts, and run summaries.
- New frontend regression coverage runs on desktop Chromium and an iPhone 12 viewport, with axe critical violations asserted to zero.

## U-Stage Summary

- U1: Improved mobile copy behavior, independent abort controllers, iOS keyboard handling, live-region semantics, global stop/edit shortcuts, and 44pt message action hit targets.
- U2: Added historical user-message editing, rerun-from-message, assistant regeneration from a specific message, downstream truncation, and run idempotency keys.
- U3: Reworked streaming autoscroll into a stick-to-bottom model with a jump-to-bottom pill, retryable stream error banners, and smoother token flushing.
- U4: Upgraded Markdown rendering with KaTeX, GFM streaming tables, Shiki-backed code blocks, safe external links/images, language labels, copy, and collapse controls.
- U5: Added conversation rename, pin, archive, export, share, read-only public views, and full-text search with jump-to-message behavior.
- U6: Added slash and @ prompt insertion, prompt CRUD, and assistant bubble metadata for model, token counts, latency, and timestamps.
- U7: Added image/file attachments with local storage, drag/drop, paste capture, composer chips, message thumbnails, and multimodal passthrough metadata.
- U8: Tuned density, spacing, typography, avatar sizing, line-height, scrollbars, code borders, theme treatment, and settings-driven compact/comfortable mode.
- U9: Added Playwright regression coverage for desktop and iPhone 12 projects plus axe critical-violation checks and this changelog.

## Backend Surface

New or changed API endpoints:

- `PATCH /api/messages/{message_id}` edits user message content.
- `POST /api/messages/{message_id}/rerun` truncates later messages and starts a new run from the edited user message.
- `POST /api/messages/{message_id}/regenerate` truncates the assistant response and later messages, then regenerates from the parent user message.
- `PATCH /api/sessions/{session_id}` updates title, pinned, and archived state.
- `GET /api/sessions/{session_id}/export?format=md|json` exports a conversation.
- `POST /api/sessions/{session_id}/share`, `DELETE /api/sessions/{session_id}/share`, and `GET /share/{token}` manage public read-only sharing.
- `GET /api/search?q=...` returns highlighted message snippets and jump targets.
- `GET /api/prompts`, `POST /api/prompts`, `PATCH /api/prompts/{id}`, and `DELETE /api/prompts/{id}` manage prompt library entries.
- `POST /api/attachments` and `GET /api/attachments/{id}` upload and serve local attachments.
- `POST /api/sessions/{session_id}/stop` stops active generation from the UI.

Storage schema:

- `0008_run_idempotency` adds `runs.idempotency_key` with a unique per-session index.
- `0009_session_management_and_search` adds session pin/archive/share fields and message full-text search indexes.
- `0010_prompts_and_run_summary` adds prompt storage and run metric summary columns.
- Message metadata now carries attachment references in `metadata.attachments[]`; assistant messages expose run summaries when available.

## Frontend Surface

The chat UI now supports resilient copy for messages and code blocks, edit/save/rerun controls for user messages, targeted assistant regeneration, retry banners, sticky autoscroll with a jump pill, search result navigation, share link creation, public read-only views, slash/@ prompt insertion, KaTeX and highlighted code rendering, attachment upload/send flows, and density-aware visual polish across desktop and mobile.

## Verification

Regression coverage lives under `frontend/e2e` and runs against two Playwright projects: `desktop-chromium` and `mobile-iphone-12`. The suite covers message/code copy, retry and regenerate, historical edit with rerun, autoscroll lock and jump-to-bottom, image attachment upload/send, desktop search-and-jump, desktop share link creation, read-only share view, slash command insertion, KaTeX rendering, and axe checks with `critical` violations asserted to zero.

Expected verification commands:

```bash
cd frontend
npm run typecheck
npm run e2e:desktop
npm run e2e:mobile

cd ../backend
python -m pytest -x -q
python -m ruff check
```

# ChatGPT Mobile Strong Alignment Design

Date: 2026-05-22

## Goal

Make Tommy's mobile chat screen strongly resemble the ChatGPT iOS app shown in the reference screenshot, while preserving Tommy's existing chat, attachment, permission, settings, and inspector functionality behind mobile-appropriate entry points.

## Scope

This change targets the mobile chat experience below the desktop `lg` breakpoint. Desktop layout, backend APIs, streaming behavior, message persistence, session storage, and tool execution contracts stay unchanged.

## Visual Direction

The mobile surface becomes a focused single-column chat product:

- Page background uses a soft off-white tone instead of the current dashboard/glass shell.
- The chat surface is unframed on mobile; message content sits directly on the page.
- The top bar floats over the conversation like ChatGPT iOS: left back/session button, centered truncated session title/subtitle, and a right action pill for new chat and more actions.
- The composer is a fixed, large rounded bottom surface with textarea, attachment, permission badge, model/density indicator, and voice/send/stop actions inside one container.
- Developer-heavy panels are not visible by default on mobile.

## Component Changes

### `frontend/components/agent-shell.tsx`

- Keep the current desktop grid for `lg` and above.
- On mobile, render a single full-height column with:
  - mobile top navigation,
  - `MessageStream`,
  - `ChatComposer`.
- Replace the current mobile header shape with a ChatGPT-like floating header:
  - left circular session/back button,
  - centered title block,
  - right pill containing new session and more/inspector actions.
- Move mobile inspector access into the right action pill or overflow path. The inspector sheet remains available, but not visually dominant.

### `frontend/components/message-stream.tsx`

- Preserve markdown rendering and message actions.
- On mobile, remove card-like chat framing and tune spacing for direct reading:
  - larger readable assistant text,
  - quieter code and metadata color,
  - compact copy/action affordances below messages.
- Keep desktop behavior unchanged.

### `frontend/components/chat-composer.tsx`

- On mobile, make the composer visually match the reference:
  - fixed bottom safe-area spacing,
  - large rounded white surface,
  - input hint text at the top-left,
  - bottom action row inside the same surface,
  - attachment and permission state on the left,
  - model/status and mic/send/stop actions on the right.
- Keep existing attachment, paste, slash prompt, keyboard offset, submit, and stop behavior.
- Desktop composer keeps its current style.

### `frontend/app/globals.css`

- Add mobile-only classes for:
  - ChatGPT-like page background,
  - floating mobile header controls,
  - unframed mobile chat surface,
  - large bottom composer.
- Avoid changing global desktop tokens unless needed for responsive overrides.

## Interaction Rules

- Session drawer still opens from the left header button.
- New chat remains available from the right action pill.
- Inspector/settings remain available from the right action pill or overflow action, opening the existing mobile sheet.
- If the user is streaming, the composer send button becomes stop, preserving current behavior.
- The iOS keyboard offset logic remains intact.

## Testing

- Run TypeScript typecheck.
- Run the mobile Playwright suite or the targeted mobile specs affected by shell/composer behavior.
- Use browser verification at an iPhone-sized viewport to confirm:
  - no desktop sidebar/right rail is visible,
  - the header does not overlap readable content,
  - the composer stays above the safe area and keyboard offset,
  - message text and code blocks remain readable,
  - session drawer and inspector sheet are still reachable.

## Out Of Scope

- Desktop redesign.
- Backend changes.
- New settings or permission model.
- Rewriting the session drawer internals.
- Replacing markdown rendering.

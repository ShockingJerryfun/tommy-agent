# ChatGPT Mobile Strong Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle Tommy's mobile chat screen to strongly match the ChatGPT iOS reference while preserving existing chat behavior.

**Architecture:** Keep the existing React component boundaries and apply mobile-only class changes in `AgentShell`, `MessageStream`, `ChatComposer`, and `globals.css`. Desktop behavior remains controlled by existing `md`, `lg`, and `xl` responsive classes.

**Tech Stack:** Next.js 15, React 19, TypeScript strict mode, Tailwind CSS, Playwright e2e.

---

## File Structure

- Modify `frontend/components/agent-shell.tsx`: mobile page wrapper and `SessionMobileHeader` shape.
- Modify `frontend/components/message-stream.tsx`: mobile chat padding, text hierarchy, assistant avatar visibility, and jump pill sizing.
- Modify `frontend/components/chat-composer.tsx`: mobile composer structure and action row.
- Modify `frontend/app/globals.css`: mobile-only ChatGPT-like shell/composer/header CSS.
- Modify `frontend/e2e/apple-admin-style.spec.ts`: update mobile assertions to the new ChatGPT-like controls while keeping desktop Apple admin checks.
- Optionally modify `frontend/e2e/composer-simplification.spec.ts`: add a mobile-safe composer visibility assertion if needed after implementation.

## Task 1: Mobile Shell And Header

**Files:**
- Modify: `frontend/components/agent-shell.tsx`
- Modify: `frontend/app/globals.css`
- Test: `frontend/e2e/apple-admin-style.spec.ts`

- [ ] **Step 1: Update the mobile e2e expectation first**

Replace the mobile navigation test expectations with the new controls:

```ts
const menuButton = page.getByRole("button", { name: "打开对话列表" });
await expect(menuButton).toBeVisible();
await expect(page.getByRole("button", { name: "新建会话" })).toBeVisible();
await expect(page.getByRole("button", { name: "打开状态和设置" })).toBeVisible();
await expect(page.getByText(/Tommy|Session/).first()).toBeVisible();

const style = await menuButton.evaluate((element) => {
  const rect = element.getBoundingClientRect();
  const computed = getComputedStyle(element);
  return {
    width: Math.round(rect.width),
    height: Math.round(rect.height),
    backgroundColor: computed.backgroundColor,
    backdropFilter: computed.backdropFilter,
    borderRadius: computed.borderRadius,
    boxShadow: computed.boxShadow,
  };
});

expect(style.width).toBeGreaterThanOrEqual(52);
expect(style.height).toBeGreaterThanOrEqual(52);
expect(style.backgroundColor).toContain("rgba(255, 255, 255");
expect(style.backdropFilter).toContain("blur(");
expect(Number.parseInt(style.borderRadius, 10)).toBeGreaterThanOrEqual(24);
expect(style.boxShadow).toContain("rgba(0, 0, 0");
```

- [ ] **Step 2: Run the mobile style test and confirm it fails**

Run: `cd frontend && npm run e2e:mobile -- apple-admin-style.spec.ts`

Expected: the mobile navigation test fails because the current menu button is 40px and the settings button is still standalone.

- [ ] **Step 3: Change the shell wrapper classes**

In `frontend/components/agent-shell.tsx`, change the outer wrapper classes to provide a ChatGPT-like mobile page background and preserve desktop padding:

```tsx
<div className="mobile-chatgpt-page h-[100dvh] overflow-hidden md:min-h-screen md:bg-transparent md:p-5">
  <div className="mx-auto flex h-full w-full max-w-[100rem] flex-col md:grid md:h-[calc(100dvh-2.5rem)] md:grid-cols-1 md:gap-4 lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[15rem_minmax(0,1fr)_20rem] 2xl:grid-cols-[16rem_minmax(0,1fr)_21rem]">
```

- [ ] **Step 4: Replace `SessionMobileHeader` markup**

Keep the same props and callbacks, but render a left round button, centered title, and right pill:

```tsx
return (
  <div className="mobile-chatgpt-header pointer-events-none absolute inset-x-0 top-0 z-30 grid grid-cols-[3.5rem_minmax(0,1fr)_8.75rem] items-start gap-2 px-4 pt-[max(0.75rem,env(safe-area-inset-top)+0.55rem)] lg:hidden">
    <button
      type="button"
      onClick={onOpenSessions}
      className="mobile-chatgpt-header-button pointer-events-auto flex h-14 w-14 items-center justify-center rounded-full text-slate-950 transition active:scale-95 dark:text-slate-100"
      aria-label={t("app.a11y.openSessions")}
    >
      <Menu className="h-6 w-6" strokeWidth={2.6} />
    </button>

    <div className="min-w-0 px-1 pt-1.5 text-center">
      <p className="truncate text-[15px] font-semibold leading-5 tracking-normal text-slate-950 dark:text-slate-50">
        {isStreaming ? t("app.top.thinking") : title || "Tommy"}
      </p>
      <p className="truncate text-[12px] font-medium leading-4 text-slate-500 dark:text-slate-400">
        {sessionId ? `Tommy · ${sessionId.slice(-6)}` : "Tommy · Jin0"}
      </p>
    </div>

    <div className="mobile-chatgpt-header-pill pointer-events-auto ml-auto flex h-14 items-center gap-3 rounded-full px-4 text-slate-950 dark:text-slate-100">
      <button type="button" onClick={onNewSession} disabled={isStreaming} className="soft-focus-ring flex h-9 w-9 items-center justify-center rounded-full transition active:scale-95 disabled:opacity-40" aria-label={t("app.a11y.newSession")}>
        <Pencil className="h-6 w-6" strokeWidth={2.4} />
      </button>
      <button type="button" onClick={onOpenInspector} className="soft-focus-ring flex h-9 w-9 items-center justify-center rounded-full transition active:scale-95" aria-label={t("app.a11y.openInspector")}>
        <MoreHorizontal className="h-6 w-6" strokeWidth={2.8} />
      </button>
    </div>
  </div>
);
```

Remove `settings`, `settingsOpen`, `tommyAvatarUrl`, `onToggleSettings`, and `onSettingsChange` from the `SessionMobileHeader` signature and call site if no longer used by the component.

- [ ] **Step 5: Add mobile header CSS**

Add to `frontend/app/globals.css` near the existing iOS surface rules:

```css
.mobile-chatgpt-page {
  background: #f4f4f2;
}

.mobile-chatgpt-header-button,
.mobile-chatgpt-header-pill {
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(255, 255, 255, 0.58);
  box-shadow:
    0 10px 26px rgba(0, 0, 0, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(20px) saturate(1.2);
  -webkit-backdrop-filter: blur(20px) saturate(1.2);
}

.dark .mobile-chatgpt-page {
  background: #111111;
}

.dark .mobile-chatgpt-header-button,
.dark .mobile-chatgpt-header-pill {
  background: rgba(32, 32, 32, 0.86);
  border-color: rgba(255, 255, 255, 0.08);
}

@media (min-width: 768px) {
  .mobile-chatgpt-page {
    background: transparent;
  }
}
```

- [ ] **Step 6: Run typecheck**

Run: `cd frontend && npm run typecheck`

Expected: no unused prop/import errors remain.

## Task 2: Mobile Message Reading Surface

**Files:**
- Modify: `frontend/components/message-stream.tsx`
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: Add mobile-specific classes in `MessageStream`**

Change:

```tsx
<main className="app-chat-surface flex min-h-0 flex-1 flex-col overflow-hidden">
```

to:

```tsx
<main className="app-chat-surface mobile-chatgpt-surface flex min-h-0 flex-1 flex-col overflow-hidden">
```

Change the log container class to:

```tsx
className="scrollbar-thin relative min-h-0 flex-1 overflow-y-auto px-5 pb-52 pt-32 sm:px-6 md:pb-6 md:pt-6"
```

Change the message stack class to:

```tsx
<div className="space-y-5 md:space-y-4">
```

- [ ] **Step 2: Tune mobile message classes**

For user messages, change the bubble class to include mobile neutral bubble styling:

```tsx
className="mobile-chatgpt-user-bubble max-w-[86%] rounded-[1.35rem] rounded-tr-md text-[15px] leading-[var(--prose-line-height)] text-slate-900 sm:max-w-[72%] md:rounded-bubble md:text-[14px] dark:text-slate-100"
```

For assistant messages, change the wrapper and content classes:

```tsx
className="group flex gap-3 animate-fade-slide-up md:gap-3"
```

```tsx
className="mobile-chatgpt-assistant-copy min-w-0 flex-1 text-[17px] leading-[1.58] md:text-[14px] md:leading-[var(--prose-line-height)]"
```

Hide the assistant avatar on mobile without removing it on desktop:

```tsx
<div className="hidden md:block">
  <AvatarImage src={tommyAvatarUrl || "/tommy-avatar.png"} fallback="T" label="Tommy" />
</div>
```

- [ ] **Step 3: Add message surface CSS**

Add:

```css
.mobile-chatgpt-surface {
  background: transparent;
}

.mobile-chatgpt-user-bubble {
  background: #e8e8e6;
  box-shadow: none;
}

.mobile-chatgpt-assistant-copy code {
  color: #8a8a84;
}

@media (min-width: 768px) {
  .mobile-chatgpt-user-bubble {
    background: var(--liquid-glass-bg);
  }
}
```

- [ ] **Step 4: Run mobile composer regression**

Run: `cd frontend && npm run e2e:mobile -- composer-simplification.spec.ts`

Expected: Enter still sends and the message appears in the log.

## Task 3: ChatGPT-Like Mobile Composer

**Files:**
- Modify: `frontend/components/chat-composer.tsx`
- Modify: `frontend/app/globals.css`
- Test: `frontend/e2e/composer-simplification.spec.ts`

- [ ] **Step 1: Add a composer style assertion**

In `composer-simplification.spec.ts`, after locating `textarea#agent-message`, add:

```ts
const composerSurface = page.locator(".ios-composer-surface").first();
await expect(composerSurface).toBeVisible();
const composerBox = await composerSurface.boundingBox();
expect(composerBox?.height ?? 0).toBeGreaterThanOrEqual(110);
```

- [ ] **Step 2: Restructure `ChatComposer` actions**

Keep the textarea and input behavior intact. Change the form class to:

```tsx
className="relative flex-shrink-0 bg-transparent px-4 pb-[calc(env(safe-area-inset-bottom)+var(--keyboard-offset,0px)+1.35rem)] pt-2 md:p-0"
```

Change the surface class to:

```tsx
className="ios-composer-surface mobile-chatgpt-composer relative overflow-hidden transition-[box-shadow,transform] duration-200 focus-within:-translate-y-0.5 md:focus-within:translate-y-0"
```

Change the input row so the textarea sits above actions on mobile and stays inline on desktop:

```tsx
<div className="flex flex-col gap-3 px-4 pb-3 pt-4 md:flex-row md:items-end md:gap-2 md:px-4 md:pb-3 md:pt-4">
```

Change the textarea class to:

```tsx
className="min-h-8 w-full flex-1 resize-none bg-transparent py-0 text-[18px] leading-6 outline-none placeholder:text-slate-400/80 disabled:cursor-not-allowed disabled:opacity-50 md:text-[15px] dark:placeholder:text-slate-600"
```

Wrap the attachment and send controls in a bottom action row on mobile:

```tsx
<div className="flex items-center justify-between gap-3 md:contents">
  <div className="flex min-w-0 items-center gap-2">
    <button ...>...</button>
    <span className="mobile-chatgpt-access-badge hidden items-center gap-1.5 text-[13px] font-semibold md:hidden">
      完全访问
    </span>
  </div>
  <div className="flex items-center gap-2">
    <span className="mobile-chatgpt-model-label hidden text-[14px] font-semibold md:hidden">5.5 高</span>
    <button ...>...</button>
  </div>
</div>
```

Do not introduce new state or change `canSubmit`, `onStop`, `onSubmit`, paste, drag, attachment upload, or prompt palette logic.

- [ ] **Step 3: Add mobile composer CSS**

Add:

```css
.mobile-chatgpt-composer {
  min-height: 132px;
  border-radius: 25px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow:
    0 18px 45px rgba(0, 0, 0, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.mobile-chatgpt-access-badge {
  color: #d95f2f;
}

.mobile-chatgpt-model-label {
  color: #111111;
}

.dark .mobile-chatgpt-composer {
  background: rgba(32, 32, 32, 0.92);
}

.dark .mobile-chatgpt-model-label {
  color: #f4f4f2;
}

@media (min-width: 768px) {
  .mobile-chatgpt-composer {
    min-height: auto;
    border-radius: var(--apple-corner-intimate);
  }
}
```

- [ ] **Step 4: Run composer regression**

Run: `cd frontend && npm run e2e:mobile -- composer-simplification.spec.ts`

Expected: the composer is at least 110px tall on mobile and Enter still sends.

## Task 4: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run TypeScript**

Run: `cd frontend && npm run typecheck`

Expected: success.

- [ ] **Step 2: Run targeted mobile e2e**

Run: `cd frontend && npm run e2e:mobile -- apple-admin-style.spec.ts composer-simplification.spec.ts`

Expected: success.

- [ ] **Step 3: Start local frontend if needed**

Run: `cd frontend && npm run dev`

Expected: Next dev server prints a localhost URL.

- [ ] **Step 4: Browser verify mobile viewport**

Open the app at the local URL in an iPhone-sized viewport and verify:

- left session button, centered title, and right action pill match the approved mock direction,
- no desktop sidebar or right rail appears,
- message text does not hide behind the header,
- composer is fixed visually at the bottom and above safe area,
- session drawer and inspector sheet still open.

- [ ] **Step 5: Commit implementation**

Run:

```bash
git add frontend/components/agent-shell.tsx frontend/components/message-stream.tsx frontend/components/chat-composer.tsx frontend/app/globals.css frontend/e2e/apple-admin-style.spec.ts frontend/e2e/composer-simplification.spec.ts docs/superpowers/plans/2026-05-22-chatgpt-mobile-strong-alignment.md
git commit -m "feat: align mobile chat with chatgpt app"
```

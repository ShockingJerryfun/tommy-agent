"use client";

import type { ReactNode } from "react";
import { useRef, useState } from "react";

type InspectorPanelProps = {
  title: string;
  icon?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  bodyClassName?: string;
};

export function InspectorPanel({
  title,
  icon,
  action,
  children,
  defaultOpen = false,
  bodyClassName = "p-3",
}: InspectorPanelProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [height, setHeight] = useState<number | undefined>();
  const panelRef = useRef<HTMLElement>(null);

  function startResize(
    edge: "top" | "bottom",
    event: React.PointerEvent<HTMLDivElement>,
  ) {
    if (!open) return;
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = panelRef.current?.getBoundingClientRect().height ?? 280;

    function onPointerMove(moveEvent: PointerEvent) {
      const delta = moveEvent.clientY - startY;
      const nextHeight =
        edge === "top" ? startHeight - delta : startHeight + delta;
      setHeight(Math.max(112, Math.min(window.innerHeight * 0.86, nextHeight)));
    }

    function onPointerUp() {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }

    document.body.style.cursor = "ns-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp, { once: true });
  }

  return (
    <section
      ref={panelRef}
      className="glass-panel resizable-inspector-panel rounded-[var(--radius-panel)]"
      data-resized={open && height ? "true" : undefined}
      style={open && height ? { height } : undefined}
    >
      {open && (
        <div
          className="resizable-inspector-panel__handle resizable-inspector-panel__handle--top"
          onPointerDown={(event) => startResize("top", event)}
          role="separator"
          aria-orientation="horizontal"
          aria-label="向上或向下调整面板高度"
        />
      )}
      <details
        className="group flex h-full min-h-0 flex-col overflow-hidden"
        onToggle={(event) => setOpen(event.currentTarget.open)}
        open={open}
      >
        <summary className="admin-panel-header flex shrink-0 cursor-pointer list-none items-center justify-between gap-2 px-4 py-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 transition hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-black/10 dark:text-slate-400 dark:hover:text-slate-200 [&::-webkit-details-marker]:hidden">
          <span className="flex min-w-0 items-center gap-2">
            {icon}
            <span className="truncate">{title}</span>
          </span>
          {action && (
            <span
              className="hidden shrink-0 group-open:block"
              onClick={(event) => event.stopPropagation()}
            >
              {action}
            </span>
          )}
        </summary>

        <div
          className={`resizable-inspector-panel__body scrollbar-thin min-h-0 flex-1 overflow-y-auto ${bodyClassName}`}
        >
          {children}
        </div>
      </details>
      {open && (
        <div
          className="resizable-inspector-panel__handle resizable-inspector-panel__handle--bottom"
          onPointerDown={(event) => startResize("bottom", event)}
          role="separator"
          aria-orientation="horizontal"
          aria-label="向上或向下调整面板高度"
        />
      )}
    </section>
  );
}

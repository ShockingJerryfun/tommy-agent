"use client";

import { ArrowUp, Square } from "lucide-react";
import { useEffect, useRef } from "react";

import type { AgentSettings } from "./settings-panel";

type ChatComposerProps = {
  value: string;
  disabled: boolean;
  isStreaming: boolean;
  commandScope: AgentSettings["commandScope"];
  workingDirectory: string;
  onChange: (value: string) => void;
  onCommandScopeChange: (value: AgentSettings["commandScope"]) => void;
  onWorkingDirectoryChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
};

export function ChatComposer({
  value,
  disabled,
  isStreaming,
  commandScope,
  workingDirectory,
  onChange,
  onCommandScopeChange,
  onWorkingDirectoryChange,
  onSubmit,
  onStop,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inputDisabled = disabled || isStreaming;
  const canSubmit = !inputDisabled && value.trim().length > 0;

  /* Auto-resize textarea up to 200px */
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!isStreaming && canSubmit) onSubmit();
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (!isStreaming && canSubmit) onSubmit();
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex-shrink-0 bg-transparent px-4 pb-[calc(env(safe-area-inset-bottom)+0.85rem)] pt-2 shadow-none md:p-0"
    >
      <div className="rounded-[1.65rem] bg-white/96 shadow-[0_18px_50px_-24px_rgb(15_23_42/0.46),0_7px_22px_-14px_rgb(15_23_42/0.28)] backdrop-blur-2xl transition-[box-shadow,transform] duration-200 focus-within:-translate-y-0.5 focus-within:shadow-[0_24px_62px_-26px_rgb(15_23_42/0.55),0_10px_28px_-16px_rgb(15_23_42/0.34)] md:rounded-panel md:shadow-composer md:focus-within:translate-y-0 md:focus-within:shadow-[0_12px_40px_-8px_rgb(15_23_42/0.15)] dark:bg-slate-900/92 dark:shadow-[0_20px_56px_-24px_rgb(0_0_0/0.88),0_8px_24px_-16px_rgb(0_0_0/0.9)] dark:focus-within:shadow-[0_24px_64px_-24px_rgb(0_0_0/0.92),0_10px_30px_-16px_rgb(0_0_0/0.95)] md:dark:bg-slate-900/68 md:dark:shadow-composer md:dark:focus-within:shadow-[0_14px_42px_-16px_rgb(0_0_0/0.72)]">
        {/* Input row */}
        <div className="flex items-end gap-2 px-3.5 py-3 md:px-4 md:pb-3 md:pt-4">
          <label className="sr-only" htmlFor="agent-message">
            消息
          </label>
          <textarea
            ref={textareaRef}
            id="agent-message"
            value={value}
            disabled={inputDisabled}
            rows={1}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="给 Tommy 发消息…"
            className="flex-1 resize-none bg-transparent py-1.5 text-[16px] leading-6 outline-none placeholder:text-slate-400/80 disabled:cursor-not-allowed disabled:opacity-50 md:text-[15px] dark:placeholder:text-slate-600"
            style={{ minHeight: "28px", maxHeight: "200px" }}
          />
          <button
            type={isStreaming ? "button" : "submit"}
            disabled={isStreaming ? false : !canSubmit}
            aria-label={isStreaming ? "停止生成" : "发送消息"}
            onClick={isStreaming ? onStop : undefined}
            className={`
              mb-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full md:rounded-control
              transition-all duration-200
              focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1
              ${
                isStreaming
                  ? "bg-red-500 text-white shadow-sm hover:bg-red-600 focus-visible:ring-red-400/50"
                  : canSubmit
                    ? "bg-slate-950 text-white shadow-sm hover:-translate-y-0.5 hover:bg-slate-800 hover:shadow-md focus-visible:ring-slate-400/50 dark:bg-slate-700 dark:text-slate-50 dark:hover:bg-slate-600"
                    : "cursor-not-allowed bg-slate-200/90 text-slate-400 dark:bg-white/10 dark:text-slate-600"
              }
            `}
          >
            {isStreaming ? (
              <Square className="h-3.5 w-3.5" fill="currentColor" strokeWidth={2.4} />
            ) : (
              <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
            )}
          </button>
        </div>

        {/* Control / hint bar */}
        <div className="flex flex-col gap-2 bg-slate-950/[0.018] px-4 py-2.5 dark:bg-white/[0.025]">
          <div className="flex flex-col gap-2 md:flex-row md:items-center">
          <label
            className="flex min-w-0 flex-1 items-center gap-2 text-[11px] text-slate-500 dark:text-slate-500"
            htmlFor="agent-working-directory"
          >
            <span className="shrink-0">工作目录</span>
            <input
              id="agent-working-directory"
              value={workingDirectory}
              disabled={inputDisabled}
              onChange={(event) => onWorkingDirectoryChange(event.target.value)}
              placeholder="例如 /path/to/your/project"
              className="min-w-0 flex-1 rounded-full bg-slate-950/[0.05] px-3 py-1 text-[11px] font-medium text-slate-600 outline-none ring-1 ring-transparent transition placeholder:text-slate-400/70 focus:ring-slate-400/30 disabled:opacity-50 dark:bg-white/[0.06] dark:text-slate-300 dark:placeholder:text-slate-600"
            />
          </label>
          <label className="flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-500">
            <span className="shrink-0">命令范围</span>
            <select
              value={commandScope}
              disabled={inputDisabled}
              onChange={(event) =>
                onCommandScopeChange(event.target.value as AgentSettings["commandScope"])
              }
              className="rounded-full bg-slate-950/[0.05] px-2 py-1 text-[11px] font-medium text-slate-600 outline-none ring-1 ring-transparent transition focus:ring-slate-400/30 disabled:opacity-50 dark:bg-white/[0.06] dark:text-slate-300"
            >
              <option value="restricted">受限制（写入/命令需审批）</option>
              <option value="unrestricted">不受限制（免审批）</option>
            </select>
          </label>
          </div>
          <p className="hidden select-none text-[11px] leading-none text-slate-400 dark:text-slate-600 md:block">
            按{" "}
            <kbd className="rounded px-1 py-0.5 font-mono text-[10px] ring-1 ring-slate-300/80 dark:ring-white/15">
              ⌘↵
            </kbd>{" "}
            发送 &nbsp;·&nbsp; Tommy 可能出错，请核实重要信息
          </p>
        </div>
      </div>
    </form>
  );
}

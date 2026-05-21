"use client";

import {
  ArrowUp,
  AtSign,
  FileSpreadsheet,
  FileText,
  FileType,
  Loader2,
  Paperclip,
  Slash,
  Square,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useI18n } from "../lib/i18n";
import type { ComposerAttachment } from "./message-stream";

type ChatComposerProps = {
  value: string;
  disabled: boolean;
  isStreaming: boolean;
  onChange: (value: string) => void;
  pendingAttachments: ComposerAttachment[];
  onAddAttachments: (files: File[]) => void | Promise<void>;
  onRemoveAttachment: (id: string) => void;
  onSubmit: () => void;
  onStop: () => void;
};

type PromptItem = {
  id: string;
  kind: "builtin" | "user";
  name: string;
  body: string;
  shortcut: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isPromptItem(value: unknown): value is PromptItem {
  return (
    isRecord(value) &&
    (value.kind === "builtin" || value.kind === "user") &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.body === "string" &&
    typeof value.shortcut === "string"
  );
}

function promptItemsFromPayload(value: unknown): PromptItem[] {
  if (!isRecord(value) || !Array.isArray(value.prompts)) return [];
  return value.prompts.filter(isPromptItem);
}

type PromptTrigger = {
  kind: "builtin" | "user";
  icon: "slash" | "at";
  start: number;
  end: number;
  query: string;
};

const PROMPTS_REFRESH_EVENT = "tommy:refresh-prompts";
const API_BASE_OVERRIDE = process.env.NEXT_PUBLIC_AGENT_API_URL ?? "";
const ACCEPTED_FILE_TYPES = "image/*,.pdf,.txt,.md,.json,.csv";
const ACCEPTED_MIME_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/jpg",
  "image/webp",
  "image/gif",
  "application/pdf",
  "text/plain",
  "text/markdown",
  "application/json",
  "text/csv",
]);
const ACCEPTED_EXTENSIONS = new Set([".pdf", ".txt", ".md", ".json", ".csv"]);

export function refreshPrompts() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(PROMPTS_REFRESH_EVENT));
  }
}

function resolveApiBase() {
  if (API_BASE_OVERRIDE) return API_BASE_OVERRIDE.replace(/\/$/, "");
  if (typeof window !== "undefined") {
    return `${window.location.origin}/agent-api`;
  }
  return "/agent-api";
}

function findTokenEnd(text: string, start: number) {
  const match = text.slice(start).match(/\s/);
  return match?.index === undefined ? text.length : start + match.index;
}

function isAcceptedFile(file: File) {
  if (file.type.startsWith("image/") && ACCEPTED_MIME_TYPES.has(file.type))
    return true;
  if (ACCEPTED_MIME_TYPES.has(file.type)) return true;
  const lowerName = file.name.toLowerCase();
  return Array.from(ACCEPTED_EXTENSIONS).some((extension) =>
    lowerName.endsWith(extension),
  );
}

function filterAcceptedFiles(files: File[]) {
  return files.filter(isAcceptedFile);
}

function getPromptTrigger(text: string, cursor: number): PromptTrigger | null {
  if (text.startsWith("/")) {
    const end = findTokenEnd(text, 0);
    if (cursor >= 1 && cursor <= end) {
      return {
        kind: "builtin",
        icon: "slash",
        start: 0,
        end,
        query: text.slice(1, cursor),
      };
    }
  }

  for (let index = cursor - 1; index >= 0; index -= 1) {
    const char = text[index];
    if (/\s/.test(char)) return null;
    if (char !== "@") continue;
    if (index > 0 && !/\s/.test(text[index - 1])) return null;
    const end = findTokenEnd(text, index);
    if (cursor <= end) {
      return {
        kind: "user",
        icon: "at",
        start: index,
        end,
        query: text.slice(index + 1, cursor),
      };
    }
  }

  return null;
}

export function ChatComposer({
  value,
  disabled,
  isStreaming,
  onChange,
  pendingAttachments,
  onAddAttachments,
  onRemoveAttachment,
  onSubmit,
  onStop,
}: ChatComposerProps) {
  const { t } = useI18n();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragDepthRef = useRef(0);
  const listboxId = "prompt-palette";
  const inputDisabled = disabled || isStreaming;
  const hasUploadInFlight = pendingAttachments.some(
    (attachment) => attachment.uploading,
  );
  const canSubmit =
    !inputDisabled &&
    !hasUploadInFlight &&
    (value.trim().length > 0 || pendingAttachments.length > 0);
  const [prompts, setPrompts] = useState<PromptItem[]>([]);
  const [cursor, setCursor] = useState(0);
  const [activeIndex, setActiveIndex] = useState(0);
  const [isDragging, setIsDragging] = useState(false);

  const trigger = useMemo(
    () => getPromptTrigger(value, cursor),
    [value, cursor],
  );
  const filteredPrompts = useMemo(() => {
    if (!trigger) return [];
    const query = trigger.query.toLowerCase();
    return prompts
      .filter((prompt) => prompt.kind === trigger.kind)
      .filter((prompt) => {
        const haystack = `${prompt.name} ${prompt.shortcut}`.toLowerCase();
        return haystack.includes(query);
      })
      .slice(0, 8);
  }, [prompts, trigger]);
  const paletteOpen = Boolean(
    trigger && filteredPrompts.length > 0 && !inputDisabled,
  );
  const activePrompt = paletteOpen ? filteredPrompts[activeIndex] : undefined;

  function updateCursorFromTextarea() {
    setCursor(textareaRef.current?.selectionStart ?? 0);
  }

  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;

    const updateKeyboardOffset = () => {
      const offset = Math.max(
        0,
        window.innerHeight - viewport.height - viewport.offsetTop,
      );
      document.documentElement.style.setProperty(
        "--keyboard-offset",
        `${offset}px`,
      );
    };

    updateKeyboardOffset();
    viewport.addEventListener("resize", updateKeyboardOffset);
    viewport.addEventListener("scroll", updateKeyboardOffset);
    return () => {
      viewport.removeEventListener("resize", updateKeyboardOffset);
      viewport.removeEventListener("scroll", updateKeyboardOffset);
      document.documentElement.style.removeProperty("--keyboard-offset");
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadPrompts() {
      try {
        const response = await fetch(`${resolveApiBase()}/api/prompts`);
        if (!response.ok) return;
        const payload: unknown = await response.json();
        if (!cancelled) setPrompts(promptItemsFromPayload(payload));
      } catch {
        // Prompt shortcuts are optional UI sugar; keep the composer usable offline.
      }
    }

    const refresh = () => void loadPrompts();
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };

    refresh();
    window.addEventListener(PROMPTS_REFRESH_EVENT, refresh);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      cancelled = true;
      window.removeEventListener(PROMPTS_REFRESH_EVENT, refresh);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, []);

  useEffect(() => {
    setActiveIndex(0);
  }, [trigger?.kind, trigger?.query]);

  useEffect(() => {
    if (activeIndex >= filteredPrompts.length) {
      setActiveIndex(Math.max(0, filteredPrompts.length - 1));
    }
  }, [activeIndex, filteredPrompts.length]);

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

  function addFiles(files: File[]) {
    const accepted = filterAcceptedFiles(files);
    if (accepted.length > 0) {
      void onAddAttachments(accepted);
    }
  }

  function handleFileInputChange(event: React.ChangeEvent<HTMLInputElement>) {
    addFiles(Array.from(event.target.files ?? []));
    event.target.value = "";
  }

  function handleDragEnter(event: React.DragEvent<HTMLFormElement>) {
    if (inputDisabled) return;
    event.preventDefault();
    dragDepthRef.current += 1;
    setIsDragging(true);
  }

  function handleDragOver(event: React.DragEvent<HTMLFormElement>) {
    if (inputDisabled) return;
    event.preventDefault();
  }

  function handleDragLeave(event: React.DragEvent<HTMLFormElement>) {
    if (inputDisabled) return;
    event.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setIsDragging(false);
  }

  function handleDrop(event: React.DragEvent<HTMLFormElement>) {
    if (inputDisabled) return;
    event.preventDefault();
    dragDepthRef.current = 0;
    setIsDragging(false);
    addFiles(Array.from(event.dataTransfer.files ?? []));
  }

  function handlePaste(event: React.ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(event.clipboardData.items)
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((file): file is File => Boolean(file));
    if (files.length === 0) return;
    event.preventDefault();
    addFiles(files);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (paletteOpen && trigger && activePrompt) {
        insertPrompt(activePrompt, trigger);
      } else if (!isStreaming && canSubmit) {
        onSubmit();
      }
      return;
    }
    if (!paletteOpen || !trigger) {
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((index) => (index + 1) % filteredPrompts.length);
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex(
        (index) =>
          (index - 1 + filteredPrompts.length) % filteredPrompts.length,
      );
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      setCursor(-1);
      return;
    }
  }

  function insertPrompt(prompt: PromptItem, activeTrigger: PromptTrigger) {
    const nextValue =
      value.slice(0, activeTrigger.start) +
      prompt.body +
      value.slice(activeTrigger.end);
    const nextCursor = activeTrigger.start + prompt.body.length;
    onChange(nextValue);
    setCursor(nextCursor);
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(nextCursor, nextCursor);
    });
  }

  return (
    <form
      onSubmit={handleSubmit}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className="relative flex-shrink-0 bg-transparent px-4 pb-[calc(env(safe-area-inset-bottom)+var(--keyboard-offset,0px)+1.25rem)] pt-2 md:p-0"
    >
      {paletteOpen && trigger && (
        <PromptPalette
          id={listboxId}
          trigger={trigger}
          prompts={filteredPrompts}
          activeIndex={activeIndex}
          onActiveIndexChange={setActiveIndex}
          onSelect={(prompt) => insertPrompt(prompt, trigger)}
        />
      )}
      <div className="ios-composer-surface relative overflow-hidden transition-[box-shadow,transform] duration-200 focus-within:-translate-y-0.5 md:focus-within:translate-y-0">
        {isDragging && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-[var(--primary-color-light)] text-[15px] font-semibold text-slate-800 shadow-[inset_0_0_0_3px_rgba(34,34,34,0.08)] dark:bg-white/[0.06] dark:text-slate-100">
            {t("composer.drop")}
          </div>
        )}
        {pendingAttachments.length > 0 && (
          <AttachmentChipStrip
            attachments={pendingAttachments}
            onRemoveAttachment={onRemoveAttachment}
          />
        )}
        {/* Input row */}
        <div className="flex items-end gap-2 px-3.5 pb-2.5 pt-3 md:px-4 md:pb-3 md:pt-4">
          <label className="sr-only" htmlFor="agent-message">
            {t("composer.label")}
          </label>
          <textarea
            ref={textareaRef}
            id="agent-message"
            value={value}
            disabled={inputDisabled}
            rows={1}
            aria-activedescendant={
              activePrompt ? `${listboxId}-${activePrompt.id}` : undefined
            }
            aria-controls={paletteOpen ? listboxId : undefined}
            onChange={(e) => {
              onChange(e.target.value);
              setCursor(e.target.selectionStart);
            }}
            onClick={updateCursorFromTextarea}
            onKeyDown={handleKeyDown}
            onKeyUp={updateCursorFromTextarea}
            onPaste={handlePaste}
            onSelect={updateCursorFromTextarea}
            placeholder={t("composer.placeholder")}
            className="flex-1 resize-none bg-transparent py-1.5 text-[16px] leading-6 outline-none placeholder:text-slate-400/80 disabled:cursor-not-allowed disabled:opacity-50 md:text-[15px] dark:placeholder:text-slate-600"
            style={{ minHeight: "28px", maxHeight: "200px" }}
          />
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_FILE_TYPES}
            className="hidden"
            onChange={handleFileInputChange}
          />
          <button
            type="button"
            disabled={inputDisabled}
            aria-label={t("composer.addAttachment")}
            onClick={() => fileInputRef.current?.click()}
            className="control-glass soft-focus-ring mb-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full text-slate-500 transition-all duration-200 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-40 dark:text-slate-400 dark:hover:text-slate-100"
          >
            <Paperclip className="h-4 w-4" strokeWidth={2.2} />
          </button>
          <button
            type={isStreaming ? "button" : "submit"}
            disabled={isStreaming ? false : !canSubmit}
            aria-label={isStreaming ? t("composer.stop") : t("composer.send")}
            onClick={isStreaming ? onStop : undefined}
            className={`
              mb-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full md:rounded-control
              transition-all duration-200
              soft-focus-ring
              ${
                isStreaming
                  ? "bg-red-500 text-white shadow-sm hover:bg-red-600 focus-visible:ring-red-400/50"
                  : canSubmit
                    ? "premium-action"
                    : "cursor-not-allowed bg-slate-200/90 text-slate-400 dark:bg-white/10 dark:text-slate-600"
              }
            `}
          >
            {isStreaming ? (
              <Square
                className="h-3.5 w-3.5"
                fill="currentColor"
                strokeWidth={2.4}
              />
            ) : (
              <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
            )}
          </button>
        </div>

      </div>
    </form>
  );
}

function AttachmentChipStrip({
  attachments,
  onRemoveAttachment,
}: {
  attachments: ComposerAttachment[];
  onRemoveAttachment: (id: string) => void;
}) {
  return (
    <div className="admin-toolbar flex gap-2 overflow-x-auto px-3.5 py-3 scrollbar-thin md:px-4">
      {attachments.map((attachment) => (
        <div
          key={attachment.id}
          className="ios-glass-field group relative flex max-w-64 flex-shrink-0 items-center gap-2 rounded-2xl p-1.5 pr-10 text-[12px] font-medium text-slate-700 dark:text-slate-200"
        >
          <AttachmentPreview attachment={attachment} />
          <span className="min-w-0 max-w-36 truncate">{attachment.name}</span>
          {attachment.uploading && (
            <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin text-slate-400" />
          )}
          <button
            type="button"
            onClick={() => onRemoveAttachment(attachment.id)}
            disabled={attachment.uploading}
            className="liquid-hover soft-focus-ring absolute right-0 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full text-slate-500 transition hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-35 dark:text-slate-400 dark:hover:text-slate-100"
            aria-label={`移除附件 ${attachment.name}`}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}

function AttachmentPreview({ attachment }: { attachment: ComposerAttachment }) {
  if (attachment.mime.startsWith("image/") && attachment.thumbnailUrl) {
    return (
      <span className="admin-card h-10 w-10 flex-shrink-0 overflow-hidden rounded-xl bg-slate-200 dark:bg-white/[0.08]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={attachment.thumbnailUrl}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover"
        />
      </span>
    );
  }
  const Icon =
    attachment.mime === "application/pdf"
      ? FileType
      : attachment.mime === "text/csv"
        ? FileSpreadsheet
        : FileText;
  return (
    <span className="admin-icon-action flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl text-slate-500 dark:bg-white/[0.08] dark:text-slate-300">
      <Icon className="h-5 w-5" />
    </span>
  );
}

function PromptPalette({
  id,
  trigger,
  prompts,
  activeIndex,
  onActiveIndexChange,
  onSelect,
}: {
  id: string;
  trigger: PromptTrigger;
  prompts: PromptItem[];
  activeIndex: number;
  onActiveIndexChange: (index: number) => void;
  onSelect: (prompt: PromptItem) => void;
}) {
  const { t } = useI18n();
  const Icon = trigger.icon === "slash" ? Slash : AtSign;
  const label =
    trigger.kind === "builtin"
      ? t("composer.promptBuiltin")
      : t("composer.promptMine");

  return (
    <div className="absolute inset-x-4 bottom-full z-30 mb-2 md:inset-x-0">
      <div
        id={id}
        role="listbox"
        aria-label={label}
        aria-activedescendant={
          prompts[activeIndex] ? `${id}-${prompts[activeIndex].id}` : undefined
        }
        className="ios-menu-surface max-h-72 overflow-y-auto rounded-2xl p-1.5 scrollbar-thin"
      >
        <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
          {label}
        </div>
        {prompts.map((prompt, index) => {
          const active = index === activeIndex;
          return (
            <button
              key={prompt.id}
              id={`${id}-${prompt.id}`}
              type="button"
              role="option"
              aria-selected={active}
              onMouseEnter={() => onActiveIndexChange(index)}
              onMouseDown={(event) => {
                event.preventDefault();
                onSelect(prompt);
              }}
              className={`flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition ${
                active
                  ? "liquid-selected"
                  : "liquid-hover text-slate-600 dark:text-slate-300"
              }`}
            >
              <span className="admin-icon-action flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-slate-500 dark:bg-white/[0.08] dark:text-slate-400">
                <Icon className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium">
                  {prompt.name}
                </span>
                <span className="block truncate text-[11px] text-slate-400 dark:text-slate-500">
                  {prompt.shortcut
                    ? `${trigger.icon === "slash" ? "/" : "@"}${prompt.shortcut}`
                    : prompt.body}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

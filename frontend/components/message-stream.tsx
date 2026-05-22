"use client";

import {
  Check,
  ChevronDown,
  Copy,
  Database,
  FileSpreadsheet,
  FileText,
  FileType,
  Layers,
  Network,
  Pencil,
  RefreshCw,
  Zap,
} from "lucide-react";
import mermaid from "mermaid";
import Image from "next/image";
import type React from "react";
import { memo, useEffect, useId, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { hostMatchesImageAllowlist } from "../lib/imageHosts";
import { useI18n } from "../lib/i18n";
import { absoluteFor, formatRelative } from "../lib/relativeTime";
import type { StreamErrorInfo } from "../lib/streamErrors";
import { CodeBlock } from "./code-block";
import type { ToolCallView } from "./tool-call-card";
import { ToolCallCard } from "./tool-call-card";

export type ComposerAttachment = {
  id: string;
  name: string;
  mime: string;
  byteSize: number;
  thumbnailUrl: string;
  uploading?: boolean;
};

export type ChatMessagePart =
  | {
      id: string;
      type: "text";
      content: string;
    }
  | {
      id: string;
      type: "reasoning";
      content: string;
    }
  | {
      id: string;
      type: "tool";
      tool: ToolCallView;
    };

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt?: string;
  tools?: ToolCallView[];
  parts?: ChatMessagePart[];
  attachments?: ComposerAttachment[];
  streamError?: StreamErrorInfo | null;
  idempotencyKey?: string;
  runId?: string;
  runSummary?: RunSummary;
};

export type RunSummary = {
  run_id: string;
  model?: string | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
  latency_ms?: number | null;
  finish_reason?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

type MessageStreamProps = {
  messages: ChatMessage[];
  isStreaming: boolean;
  copiedMessageId?: string | null;
  expandedTools?: boolean;
  userAvatarUrl?: string;
  tommyAvatarUrl?: string;
  headerAction?: React.ReactNode;
  onCopyMessage: (message: ChatMessage) => void;
  onRegenerate: () => void;
  onRetry: (messageId: string) => void | Promise<void>;
  onEditMessage: (messageId: string, content: string) => Promise<void> | void;
  onEditAndRerunMessage: (
    messageId: string,
    content: string,
  ) => Promise<void> | void;
  onApproveRequest: (approvalId: string) => void;
  onRejectApprovalRequest: (approvalId: string) => void;
};

export function MessageStream({
  messages,
  isStreaming,
  copiedMessageId,
  expandedTools = false,
  userAvatarUrl = "",
  tommyAvatarUrl = "",
  headerAction,
  onCopyMessage,
  onRegenerate,
  onRetry,
  onEditMessage,
  onEditAndRerunMessage,
  onApproveRequest,
  onRejectApprovalRequest,
}: MessageStreamProps) {
  const { t } = useI18n();
  const scrollRef = useRef<HTMLDivElement>(null);
  const stuckToBottomRef = useRef(true);
  const previousMessageLengthRef = useRef(messages.length);
  const [showJumpPill, setShowJumpPill] = useState(false);

  /* Auto-scroll while the viewport is intentionally stuck to the latest token. */
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (messages.length > previousMessageLengthRef.current) {
      stuckToBottomRef.current = true;
      setShowJumpPill(false);
      el.scrollTop = el.scrollHeight;
      previousMessageLengthRef.current = messages.length;
      return;
    }
    previousMessageLengthRef.current = messages.length;
    if (!stuckToBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, isStreaming]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distance < 64) {
      stuckToBottomRef.current = true;
      setShowJumpPill(false);
      return;
    }
    stuckToBottomRef.current = false;
    setShowJumpPill(true);
  }

  function jumpToBottom() {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    stuckToBottomRef.current = true;
    setShowJumpPill(false);
  }

  const lastAssistantIdx = messages.reduce(
    (acc, m, i) => (m.role === "assistant" ? i : acc),
    -1,
  );

  return (
    <main className="app-chat-surface mobile-chatgpt-surface flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* ── Header ── */}
      <div className="admin-toolbar mx-3 mt-3 hidden items-center justify-between px-5 py-3 md:flex">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            Conversation
          </p>
          <h1 className="mt-0.5 text-[15px] font-semibold tracking-tight">
            LangGraph Agent
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <StreamingBadge visible={isStreaming} />
          {headerAction}
        </div>
      </div>

      {/* ── Message list ── */}
      <div
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        onScroll={handleScroll}
        className="scrollbar-thin relative min-h-0 flex-1 overflow-y-auto px-5 pb-52 pt-32 sm:px-6 md:pb-6 md:pt-6"
      >
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="space-y-5 md:space-y-4">
            {messages.map((message, idx) => (
              <MessageBubble
                key={message.id}
                message={message}
                isLastAssistant={idx === lastAssistantIdx}
                isStreaming={isStreaming}
                copied={copiedMessageId === message.id}
                expandedTools={expandedTools}
                onCopy={() => onCopyMessage(message)}
                onRegenerate={
                  idx === lastAssistantIdx ? onRegenerate : undefined
                }
                onRetry={onRetry}
                onEditMessage={onEditMessage}
                onEditAndRerunMessage={onEditAndRerunMessage}
                onApproveRequest={onApproveRequest}
                onRejectApprovalRequest={onRejectApprovalRequest}
                userAvatarUrl={userAvatarUrl}
                tommyAvatarUrl={tommyAvatarUrl}
              />
            ))}
          </div>
        )}
        {messages.length > 0 && (
          <div
            className={`pointer-events-none sticky bottom-4 z-20 mt-4 flex justify-end transition duration-200 ${
              showJumpPill ? "opacity-100" : "opacity-0"
            }`}
          >
            <button
              type="button"
              onClick={jumpToBottom}
            aria-label={t("stream.scrollBottom")}
              tabIndex={showJumpPill ? 0 : -1}
              className={`ios-glass-pill soft-focus-ring pointer-events-auto inline-flex min-h-11 min-w-11 items-center justify-center gap-2 px-3 text-[13px] font-medium text-slate-700 transition hover:-translate-y-0.5 dark:text-slate-100 ${
                showJumpPill ? "" : "pointer-events-none"
              }`}
            >
              <ChevronDown className="h-5 w-5" />
              <span className="hidden sm:inline">{t("stream.scrollBottom")}</span>
            </button>
          </div>
        )}
      </div>
    </main>
  );
}

/* ─────────────────────────────────────────── */
/*  Streaming badge                            */
/* ─────────────────────────────────────────── */

function StreamingBadge({ visible }: { visible: boolean }) {
  const { t } = useI18n();
  if (!visible) return null;
  return (
    <span className="flex animate-fade-slide-up items-center gap-2 rounded-full bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
      </span>
      {t("stream.generating")}
    </span>
  );
}

/* ─────────────────────────────────────────── */
/*  Empty / welcome state                      */
/* ─────────────────────────────────────────── */

function EmptyState() {
  const { t } = useI18n();
  const capabilities = [
    {
      icon: Zap,
      label: t("stream.feature.tools"),
      desc: t("stream.feature.toolsDesc"),
    },
    {
      icon: Database,
      label: t("stream.feature.memory"),
      desc: t("stream.feature.memoryDesc"),
    },
    {
      icon: Layers,
      label: t("stream.feature.reasoning"),
      desc: t("stream.feature.reasoningDesc"),
    },
    {
      icon: Network,
      label: t("stream.feature.tasks"),
      desc: t("stream.feature.tasksDesc"),
    },
  ];

  return (
    <div className="flex h-full min-h-[18rem] flex-col items-center justify-center gap-7 px-4 py-8 text-center animate-fade-slide-up md:min-h-[22rem] md:gap-8 md:py-10">
      <div className="flex flex-col items-center gap-4">
        {/* Logo mark */}
        <div className="relative">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--btn-primary)] shadow-[0_8px_24px_-8px_rgb(15_23_42/0.35)] dark:bg-slate-200">
            <svg
              className="h-7 w-7 text-white"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 2a7 7 0 0 1 7 7c0 2.5-1.3 4.7-3.3 6L17 21H7l1.3-6A7 7 0 0 1 5 9a7 7 0 0 1 7-7z" />
              <path d="M9 17h6" />
            </svg>
          </div>
          <span className="absolute -bottom-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500 shadow-sm">
            <span className="h-1.5 w-1.5 rounded-full bg-white" />
          </span>
        </div>

        <div>
          <h2 className="text-xl font-semibold tracking-tight">
            {t("stream.heroTitle")}
          </h2>
          <p className="mt-2 max-w-xs text-[13px] leading-relaxed text-slate-500 dark:text-slate-400">
            {t("stream.heroSubtitle")}
          </p>
        </div>
      </div>

      {/* Capability cards */}
      <div className="hidden w-full max-w-md grid-cols-2 gap-2 md:grid">
        {capabilities.map(({ icon: Icon, label, desc }) => (
          <div
            key={label}
            className="admin-card rounded-2xl p-3.5 text-left transition-colors"
          >
            <div className="admin-icon-action mb-2 flex h-7 w-7 items-center justify-center rounded-lg dark:bg-white/[0.08]">
              <Icon className="h-3.5 w-3.5 text-slate-500 dark:text-slate-400" />
            </div>
            <p className="text-[13px] font-medium leading-tight">{label}</p>
            <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
              {desc}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────── */
/*  Message bubble                             */
/* ─────────────────────────────────────────── */

type MessageBubbleProps = {
  message: ChatMessage;
  isLastAssistant: boolean;
  isStreaming: boolean;
  copied: boolean;
  expandedTools: boolean;
  onCopy: () => void;
  onRegenerate?: () => void;
  onRetry: (messageId: string) => void | Promise<void>;
  onEditMessage: (messageId: string, content: string) => Promise<void> | void;
  onEditAndRerunMessage: (
    messageId: string,
    content: string,
  ) => Promise<void> | void;
  onApproveRequest: (approvalId: string) => void;
  onRejectApprovalRequest: (approvalId: string) => void;
  userAvatarUrl: string;
  tommyAvatarUrl: string;
};

const MessageBubble = memo(function MessageBubble({
  message,
  isLastAssistant,
  isStreaming,
  copied,
  expandedTools,
  onCopy,
  onRegenerate,
  onRetry,
  onEditMessage,
  onEditAndRerunMessage,
  onApproveRequest,
  onRejectApprovalRequest,
  userAvatarUrl,
  tommyAvatarUrl,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  const [isSaving, setIsSaving] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const showCursor = isLastAssistant && isStreaming && message.content !== "";
  const hasReasoningPart = (message.parts ?? []).some(
    (part) => part.type === "reasoning" && part.content.length > 0,
  );
  const showTyping =
    isLastAssistant &&
    isStreaming &&
    message.content === "" &&
    (message.tools?.length ?? 0) === 0 &&
    !hasReasoningPart;

  useEffect(() => {
    if (!isEditing) {
      setDraft(message.content);
    }
  }, [isEditing, message.content]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [draft, isEditing]);

  async function saveEdit(rerun: boolean) {
    const nextContent = draft;
    if (!nextContent.trim() || nextContent === message.content || isSaving)
      return;
    setIsSaving(true);
    try {
      if (rerun) {
        await onEditAndRerunMessage(message.id, nextContent);
      } else {
        await onEditMessage(message.id, nextContent);
      }
      setIsEditing(false);
    } finally {
      setIsSaving(false);
    }
  }

  if (isUser) {
    const saveDisabled = isSaving || !draft.trim() || draft === message.content;
    return (
      <div
        id={`message-${message.id}`}
        className="group flex flex-col items-end gap-1 animate-fade-slide-up"
      >
        <div
          className="mobile-chatgpt-user-bubble max-w-[86%] rounded-[1.35rem] rounded-tr-md text-[15px] leading-[var(--prose-line-height)] text-slate-900 sm:max-w-[72%] md:rounded-bubble md:text-[14px] dark:text-slate-100"
          style={{
            padding: "var(--message-padding)",
          }}
        >
          <MessageAttachmentGrid attachments={message.attachments ?? []} />
          {isEditing ? (
            <div className="min-w-[min(28rem,70vw)] space-y-3">
              <textarea
                ref={textareaRef}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                className="ios-glass-field soft-focus-ring max-h-60 min-h-24 w-full resize-none overflow-hidden rounded-2xl px-3 py-2 text-[15px] leading-relaxed outline-none transition"
                aria-label="编辑消息"
                disabled={isSaving}
              />
              <div className="flex flex-wrap justify-end gap-2 text-[12px] font-medium">
                <button
                  type="button"
                  onClick={() => void saveEdit(false)}
                  disabled={saveDisabled}
                  className="premium-action soft-focus-ring min-h-11 px-4 text-[12px] font-semibold"
                >
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => void saveEdit(true)}
                  disabled={saveDisabled}
                  className="premium-action soft-focus-ring min-h-11 px-4 text-[12px] font-semibold disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Save & Rerun
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setDraft(message.content);
                    setIsEditing(false);
                  }}
                  disabled={isSaving}
                  className="admin-secondary-action soft-focus-ring min-h-11 px-4 text-[12px] font-semibold disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <p className="whitespace-pre-wrap">{message.content}</p>
          )}
        </div>
        {!isEditing && (
          <div className="flex items-center gap-2">
            <MessageActions
              copied={copied}
              onCopy={onCopy}
              onEdit={() => {
                setIsEditing(true);
              }}
              align="right"
            />
            <AvatarImage src={userAvatarUrl} fallback="U" label="You" />
          </div>
        )}
      </div>
    );
  }

  /* Assistant message — no bubble, avatar + text */
  return (
    <div
      id={`message-${message.id}`}
      className="group flex gap-3 animate-fade-slide-up md:gap-3"
    >
      {/* Avatar */}
      <div className="hidden md:block">
        <AvatarImage
          src={tommyAvatarUrl || "/tommy-avatar.png"}
          fallback="T"
          label="Tommy"
        />
      </div>

      {/* Content */}
      <div
        className="mobile-chatgpt-assistant-copy min-w-0 flex-1 text-[17px] leading-[1.58] md:text-[14px] md:leading-[var(--prose-line-height)]"
        style={{
          padding: "var(--message-padding)",
        }}
      >
        {showTyping ? (
          <TypingIndicator />
        ) : (
          <>
            {message.streamError && (
              <StreamErrorBanner
                error={message.streamError}
                disabled={isSaving || isStreaming}
                onRetry={() => void onRetry(message.id)}
              />
            )}
            <MessageContent
              message={message}
              showCursor={showCursor}
              expandedTools={expandedTools}
              isLastAssistant={isLastAssistant}
              isStreaming={isStreaming}
              onApproveRequest={onApproveRequest}
              onRejectApprovalRequest={onRejectApprovalRequest}
            />
            {message.runSummary && (
              <MessageRunMetadata
                summary={message.runSummary}
                createdAt={message.createdAt}
              />
            )}
            {(message.content || message.tools?.length) && (
              <MessageActions
                copied={copied}
                onCopy={onCopy}
                onRegenerate={isLastAssistant ? onRegenerate : undefined}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}, areMessageBubblePropsEqual);

function AvatarImage({
  src,
  fallback,
  label,
}: {
  src: string;
  fallback: string;
  label: string;
}) {
  if (!src) {
    return (
      <span
        aria-label={label}
        className="liquid-selected mt-1 flex flex-shrink-0 items-center justify-center rounded-full text-[12px] font-semibold"
        style={{
          height: "var(--message-avatar-size)",
          width: "var(--message-avatar-size)",
        }}
      >
        {fallback}
      </span>
    );
  }

  return (
    <img
      src={src}
      alt={label}
      loading="lazy"
      className="mt-1 flex-shrink-0 rounded-full object-cover shadow-sm"
      style={{
        height: "var(--message-avatar-size)",
        width: "var(--message-avatar-size)",
      }}
    />
  );
}

function MessageAttachmentGrid({
  attachments,
}: {
  attachments: ComposerAttachment[];
}) {
  if (attachments.length === 0) return null;
  return (
    <div className="mb-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
      {attachments.map((attachment) =>
        attachment.mime.startsWith("image/") ? (
          <a
            key={attachment.id}
            href={attachment.thumbnailUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="ios-glass-field block h-20 w-20 overflow-hidden rounded-2xl transition hover:opacity-90"
            aria-label={`打开附件 ${attachment.name}`}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={attachment.thumbnailUrl}
              alt={attachment.name}
              loading="lazy"
              className="h-full w-full object-cover"
            />
          </a>
        ) : (
          <a
            key={attachment.id}
            href={attachment.thumbnailUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="admin-card flex min-h-11 max-w-48 items-center gap-2 rounded-2xl px-3 py-2 text-[12px] font-medium text-slate-700 transition dark:text-slate-200"
            aria-label={`打开附件 ${attachment.name}`}
          >
            <AttachmentFileIcon
              mime={attachment.mime}
              className="h-4 w-4 flex-shrink-0"
            />
            <span className="truncate">{attachment.name}</span>
          </a>
        ),
      )}
    </div>
  );
}

function AttachmentFileIcon({
  mime,
  className,
}: {
  mime: string;
  className?: string;
}) {
  if (mime === "application/pdf") return <FileType className={className} />;
  if (mime === "text/csv") return <FileSpreadsheet className={className} />;
  return <FileText className={className} />;
}

function MessageRunMetadata({
  summary,
  createdAt,
}: {
  summary: RunSummary;
  createdAt?: string;
}) {
  const totalTokens =
    typeof summary.total_tokens === "number" && summary.total_tokens > 0
      ? `${summary.total_tokens} tokens`
      : "—";
  const latency =
    typeof summary.latency_ms === "number" && summary.latency_ms > 0
      ? `${(summary.latency_ms / 1000).toFixed(2)}s`
      : "—";

  return (
    <div className="mt-1.5 text-[11px] text-slate-400 opacity-100 transition md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100 dark:text-slate-500">
      <span>{summary.model || "—"}</span>
      <span className="px-1.5">·</span>
      <span>{totalTokens}</span>
      <span className="px-1.5">·</span>
      <span>{latency}</span>
      {createdAt && (
        <>
          <span className="px-1.5">·</span>
          <RelativeTime ts={createdAt} />
        </>
      )}
    </div>
  );
}

function RelativeTime({ ts }: { ts: string }) {
  return <time title={absoluteFor(ts)}>{formatRelative(ts)}</time>;
}

function areMessageBubblePropsEqual(
  previous: MessageBubbleProps,
  next: MessageBubbleProps,
) {
  return (
    previous.message === next.message &&
    previous.isLastAssistant === next.isLastAssistant &&
    previous.isStreaming === next.isStreaming &&
    previous.copied === next.copied &&
    previous.expandedTools === next.expandedTools &&
    previous.userAvatarUrl === next.userAvatarUrl &&
    previous.tommyAvatarUrl === next.tommyAvatarUrl
  );
}

function StreamErrorBanner({
  error,
  disabled,
  onRetry,
}: {
  error: StreamErrorInfo;
  disabled: boolean;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  const titleByKind: Record<StreamErrorInfo["kind"], string> = {
    network: "网络中断",
    http_4xx: "请求失败 (4xx)",
    http_5xx: "服务繁忙 (5xx)",
    rate_limit: "请求过多 (429)",
    unknown: "生成中断",
  };

  return (
    <div className="admin-error-card mb-3 max-w-[42rem] p-3 dark:bg-red-950/35 dark:text-red-100">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-[13px] font-semibold">{titleByKind[error.kind]}</p>
          <p className="mt-1 break-words text-[12px] leading-relaxed text-red-700 dark:text-red-200/85">
            {error.message}
          </p>
        </div>
        {error.retryable && (
          <button
            type="button"
            onClick={onRetry}
            disabled={disabled}
            className="soft-focus-ring inline-flex min-h-11 flex-shrink-0 items-center justify-center rounded-lg bg-red-600 px-4 text-[13px] font-semibold text-white transition hover:-translate-y-0.5 hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-red-500 dark:hover:bg-red-400"
          >
            {t("stream.retry")}
          </button>
        )}
      </div>
    </div>
  );
}

function ReasoningBlock({
  content,
  isLive,
}: {
  content: string;
  isLive: boolean;
}) {
  const [userToggled, setUserToggled] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const isOpen = userToggled ? userOpen : isLive;
  const summary = content.slice(-90).replace(/\s+/g, " ").trim();
  return (
    <details
      className="admin-card group my-1.5 max-w-[36rem] overflow-hidden rounded-2xl text-slate-600 dark:text-slate-300"
      open={isOpen}
      onToggle={(e) => {
        setUserToggled(true);
        setUserOpen((e.target as HTMLDetailsElement).open);
      }}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-[12px] leading-none [&::-webkit-details-marker]:hidden">
        <span className="relative flex h-2 w-2 flex-shrink-0">
          {isLive && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--primary-color)] opacity-60" />
          )}
          <span
            className={`relative inline-flex h-2 w-2 rounded-full ${
              isLive ? "bg-[var(--primary-color)]" : "bg-slate-400"
            }`}
          />
        </span>
        <span className="min-w-0 flex-1 truncate font-medium">
          {isLive ? "正在思考" : "思考过程"}
          {summary ? (
            <span className="ml-1 font-normal text-slate-400">· {summary}</span>
          ) : null}
        </span>
        <ChevronDown className="h-3.5 w-3.5 flex-shrink-0 text-slate-400 transition-transform group-open:rotate-180" />
      </summary>

      <div className="px-3 pb-2.5 pt-1 text-[12px] leading-relaxed text-slate-500 dark:text-slate-400">
        <div className="whitespace-pre-wrap break-words">
          {content}
          {isLive && (
            <span className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] rounded-sm bg-slate-500 opacity-70 animate-cursor-blink dark:bg-slate-300" />
          )}
        </div>
      </div>
    </details>
  );
}

function MessageActions({
  copied,
  onCopy,
  onRegenerate,
  onEdit,
  align = "left",
}: {
  copied: boolean;
  onCopy: () => void;
  onRegenerate?: () => void;
  onEdit?: () => void;
  align?: "left" | "right";
}) {
  const [labelVisible, setLabelVisible] = useState(false);

  function copy() {
    onCopy();
    setLabelVisible(true);
    window.setTimeout(() => setLabelVisible(false), 1200);
  }

  return (
    <div
      className={`mt-1 flex items-center gap-0.5 text-slate-400 opacity-100 transition md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100 ${
        align === "right" ? "justify-end" : ""
      }`}
    >
      <button
        type="button"
        onClick={copy}
        className="liquid-hover soft-focus-ring inline-flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 transition hover:-translate-y-0.5 hover:text-slate-700 dark:hover:text-slate-200"
        aria-label="复制消息"
      >
        {copied || labelVisible ? (
          <Check className="h-4 w-4 text-emerald-500" />
        ) : (
          <Copy className="h-4 w-4" />
        )}
      </button>
      {onRegenerate && (
        <button
          type="button"
          onClick={onRegenerate}
          className="liquid-hover soft-focus-ring inline-flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 transition hover:-translate-y-0.5 hover:text-slate-700 dark:hover:text-slate-200"
          aria-label="重新生成"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      )}
      {onEdit && (
        <button
          type="button"
          onClick={onEdit}
          className="liquid-hover soft-focus-ring inline-flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 transition hover:-translate-y-0.5 hover:text-slate-700 dark:hover:text-slate-200"
          aria-label="编辑消息"
        >
          <Pencil className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

function MessageContent({
  message,
  showCursor,
  expandedTools,
  isLastAssistant,
  isStreaming,
  onApproveRequest,
  onRejectApprovalRequest,
}: {
  message: ChatMessage;
  showCursor: boolean;
  expandedTools: boolean;
  isLastAssistant: boolean;
  isStreaming: boolean;
  onApproveRequest: (approvalId: string) => void;
  onRejectApprovalRequest: (approvalId: string) => void;
}) {
  const parts = message.parts?.length
    ? message.parts
    : [
        ...(message.content
          ? [
              {
                id: `${message.id}-text`,
                type: "text" as const,
                content: message.content,
              },
            ]
          : []),
        ...((message.tools ?? []).map((tool) => ({
          id: `${message.id}-${tool.id}`,
          type: "tool" as const,
          tool,
        })) satisfies ChatMessagePart[]),
      ];

  if (parts.length === 0) return null;

  const rendered: React.ReactNode[] = [];
  let pendingTools: ToolCallView[] = [];

  function flushTools(key: string) {
    if (pendingTools.length === 0) return;
    rendered.push(
      <ToolCallSummary
        key={key}
        tools={pendingTools}
        expandedTools={expandedTools}
        onApproveRequest={onApproveRequest}
        onRejectApprovalRequest={onRejectApprovalRequest}
      />,
    );
    pendingTools = [];
  }

  parts.forEach((part, index) => {
    if (part.type === "tool") {
      pendingTools.push(part.tool);
      return;
    }

    flushTools(`tools-before-${part.id}`);

    if (part.type === "reasoning") {
      if (!part.content) return;
      const isLive =
        isLastAssistant && isStreaming && index === parts.length - 1;
      rendered.push(
        <ReasoningBlock key={part.id} content={part.content} isLive={isLive} />,
      );
      return;
    }

    if (part.content) {
      rendered.push(
        <MessageText
          key={part.id}
          content={part.content}
          showCursor={showCursor && index === parts.length - 1}
        />,
      );
    }
  });

  flushTools("tools-tail");

  return <div className="space-y-2.5">{rendered}</div>;
}

function MessageText({
  content,
  showCursor,
}: {
  content: string;
  showCursor: boolean;
}) {
  if (showCursor) {
    return <StreamingMarkdown content={content} showCursor />;
  }

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={markdownComponents}
      >
        {content}
      </ReactMarkdown>
      {showCursor && (
        <span className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[2px] rounded-sm bg-slate-700 opacity-80 animate-cursor-blink dark:bg-slate-300" />
      )}
    </div>
  );
}

function StreamingMarkdown({
  content,
  showCursor,
}: {
  content: string;
  showCursor: boolean;
}) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={markdownComponents}
      >
        {content}
      </ReactMarkdown>
      {showCursor && (
        <span className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[2px] rounded-sm bg-slate-700 opacity-80 animate-cursor-blink dark:bg-slate-300" />
      )}
    </div>
  );
}

function isUnsafeHref(href: string) {
  return /^\s*javascript:/i.test(href);
}

function isExternalHref(href: string) {
  if (href.startsWith("/") || href.startsWith("#")) return false;
  try {
    const url = new URL(href);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export const markdownComponents: Components = {
  p({ children }) {
    return <p className="my-2.5">{children}</p>;
  },
  h1({ children }) {
    return (
      <h1 className="mb-2 mt-4 text-xl font-semibold tracking-tight">
        {children}
      </h1>
    );
  },
  h2({ children }) {
    return (
      <h2 className="mb-2 mt-4 text-lg font-semibold tracking-tight">
        {children}
      </h2>
    );
  },
  h3({ children }) {
    return (
      <h3 className="mb-1.5 mt-3 text-base font-semibold tracking-tight">
        {children}
      </h3>
    );
  },
  ul({ children }) {
    return <ul className="my-2 list-disc space-y-1.5 pl-5">{children}</ul>;
  },
  ol({ children }) {
    return <ol className="my-2 list-decimal space-y-1.5 pl-5">{children}</ol>;
  },
  li({ children }) {
    return <li>{children}</li>;
  },
  a({ children, href }) {
    if (!href || isUnsafeHref(href)) {
      return <>{children}</>;
    }
    const external = isExternalHref(href);
    return (
      <a
        href={href}
        target={external ? "_blank" : undefined}
        rel={external ? "noopener noreferrer nofollow" : undefined}
        className="underline-offset-2 hover:underline"
      >
        {children}
      </a>
    );
  },
  img({ src, alt }) {
    if (typeof src !== "string" || !src || isUnsafeHref(src)) {
      return null;
    }
    if (hostMatchesImageAllowlist(src)) {
      return (
        <Image
          src={src}
          alt={alt ?? ""}
          width={800}
          height={500}
          style={{ height: "auto", maxWidth: "100%" }}
          className="rounded-xl"
        />
      );
    }
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt={alt ?? ""}
        loading="lazy"
        referrerPolicy="no-referrer"
        className="max-w-full rounded-xl"
      />
    );
  },
  blockquote({ children }) {
    return (
      <blockquote className="my-2 rounded-2xl px-4 py-3 italic text-slate-600 shadow-[var(--liquid-glass-shadow)] dark:text-slate-300">
        {children}
      </blockquote>
    );
  },
  table({ children }) {
    return (
      <div className="ios-glass-field my-3 overflow-x-auto rounded-2xl scrollbar-thin">
        <table className="min-w-full border-separate border-spacing-0 text-left text-[13px]">
          {children}
        </table>
      </div>
    );
  },
  th({ children }) {
    return (
      <th className="px-3 py-2 font-semibold text-slate-700 shadow-[inset_0_-1px_0_rgba(15,23,42,0.05)] dark:text-slate-200">
        {children}
      </th>
    );
  },
  td({ children }) {
    return (
      <td className="px-3 py-2 align-top text-slate-600 dark:text-slate-300">
        {children}
      </td>
    );
  },
  pre({ children }) {
    return <>{children}</>;
  },
  code({ children, className }) {
    const value = String(children).replace(/\n$/, "");
    const language = /language-([\w-]+)/.exec(className ?? "")?.[1] ?? "";
    if (language === "mermaid") {
      return <MermaidBlock chart={value} />;
    }
    if (!className && !value.includes("\n")) {
      return (
        <code className="ios-glass-field rounded-md px-1 py-0.5 font-mono text-[0.92em] text-slate-800 dark:text-slate-100">
          {children}
        </code>
      );
    }
    return <CodeBlock code={value} language={language} />;
  },
};

function MermaidBlock({ chart }: { chart: string }) {
  const id = useId().replace(/:/g, "");
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");
  const [darkMode, setDarkMode] = useState(false);

  useEffect(() => {
    const update = () =>
      setDarkMode(document.documentElement.classList.contains("dark"));
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    const themeVariables = darkMode
      ? {
          background: "transparent",
          primaryColor: "#1e293b",
          primaryTextColor: "#e2e8f0",
          primaryBorderColor: "#475569",
          lineColor: "#94a3b8",
          secondaryColor: "#0f172a",
          tertiaryColor: "#020617",
          clusterBkg: "#0f172a",
          clusterBorder: "#334155",
          edgeLabelBackground: "#0f172a",
          nodeTextColor: "#e2e8f0",
          textColor: "#e2e8f0",
        }
      : {
          background: "transparent",
          primaryColor: "#f8fafc",
          primaryTextColor: "#334155",
          primaryBorderColor: "#cbd5e1",
          lineColor: "#64748b",
          secondaryColor: "#f1f5f9",
          tertiaryColor: "#ffffff",
          clusterBkg: "#f8fafc",
          clusterBorder: "#cbd5e1",
          edgeLabelBackground: "#ffffff",
          nodeTextColor: "#334155",
          textColor: "#334155",
        };
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      themeVariables,
    });
    mermaid
      .render(`mermaid-${id}`, chart)
      .then((result) => {
        if (!cancelled) {
          setSvg(result.svg);
          setError("");
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [chart, darkMode, id]);

  if (error) {
    return <CodeBlock code={chart} language="mermaid" />;
  }

  return (
    <div className="message-diagram-block my-3 overflow-x-auto rounded-2xl border p-3 scrollbar-thin">
      {svg ? (
        <div
          className="min-w-max [&_svg]:max-w-none"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      ) : (
        <p className="text-[12px] text-slate-400">正在渲染 Mermaid…</p>
      )}
    </div>
  );
}

function ToolCallSummary({
  tools,
  expandedTools,
  onApproveRequest,
  onRejectApprovalRequest,
}: {
  tools: ToolCallView[];
  expandedTools: boolean;
  onApproveRequest: (approvalId: string) => void;
  onRejectApprovalRequest: (approvalId: string) => void;
}) {
  if (tools.length === 0) return null;
  if (tools.length <= 2) {
    return (
      <>
        {tools.map((tool) => (
          <ToolCallCard
            key={tool.id}
            tool={tool}
            defaultOpen={expandedTools}
            onApprove={onApproveRequest}
            onReject={onRejectApprovalRequest}
          />
        ))}
      </>
    );
  }

  const latestTools = tools.slice(-4);
  const waiting = tools.filter(
    (tool) => tool.status === "pending_approval",
  ).length;
  const running = tools.filter((tool) => tool.status === "running").length;
  const failed = tools.filter((tool) => tool.status === "error").length;
  const toolNames = Array.from(new Set(tools.map((tool) => tool.name))).slice(
    0,
    3,
  );
  const statusText =
    waiting > 0
      ? `${waiting} 个待审批`
      : running > 0
        ? `${running} 个运行中`
        : failed > 0
          ? `${failed} 个失败`
          : "全部完成";

  return (
    <details
      open={(expandedTools && tools.length <= 4) || waiting > 0}
      className="ios-glass-field group mt-2 max-w-[32rem] overflow-hidden rounded-2xl text-slate-600 dark:text-slate-300"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-1.5 text-[12px] leading-none [&::-webkit-details-marker]:hidden">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        <span className="min-w-0 flex-1 truncate font-medium">
          工具调用 {tools.length} 次 · {statusText}
        </span>
        <span className="hidden truncate text-[11px] text-slate-400 sm:block">
          {toolNames.join(" / ")}
        </span>
        <ChevronDown className="h-3.5 w-3.5 flex-shrink-0 text-slate-400 transition-transform group-open:rotate-180" />
      </summary>

      <div className="space-y-1 px-2 pb-2 pt-1">
        {latestTools.map((tool) => (
          <ToolCallCard
            key={tool.id}
            tool={tool}
            defaultOpen={false}
            compact
            onApprove={onApproveRequest}
            onReject={onRejectApprovalRequest}
          />
        ))}
        {tools.length > latestTools.length && (
          <p className="px-1 pt-1 text-[11px] text-slate-400">
            其余 {tools.length - latestTools.length} 次工具调用已折叠，可在右侧
            Run State 查看。
          </p>
        )}
      </div>
    </details>
  );
}

/* ─────────────────────────────────────────── */
/*  Typing indicator (three bouncing dots)     */
/* ─────────────────────────────────────────── */

function TypingIndicator() {
  return (
    <span className="flex items-center gap-1.5 py-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-2 w-2 rounded-full bg-slate-300 dark:bg-slate-600"
          style={{
            animation: "typing-dot 1.2s ease-in-out infinite",
            animationDelay: `${i * 0.18}s`,
          }}
        />
      ))}
    </span>
  );
}

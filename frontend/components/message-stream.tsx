"use client";

import {
  Check,
  ChevronDown,
  Copy,
  Database,
  Layers,
  Network,
  RefreshCw,
  Zap,
} from "lucide-react";
import mermaid from "mermaid";
import { useEffect, useId, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ToolCallView } from "./tool-call-card";
import { ToolCallCard } from "./tool-call-card";

export type ChatMessagePart =
  | {
      id: string;
      type: "text";
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
  tools?: ToolCallView[];
  parts?: ChatMessagePart[];
};

type MessageStreamProps = {
  messages: ChatMessage[];
  isStreaming: boolean;
  copiedMessageId?: string | null;
  expandedTools?: boolean;
  onCopyMessage: (message: ChatMessage) => void;
  onRegenerate: () => void;
};

export function MessageStream({
  messages,
  isStreaming,
  copiedMessageId,
  expandedTools = false,
  onCopyMessage,
  onRegenerate,
}: MessageStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  /* Auto-scroll to bottom on new content */
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, isStreaming]);

  const lastAssistantIdx = messages.reduce(
    (acc, m, i) => (m.role === "assistant" ? i : acc),
    -1,
  );

  return (
    <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-50/60 dark:bg-slate-950 md:rounded-panel md:bg-white/82 md:shadow-soft md:backdrop-blur-xl md:dark:bg-slate-950/62">
      {/* ── Header ── */}
      <div className="hidden items-center justify-between border-b border-slate-950/[0.06] px-5 py-4 dark:border-white/[0.07] md:flex">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">
            Conversation
          </p>
          <h1 className="mt-0.5 text-[15px] font-semibold tracking-tight">
            LangGraph Agent
          </h1>
        </div>
        <StreamingBadge visible={isStreaming} />
      </div>

      {/* ── Message list ── */}
      <div
        ref={scrollRef}
        className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 pb-6 pt-5 sm:px-6 md:py-6"
      >
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="space-y-4 md:space-y-5">
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
              />
            ))}
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
  if (!visible) return null;
  return (
    <span className="flex animate-fade-slide-up items-center gap-2 rounded-full bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
      </span>
      生成中
    </span>
  );
}

/* ─────────────────────────────────────────── */
/*  Empty / welcome state                      */
/* ─────────────────────────────────────────── */

const CAPABILITIES = [
  {
    icon: Zap,
    label: "工具调用",
    desc: "执行搜索、计算等外部操作",
  },
  {
    icon: Database,
    label: "长期记忆",
    desc: "跨对话保持上下文记忆",
  },
  {
    icon: Layers,
    label: "流式推理",
    desc: "实时输出思考链路过程",
  },
  {
    icon: Network,
    label: "任务分解",
    desc: "复杂任务自动拆解执行",
  },
];

function EmptyState() {
  return (
    <div className="flex h-full min-h-[18rem] flex-col items-center justify-center gap-7 px-4 py-8 text-center animate-fade-slide-up md:min-h-[22rem] md:gap-8 md:py-10">
      <div className="flex flex-col items-center gap-4">
        {/* Logo mark */}
        <div className="relative">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-slate-900 to-slate-600 shadow-[0_8px_24px_-8px_rgb(15_23_42/0.45)] dark:from-slate-600 dark:to-slate-400">
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
            你好，我是 Tommy
          </h2>
          <p className="mt-2 max-w-xs text-[13px] leading-relaxed text-slate-500 dark:text-slate-400">
            LangGraph 驱动的 AI Agent，支持工具调用、记忆管理与实时推理
          </p>
        </div>
      </div>

      {/* Capability cards */}
      <div className="grid w-full max-w-md grid-cols-2 gap-2">
        {CAPABILITIES.map(({ icon: Icon, label, desc }) => (
          <div
            key={label}
            className="rounded-2xl border border-slate-950/[0.07] bg-slate-50/70 p-3.5 text-left transition-colors hover:bg-slate-100/60 dark:border-white/[0.07] dark:bg-white/[0.04] dark:hover:bg-white/[0.07]"
          >
            <div className="mb-2 flex h-7 w-7 items-center justify-center rounded-lg bg-slate-950/[0.05] dark:bg-white/[0.08]">
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

function MessageBubble({
  message,
  isLastAssistant,
  isStreaming,
  copied,
  expandedTools,
  onCopy,
  onRegenerate,
}: {
  message: ChatMessage;
  isLastAssistant: boolean;
  isStreaming: boolean;
  copied: boolean;
  expandedTools: boolean;
  onCopy: () => void;
  onRegenerate?: () => void;
}) {
  const isUser = message.role === "user";
  const showCursor = isLastAssistant && isStreaming && message.content !== "";
  const showTyping =
    isLastAssistant &&
    isStreaming &&
    message.content === "" &&
    (message.tools?.length ?? 0) === 0;

  if (isUser) {
    return (
      <div className="group flex flex-col items-end gap-1 animate-fade-slide-up">
        <div className="max-w-[86%] rounded-[1.35rem] rounded-tr-md bg-slate-200/75 px-4 py-3 text-[15px] leading-relaxed sm:max-w-[72%] md:rounded-bubble md:bg-slate-100 md:text-[14px] dark:bg-white/[0.1]">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
        <MessageActions copied={copied} onCopy={onCopy} align="right" />
      </div>
    );
  }

  /* Assistant message — no bubble, avatar + text */
  return (
    <div className="group flex gap-3 animate-fade-slide-up">
      {/* Avatar */}
      <div className="mt-1 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-slate-900 to-slate-600 shadow-sm dark:from-slate-600 dark:to-slate-400">
        <svg
          className="h-3.5 w-3.5 text-white"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M12 2a7 7 0 0 1 7 7c0 2.5-1.3 4.7-3.3 6L17 21H7l1.3-6A7 7 0 0 1 5 9a7 7 0 0 1 7-7z" />
          <path d="M9 17h6" />
        </svg>
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1 pt-0.5 text-[15px] leading-6 md:text-[14px]">
        {showTyping ? (
          <TypingIndicator />
        ) : (
          <>
            <MessageContent
              message={message}
              showCursor={showCursor}
              expandedTools={expandedTools}
            />
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
}

function MessageActions({
  copied,
  onCopy,
  onRegenerate,
  align = "left",
}: {
  copied: boolean;
  onCopy: () => void;
  onRegenerate?: () => void;
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
      className={`mt-1 flex items-center gap-1 text-slate-400 opacity-100 transition md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100 ${
        align === "right" ? "justify-end" : ""
      }`}
    >
      <button
        type="button"
        onClick={copy}
        className="rounded-lg p-1.5 transition hover:bg-slate-950/[0.05] hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/30 dark:hover:bg-white/[0.08] dark:hover:text-slate-200"
        aria-label="复制消息"
      >
        {copied || labelVisible ? (
          <Check className="h-3.5 w-3.5 text-emerald-500" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </button>
      {onRegenerate && (
        <button
          type="button"
          onClick={onRegenerate}
          className="rounded-lg p-1.5 transition hover:bg-slate-950/[0.05] hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/30 dark:hover:bg-white/[0.08] dark:hover:text-slate-200"
          aria-label="重新生成"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

function MessageContent({
  message,
  showCursor,
  expandedTools,
}: {
  message: ChatMessage;
  showCursor: boolean;
  expandedTools: boolean;
}) {
  const parts = message.parts?.length
    ? message.parts
    : [
        ...(message.content
          ? [{ id: `${message.id}-text`, type: "text" as const, content: message.content }]
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
  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
      {showCursor && (
        <span className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[2px] rounded-sm bg-slate-700 opacity-80 animate-cursor-blink dark:bg-slate-300" />
      )}
    </div>
  );
}

const markdownComponents: Components = {
  p({ children }) {
    return <p className="my-1.5 leading-6">{children}</p>;
  },
  h1({ children }) {
    return <h1 className="mb-2 mt-4 text-xl font-semibold tracking-tight">{children}</h1>;
  },
  h2({ children }) {
    return <h2 className="mb-2 mt-4 text-lg font-semibold tracking-tight">{children}</h2>;
  },
  h3({ children }) {
    return <h3 className="mb-1.5 mt-3 text-base font-semibold tracking-tight">{children}</h3>;
  },
  ul({ children }) {
    return <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>;
  },
  ol({ children }) {
    return <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>;
  },
  li({ children }) {
    return <li className="leading-6">{children}</li>;
  },
  a({ children, href }) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="font-medium text-slate-900 underline decoration-slate-300 underline-offset-4 transition hover:decoration-slate-700 dark:text-slate-100 dark:decoration-slate-600"
      >
        {children}
      </a>
    );
  },
  blockquote({ children }) {
    return (
      <blockquote className="my-2 border-l-2 border-slate-300 pl-3 text-slate-500 dark:border-slate-700 dark:text-slate-400">
        {children}
      </blockquote>
    );
  },
  table({ children }) {
    return (
      <div className="my-3 overflow-x-auto rounded-2xl border border-slate-950/[0.06] scrollbar-thin dark:border-white/[0.08]">
        <table className="min-w-full border-collapse text-left text-[13px]">{children}</table>
      </div>
    );
  },
  th({ children }) {
    return (
      <th className="border-b border-slate-950/[0.06] bg-slate-950/[0.035] px-3 py-2 font-semibold text-slate-700 dark:border-white/[0.08] dark:bg-white/[0.06] dark:text-slate-200">
        {children}
      </th>
    );
  },
  td({ children }) {
    return (
      <td className="border-b border-slate-950/[0.05] px-3 py-2 align-top text-slate-600 dark:border-white/[0.06] dark:text-slate-300">
        {children}
      </td>
    );
  },
  pre({ children }) {
    return <>{children}</>;
  },
  code({ children, className }) {
    const value = String(children).replace(/\n$/, "");
    const language = /language-(\w+)/.exec(className ?? "")?.[1] ?? "";
    if (language === "mermaid") {
      return <MermaidBlock chart={value} />;
    }
    if (!className && !value.includes("\n")) {
      return (
        <code className="rounded-md bg-slate-950/[0.06] px-1.5 py-0.5 font-mono text-[0.92em] text-slate-700 dark:bg-white/[0.08] dark:text-slate-200">
          {children}
        </code>
      );
    }
    return <CodeBlock code={value} language={language} />;
  },
};

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);

  async function copyCode() {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <figure className="my-3 overflow-hidden rounded-2xl bg-slate-950/[0.045] shadow-[inset_0_0_0_1px_rgb(15_23_42/0.045)] dark:bg-white/[0.06] dark:shadow-[inset_0_0_0_1px_rgb(255_255_255/0.06)]">
      <figcaption className="flex items-center justify-between border-b border-slate-950/[0.05] px-3 py-1.5 dark:border-white/[0.07]">
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-400">
          {language || "text"}
        </span>
        <button
          type="button"
          onClick={copyCode}
          className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-medium text-slate-400 transition hover:bg-slate-950/[0.05] hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/30 dark:hover:bg-white/[0.08] dark:hover:text-slate-200"
        >
          {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
          {copied ? "已复制" : "复制"}
        </button>
      </figcaption>
      <pre className="max-h-80 overflow-auto px-3 py-2.5 font-mono text-[12px] leading-5 text-slate-600 scrollbar-thin dark:text-slate-300">
        <code>{code}</code>
      </pre>
    </figure>
  );
}

function MermaidBlock({ chart }: { chart: string }) {
  const id = useId().replace(/:/g, "");
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");
  const [darkMode, setDarkMode] = useState(false);

  useEffect(() => {
    const update = () => setDarkMode(document.documentElement.classList.contains("dark"));
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: darkMode ? "dark" : "neutral",
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
    <div className="my-3 overflow-x-auto rounded-2xl bg-slate-950/[0.035] p-3 scrollbar-thin dark:bg-white/[0.055]">
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
}: {
  tools: ToolCallView[];
  expandedTools: boolean;
}) {
  if (tools.length === 0) return null;
  if (tools.length <= 2) {
    return (
      <>
        {tools.map((tool) => (
          <ToolCallCard key={tool.id} tool={tool} defaultOpen={expandedTools} />
        ))}
      </>
    );
  }

  const latestTools = tools.slice(-4);
  const running = tools.filter((tool) => tool.status === "running").length;
  const failed = tools.filter((tool) => tool.status === "error").length;
  const toolNames = Array.from(new Set(tools.map((tool) => tool.name))).slice(0, 3);
  const statusText =
    running > 0 ? `${running} 个运行中` : failed > 0 ? `${failed} 个失败` : "全部完成";

  return (
    <details
      open={expandedTools && tools.length <= 4}
      className="group mt-2 max-w-[32rem] overflow-hidden rounded-xl bg-slate-950/[0.03] text-slate-600 dark:bg-white/[0.05] dark:text-slate-300"
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

      <div className="space-y-1 border-t border-slate-950/[0.05] px-2 pb-2 pt-1.5 dark:border-white/[0.06]">
        {latestTools.map((tool) => (
          <ToolCallCard key={tool.id} tool={tool} defaultOpen={false} compact />
        ))}
        {tools.length > latestTools.length && (
          <p className="px-1 pt-1 text-[11px] text-slate-400">
            其余 {tools.length - latestTools.length} 次工具调用已折叠，可在右侧 Run State 查看。
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

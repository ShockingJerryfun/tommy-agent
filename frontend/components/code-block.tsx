"use client";

import { Check, ChevronDown, ChevronUp, Copy } from "lucide-react";
import { memo, useEffect, useMemo, useState } from "react";
import { getSingletonHighlighter } from "shiki/bundle/web";

import { copyToClipboard } from "../lib/clipboard";
import { useToast } from "./toast-provider";

const SUPPORTED_LANGUAGES = new Set([
  "python",
  "typescript",
  "javascript",
  "tsx",
  "jsx",
  "bash",
  "sh",
  "json",
  "yaml",
  "html",
  "css",
  "rust",
  "go",
  "sql",
  "markdown",
  "diff",
]);

const COLLAPSE_LINE_THRESHOLD = 20;

type CodeBlockProps = {
  code: string;
  language: string;
};

function normalizeLanguage(language: string) {
  return language.trim().toLowerCase();
}

function CodeBlockComponent({ code, language }: CodeBlockProps) {
  const normalizedLanguage = normalizeLanguage(language);
  const displayLanguage = normalizedLanguage || "text";
  const lineCount = useMemo(() => code.split("\n").length, [code]);
  const [collapsed, setCollapsed] = useState(
    lineCount > COLLAPSE_LINE_THRESHOLD,
  );
  const [copied, setCopied] = useState(false);
  const [html, setHtml] = useState<string | null>(null);
  const [highlightFailed, setHighlightFailed] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    setCollapsed(lineCount > COLLAPSE_LINE_THRESHOLD);
  }, [code, lineCount]);

  useEffect(() => {
    let cancelled = false;
    setHtml(null);
    setHighlightFailed(false);

    if (!SUPPORTED_LANGUAGES.has(normalizedLanguage)) {
      setHighlightFailed(true);
      return () => {
        cancelled = true;
      };
    }

    getSingletonHighlighter({
      themes: ["github-light", "github-dark"],
      langs: [normalizedLanguage],
    })
      .then((highlighter) =>
        highlighter.codeToHtml(code, {
          lang: normalizedLanguage,
          themes: {
            light: "github-light",
            dark: "github-dark",
          },
          defaultColor: false,
        }),
      )
      .then((nextHtml) => {
        if (!cancelled) setHtml(nextHtml);
      })
      .catch(() => {
        if (!cancelled) setHighlightFailed(true);
      });

    return () => {
      cancelled = true;
    };
  }, [code, normalizedLanguage]);

  async function copyCode() {
    const success = await copyToClipboard(code);
    if (success) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    }
    toast(success ? "Copied" : "Copy failed", {
      tone: success ? "success" : "error",
    });
  }

  const hiddenLineCount = Math.max(lineCount - COLLAPSE_LINE_THRESHOLD, 0);

  return (
    <div className="message-code-block admin-card group relative my-3 overflow-hidden rounded-2xl">
      <div className="message-code-block__header flex items-center justify-between px-3 py-2 text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
        <span className="font-mono">{displayLanguage}</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setCollapsed((current) => !current)}
            aria-label={collapsed ? "展开" : "折叠"}
            className="admin-icon-action soft-focus-ring inline-flex h-7 w-7 items-center justify-center rounded-lg transition dark:hover:text-slate-200"
          >
            {collapsed ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronUp className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            type="button"
            onClick={copyCode}
            aria-label="复制代码"
            className="admin-icon-action soft-focus-ring inline-flex h-7 w-7 items-center justify-center rounded-lg transition dark:hover:text-slate-200"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-emerald-500" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>
      <div className={collapsed ? "max-h-[8rem] overflow-hidden" : ""}>
        {html && !highlightFailed ? (
          <div
            className="overflow-x-auto text-[12px] leading-5 scrollbar-thin [&_.shiki]:m-0 [&_.shiki]:overflow-x-auto [&_.shiki]:bg-transparent [&_.shiki]:px-3 [&_.shiki]:py-2.5"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <pre className="overflow-x-auto px-3 py-2.5 font-mono text-[12px] leading-5 text-slate-600 scrollbar-thin dark:text-slate-300">
            <code>{code}</code>
          </pre>
        )}
      </div>
      {collapsed && (
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="liquid-hover soft-focus-ring w-full py-1.5 text-[12px] font-medium text-slate-500 shadow-[inset_0_1px_0_rgba(255,255,255,0.55)] transition hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
        >
          展开剩余 {hiddenLineCount} 行
        </button>
      )}
    </div>
  );
}

export const CodeBlock = memo(CodeBlockComponent);

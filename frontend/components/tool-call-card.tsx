import { CheckCircle2, ChevronDown, Loader2, XCircle } from "lucide-react";

export type ToolCallView = {
  id: string;
  name: string;
  status: "running" | "done" | "error";
  summary?: string;
};

type ToolCallCardProps = {
  tool: ToolCallView;
  defaultOpen?: boolean;
  compact?: boolean;
};

export function ToolCallCard({ tool, defaultOpen = false, compact = false }: ToolCallCardProps) {
  return (
    <details
      open={defaultOpen}
      className={`group max-w-full overflow-hidden rounded-xl bg-slate-950/[0.035] text-slate-600 transition-colors animate-fade-slide-up open:w-full dark:bg-white/[0.055] dark:text-slate-300 ${
        compact ? "w-full" : "mt-2 w-fit"
      }`}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-1.5 text-[12px] leading-none [&::-webkit-details-marker]:hidden">
        <StatusIcon status={tool.status} />
        <span className="min-w-0 truncate font-medium">
          {tool.name}
        </span>
        <StatusBadge status={tool.status} />
        <ChevronDown className="h-3.5 w-3.5 text-slate-400 transition-transform group-open:rotate-180" />
      </summary>

      {tool.summary && (
        <div className="border-t border-slate-950/[0.05] px-2.5 pb-2 pt-1.5 dark:border-white/[0.06]">
          <p className="max-h-20 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-slate-500 dark:text-slate-400">
            {tool.summary}
          </p>
        </div>
      )}
    </details>
  );
}

function StatusIcon({ status }: { status: ToolCallView["status"] }) {
  if (status === "running") {
    return (
      <Loader2
        className="h-3.5 w-3.5 flex-shrink-0 animate-spin text-amber-500"
        strokeWidth={2}
      />
    );
  }
  if (status === "done") {
    return (
      <CheckCircle2
        className="h-3.5 w-3.5 flex-shrink-0 text-emerald-500"
        strokeWidth={2}
      />
    );
  }
  return (
    <XCircle
      className="h-3.5 w-3.5 flex-shrink-0 text-red-500"
      strokeWidth={2}
    />
  );
}

const BADGE_STYLES = {
  running:
    "bg-amber-500/10 text-amber-600 dark:bg-amber-500/15 dark:text-amber-400",
  done: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400",
  error: "bg-red-50 text-red-600 dark:bg-red-500/15 dark:text-red-400",
} as const;

const BADGE_LABELS = {
  running: "运行中",
  done: "完成",
  error: "错误",
} as const;

function StatusBadge({ status }: { status: ToolCallView["status"] }) {
  return (
    <span
      className={`flex-shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${BADGE_STYLES[status]}`}
    >
      {BADGE_LABELS[status]}
    </span>
  );
}

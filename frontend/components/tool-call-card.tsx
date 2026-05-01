import {
  Check,
  CheckCircle2,
  ChevronDown,
  Loader2,
  ShieldAlert,
  X,
  XCircle,
} from "lucide-react";

import { useI18n } from "../lib/i18n";
import type { ApprovalRequestView } from "./approval-panel";

export type ToolCallView = {
  id: string;
  name: string;
  status: "running" | "done" | "error" | "pending_approval";
  summary?: string;
  approval?: ApprovalRequestView;
};

type ToolCallCardProps = {
  tool: ToolCallView;
  defaultOpen?: boolean;
  compact?: boolean;
  onApprove?: (approvalId: string) => void;
  onReject?: (approvalId: string) => void;
};

export function ToolCallCard({
  tool,
  defaultOpen = false,
  compact = false,
  onApprove,
  onReject,
}: ToolCallCardProps) {
  const { t } = useI18n();
  const approval = tool.approval;
  return (
    <details
      open={defaultOpen || tool.status === "pending_approval"}
      className={`admin-card group max-w-full overflow-hidden rounded-2xl text-slate-600 transition-colors animate-fade-slide-up open:w-full dark:text-slate-300 ${
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

      {approval && (
        <div className="px-3 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.5)] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
          <div className="flex items-start gap-2">
            <ShieldAlert className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-500" />
            <div className="min-w-0 flex-1">
              <p className="text-[12px] font-semibold text-slate-800 dark:text-slate-100">
                {t("approvals.required")}
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-600 dark:text-slate-300">
                {approval.summary}
              </p>
              {approval.args && (
                <pre className="ios-glass-field mt-2 max-h-28 overflow-auto rounded-lg p-2 text-[10px] leading-relaxed text-slate-500 dark:text-slate-400">
                  {JSON.stringify(approval.args, null, 2)}
                </pre>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => onApprove?.(approval.id)}
                  disabled={!onApprove}
                  className="premium-action soft-focus-ring inline-flex min-h-9 items-center gap-1.5 px-3 text-[11px] font-semibold"
                >
                  <Check className="h-3.5 w-3.5" />
                  {t("approvals.approve")}
                </button>
                <button
                  type="button"
                  onClick={() => onReject?.(approval.id)}
                  disabled={!onReject}
                  className="admin-secondary-action inline-flex min-h-9 items-center gap-1.5 px-3 text-[11px] font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <X className="h-3.5 w-3.5" />
                  {t("approvals.reject")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {tool.summary && (
        <div className="px-2.5 pb-2 pt-1">
          <p className="max-h-20 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-slate-500 dark:text-slate-400">
            {tool.summary}
          </p>
        </div>
      )}
    </details>
  );
}

function StatusIcon({ status }: { status: ToolCallView["status"] }) {
  if (status === "running" || status === "pending_approval") {
    return (
      <Loader2
        className={`h-3.5 w-3.5 flex-shrink-0 text-amber-500 ${
          status === "running" ? "animate-spin" : ""
        }`}
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
  running: "admin-badge-warning",
  pending_approval: "admin-badge-warning",
  done: "admin-badge-success",
  error: "admin-badge-error",
} as const;

function StatusBadge({ status }: { status: ToolCallView["status"] }) {
  const { t } = useI18n();
  const badgeLabels: Record<ToolCallView["status"], string> = {
    running: t("run.running"),
    pending_approval: t("run.pendingApproval"),
    done: t("run.done"),
    error: t("run.error"),
  };

  return (
    <span
      className={`admin-badge flex-shrink-0 text-[10px] ${BADGE_STYLES[status]}`}
    >
      {badgeLabels[status]}
    </span>
  );
}

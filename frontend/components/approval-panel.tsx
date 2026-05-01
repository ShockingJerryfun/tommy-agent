"use client";

import { Check, ShieldAlert, X } from "lucide-react";

import { useI18n } from "../lib/i18n";
import { InspectorPanel } from "./inspector-panel";

export type ApprovalRequestView = {
  id: string;
  tool_call_id?: string;
  tool_name: string;
  args?: Record<string, unknown>;
  risk_level: string;
  summary: string;
  status: "pending" | "approved" | "rejected" | "executed" | "failed";
  result?: string;
  error?: string;
  created_at?: string;
};

type ApprovalPanelProps = {
  approvals: ApprovalRequestView[];
  onApprove: (approvalId: string) => void;
  onReject: (approvalId: string) => void;
};

export function ApprovalPanel({ approvals, onApprove, onReject }: ApprovalPanelProps) {
  const { t } = useI18n();

  return (
    <InspectorPanel
      title={t("approvals.title")}
      icon={<ShieldAlert className="h-3.5 w-3.5" strokeWidth={2} />}
      defaultOpen={approvals.length > 0}
      bodyClassName="p-0"
      action={
        approvals.length > 0 ? (
          <span className="admin-badge admin-badge-warning text-[10px]">
            {approvals.length}
          </span>
        ) : undefined
      }
    >
      <div className="space-y-2 p-3">
        {approvals.length === 0 ? (
          <p className="ios-glass-field rounded-xl px-3 py-2 text-[12px] text-slate-400">
            {t("approvals.empty")}
          </p>
        ) : (
          approvals.slice(0, 5).map((approval) => (
            <div
              key={approval.id}
              className="admin-card rounded-2xl p-3 text-[12px]"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate font-semibold text-slate-800 dark:text-slate-100">
                    {approval.tool_name}
                  </p>
                  <p className="mt-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-400">
                    {t("approvals.risk", { risk: approval.risk_level })}
                  </p>
                </div>
                <span className="admin-badge admin-badge-neutral text-[10px]">
                  {approval.status}
                </span>
              </div>

              <p className="mt-2 line-clamp-4 text-slate-600 dark:text-slate-300">
                {approval.summary}
              </p>
              {approval.args && (
                <pre className="ios-glass-field mt-2 max-h-24 overflow-auto rounded-xl p-2 text-[10px] leading-relaxed text-slate-500 dark:text-slate-400">
                  {JSON.stringify(approval.args, null, 2)}
                </pre>
              )}

              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  onClick={() => onApprove(approval.id)}
                  className="premium-action soft-focus-ring inline-flex items-center gap-1 px-2.5 py-1 text-[10px] font-semibold"
                >
                  <Check className="h-3 w-3" />
                  {t("approvals.approve")}
                </button>
                <button
                  type="button"
                  onClick={() => onReject(approval.id)}
                  className="admin-secondary-action soft-focus-ring inline-flex items-center gap-1 px-2.5 py-1 text-[10px] font-semibold"
                >
                  <X className="h-3 w-3" />
                  {t("approvals.reject")}
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </InspectorPanel>
  );
}

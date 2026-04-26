"use client";

import { Check, ShieldAlert, X } from "lucide-react";

import { InspectorPanel } from "./inspector-panel";

export type ApprovalRequestView = {
  id: string;
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
  return (
    <InspectorPanel
      title="Approvals"
      icon={<ShieldAlert className="h-3.5 w-3.5" strokeWidth={2} />}
      defaultOpen={approvals.length > 0}
      bodyClassName="p-0"
      action={
        approvals.length > 0 ? (
          <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-400">
            {approvals.length}
          </span>
        ) : undefined
      }
    >
      <div className="space-y-2 p-3">
        {approvals.length === 0 ? (
          <p className="rounded-xl bg-slate-950/[0.025] px-3 py-2 text-[12px] text-slate-400 dark:bg-white/[0.035]">
            暂无待审批操作
          </p>
        ) : (
          approvals.slice(0, 5).map((approval) => (
            <div
              key={approval.id}
              className="rounded-2xl border border-amber-500/15 bg-amber-500/[0.035] p-3 text-[12px] dark:bg-amber-400/[0.05]"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate font-semibold text-slate-800 dark:text-slate-100">
                    {approval.tool_name}
                  </p>
                  <p className="mt-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-400">
                    风险：{approval.risk_level}
                  </p>
                </div>
                <span className="rounded-full bg-slate-950/[0.06] px-2 py-0.5 text-[10px] font-semibold text-slate-500 dark:bg-white/[0.08] dark:text-slate-400">
                  {approval.status}
                </span>
              </div>

              <p className="mt-2 line-clamp-4 text-slate-600 dark:text-slate-300">
                {approval.summary}
              </p>
              {approval.args && (
                <pre className="mt-2 max-h-24 overflow-auto rounded-xl bg-slate-950/[0.04] p-2 text-[10px] leading-relaxed text-slate-500 dark:bg-black/20 dark:text-slate-400">
                  {JSON.stringify(approval.args, null, 2)}
                </pre>
              )}

              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  onClick={() => onApprove(approval.id)}
                  className="inline-flex items-center gap-1 rounded-full bg-slate-900 px-2.5 py-1 text-[10px] font-semibold text-white transition hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
                >
                  <Check className="h-3 w-3" />
                  批准执行
                </button>
                <button
                  type="button"
                  onClick={() => onReject(approval.id)}
                  className="inline-flex items-center gap-1 rounded-full bg-slate-950/[0.06] px-2.5 py-1 text-[10px] font-semibold text-slate-500 transition hover:bg-slate-950/[0.1] dark:bg-white/[0.07] dark:text-slate-400"
                >
                  <X className="h-3 w-3" />
                  拒绝
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </InspectorPanel>
  );
}

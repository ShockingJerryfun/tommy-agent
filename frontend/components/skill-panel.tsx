"use client";

import { Check, Sparkles, X } from "lucide-react";

import { InspectorPanel } from "./inspector-panel";

export type SkillSummaryView = {
  name: string;
  path: string;
  description?: string;
  updated_at?: string;
};

export type SkillProposalView = {
  id: string;
  name: string;
  relative_path: string;
  action: "create" | "update";
  rationale: string;
  content: string;
  risks?: string[];
  status: "proposed" | "applied" | "rejected";
  metadata?: Record<string, unknown>;
};

type SkillPanelProps = {
  skills: SkillSummaryView[];
  proposals: SkillProposalView[];
  onApplyProposal: (proposalId: string) => void;
  onRejectProposal: (proposalId: string) => void;
};

export function SkillPanel({
  skills,
  proposals,
  onApplyProposal,
  onRejectProposal,
}: SkillPanelProps) {
  return (
    <InspectorPanel
      title="Skills"
      icon={<Sparkles className="h-3.5 w-3.5" strokeWidth={2} />}
      defaultOpen
    >
      <div className="space-y-3">
        <div>
          <p className="mb-2 px-1 text-[11px] font-medium text-slate-400">
            已安装 {skills.length}
          </p>
          {skills.length === 0 ? (
            <p className="rounded-xl bg-slate-950/[0.025] px-3 py-2 text-[12px] text-slate-400 dark:bg-white/[0.035]">
              暂无已安装 skill
            </p>
          ) : (
            <div className="space-y-1.5">
              {skills.slice(0, 4).map((skill) => (
                <div
                  key={skill.path}
                  className="rounded-xl bg-slate-950/[0.03] px-3 py-2 text-[12px] dark:bg-white/[0.04]"
                >
                  <p className="font-medium text-slate-700 dark:text-slate-200">
                    {skill.name}
                  </p>
                  <p className="mt-0.5 line-clamp-2 text-slate-400">
                    {skill.description || skill.path}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>

        <div>
          <p className="mb-2 px-1 text-[11px] font-medium text-slate-400">
            待确认 {proposals.length}
          </p>
          {proposals.length === 0 ? (
            <p className="rounded-xl bg-slate-950/[0.025] px-3 py-2 text-[12px] text-slate-400 dark:bg-white/[0.035]">
              agent 还没有提出 skill 更新
            </p>
          ) : (
            <div className="space-y-2">
              {proposals.slice(0, 4).map((proposal) => (
                <div
                  key={proposal.id}
                  className="rounded-2xl border border-slate-950/[0.06] bg-slate-950/[0.025] p-3 text-[12px] dark:border-white/[0.07] dark:bg-white/[0.035]"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-slate-700 dark:text-slate-200">
                        {proposal.name}
                      </p>
                      <p className="mt-0.5 truncate text-[11px] text-slate-400">
                        {proposal.action} · {proposal.relative_path}
                      </p>
                    </div>
                    {proposal.metadata?.allow_auto_apply === true && (
                      <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
                        auto
                      </span>
                    )}
                  </div>
                  <p className="mt-2 line-clamp-3 text-slate-500 dark:text-slate-400">
                    {proposal.rationale}
                  </p>
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      onClick={() => onApplyProposal(proposal.id)}
                      className="inline-flex items-center gap-1 rounded-full bg-slate-900 px-2.5 py-1 text-[10px] font-semibold text-white transition hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
                    >
                      <Check className="h-3 w-3" />
                      应用
                    </button>
                    <button
                      type="button"
                      onClick={() => onRejectProposal(proposal.id)}
                      className="inline-flex items-center gap-1 rounded-full bg-slate-950/[0.06] px-2.5 py-1 text-[10px] font-semibold text-slate-500 transition hover:bg-slate-950/[0.1] dark:bg-white/[0.07] dark:text-slate-400"
                    >
                      <X className="h-3 w-3" />
                      拒绝
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </InspectorPanel>
  );
}

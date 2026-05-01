"use client";

import { Check, Sparkles, X } from "lucide-react";

import { useI18n } from "../lib/i18n";
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
  const { t } = useI18n();

  return (
    <InspectorPanel
      title="Skills"
      icon={<Sparkles className="h-3.5 w-3.5" strokeWidth={2} />}
      defaultOpen
    >
      <div className="space-y-3">
        <div>
          <p className="mb-2 px-1 text-[11px] font-medium text-slate-400">
            {t("skills.installed", { count: skills.length })}
          </p>
          {skills.length === 0 ? (
            <p className="ios-glass-field rounded-xl px-3 py-2 text-[12px] text-slate-400">
              {t("skills.emptyInstalled")}
            </p>
          ) : (
            <div className="space-y-1.5">
              {skills.slice(0, 4).map((skill) => (
                <div
                  key={skill.path}
                  className="admin-card rounded-xl px-3 py-2 text-[12px]"
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
            {t("skills.pending", { count: proposals.length })}
          </p>
          {proposals.length === 0 ? (
            <p className="ios-glass-field rounded-xl px-3 py-2 text-[12px] text-slate-400">
              {t("skills.emptyPending")}
            </p>
          ) : (
            <div className="space-y-2">
              {proposals.slice(0, 4).map((proposal) => (
                <div
                  key={proposal.id}
                  className="admin-card rounded-2xl p-3 text-[12px]"
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
                      <span className="admin-badge admin-badge-success text-[10px]">
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
                      className="premium-action soft-focus-ring inline-flex items-center gap-1 px-2.5 py-1 text-[10px] font-semibold"
                    >
                      <Check className="h-3 w-3" />
                      {t("skills.apply")}
                    </button>
                    <button
                      type="button"
                      onClick={() => onRejectProposal(proposal.id)}
                      className="admin-secondary-action soft-focus-ring inline-flex items-center gap-1 px-2.5 py-1 text-[10px] font-semibold"
                    >
                      <X className="h-3 w-3" />
                      {t("skills.reject")}
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

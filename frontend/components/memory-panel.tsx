import { Archive, Brain, Check, Database } from "lucide-react";

import { useI18n } from "../lib/i18n";
import { InspectorPanel } from "./inspector-panel";

export type ContextPactView = {
  summary?: string;
  goals?: string[];
  constraints?: string[];
  facts?: string[];
  open_questions?: string[];
  active_skills?: string[];
};

export type MemoryProposalView = {
  id: string;
  content: string;
  status: string;
};

export type CompactionRunView = {
  id: string;
  summary: string;
  message_count?: number;
  kept_messages?: number;
};

type MemoryPanelProps = {
  sessionId: string;
  status: string;
  contextPact?: ContextPactView;
  memoryProposals?: MemoryProposalView[];
  compactionRuns?: CompactionRunView[];
  onConfirmMemory?: (memoryId: string) => void;
  onCompact?: () => void;
};

export function MemoryPanel({
  sessionId,
  status,
  contextPact,
  memoryProposals = [],
  compactionRuns = [],
  onConfirmMemory,
  onCompact,
}: MemoryPanelProps) {
  const { t } = useI18n();
  const sessionLabel =
    sessionId === "loading"
      ? t("memory.sessionLoading")
      : t("memory.sessionLabel", { id: sessionId.slice(-6) });
  const latestCompaction = compactionRuns[0];

  return (
    <InspectorPanel
      title="Memory"
      icon={<Database className="h-3.5 w-3.5" strokeWidth={2} />}
      defaultOpen
      bodyClassName="p-0"
      action={
        onCompact ? (
          <button
            type="button"
            onClick={onCompact}
            className="admin-secondary-action soft-focus-ring px-2 py-1 text-[10px] font-medium"
          >
            {t("memory.compress")}
          </button>
        ) : undefined
      }
    >
      <dl className="space-y-2 p-3">
        <DataRow label={t("memory.currentSession")}>
          <span className="text-[13px] text-slate-700 dark:text-slate-300">
            {sessionLabel}
          </span>
        </DataRow>
        <DataRow label={t("memory.status")}>
          <span className="text-[13px] text-slate-700 dark:text-slate-300">
            {status}
          </span>
        </DataRow>
        <DataRow label="Context Pact">
          <PactSummary pact={contextPact} />
        </DataRow>
        <DataRow label={t("memory.pending", { count: memoryProposals.length })}>
          {memoryProposals.length === 0 ? (
            <span className="text-[12px] text-slate-400">
              {t("memory.emptyPending")}
            </span>
          ) : (
            <div className="space-y-2">
              {memoryProposals.slice(0, 3).map((proposal) => (
                <div
                  key={proposal.id}
                  className="admin-card rounded-xl p-2.5 text-[12px] text-slate-600 dark:text-slate-300"
                >
                  <p className="line-clamp-3">{proposal.content}</p>
                  {onConfirmMemory && (
                    <button
                      type="button"
                      onClick={() => onConfirmMemory(proposal.id)}
                      className="admin-badge admin-badge-success mt-2 gap-1 text-[10px]"
                    >
                      <Check className="h-3 w-3" />
                      {t("memory.confirm")}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </DataRow>
        <DataRow label={t("memory.latestCompaction")}>
          {latestCompaction ? (
            <div className="space-y-1.5 text-[12px] text-slate-600 dark:text-slate-300">
              <div className="flex items-center gap-1.5 text-slate-400">
                <Archive className="h-3 w-3" />
                <span>
                  {t("memory.compactionSummary", {
                    messages: latestCompaction.message_count ?? 0,
                    kept: latestCompaction.kept_messages ?? 0,
                  })}
                </span>
              </div>
              <p className="line-clamp-4">{latestCompaction.summary}</p>
            </div>
          ) : (
            <span className="text-[12px] text-slate-400">
              {t("memory.noCompaction")}
            </span>
          )}
        </DataRow>
      </dl>
    </InspectorPanel>
  );
}

function PactSummary({ pact }: { pact?: ContextPactView }) {
  const { t } = useI18n();
  if (!pact || (!pact.summary && !pact.goals?.length && !pact.facts?.length)) {
    return (
      <span className="text-[12px] text-slate-400">
        {t("memory.noContext")}
      </span>
    );
  }
  return (
    <div className="space-y-2 text-[12px] text-slate-600 dark:text-slate-300">
      {pact.summary && (
        <p className="line-clamp-4 leading-relaxed">
          <Brain className="mr-1 inline h-3 w-3 text-slate-400" />
          {pact.summary}
        </p>
      )}
      <PactList label={t("memory.goals")} items={pact.goals} />
      <PactList label={t("memory.facts")} items={pact.facts} />
      <PactList label={t("memory.openQuestions")} items={pact.open_questions} />
    </div>
  );
}

function PactList({ label, items }: { label: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
        {label}
      </p>
      <ul className="space-y-1">
        {items.slice(0, 3).map((item) => (
          <li key={item} className="line-clamp-2">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function DataRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="ios-glass-field rounded-xl px-4 py-3">
      <dt className="mb-1 text-[11px] font-medium text-slate-400">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

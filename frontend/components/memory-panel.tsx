import { Archive, Brain, Check, Database } from "lucide-react";

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
  const sessionLabel = sessionId === "loading" ? "加载中…" : `会话 ${sessionId.slice(-6)}`;
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
            className="rounded-full bg-slate-950/[0.05] px-2 py-1 text-[10px] font-medium text-slate-500 transition hover:bg-slate-950/[0.08] dark:bg-white/[0.06] dark:text-slate-400 dark:hover:bg-white/[0.1]"
          >
            压缩
          </button>
        ) : undefined
      }
    >
      <dl className="divide-y divide-slate-950/[0.04] dark:divide-white/[0.05]">
        <DataRow label="当前会话">
          <span className="text-[13px] text-slate-700 dark:text-slate-300">
            {sessionLabel}
          </span>
        </DataRow>
        <DataRow label="状态">
          <span className="text-[13px] text-slate-700 dark:text-slate-300">
            {status}
          </span>
        </DataRow>
        <DataRow label="Context Pact">
          <PactSummary pact={contextPact} />
        </DataRow>
        <DataRow label={`待确认记忆 ${memoryProposals.length}`}>
          {memoryProposals.length === 0 ? (
            <span className="text-[12px] text-slate-400">暂无待确认记忆</span>
          ) : (
            <div className="space-y-2">
              {memoryProposals.slice(0, 3).map((proposal) => (
                <div
                  key={proposal.id}
                  className="rounded-xl bg-slate-950/[0.035] p-2.5 text-[12px] text-slate-600 dark:bg-white/[0.04] dark:text-slate-300"
                >
                  <p className="line-clamp-3">{proposal.content}</p>
                  {onConfirmMemory && (
                    <button
                      type="button"
                      onClick={() => onConfirmMemory(proposal.id)}
                      className="mt-2 inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400"
                    >
                      <Check className="h-3 w-3" />
                      确认记忆
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </DataRow>
        <DataRow label="最近压缩">
          {latestCompaction ? (
            <div className="space-y-1.5 text-[12px] text-slate-600 dark:text-slate-300">
              <div className="flex items-center gap-1.5 text-slate-400">
                <Archive className="h-3 w-3" />
                <span>
                  {latestCompaction.message_count ?? 0} 条消息，保留 {latestCompaction.kept_messages ?? 0} 条
                </span>
              </div>
              <p className="line-clamp-4">{latestCompaction.summary}</p>
            </div>
          ) : (
            <span className="text-[12px] text-slate-400">还没有压缩记录</span>
          )}
        </DataRow>
      </dl>
    </InspectorPanel>
  );
}

function PactSummary({ pact }: { pact?: ContextPactView }) {
  if (!pact || (!pact.summary && !pact.goals?.length && !pact.facts?.length)) {
    return <span className="text-[12px] text-slate-400">暂无结构化上下文</span>;
  }
  return (
    <div className="space-y-2 text-[12px] text-slate-600 dark:text-slate-300">
      {pact.summary && (
        <p className="line-clamp-4 leading-relaxed">
          <Brain className="mr-1 inline h-3 w-3 text-slate-400" />
          {pact.summary}
        </p>
      )}
      <PactList label="目标" items={pact.goals} />
      <PactList label="事实" items={pact.facts} />
      <PactList label="开放问题" items={pact.open_questions} />
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
    <div className="px-4 py-3">
      <dt className="mb-1 text-[11px] font-medium text-slate-400">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

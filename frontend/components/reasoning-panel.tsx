"use client";

import { Activity, ChevronDown } from "lucide-react";
import { useMemo, useState } from "react";

import { type I18nKey, useI18n } from "../lib/i18n";
import { InspectorPanel } from "./inspector-panel";

export type RunStep = {
  id: string;
  type:
    | "user"
    | "agent"
    | "context"
    | "tool"
    | "memory"
    | "skill"
    | "pact"
    | "compaction"
    | "delegate"
    | "approval"
    | "subagent"
    | "model"
    | "verification"
    | "done"
    | "error";
  label: string;
  status: "running" | "done" | "error";
  at: number;
  payload?: Record<string, unknown>;
};

type ReasoningPanelProps = {
  steps: RunStep[];
  showGraph?: boolean;
};

/* ── Pipeline node definitions ─────────────────────────── */

type PipelineNodeId =
  | "input"
  | "context"
  | "compress"
  | "memoryRead"
  | "thinking"
  | "toolExec"
  | "approval"
  | "subagent"
  | "verification"
  | "memoryWrite"
  | "output";

type NodeStatus = "idle" | "active" | "done" | "error";

type PipelineNodeState = {
  id: PipelineNodeId;
  label: string;
  status: NodeStatus;
  detail?: string;
  toolCount?: number;
  triggered: boolean;
};

type PipelineNodeDraft = Omit<PipelineNodeState, "id" | "label">;

const PIPELINE_TEMPLATE: { id: PipelineNodeId; label: string; conditional: boolean }[] = [
  { id: "input", label: "接收输入", conditional: false },
  { id: "context", label: "构建上下文", conditional: false },
  { id: "compress", label: "上下文压缩", conditional: true },
  { id: "memoryRead", label: "记忆检索", conditional: true },
  { id: "thinking", label: "模型思考", conditional: false },
  { id: "toolExec", label: "工具调用", conditional: true },
  { id: "approval", label: "审批等待", conditional: true },
  { id: "subagent", label: "子 Agent", conditional: true },
  { id: "verification", label: "任务验证", conditional: true },
  { id: "memoryWrite", label: "记忆写入", conditional: true },
  { id: "output", label: "模型输出", conditional: false },
];

/* ── Build pipeline state from RunStep array ───────────── */

function buildPipelineState(steps: RunStep[]): PipelineNodeState[] {
  const state = new Map<PipelineNodeId, PipelineNodeDraft>();

  for (const t of PIPELINE_TEMPLATE) {
    state.set(t.id, { status: "idle", triggered: false });
  }

  let hasAnyStep = false;

  for (const step of steps) {
    hasAnyStep = true;

    if (step.type === "user") {
      promote(state, "input", step.status);
    }

    if (step.type === "context" || step.type === "pact") {
      promote(state, "context", step.status);
      const memories = step.payload?.injected_memories;
      if (Array.isArray(memories) && memories.length > 0) {
        promote(state, "memoryRead", step.status);
        const cur = nodeDraft(state, "memoryRead");
        cur.detail = `${memories.length} 条记忆`;
      }
    }

    if (step.type === "compaction") {
      promote(state, "compress", step.status);
    }

    if (step.type === "agent") {
      const node = step.payload?.node;
      if (node === "agent" || node === "planner" || node === "critic" || node === "reflector") {
        promote(state, "thinking", step.status);
        const labels: Record<string, string> = {
          agent: "模型生成",
          planner: "规划步骤",
          critic: "质量检查",
          reflector: "运行反馈",
        };
        const cur = nodeDraft(state, "thinking");
        cur.detail = labels[node as string] ?? String(node);
      } else {
        promote(state, "thinking", step.status);
      }
    }

    if (step.type === "model") {
      promote(state, "thinking", step.status);
      const cur = nodeDraft(state, "thinking");
      cur.detail = step.label;
    }

    if (step.type === "tool") {
      promote(state, "toolExec", step.status);
      const cur = nodeDraft(state, "toolExec");
      cur.toolCount = (cur.toolCount ?? 0) + (step.status !== "running" ? 1 : 0);
      const toolName = stripToolStatus(step.label);
      cur.detail = toolName;
    }

    if (step.type === "approval") {
      promote(state, "approval", step.status);
    }

    if (step.type === "delegate" || step.type === "subagent") {
      promote(state, "subagent", step.status);
    }

    if (step.type === "verification") {
      promote(state, "verification", step.status);
      const cur = nodeDraft(state, "verification");
      cur.detail = step.label;
    }

    if (step.type === "memory" || step.type === "skill") {
      promote(state, "memoryWrite", step.status);
      const cur = nodeDraft(state, "memoryWrite");
      cur.detail = step.type === "skill" ? "Skill 提案" : "记忆提案";
    }

    if (step.type === "done") {
      promote(state, "output", "done");
      for (const [, v] of state) {
        if (v.status === "active") v.status = "done";
      }
    }

    if (step.type === "error") {
      promote(state, "output", "error");
    }
  }

  if (hasAnyStep) {
    const tokenStep = steps.find(
      (s) => s.type === "agent" && s.status === "running" && s.payload?.thinking_key === "agent",
    );
    if (tokenStep) {
      promote(state, "output", "active");
    }
  }

  return PIPELINE_TEMPLATE.map((t) => {
    const s = nodeDraft(state, t.id);
    return {
      id: t.id,
      label: t.label,
      status: s.status,
      detail: s.detail,
      toolCount: s.toolCount,
      triggered: s.triggered,
    };
  });
}

function promote(
  state: Map<PipelineNodeId, PipelineNodeDraft>,
  id: PipelineNodeId,
  stepStatusOrNode: RunStep["status"] | NodeStatus,
) {
  const cur = nodeDraft(state, id);
  cur.triggered = true;
  const mapped: Record<string, NodeStatus> = { running: "active", error: "error", done: "done", idle: "idle", active: "active" };
  const next = mapped[stepStatusOrNode] ?? "done";
  const rank: Record<NodeStatus, number> = { idle: 0, done: 1, active: 2, error: 3 };
  if (rank[next] >= rank[cur.status]) {
    cur.status = next;
  }
}

function nodeDraft(
  state: Map<PipelineNodeId, PipelineNodeDraft>,
  id: PipelineNodeId,
): PipelineNodeDraft {
  let current = state.get(id);
  if (!current) {
    current = { status: "idle", triggered: false };
    state.set(id, current);
  }
  return current;
}

/* ── Context summary (preserved) ───────────────────────── */

type ContextSectionSummary = {
  name: string;
  title: string;
  source: string;
  charCount: number;
  truncated: boolean;
};

function latestContextSummary(steps: RunStep[]) {
  const contextStep = [...steps].reverse().find((step) => step.type === "context");
  const payload = contextStep?.payload;
  if (!payload) return null;
  const rawSections = Array.isArray(payload.sections) ? payload.sections : [];
  const sections = rawSections
    .map((item): ContextSectionSummary | null => {
      if (!item || typeof item !== "object") return null;
      const section = item as Record<string, unknown>;
      return {
        name: String(section.name ?? section.title ?? "section"),
        title: String(section.title ?? section.name ?? "Section"),
        source: String(section.source ?? ""),
        charCount: Number(section.char_count ?? 0),
        truncated: Boolean(section.truncated),
      };
    })
    .filter(Boolean) as ContextSectionSummary[];
  return {
    sectionCount: Number(payload.section_count ?? sections.length),
    totalChars: Number(payload.total_chars ?? 0),
    memoryCount: Array.isArray(payload.injected_memories) ? payload.injected_memories.length : 0,
    sections,
  };
}

/* ── Coalesce (for step detail list) ───────────────────── */

function coalesceRunSteps(steps: RunStep[]) {
  const byKey = new Map<string, RunStep>();
  const completedToolCounts = new Map<string, number>();
  const keys: string[] = [];

  for (const step of steps) {
    const key = graphStepKey(step);
    const existing = byKey.get(key);
    if (!existing) keys.push(key);
    if (step.type === "tool" && step.status !== "running") {
      completedToolCounts.set(key, (completedToolCounts.get(key) ?? 0) + 1);
    }
    byKey.set(key, {
      ...(existing ?? step),
      ...step,
      id: existing?.id ?? step.id,
      payload: { ...(existing?.payload ?? {}), ...(step.payload ?? {}) },
    });
  }

  const doneIndex = keys.indexOf("done");
  if (doneIndex >= 0) {
    for (const [key, step] of byKey) {
      if (key !== "error" && step.status === "running") {
        byKey.set(key, { ...step, status: "done" });
      }
    }
  }

  return keys
    .map((key) => {
      const step = byKey.get(key);
      if (!step) return undefined;
      const count = step.type === "tool" ? completedToolCounts.get(key) || 1 : 1;
      if (step.type !== "tool" || count <= 1) return step;
      return { ...step, label: `${stripToolStatus(step.label)} ×${count}` };
    })
    .filter(Boolean) as RunStep[];
}

function graphStepKey(step: RunStep) {
  if (step.type === "tool") {
    return `tool-${stripToolStatus(step.label)}`;
  }
  return step.type;
}

function stripToolStatus(label: string) {
  return label.replace(/\s*(运行中|完成|失败|待审批)$/u, "") || "工具";
}

/* ── Pipeline Graph Component ──────────────────────────── */

function PipelineGraph({ nodes }: { nodes: PipelineNodeState[] }) {
  const { t } = useI18n();
  const visible = nodes.filter((n) => {
    const tmpl = PIPELINE_TEMPLATE.find((t) => t.id === n.id);
    if (!tmpl?.conditional) return true;
    return n.triggered;
  });

  if (visible.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-[12px] text-slate-400 dark:text-slate-600">
        {t("run.waitingGraph")}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-0">
      {visible.map((node, index) => (
        <div key={node.id}>
          {index > 0 && <PipelineEdge active={node.status === "active"} />}
          <PipelineNodeRow node={node} />
        </div>
      ))}
    </div>
  );
}

function PipelineEdge({ active }: { active: boolean }) {
  return (
    <div className="flex items-center pl-[19px]">
      <div
        className={`h-4 w-px ${
          active
            ? "bg-emerald-300/70 dark:bg-emerald-400/35"
            : "bg-slate-300/50 dark:bg-slate-700/50"
        }`}
      />
    </div>
  );
}

function PipelineNodeRow({ node }: { node: PipelineNodeState }) {
  const { t } = useI18n();
  const statusClasses: Record<NodeStatus, string> = {
    idle: "bg-white/25 text-slate-400 shadow-[inset_0_1px_0_rgba(255,255,255,0.36)] backdrop-blur-md dark:bg-white/[0.04] dark:text-slate-600",
    active: "liquid-selected text-[#166534] dark:text-emerald-200",
    done: "bg-white/30 text-slate-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.42)] backdrop-blur-md dark:bg-white/[0.07] dark:text-slate-200",
    error: "bg-red-100/60 text-[#991b1b] shadow-[inset_0_1px_0_rgba(255,255,255,0.38)] backdrop-blur-md dark:bg-red-400/[0.1] dark:text-red-400",
  };

  return (
    <div className="flex items-center gap-2.5">
      <StatusDot status={node.status} />
      <div
        className={`flex min-h-[30px] flex-1 items-center justify-between gap-2 rounded-xl px-3 py-1.5 text-[11.5px] font-medium transition-all duration-300 ${statusClasses[node.status]}`}
      >
        <span className="flex items-center gap-1.5">
          {t(`run.pipeline.${node.id}` as I18nKey)}
          {node.status === "active" && (
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
          )}
        </span>
        <span className="flex items-center gap-1.5 text-[10px] font-normal opacity-70">
          {node.detail && <span>{node.detail}</span>}
          {node.toolCount != null && node.toolCount > 0 && (
            <span className="admin-badge admin-badge-neutral px-1.5 py-0.5 text-[10px]">
              ×{node.toolCount}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}

function StatusDot({ status }: { status: NodeStatus }) {
  if (status === "done") {
    return (
      <div className="flex h-[10px] w-[10px] flex-shrink-0 items-center justify-center">
        <svg viewBox="0 0 10 10" className="h-[10px] w-[10px]">
          <circle cx="5" cy="5" r="4" fill="none" stroke="rgb(16 185 129)" strokeWidth="1.5" />
          <path d="M3 5.2 L4.5 6.5 L7 3.5" fill="none" stroke="rgb(16 185 129)" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
    );
  }
  if (status === "active") {
    return (
      <div className="flex h-[10px] w-[10px] flex-shrink-0 items-center justify-center">
        <div className="h-2.5 w-2.5 animate-pulse rounded-full bg-emerald-400 shadow-[0_0_0_3px_rgba(46,204,113,0.18)]" />
      </div>
    );
  }
  if (status === "error") {
    return (
      <div className="flex h-[10px] w-[10px] flex-shrink-0 items-center justify-center">
        <div className="h-2 w-2 rounded-full bg-red-400 shadow-[0_0_0_3px_rgba(231,76,60,0.16)]" />
      </div>
    );
  }
  return (
    <div className="flex h-[10px] w-[10px] flex-shrink-0 items-center justify-center">
      <div className="h-1.5 w-1.5 rounded-full bg-slate-300 dark:bg-slate-700" />
    </div>
  );
}

/* ── Main component ────────────────────────────────────── */

export function ReasoningPanel({ steps, showGraph = true }: ReasoningPanelProps) {
  const { t } = useI18n();
  const visibleSteps = useMemo(() => coalesceRunSteps(steps), [steps]);
  const pipelineNodes = useMemo(() => buildPipelineState(steps), [steps]);
  const contextSummary = useMemo(() => latestContextSummary(visibleSteps), [visibleSteps]);
  const [detailOpen, setDetailOpen] = useState(false);

  return (
    <InspectorPanel
      title="Run State"
      icon={<Activity className="h-3.5 w-3.5" strokeWidth={2} />}
      defaultOpen
    >
      <div className="space-y-3">
        {showGraph && (
          <div className="admin-card rounded-2xl p-3">
            <PipelineGraph nodes={pipelineNodes} />
          </div>
        )}

        {contextSummary && (
          <div className="admin-card rounded-2xl p-3 text-[12px] text-slate-600 dark:text-slate-400">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-slate-700 dark:text-slate-200">
                Prompt Context
              </span>
              <span className="text-slate-400 dark:text-slate-500">
                {contextSummary.sectionCount} sections · {contextSummary.totalChars} chars
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {contextSummary.sections.slice(0, 6).map((section) => (
                <span
                  key={section.name}
                  className="admin-badge admin-badge-neutral text-[11px]"
                  title={section.source}
                >
                  {section.title} · {section.charCount}
                  {section.truncated ? " truncated" : ""}
                </span>
              ))}
            </div>
            <div className="mt-2 text-[11px] text-slate-400 dark:text-slate-500">
              injected memories: {contextSummary.memoryCount}
            </div>
          </div>
        )}

        {visibleSteps.length > 0 && (
          <div>
            <button
              type="button"
              onClick={() => setDetailOpen((v) => !v)}
              className="liquid-hover flex w-full items-center gap-1.5 rounded-xl px-2 py-1.5 text-[11px] font-medium text-slate-400 transition hover:text-slate-600 dark:text-slate-600 dark:hover:text-slate-400"
            >
              <ChevronDown
                className={`h-3 w-3 transition-transform ${detailOpen ? "rotate-0" : "-rotate-90"}`}
              />
              {t("run.detailEvents", { count: visibleSteps.length })}
            </button>
            {detailOpen && (
              <div className="mt-1.5 space-y-1.5">
                {visibleSteps.map((step) => (
                  <div
                    key={step.id}
                    className="admin-card flex items-center justify-between rounded-xl px-3 py-2.5 text-[12px] leading-relaxed text-slate-600 animate-fade-slide-up dark:text-slate-400"
                  >
                    <span>{step.label}</span>
                    <span className={stepStatusClassName(step.status)}>
                      {step.status === "running"
                        ? t("run.running")
                        : step.status === "error"
                          ? t("run.error")
                          : t("run.done")}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </InspectorPanel>
  );
}

function stepStatusClassName(status: RunStep["status"]) {
  if (status === "running") return "text-amber-500";
  if (status === "error") return "text-red-500";
  return "text-emerald-500";
}

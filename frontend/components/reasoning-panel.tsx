"use client";

import { Activity, Maximize2, Minus, Plus, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";

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

export function ReasoningPanel({ steps, showGraph = true }: ReasoningPanelProps) {
  const visibleSteps = useMemo(() => coalesceRunSteps(steps), [steps]);
  const graph = useMemo(() => buildProgressiveGraph(visibleSteps), [visibleSteps]);
  const contextSummary = useMemo(() => latestContextSummary(visibleSteps), [visibleSteps]);
  const [expanded, setExpanded] = useState(false);
  const [zoom, setZoom] = useState(1);
  const graphHeight = expanded ? 220 : 128;

  return (
    <InspectorPanel
      title="Run State"
      icon={<Activity className="h-3.5 w-3.5" strokeWidth={2} />}
      defaultOpen
      action={
        showGraph ? (
          <div className="flex items-center gap-1 text-slate-400">
            <GraphButton label="缩小" onClick={() => setZoom((value) => Math.max(0.75, value - 0.15))}>
              <Minus className="h-3 w-3" />
            </GraphButton>
            <GraphButton label="重置缩放" onClick={() => setZoom(1)}>
              <RotateCcw className="h-3 w-3" />
            </GraphButton>
            <GraphButton label="放大" onClick={() => setZoom((value) => Math.min(1.6, value + 0.15))}>
              <Plus className="h-3 w-3" />
            </GraphButton>
            <GraphButton label={expanded ? "收起运行图" : "展开运行图"} onClick={() => setExpanded((value) => !value)}>
              <Maximize2 className="h-3 w-3" />
            </GraphButton>
          </div>
        ) : undefined
      }
    >
      <div className="space-y-3">
        {showGraph && (
          <div
            className="overflow-auto rounded-2xl bg-slate-950/[0.025] p-3 scrollbar-thin dark:bg-white/[0.035]"
            style={{ height: graphHeight }}
          >
            {graph.nodes.length === 0 ? (
              <div className="flex h-full items-center justify-center text-[12px] text-slate-400 dark:text-slate-600">
                等待运行图…
              </div>
            ) : (
              <RunGraph nodes={graph.nodes} zoom={zoom} expanded={expanded} />
            )}
          </div>
        )}

        {contextSummary && (
          <div className="rounded-2xl border border-slate-950/[0.06] bg-white/55 p-3 text-[12px] text-slate-600 shadow-sm dark:border-white/[0.08] dark:bg-white/[0.035] dark:text-slate-400">
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
                  className="rounded-full bg-slate-950/[0.04] px-2 py-1 text-[11px] text-slate-500 dark:bg-white/[0.06] dark:text-slate-400"
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

        {visibleSteps.length === 0 ? (
          <p className="px-1 py-2 text-[12px] text-slate-400 dark:text-slate-600">
            等待节点更新…
          </p>
        ) : (
          <div className="space-y-1.5">
            {visibleSteps.slice(-6).map((step) => (
              <div
                key={step.id}
                className="flex items-center justify-between rounded-xl bg-slate-950/[0.03] px-3 py-2.5 text-[12px] leading-relaxed text-slate-600 animate-fade-slide-up dark:bg-white/[0.04] dark:text-slate-400"
              >
                <span>{step.label}</span>
                <span className={stepStatusClassName(step.status)}>
                  {step.status === "running"
                    ? "运行中"
                    : step.status === "error"
                      ? "错误"
                      : "完成"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </InspectorPanel>
  );
}

type GraphNode = {
  id: string;
  label: string;
  status: RunStep["status"];
  kind: RunStep["type"];
  x: number;
  y: number;
};

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
  return label.replace(/\s*(运行中|完成|失败)$/u, "") || "工具";
}

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

function RunGraph({
  nodes,
  zoom,
  expanded,
}: {
  nodes: GraphNode[];
  zoom: number;
  expanded: boolean;
}) {
  const nodeWidth = 68;
  const width = Math.max(286, nodes.length * 78 + 10) * zoom;
  const height = (expanded ? 152 : 78) * zoom;
  const scaledNodes = nodes.map((node) => ({
    ...node,
    x: node.x * zoom,
    y: node.y * zoom,
  }));

  return (
    <div className="relative" style={{ width, height }}>
      <svg className="absolute inset-0 h-full w-full overflow-visible" aria-hidden="true">
        <defs>
          <marker
            id="run-arrow"
            markerHeight="7"
            markerWidth="7"
            orient="auto"
            refX="6"
            refY="3.5"
          >
            <path d="M0,0 L7,3.5 L0,7 Z" fill="rgb(148 163 184 / 0.55)" />
          </marker>
        </defs>
        {scaledNodes.slice(1).map((node, index) => {
          const source = scaledNodes[index];
          const startX = source.x + nodeWidth * zoom;
          const startY = source.y + 18 * zoom;
          const endX = node.x;
          const endY = node.y + 18 * zoom;
          const midX = (startX + endX) / 2;
          return (
            <path
              key={`${source.id}-${node.id}`}
              d={`M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX - 8} ${endY}`}
              fill="none"
              markerEnd="url(#run-arrow)"
              stroke={node.status === "running" ? "#10b981" : "rgb(148 163 184 / 0.45)"}
              strokeDasharray={node.status === "running" ? "4 4" : undefined}
              strokeLinecap="round"
              strokeWidth={node.status === "running" ? 1.7 : 1.2}
            />
          );
        })}
      </svg>

      {scaledNodes.map((node) => (
        <div
          key={node.id}
          className={`absolute flex h-8 w-[68px] items-center justify-center rounded-2xl px-2 text-[10.5px] font-semibold shadow-[0_8px_24px_-18px_rgb(15_23_42/0.55)] ${nodeClassName(node.status)}`}
          style={{
            left: node.x,
            top: node.y,
            transform: `scale(${zoom})`,
            transformOrigin: "top left",
          }}
          title={node.label}
        >
          <span className="max-w-full truncate">{node.label}</span>
        </div>
      ))}
    </div>
  );
}

function buildProgressiveGraph(steps: RunStep[]): { nodes: GraphNode[] } {
  const byId = new Map<string, RunStep>();
  const orderedIds: string[] = [];
  const upsert = (step: RunStep, id: string, label: string) => {
    const existing = byId.get(id);
    if (!existing) {
      orderedIds.push(id);
    }
    byId.set(id, {
      ...(existing ?? step),
      ...step,
      id,
      label,
      status: step.status,
    });
  };

  for (const step of steps) {
    if (step.type === "user") upsert(step, "user", "输入");
    if (step.type === "context") upsert(step, "context", "上下文");
    if (step.type === "agent") upsert(step, "agent", "Agent");
    if (step.type === "memory") upsert(step, "memory", "记忆");
    if (step.type === "skill") upsert(step, "skill", "Skill");
    if (step.type === "pact") upsert(step, "pact", "Pact");
    if (step.type === "compaction") upsert(step, "compaction", "压缩");
    if (step.type === "delegate") upsert(step, "delegate", "委派");
    if (step.type === "approval") upsert(step, "approval", "审批");
    if (step.type === "subagent") upsert(step, "subagent", "子 Agent");
    if (step.type === "tool") {
      const toolName = stripToolStatus(step.label);
      upsert(step, graphStepKey(step), toolName);
    }
    if (step.type === "error") upsert(step, "error", "错误");
    if (step.type === "done") upsert(step, "done", "完成");
  }

  const nodeSteps = orderedIds.map((id) => byId.get(id)).filter(Boolean) as RunStep[];
  const columns = Math.max(1, nodeSteps.length);
  const nodes = nodeSteps.map<GraphNode>((step, index) => ({
    id: step.id,
    label: step.label,
    status: step.status,
    kind: step.type,
    x: columns === 1 ? 108 : index * 78 + 6,
    y: step.type === "tool" && index > 1 ? 62 : 18,
  }));

  return { nodes };
}

function nodeClassName(status: RunStep["status"]) {
  if (status === "error") return "!bg-red-500/10 !text-red-600 ring-1 ring-red-400/30";
  if (status === "running") {
    return "!bg-emerald-500/[0.12] !text-emerald-700 ring-1 ring-emerald-400/35";
  }
  return "!bg-slate-950/[0.07] !text-slate-700 dark:!bg-white/[0.09] dark:!text-slate-200";
}

function GraphButton({
  label,
  children,
  onClick,
}: {
  label: string;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="rounded-lg p-1 transition hover:bg-slate-950/[0.05] hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/30 dark:hover:bg-white/[0.08] dark:hover:text-slate-200"
    >
      {children}
    </button>
  );
}

function stepStatusClassName(status: RunStep["status"]) {
  if (status === "running") return "text-amber-500";
  if (status === "error") return "text-red-500";
  return "text-emerald-500";
}

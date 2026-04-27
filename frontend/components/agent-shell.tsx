"use client";

import { fetchEventSource } from "@microsoft/fetch-event-source";
import { Menu, Plus, SlidersHorizontal, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  type ApprovalRequestView,
  ApprovalPanel,
} from "./approval-panel";
import { ChatComposer } from "./chat-composer";
import { type ChatMessage, type ChatMessagePart, MessageStream } from "./message-stream";
import {
  type CompactionRunView,
  type ContextPactView,
  type MemoryProposalView,
  MemoryPanel,
} from "./memory-panel";
import { type RunStep, ReasoningPanel } from "./reasoning-panel";
import {
  type AgentSettings,
  SettingsPanel,
} from "./settings-panel";
import {
  type SessionListItem,
  SessionSidebar,
  shortSessionLabel,
} from "./session-sidebar";
import {
  type SkillProposalView,
  type SkillSummaryView,
  SkillPanel,
} from "./skill-panel";
import type { ToolCallView } from "./tool-call-card";

type AgentEvent = {
  type: string;
  data: Record<string, unknown>;
};

const API_BASE = "/agent-api";
const SESSION_ID_KEY = "tommy.session_id";
const SETTINGS_KEY = "tommy.settings";

const DEFAULT_SETTINGS: AgentSettings = {
  model: "deepseek-v4-pro",
  responseStyle: "balanced",
  temperature: 0.2,
  theme: "system",
  showRunGraph: true,
  expandedTools: false,
  commandScope: "restricted",
  workingDirectory: "",
};

function loadSettings(): AgentSettings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    return { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<AgentSettings>) };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function saveSettings(settings: AgentSettings) {
  window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function resolveApiBase() {
  return API_BASE;
}

function createClientId(prefix = "id") {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (typeof randomUUID === "function") {
    return `${prefix}-${randomUUID.call(globalThis.crypto)}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function applyTheme(theme: AgentSettings["theme"]) {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const dark = theme === "dark" || (theme === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

function readableNodeUpdate(data: Record<string, unknown>) {
  const updates = Array.isArray(data.updates) ? data.updates : [];
  if (updates.includes("action")) return "工具调用完成";
  if (updates.includes("agent")) return "回复已更新";
  return "状态已更新";
}

function createRunStep(
  type: RunStep["type"],
  label: string,
  status: RunStep["status"] = "done",
  payload?: Record<string, unknown>,
): RunStep {
  return {
    id: createClientId(type),
    type,
    label,
    status,
    at: Date.now(),
    payload,
  };
}

function runStepKey(step: RunStep) {
  if (step.type === "tool") {
    return `tool-${String(step.payload?.tool_call_id ?? step.payload?.run_id ?? step.label)}`;
  }
  return step.type;
}

function appendTextPart(parts: ChatMessagePart[] | undefined, content: string): ChatMessagePart[] {
  const next = [...(parts ?? [])];
  const last = next[next.length - 1];
  if (last?.type === "text") {
    next[next.length - 1] = { ...last, content: `${last.content}${content}` };
  } else {
    next.push({ id: createClientId("text"), type: "text", content });
  }
  return next;
}

function upsertToolPart(parts: ChatMessagePart[] | undefined, tool: ToolCallView): ChatMessagePart[] {
  const next = [...(parts ?? [])];
  const index = next.findIndex((part) => part.type === "tool" && part.tool.id === tool.id);
  if (index >= 0) {
    const existing = next[index];
    if (existing.type === "tool") {
      next[index] = { ...existing, tool: { ...existing.tool, ...tool } };
    }
  } else {
    next.push({ id: `tool-${tool.id}`, type: "tool", tool });
  }
  return next;
}

type ApiSessionListItem = {
  id: string;
  title: string;
  preview: string;
  updated_at: string;
};

type ApiMessage = {
  id: string;
  role: ChatMessage["role"];
  content: string;
  metadata?: Record<string, unknown>;
  created_at: string;
};

type ApiRunEvent = {
  id: string;
  run_id?: string;
  type: RunStep["type"];
  label: string;
  status: RunStep["status"];
  payload?: Record<string, unknown>;
  sequence?: number;
  created_at: string;
};

type ApiRun = {
  id: string;
  session_id: string;
  agent_id: string;
  status: "queued" | "running" | "completed" | "cancelled" | "interrupted" | "error";
  input: string;
  metadata?: Record<string, unknown>;
  assistant_message_id?: string | null;
  cancel_requested?: boolean;
  created_at: string;
  started_at?: string | null;
  updated_at: string;
  finished_at?: string | null;
  error?: string;
};

type ApiToolCall = {
  id: string;
  run_id: string;
  name: string;
  status: "running" | "done" | "error";
  args?: Record<string, unknown>;
  result?: string;
};

type ApiSessionDetail = {
  session?: Record<string, unknown>;
  messages: ApiMessage[];
  run_events: ApiRunEvent[];
  tool_calls: ApiToolCall[];
  latest_run?: ApiRun | null;
  active_run?: ApiRun | null;
  runs?: ApiRun[];
  context_pact?: ContextPactView;
  skill_proposals?: SkillProposalView[];
  memory_proposals?: MemoryProposalView[];
  compaction_runs?: CompactionRunView[];
  skills?: SkillSummaryView[];
  pending_approvals?: ApprovalRequestView[];
};

function isToolCallView(value: unknown): value is ToolCallView {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ToolCallView>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.name === "string" &&
    (candidate.status === "running" ||
      candidate.status === "done" ||
      candidate.status === "error")
  );
}

function parseStoredParts(value: unknown): ChatMessagePart[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const parts: ChatMessagePart[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const part = item as {
      id?: unknown;
      type?: unknown;
      content?: unknown;
      tool?: unknown;
    };
    if (part.type === "text" && typeof part.content === "string") {
      parts.push({
        id: typeof part.id === "string" ? part.id : createClientId("text"),
        type: "text",
        content: part.content,
      });
    }
    if (part.type === "tool" && isToolCallView(part.tool)) {
      parts.push({
        id: typeof part.id === "string" ? part.id : `tool-${part.tool.id}`,
        type: "tool",
        tool: part.tool,
      });
    }
  }
  return parts.length > 0 ? parts : undefined;
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${resolveApiBase()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`);
  }
  return (await response.json()) as T;
}

function toSessionListItem(item: ApiSessionListItem): SessionListItem {
  return {
    id: item.id,
    title: item.title,
    preview: item.preview,
    updatedAt: Date.parse(item.updated_at) || Date.now(),
  };
}

function toRunStep(event: ApiRunEvent): RunStep {
  return {
    id: event.id,
    type: event.type,
    label: event.label,
    status: event.status,
    at: Date.parse(event.created_at) || Date.now(),
    payload: event.payload,
  };
}

function maxRunEventSequence(events: ApiRunEvent[], runId: string) {
  return events.reduce((max, event) => {
    if (event.run_id && event.run_id !== runId) return max;
    return typeof event.sequence === "number" ? Math.max(max, event.sequence) : max;
  }, -1);
}

function attachTools(messages: ApiMessage[], tools: ApiToolCall[]): ChatMessage[] {
  const groupedTools = new Map<string, ToolCallView[]>();
  for (const tool of tools) {
    const items = groupedTools.get(tool.run_id) ?? [];
    items.push({
      id: tool.id,
      name: tool.name,
      status: tool.status,
      summary: tool.result || (tool.args ? JSON.stringify(tool.args) : tool.status),
    });
    groupedTools.set(tool.run_id, items);
  }

  return messages.map((message) => {
    const runId = String(message.metadata?.run_id ?? "");
    const toolsForMessage = message.role === "assistant" ? groupedTools.get(runId) : undefined;
    const storedParts = parseStoredParts(message.metadata?.parts);
    const fallbackParts: ChatMessagePart[] = [
      ...(message.content
        ? [{ id: `${message.id}-text`, type: "text" as const, content: message.content }]
        : []),
      ...((toolsForMessage ?? []).map((tool) => ({
        id: `${message.id}-${tool.id}`,
        type: "tool" as const,
        tool,
      })) satisfies ChatMessagePart[]),
    ];
    return {
      id: message.id,
      role: message.role,
      content: message.content,
      tools: toolsForMessage,
      parts: storedParts ?? (fallbackParts.length > 0 ? fallbackParts : undefined),
    };
  });
}

export function AgentShell() {
  const [sessionId, setSessionId] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [steps, setSteps] = useState<RunStep[]>([]);
  const [settings, setSettings] = useState<AgentSettings>(DEFAULT_SETTINGS);
  const [memoryStatus, setMemoryStatus] = useState("Ready");
  const [contextPact, setContextPact] = useState<ContextPactView>({});
  const [memoryProposals, setMemoryProposals] = useState<MemoryProposalView[]>([]);
  const [compactionRuns, setCompactionRuns] = useState<CompactionRunView[]>([]);
  const [skills, setSkills] = useState<SkillSummaryView[]>([]);
  const [skillProposals, setSkillProposals] = useState<SkillProposalView[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalRequestView[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [mobileSessionsOpen, setMobileSessionsOpen] = useState(false);
  const [mobileInspectorOpen, setMobileInspectorOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const stopRequestedRef = useRef(false);
  const currentRunIdRef = useRef<string | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const stepsRef = useRef<RunStep[]>([]);
  const [, setCurrentRunId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const initialSettings = loadSettings();
    setSettings(initialSettings);
    applyTheme(initialSettings.theme);

    async function boot() {
      try {
        const nextSessions = await fetchSessions();
        let nextSessionId = window.localStorage.getItem(SESSION_ID_KEY) ?? "";
        if (!nextSessionId || !nextSessions.some((session) => session.id === nextSessionId)) {
          nextSessionId = nextSessions[0]?.id ?? (await createBackendSession());
        }
        const sessionsAfterCreate =
          nextSessions.length > 0 ? nextSessions : await fetchSessions();
        if (cancelled) return;
        setSessions(sessionsAfterCreate);
        await loadSession(nextSessionId);
      } catch (error) {
        if (!cancelled) setMemoryStatus(`初始化失败: ${String(error)}`);
      }
    }

    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    applyTheme(settings.theme);
    if (settings.theme !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = () => applyTheme("system");
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, [settings.theme]);

  async function fetchSessions() {
    const result = await apiJson<{ sessions: ApiSessionListItem[] }>("/api/sessions");
    return result.sessions.map(toSessionListItem);
  }

  async function createBackendSession() {
    const result = await apiJson<{ session_id: string }>("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ title: "新对话" }),
    });
    return result.session_id;
  }

  async function refreshSessions() {
    const nextSessions = await fetchSessions();
    setSessions(nextSessions);
    return nextSessions;
  }

  function setActiveRunId(runId: string | null) {
    currentRunIdRef.current = runId;
    setCurrentRunId(runId);
  }

  async function loadSession(nextSessionId: string) {
    abortRef.current?.abort();
    abortRef.current = null;
    setActiveRunId(null);
    const detail = await apiJson<ApiSessionDetail>(`/api/sessions/${nextSessionId}`);
    const loadedMessages = attachTools(detail.messages, detail.tool_calls);
    const loadedSteps = detail.run_events.map(toRunStep);
    window.localStorage.setItem(SESSION_ID_KEY, nextSessionId);
    setSessionId(nextSessionId);
    setInput("");
    messagesRef.current = loadedMessages;
    stepsRef.current = loadedSteps;
    setMessages(loadedMessages);
    setSteps(loadedSteps);
    setContextPact(detail.context_pact ?? {});
    setMemoryProposals(detail.memory_proposals ?? []);
    setCompactionRuns(detail.compaction_runs ?? []);
    setSkills(detail.skills ?? []);
    setSkillProposals(detail.skill_proposals ?? []);
    setPendingApprovals(detail.pending_approvals ?? []);
    const activeRun = detail.active_run;
    if (activeRun && ["queued", "running"].includes(activeRun.status)) {
      const afterSequence = maxRunEventSequence(detail.run_events, activeRun.id);
      setActiveRunId(activeRun.id);
      setIsStreaming(true);
      setMemoryStatus("生成中，正在重新连接");
      void subscribeRunEvents(activeRun.id, afterSequence >= 0 ? afterSequence : undefined);
      return;
    }
    setIsStreaming(false);
    setMemoryStatus("Ready");
  }

  async function refreshCurrentSession() {
    if (!sessionId) return;
    await loadSession(sessionId);
  }

  async function confirmMemory(memoryId: string) {
    await apiJson<{ memory: MemoryProposalView }>(`/api/memory/${memoryId}/confirm`, {
      method: "POST",
    });
    setMemoryStatus("记忆已确认");
    await refreshCurrentSession();
  }

  async function compactCurrentSession() {
    if (!sessionId || isStreaming) return;
    const result = await apiJson<{ compaction: CompactionRunView | null; pact: ContextPactView }>(
      `/api/sessions/${sessionId}/compact`,
      {
        method: "POST",
        body: JSON.stringify({ keep_recent: 18 }),
      },
    );
    if (result.pact) setContextPact(result.pact);
    if (result.compaction) {
      setCompactionRuns((current) => [result.compaction as CompactionRunView, ...current]);
      persistStep(createRunStep("compaction", "手动压缩完成", "done", result));
      setMemoryStatus("会话已压缩");
    }
    await refreshCurrentSession();
  }

  async function applySkillProposal(proposalId: string) {
    await apiJson<{ proposal: SkillProposalView }>(`/api/skills/proposals/${proposalId}/apply`, {
      method: "POST",
    });
    setMemoryStatus("Skill 已应用");
    await refreshCurrentSession();
  }

  async function rejectSkillProposal(proposalId: string) {
    await apiJson<{ proposal: SkillProposalView }>(`/api/skills/proposals/${proposalId}/reject`, {
      method: "POST",
    });
    setMemoryStatus("Skill 提案已拒绝");
    await refreshCurrentSession();
  }

  async function approveRequest(approvalId: string) {
    await apiJson<{ approval: ApprovalRequestView; result?: string }>(
      `/api/approvals/${approvalId}/approve`,
      { method: "POST" },
    );
    setMemoryStatus("审批已执行");
    await refreshCurrentSession();
  }

  async function rejectApprovalRequest(approvalId: string) {
    await apiJson<{ approval: ApprovalRequestView }>(`/api/approvals/${approvalId}/reject`, {
      method: "POST",
    });
    setMemoryStatus("审批已拒绝");
    await refreshCurrentSession();
  }

  async function resetSession() {
    if (isStreaming) return;
    const next = await createBackendSession();
    const nextSessions = await refreshSessions();
    window.localStorage.setItem(SESSION_ID_KEY, next);
    setSessionId(next);
    setSessions(nextSessions);
    setInput("");
    messagesRef.current = [];
    stepsRef.current = [];
    setMessages([]);
    setSteps([]);
    setContextPact({});
    setMemoryProposals([]);
    setCompactionRuns([]);
    setSkills([]);
    setSkillProposals([]);
    setPendingApprovals([]);
    setMemoryStatus("新对话");
  }

  async function selectSession(nextSessionId: string) {
    if (nextSessionId === sessionId) return;
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    setActiveRunId(null);
    await loadSession(nextSessionId);
  }

  async function deleteSession(targetSessionId: string) {
    if (isStreaming) return;
    const target = sessions.find((session) => session.id === targetSessionId);
    const confirmed = window.confirm(
      `删除「${target?.title ?? shortSessionLabel(targetSessionId)}」？此操作会删除本地数据库中的对话记录。`,
    );
    if (!confirmed) return;

    await apiJson<{ status: string }>(`/api/sessions/${targetSessionId}`, {
      method: "DELETE",
    });
    let remaining = await refreshSessions();

    if (remaining.length === 0) {
      const next = await createBackendSession();
      remaining = await refreshSessions();
      window.localStorage.setItem(SESSION_ID_KEY, next);
      setSessionId(next);
      setInput("");
      messagesRef.current = [];
      stepsRef.current = [];
      setMessages([]);
      setSteps([]);
      setContextPact({});
      setMemoryProposals([]);
      setCompactionRuns([]);
      setSkills([]);
      setSkillProposals([]);
      setPendingApprovals([]);
      setMemoryStatus("新对话");
      return;
    }

    if (targetSessionId === sessionId) {
      const next = remaining[0];
      await loadSession(next.id);
    }
  }

  function persistMessageState(updater: (current: ChatMessage[]) => ChatMessage[]) {
    setMessages((current) => {
      const next = updater(current);
      messagesRef.current = next;
      return next;
    });
  }

  function persistStep(step: RunStep) {
    setSteps((current) => {
      const normalized =
        step.type === "done"
          ? current.map((item) =>
              item.status === "running" ? { ...item, status: "done" as const } : item,
            )
          : current;
      const key = runStepKey(step);
      const existingIndex = normalized.findIndex((item) => runStepKey(item) === key);
      const next =
        existingIndex >= 0
          ? normalized.map((item, index) =>
              index === existingIndex
                ? {
                    ...item,
                    ...step,
                    id: item.id,
                    at: step.at,
                    payload: { ...(item.payload ?? {}), ...(step.payload ?? {}) },
                  }
                : item,
            )
          : [...normalized, step];
      const trimmed = next.slice(-20);
      stepsRef.current = trimmed;
      return trimmed;
    });
  }

  function updateSettings(nextSettings: AgentSettings) {
    setSettings(nextSettings);
    saveSettings(nextSettings);
  }

  function updateSessionSummary(nextMessages: ChatMessage[]) {
    const firstUser = nextMessages.find((message) => message.role === "user");
    const lastAssistant = [...nextMessages]
      .reverse()
      .find((message) => message.role === "assistant" && message.content.trim());
    const titleSource = firstUser?.content?.replace(/\s+/g, " ").trim();
    const previewSource = (lastAssistant ?? firstUser)?.content?.replace(/\s+/g, " ").trim();

    const nextSessions = [
      {
        id: sessionId,
        title: titleSource
          ? titleSource.length > 24
            ? `${titleSource.slice(0, 24)}…`
            : titleSource
          : shortSessionLabel(sessionId),
        preview: previewSource
          ? previewSource.length > 54
            ? `${previewSource.slice(0, 54)}…`
            : previewSource
          : "还没有消息",
        updatedAt: Date.now(),
      },
      ...sessions.filter((session) => session.id !== sessionId),
    ];
    setSessions(nextSessions);
  }

  function appendAssistantToken(content: string) {
    persistMessageState((current) => {
      const last = current[current.length - 1];
      if (last?.role === "assistant") {
        return [
          ...current.slice(0, -1),
          {
            ...last,
            content: `${last.content}${content}`,
            parts: appendTextPart(last.parts, content),
          },
        ];
      }
      return [
        ...current,
        {
          id: createClientId("message"),
          role: "assistant",
          content,
          parts: [{ id: createClientId("text"), type: "text", content }],
        },
      ];
    });
  }

  function updateAssistantTool(tool: ToolCallView) {
    persistMessageState((current) => {
      const next = [...current];
      let index = next.length - 1;
      while (index >= 0 && next[index]?.role !== "assistant") {
        index -= 1;
      }
      if (index < 0) {
        return [
          ...next,
          {
            id: createClientId("message"),
            role: "assistant",
            content: "",
            tools: [tool],
            parts: [{ id: `tool-${tool.id}`, type: "tool", tool }],
          },
        ];
      }

      const assistant = next[index];
      const tools = assistant.tools ?? [];
      const existing = tools.findIndex((item) => item.id === tool.id);
      const updatedTools =
        existing >= 0
          ? tools.map((item) => (item.id === tool.id ? { ...item, ...tool } : item))
          : [...tools, tool];
      next[index] = {
        ...assistant,
        tools: updatedTools,
        parts: upsertToolPart(assistant.parts, tool),
      };
      return next;
    });
  }

  function handleAgentEvent(payload: AgentEvent) {
    const data = payload.data;

    if (payload.type === "token") {
      if (!stepsRef.current.some((step) => step.type === "agent" && step.status === "running")) {
        persistStep(createRunStep("agent", "Agent 正在生成", "running"));
      }
      appendAssistantToken(String(data.content ?? ""));
      return;
    }

    if (payload.type === "tool_start") {
      const id = String(
        data.tool_call_id ?? data.run_id ?? createClientId("tool-call"),
      );
      const args = data.args ?? data.input;
      updateAssistantTool({
        id,
        name: String(data.tool ?? "tool"),
        status: "running",
        summary: args ? JSON.stringify(args) : "正在运行…",
      });
      persistStep(
        createRunStep("tool", `${String(data.tool ?? "工具")} 运行中`, "running", data),
      );
      return;
    }

    if (payload.type === "tool_end") {
      const id = String(data.tool_call_id ?? data.run_id ?? "");
      updateAssistantTool({
        id,
        name: String(data.tool ?? "tool"),
        status: String(data.status ?? "ok") === "error" ? "error" : "done",
        summary: String(data.content ?? data.output ?? ""),
      });
      persistStep(
        createRunStep(
          "tool",
          `${String(data.tool ?? "工具")} ${String(data.status ?? "ok") === "error" ? "失败" : "完成"}`,
          String(data.status ?? "ok") === "error" ? "error" : "done",
          data,
        ),
      );
      return;
    }

    if (payload.type === "node_end") {
      persistStep(createRunStep("agent", readableNodeUpdate(data), "done", data));
      return;
    }

    if (payload.type === "approval_pending") {
      const approval = data.approval;
      if (approval && typeof approval === "object") {
        const view = approval as ApprovalRequestView;
        setPendingApprovals((current) => [
          view,
          ...current.filter((item) => item.id !== view.id),
        ]);
      }
      setMemoryStatus("有操作等待审批");
      persistStep(createRunStep("approval", "等待用户审批", "running", data));
      return;
    }

    if (payload.type === "approval_resolved") {
      const approval = data.approval;
      if (approval && typeof approval === "object") {
        const view = approval as ApprovalRequestView;
        setPendingApprovals((current) => current.filter((item) => item.id !== view.id));
      }
      setMemoryStatus("审批已处理");
      persistStep(createRunStep("approval", "审批已处理", "done", data));
      return;
    }

    if (payload.type === "subagent_start") {
      persistStep(createRunStep("subagent", `子 Agent ${String(data.target_agent ?? "")} 启动`, "running", data));
      return;
    }

    if (payload.type === "subagent_end") {
      persistStep(createRunStep("subagent", `子 Agent ${String(data.target_agent ?? "")} 完成`, "done", data));
      return;
    }

    if (payload.type === "memory") {
      setMemoryStatus("记忆状态更新");
      if (data.proposal && typeof data.proposal === "object") {
        setMemoryProposals((current) => [
          data.proposal as MemoryProposalView,
          ...current.filter((item) => item.id !== (data.proposal as MemoryProposalView).id),
        ]);
      }
      persistStep(createRunStep("memory", "记忆状态更新", "done", data));
      return;
    }

    if (payload.type === "compaction") {
      setMemoryStatus("会话已压缩");
      if (data.pact && typeof data.pact === "object") {
        setContextPact(data.pact as ContextPactView);
      }
      if (data.compaction && typeof data.compaction === "object") {
        setCompactionRuns((current) => [
          data.compaction as CompactionRunView,
          ...current.filter((item) => item.id !== (data.compaction as CompactionRunView).id),
        ]);
      }
      persistStep(createRunStep("compaction", "会话已压缩", "done", data));
      return;
    }

    if (payload.type === "skill") {
      const proposal = data.proposal;
      if (proposal && typeof proposal === "object") {
        const view = proposal as SkillProposalView;
        setSkillProposals((current) =>
          view.status === "proposed"
            ? [view, ...current.filter((item) => item.id !== view.id)]
            : current.filter((item) => item.id !== view.id),
        );
      }
      setMemoryStatus("Skill 提案已更新");
      persistStep(createRunStep("skill", "Skill 提案已更新", "done", data));
      return;
    }

    if (payload.type === "pact") {
      if (data.pact && typeof data.pact === "object") {
        setContextPact(data.pact as ContextPactView);
      }
      setMemoryStatus("Context Pact 已更新");
      persistStep(createRunStep("pact", "Context Pact 已更新", "done", data));
      return;
    }

    if (payload.type === "delegate") {
      setMemoryStatus("已记录委派任务");
      persistStep(createRunStep("delegate", `委派给 ${String(data.target_agent ?? "agent")}`, "done", data));
      return;
    }

    if (payload.type === "error") {
      setMemoryStatus(`Error: ${String(data.message ?? "Unknown error")}`);
      persistStep(createRunStep("error", "请求出错", "error"));
      setIsStreaming(false);
      setActiveRunId(null);
      return;
    }

    if (payload.type === "cancelled" || payload.type === "interrupted") {
      setMemoryStatus("已停止生成，内容已保存");
      setIsStreaming(false);
      setActiveRunId(null);
      persistStep(createRunStep("agent", "生成已停止", "done", data));
      void refreshSessions();
      return;
    }

    if (payload.type === "stopped") {
      setMemoryStatus("已停止生成，内容已保存");
      setIsStreaming(false);
      setActiveRunId(null);
      persistStep(createRunStep("agent", "生成已停止", "done", data));
      void refreshSessions();
      return;
    }

    if (payload.type === "done") {
      setIsStreaming(false);
      setActiveRunId(null);
      persistStep(createRunStep("done", "完成", "done"));
      updateSessionSummary(messagesRef.current);
      void refreshSessions();
      void refreshCurrentSession();
    }
  }

  async function subscribeRunEvents(runId: string, afterSequence?: number) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    stopRequestedRef.current = false;
    setActiveRunId(runId);
    setIsStreaming(true);

    const query =
      typeof afterSequence === "number" ? `?after_sequence=${encodeURIComponent(afterSequence)}` : "";

    try {
      await fetchEventSource(`${resolveApiBase()}/api/runs/${runId}/events${query}`, {
        method: "GET",
        signal: controller.signal,
        onmessage(event) {
          const parsed = JSON.parse(event.data) as AgentEvent;
          handleAgentEvent(parsed);
        },
        onerror(error) {
          if (controller.signal.aborted || stopRequestedRef.current) return;
          setIsStreaming(false);
          setMemoryStatus(`Stream error: ${String(error)}`);
          throw error;
        },
        onclose() {
          setIsStreaming(false);
        },
      });
    } catch (error) {
      if (!controller.signal.aborted && !stopRequestedRef.current) {
        setIsStreaming(false);
        setMemoryStatus(`Stream error: ${String(error)}`);
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
      if (stopRequestedRef.current) {
        setIsStreaming(false);
      }
      stopRequestedRef.current = false;
    }
  }

  async function streamLegacyMessage({
    message,
    nextMessages,
    history = [],
    resetThread = false,
  }: {
    message: string;
    nextMessages: ChatMessage[];
    history?: ChatMessage[];
    resetThread?: boolean;
  }) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    stopRequestedRef.current = false;
    setInput("");
    setIsStreaming(true);
    stepsRef.current = [createRunStep("user", "收到输入", "done")];
    setSteps(stepsRef.current);
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
    updateSessionSummary(nextMessages);

    try {
      await fetchEventSource(`${resolveApiBase()}/api/chat/stream`, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          reset_thread: resetThread,
          metadata: {
            frontend_settings: settings,
          },
          history: history
            .filter((item) => item.role === "user" || item.role === "assistant")
            .filter((item) => item.content.trim())
            .map((item) => ({ role: item.role, content: item.content })),
        }),
        onmessage(event) {
          const parsed = JSON.parse(event.data) as AgentEvent;
          handleAgentEvent(parsed);
        },
        onerror(error) {
          if (controller.signal.aborted || stopRequestedRef.current) return;
          setIsStreaming(false);
          setMemoryStatus(`Stream error: ${String(error)}`);
          throw error;
        },
        onclose() {
          setIsStreaming(false);
        },
      });
    } catch (error) {
      if (!controller.signal.aborted && !stopRequestedRef.current) {
        setIsStreaming(false);
        setMemoryStatus(`Stream error: ${String(error)}`);
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
      if (stopRequestedRef.current) {
        setIsStreaming(false);
      }
      stopRequestedRef.current = false;
    }
  }

  async function streamMessage({
    message,
    nextMessages,
    history = [],
    resetThread = false,
  }: {
    message: string;
    nextMessages: ChatMessage[];
    history?: ChatMessage[];
    resetThread?: boolean;
  }) {
    abortRef.current?.abort();
    stopRequestedRef.current = false;
    setActiveRunId(null);
    setInput("");
    setIsStreaming(true);
    stepsRef.current = [createRunStep("user", "收到输入", "done")];
    setSteps(stepsRef.current);
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
    updateSessionSummary(nextMessages);

    const body = {
      session_id: sessionId,
      message,
      reset_thread: resetThread,
      metadata: {
        frontend_settings: settings,
      },
      history: history
        .filter((item) => item.role === "user" || item.role === "assistant")
        .filter((item) => item.content.trim())
        .map((item) => ({ role: item.role, content: item.content })),
    };

    try {
      const run = await apiJson<{ run_id: string; status: string }>("/api/runs", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setActiveRunId(run.run_id);
      await subscribeRunEvents(run.run_id);
    } catch (error) {
      if (!String(error).includes("API 404") && !String(error).includes("API 405")) {
        setIsStreaming(false);
        setMemoryStatus(`Run error: ${String(error)}`);
        return;
      }
      await streamLegacyMessage({
        message,
        nextMessages,
        history,
        resetThread,
      });
    }
  }

  async function stopStreaming() {
    if (!sessionId || !isStreaming) return;
    stopRequestedRef.current = true;
    const runId = currentRunIdRef.current;
    if (runId) {
      try {
        await apiJson<{ run: ApiRun }>(`/api/runs/${runId}/cancel`, {
          method: "POST",
        });
      } catch {
        try {
          await apiJson<{ status: string }>(`/api/sessions/${sessionId}/stop`, {
            method: "POST",
            body: JSON.stringify({ run_id: runId }),
          });
        } catch {
          // Local UI should still stop even if the stop endpoint is unavailable.
        }
      }
    } else {
      try {
        await apiJson<{ status: string }>(`/api/sessions/${sessionId}/stop`, {
          method: "POST",
        });
      } catch {
        // Local UI should still stop even if the legacy stop endpoint is unavailable.
      }
    }
    abortRef.current?.abort();
    setActiveRunId(null);
    setIsStreaming(false);
    setMemoryStatus("已停止生成，内容已保存");
    persistStep(createRunStep("agent", "已停止生成", "done"));
    void refreshSessions();
  }

  async function sendMessage() {
    const message = input.trim();
    if (!message || !sessionId || isStreaming) return;

    await streamMessage({
      message,
      nextMessages: [
        ...messagesRef.current,
        { id: createClientId("message"), role: "user", content: message },
        { id: createClientId("message"), role: "assistant", content: "", parts: [] },
      ],
    });
  }

  async function copyMessage(message: ChatMessage) {
    const toolText =
      message.tools
        ?.map((tool) => `[${tool.name}] ${tool.summary ?? tool.status}`)
        .join("\n") ?? "";
    const text = [message.content, toolText].filter(Boolean).join("\n\n");
    await navigator.clipboard.writeText(text);
    setCopiedMessageId(message.id);
    window.setTimeout(() => setCopiedMessageId(null), 1200);
  }

  async function regenerateLastResponse() {
    if (isStreaming || !sessionId) return;
    const current = messagesRef.current;
    const lastAssistantIndex = [...current]
      .map((message, index) => ({ message, index }))
      .reverse()
      .find((item) => item.message.role === "assistant")?.index;

    if (lastAssistantIndex === undefined) return;
    const lastUserIndex = current
      .slice(0, lastAssistantIndex)
      .map((message, index) => ({ message, index }))
      .reverse()
      .find((item) => item.message.role === "user")?.index;

    if (lastUserIndex === undefined) return;
    const lastUser = current[lastUserIndex];
    const history = current.slice(0, lastUserIndex);
    const nextMessages: ChatMessage[] = [
      ...history,
      lastUser,
      { id: createClientId("message"), role: "assistant", content: "", parts: [] },
    ];

    await streamMessage({
      message: lastUser.content,
      nextMessages,
      history,
      resetThread: true,
    });
  }

  const activeSession = sessions.find((session) => session.id === sessionId);

  return (
    <div className="h-[100dvh] overflow-hidden bg-slate-50/60 md:min-h-screen md:p-5 dark:bg-slate-950/20">
      <div className="mx-auto flex h-full w-full max-w-[100rem] flex-col md:grid md:h-[calc(100dvh-2.5rem)] md:grid-cols-1 md:gap-3 lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[15rem_minmax(0,1fr)_20rem] 2xl:grid-cols-[16rem_minmax(0,1fr)_21rem]">
        {/* Mobile-only header */}
        <SessionMobileHeader
          sessionId={sessionId}
          title={activeSession?.title}
          isStreaming={isStreaming}
          onNewSession={resetSession}
          onOpenSessions={() => setMobileSessionsOpen(true)}
          onOpenInspector={() => setMobileInspectorOpen(true)}
        />

        <MobileSessionDrawer
          open={mobileSessionsOpen}
          sessionId={sessionId}
          sessions={sessions}
          isStreaming={isStreaming}
          onClose={() => setMobileSessionsOpen(false)}
          onNewSession={resetSession}
          onSelectSession={selectSession}
          onDeleteSession={deleteSession}
        />

        <MobileInspectorSheet
          open={mobileInspectorOpen}
          sessionId={sessionId}
          memoryStatus={memoryStatus}
          contextPact={contextPact}
          memoryProposals={memoryProposals}
          compactionRuns={compactionRuns}
          skills={skills}
          skillProposals={skillProposals}
          pendingApprovals={pendingApprovals}
          steps={steps}
          settings={settings}
          onApproveRequest={approveRequest}
          onRejectApprovalRequest={rejectApprovalRequest}
          onConfirmMemory={confirmMemory}
          onCompact={compactCurrentSession}
          onApplySkillProposal={applySkillProposal}
          onRejectSkillProposal={rejectSkillProposal}
          onSettingsChange={updateSettings}
          onClose={() => setMobileInspectorOpen(false)}
        />

        {/* Desktop sidebar */}
        <SessionSidebar
          sessionId={sessionId}
          sessions={sessions}
          isStreaming={isStreaming}
          onNewSession={resetSession}
          onSelectSession={selectSession}
          onDeleteSession={deleteSession}
        />

        {/* Main chat column */}
        <div className="flex min-h-0 flex-1 flex-col md:gap-3">
          <MessageStream
            messages={messages}
            isStreaming={isStreaming}
            copiedMessageId={copiedMessageId}
            expandedTools={settings.expandedTools}
            onCopyMessage={copyMessage}
            onRegenerate={regenerateLastResponse}
          />
          <ChatComposer
            value={input}
            disabled={isStreaming}
            isStreaming={isStreaming}
            commandScope={settings.commandScope}
            workingDirectory={settings.workingDirectory}
            onChange={setInput}
            onCommandScopeChange={(commandScope) => updateSettings({ ...settings, commandScope })}
            onWorkingDirectoryChange={(workingDirectory) =>
              updateSettings({ ...settings, workingDirectory })
            }
            onSubmit={sendMessage}
            onStop={stopStreaming}
          />
        </div>

        {/* Right panels — xl+ */}
        <aside className="hidden min-h-0 overflow-y-auto pr-1 scrollbar-thin xl:flex xl:flex-col xl:gap-3">
          <ApprovalPanel
            approvals={pendingApprovals}
            onApprove={approveRequest}
            onReject={rejectApprovalRequest}
          />
          <MemoryPanel
            sessionId={sessionId || "loading"}
            status={memoryStatus}
            contextPact={contextPact}
            memoryProposals={memoryProposals}
            compactionRuns={compactionRuns}
            onConfirmMemory={confirmMemory}
            onCompact={compactCurrentSession}
          />
          <SkillPanel
            skills={skills}
            proposals={skillProposals}
            onApplyProposal={applySkillProposal}
            onRejectProposal={rejectSkillProposal}
          />
          <ReasoningPanel steps={steps} showGraph={settings.showRunGraph} />
          <SettingsPanel settings={settings} onChange={updateSettings} />
        </aside>

        {/* Right panels — below xl */}
        <div className="hidden max-h-[42dvh] min-h-0 gap-3 overflow-y-auto pr-1 scrollbar-thin lg:col-span-2 lg:grid xl:hidden">
          <ApprovalPanel
            approvals={pendingApprovals}
            onApprove={approveRequest}
            onReject={rejectApprovalRequest}
          />
          <MemoryPanel
            sessionId={sessionId || "loading"}
            status={memoryStatus}
            contextPact={contextPact}
            memoryProposals={memoryProposals}
            compactionRuns={compactionRuns}
            onConfirmMemory={confirmMemory}
            onCompact={compactCurrentSession}
          />
          <SkillPanel
            skills={skills}
            proposals={skillProposals}
            onApplyProposal={applySkillProposal}
            onRejectProposal={rejectSkillProposal}
          />
          <ReasoningPanel steps={steps} showGraph={settings.showRunGraph} />
          <SettingsPanel settings={settings} onChange={updateSettings} />
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────── */
/*  Mobile header                              */
/* ─────────────────────────────────────────── */

function SessionMobileHeader({
  sessionId,
  title,
  isStreaming,
  onNewSession,
  onOpenSessions,
  onOpenInspector,
}: {
  sessionId: string;
  title?: string;
  isStreaming: boolean;
  onNewSession: () => void;
  onOpenSessions: () => void;
  onOpenInspector: () => void;
}) {
  return (
    <div className="z-30 flex h-[calc(3.5rem+env(safe-area-inset-top))] flex-shrink-0 items-end justify-between border-b border-slate-950/[0.06] bg-slate-50/88 px-3 pb-2.5 pt-[env(safe-area-inset-top)] backdrop-blur-2xl dark:border-white/[0.07] dark:bg-slate-950/82 lg:hidden">
      <button
        type="button"
        onClick={onOpenSessions}
        className="flex h-10 w-10 items-center justify-center rounded-full text-slate-700 transition active:scale-95 active:bg-slate-950/[0.06] focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/35 dark:text-slate-200 dark:active:bg-white/[0.08]"
        aria-label="打开对话列表"
      >
        <Menu className="h-5 w-5" strokeWidth={2.2} />
      </button>

      <div className="min-w-0 flex-1 px-2 text-center">
        <p className="truncate text-[15px] font-semibold tracking-tight">
          {title || "Tommy"}
        </p>
        <p className="mx-auto mt-0.5 max-w-[12rem] truncate text-[11px] leading-tight text-slate-400 dark:text-slate-500">
          {isStreaming ? "正在回答…" : shortSessionLabel(sessionId)}
        </p>
      </div>

      <div className="flex items-center gap-0.5">
        <button
          type="button"
          onClick={onOpenInspector}
          className="flex h-10 w-10 items-center justify-center rounded-full text-slate-700 transition active:scale-95 active:bg-slate-950/[0.06] focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/35 dark:text-slate-200 dark:active:bg-white/[0.08]"
          aria-label="打开状态和设置"
        >
          <SlidersHorizontal className="h-5 w-5" strokeWidth={2.1} />
        </button>
        <button
          type="button"
          onClick={onNewSession}
          disabled={isStreaming}
          className="flex h-10 w-10 items-center justify-center rounded-full text-slate-700 transition active:scale-95 active:bg-slate-950/[0.06] disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/35 dark:text-slate-200 dark:active:bg-white/[0.08]"
          aria-label="新建对话"
        >
          <Plus className="h-5 w-5" strokeWidth={2.2} />
        </button>
      </div>
    </div>
  );
}

function MobileInspectorSheet({
  open,
  sessionId,
  memoryStatus,
  contextPact,
  memoryProposals,
  compactionRuns,
  skills,
  skillProposals,
  pendingApprovals,
  steps,
  settings,
  onApproveRequest,
  onRejectApprovalRequest,
  onConfirmMemory,
  onCompact,
  onApplySkillProposal,
  onRejectSkillProposal,
  onSettingsChange,
  onClose,
}: {
  open: boolean;
  sessionId: string;
  memoryStatus: string;
  contextPact: ContextPactView;
  memoryProposals: MemoryProposalView[];
  compactionRuns: CompactionRunView[];
  skills: SkillSummaryView[];
  skillProposals: SkillProposalView[];
  pendingApprovals: ApprovalRequestView[];
  steps: RunStep[];
  settings: AgentSettings;
  onApproveRequest: (approvalId: string) => void;
  onRejectApprovalRequest: (approvalId: string) => void;
  onConfirmMemory: (memoryId: string) => void;
  onCompact: () => void;
  onApplySkillProposal: (proposalId: string) => void;
  onRejectSkillProposal: (proposalId: string) => void;
  onSettingsChange: (settings: AgentSettings) => void;
  onClose: () => void;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <button
        type="button"
        className="absolute inset-0 bg-slate-950/35 backdrop-blur-sm dark:bg-black/50"
        onClick={onClose}
        aria-label="关闭状态和设置"
      />
      <section className="absolute inset-x-5 bottom-3 mx-auto max-h-[82dvh] max-w-[24rem] overflow-y-auto rounded-[1.75rem] bg-slate-50 px-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] pt-3 shadow-[0_24px_70px_-30px_rgb(15_23_42/0.62)] dark:bg-slate-950">
        <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-slate-300/80 dark:bg-slate-700" />
        <div className="mb-3 flex items-center justify-between px-1">
          <div>
            <p className="text-[17px] font-semibold tracking-tight">状态和设置</p>
            <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
              当前对话的运行、记忆与模型配置
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-9 w-9 items-center justify-center rounded-full text-slate-500 transition active:scale-95 active:bg-slate-950/[0.06] focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/35 dark:text-slate-300 dark:active:bg-white/[0.08]"
            aria-label="关闭"
          >
            <X className="h-5 w-5" strokeWidth={2.2} />
          </button>
        </div>

        <div className="space-y-3">
          <ApprovalPanel
            approvals={pendingApprovals}
            onApprove={onApproveRequest}
            onReject={onRejectApprovalRequest}
          />
          <MemoryPanel
            sessionId={sessionId || "loading"}
            status={memoryStatus}
            contextPact={contextPact}
            memoryProposals={memoryProposals}
            compactionRuns={compactionRuns}
            onConfirmMemory={onConfirmMemory}
            onCompact={onCompact}
          />
          <SkillPanel
            skills={skills}
            proposals={skillProposals}
            onApplyProposal={onApplySkillProposal}
            onRejectProposal={onRejectSkillProposal}
          />
          <ReasoningPanel steps={steps} showGraph={settings.showRunGraph} />
          <SettingsPanel settings={settings} onChange={onSettingsChange} />
        </div>
      </section>
    </div>
  );
}

function MobileSessionDrawer({
  open,
  sessionId,
  sessions,
  isStreaming,
  onClose,
  onNewSession,
  onSelectSession,
  onDeleteSession,
}: {
  open: boolean;
  sessionId: string;
  sessions: SessionListItem[];
  isStreaming: boolean;
  onClose: () => void;
  onNewSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <button
        type="button"
        className="absolute inset-0 bg-slate-950/30 backdrop-blur-sm dark:bg-black/45"
        onClick={onClose}
        aria-label="关闭对话列表"
      />

      <aside className="relative flex h-full w-[86vw] max-w-[22rem] flex-col bg-white shadow-[18px_0_60px_-28px_rgb(15_23_42/0.45)] dark:bg-slate-950">
        <div className="flex items-center justify-between border-b border-slate-950/[0.06] px-4 pb-3 pt-[calc(env(safe-area-inset-top)+1rem)] dark:border-white/[0.07]">
          <div>
            <p className="text-[17px] font-semibold tracking-tight">对话</p>
            <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
              {isStreaming ? "Tommy 正在处理" : "选择或开始新对话"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-9 w-9 items-center justify-center rounded-full text-slate-500 transition active:scale-95 active:bg-slate-950/[0.06] focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/35 dark:text-slate-300 dark:active:bg-white/[0.08]"
            aria-label="关闭"
          >
            <X className="h-5 w-5" strokeWidth={2.2} />
          </button>
        </div>

        <div className="border-b border-slate-950/[0.06] p-4 dark:border-white/[0.07]">
          <button
            type="button"
            onClick={() => {
              onNewSession();
              onClose();
            }}
            disabled={isStreaming}
            className="flex min-h-11 w-full items-center justify-center gap-2 rounded-2xl bg-slate-950 px-4 py-3 text-[15px] font-medium text-white transition active:scale-[0.98] disabled:opacity-45 dark:bg-slate-700 dark:text-slate-50 dark:active:bg-slate-600"
          >
            <Plus className="h-4 w-4" strokeWidth={2.4} />
            新对话
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 scrollbar-thin">
          {sessions.length === 0 ? (
            <div className="rounded-2xl bg-slate-950/[0.04] px-4 py-3 text-sm text-slate-400 dark:bg-white/[0.05]">
              还没有对话
            </div>
          ) : (
            <div className="space-y-1">
              {sessions.map((session) => (
                <div
                  key={session.id}
                  className={`group flex items-center gap-1 rounded-2xl transition-colors ${
                    session.id === sessionId
                      ? "bg-slate-950/[0.07] dark:bg-white/[0.09]"
                      : "active:bg-slate-950/[0.05] dark:active:bg-white/[0.07]"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => {
                      onSelectSession(session.id);
                      onClose();
                    }}
                    className="min-h-[4.25rem] min-w-0 flex-1 px-3.5 py-2.5 text-left"
                  >
                    <p className="truncate text-[14px] font-medium text-slate-800 dark:text-slate-100">
                      {session.title}
                    </p>
                    <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-slate-500 dark:text-slate-500">
                      {session.preview || shortSessionLabel(session.id)}
                    </p>
                  </button>
                  <button
                    type="button"
                    disabled={isStreaming}
                    onClick={() => onDeleteSession(session.id)}
                    className="mr-2 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full text-slate-300 transition active:bg-red-500/10 active:text-red-500 disabled:opacity-40 dark:text-slate-600"
                    aria-label={`删除对话：${session.title}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

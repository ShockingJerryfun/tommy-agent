"use client";

import {
  type EventSourceMessage,
  fetchEventSource,
} from "@microsoft/fetch-event-source";
import {
  Archive,
  Download,
  FileJson,
  Link2,
  Menu,
  MoreHorizontal,
  Pencil,
  Pin,
  Plus,
  Search,
  Settings2,
  SlidersHorizontal,
  Trash2,
  X,
} from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import { copyToClipboard } from "../lib/clipboard";
import { useI18n } from "../lib/i18n";
import {
  classifyStreamError,
  StreamHttpError,
  type StreamErrorInfo,
} from "../lib/streamErrors";
import { sanitizeSearchSnippet } from "../lib/snippetSanitize";
import { type ApprovalRequestView, ApprovalPanel } from "./approval-panel";
import { ChatComposer } from "./chat-composer";
import { LanguageToggle } from "./language-toggle";
import {
  type ChatMessage,
  type ChatMessagePart,
  type ComposerAttachment,
  MessageStream,
} from "./message-stream";
import {
  type CompactionRunView,
  type ContextPactView,
  type MemoryProposalView,
  MemoryPanel,
} from "./memory-panel";
import { type RunStep, ReasoningPanel } from "./reasoning-panel";
import { type AgentSettings, SettingsPanel } from "./settings-panel";
import {
  type SearchResultItem,
  type SessionListItem,
  SessionSidebar,
  shortSessionLabel,
} from "./session-sidebar";
import {
  type SkillProposalView,
  type SkillSummaryView,
  SkillPanel,
} from "./skill-panel";
import { useToast } from "./toast-provider";
import type { ToolCallView } from "./tool-call-card";

type AgentEvent = {
  type: string;
  data: Record<string, unknown>;
};

const API_BASE_OVERRIDE = process.env.NEXT_PUBLIC_AGENT_API_URL ?? "";
const STREAM_API_BASE_OVERRIDE =
  process.env.NEXT_PUBLIC_AGENT_STREAM_API_URL ?? API_BASE_OVERRIDE;
const SESSION_ID_KEY = "tommy.session_id";
const SETTINGS_KEY = "tommy.settings";

const DEFAULT_SETTINGS: AgentSettings = {
  model: "deepseek-v4-pro",
  responseStyle: "balanced",
  temperature: 0.2,
  thinkingMode: true,
  thinkingEffort: "high",
  theme: "system",
  density: "comfortable",
  showRunGraph: true,
  expandedTools: false,
  commandScope: "unrestricted",
  workingDirectory: "",
  userAvatarUrl: "",
  tommyAvatarUrl: "",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isResponseStyle(value: unknown): value is AgentSettings["responseStyle"] {
  return value === "balanced" || value === "concise" || value === "detailed";
}

function isThinkingEffort(value: unknown): value is AgentSettings["thinkingEffort"] {
  return value === "high" || value === "max";
}

function isTheme(value: unknown): value is AgentSettings["theme"] {
  return value === "system" || value === "light" || value === "dark";
}

function isDensity(value: unknown): value is AgentSettings["density"] {
  return value === "compact" || value === "comfortable";
}

function parseStoredSettings(value: unknown): Partial<AgentSettings> {
  if (!isRecord(value)) return {};
  const settings: Partial<AgentSettings> = {};
  if (typeof value.model === "string") settings.model = value.model;
  if (isResponseStyle(value.responseStyle)) settings.responseStyle = value.responseStyle;
  if (typeof value.temperature === "number") settings.temperature = value.temperature;
  if (typeof value.thinkingMode === "boolean") settings.thinkingMode = value.thinkingMode;
  if (isThinkingEffort(value.thinkingEffort)) settings.thinkingEffort = value.thinkingEffort;
  if (isTheme(value.theme)) settings.theme = value.theme;
  if (isDensity(value.density)) settings.density = value.density;
  if (typeof value.showRunGraph === "boolean") settings.showRunGraph = value.showRunGraph;
  if (typeof value.expandedTools === "boolean") settings.expandedTools = value.expandedTools;
  if (typeof value.userAvatarUrl === "string") settings.userAvatarUrl = value.userAvatarUrl;
  if (typeof value.tommyAvatarUrl === "string") settings.tommyAvatarUrl = value.tommyAvatarUrl;
  return settings;
}

function loadSettings(): AgentSettings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const stored = parseStoredSettings(JSON.parse(raw));
    return {
      ...DEFAULT_SETTINGS,
      ...stored,
      commandScope: "unrestricted",
      workingDirectory: "",
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function saveSettings(settings: AgentSettings) {
  window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function runtimeSettings(settings: AgentSettings) {
  const { userAvatarUrl: _userAvatarUrl, tommyAvatarUrl: _tommyAvatarUrl, ...runtime } = settings;
  return runtime;
}

function resolveApiBase() {
  if (API_BASE_OVERRIDE) return API_BASE_OVERRIDE.replace(/\/$/, "");
  if (typeof window !== "undefined") {
    return `${window.location.origin}/agent-api`;
  }
  return "/agent-api";
}

function resolveStreamApiBase() {
  if (STREAM_API_BASE_OVERRIDE)
    return STREAM_API_BASE_OVERRIDE.replace(/\/$/, "");
  return resolveApiBase();
}

function createClientId(prefix = "id") {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (typeof randomUUID === "function") {
    return `${prefix}-${randomUUID.call(globalThis.crypto)}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function createIdempotencyKey() {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (typeof randomUUID === "function") {
    return randomUUID.call(globalThis.crypto);
  }
  return createClientId("idem");
}

function applyTheme(theme: AgentSettings["theme"]) {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const dark = theme === "dark" || (theme === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

function applyDensity(density: AgentSettings["density"]) {
  document.documentElement.dataset.density = density;
}

function readableNodeUpdate(data: Record<string, unknown>) {
  const node = typeof data.node === "string" ? data.node : "";
  if (node) return readableGraphNode(node);
  const updates = Array.isArray(data.updates) ? data.updates.map(String) : [];
  if (updates.length === 0) return "状态已更新";
  return updates.map(readableGraphNode).join(" · ");
}

function readableGraphNode(node: string) {
  const labels: Record<string, string> = {
    pre_run: "初始化运行预算",
    planner: "规划执行步骤",
    agent: "模型开始生成",
    action: "执行工具调用",
    critic: "检查回答质量",
    reflector: "整理运行反馈",
  };
  return labels[node] ?? `运行节点：${node}`;
}

function nodeStepKey(data: Record<string, unknown>) {
  const node = typeof data.node === "string" ? data.node : "";
  if (node) return node;
  const updates = Array.isArray(data.updates) ? data.updates.map(String) : [];
  return updates.join("-");
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
  if (step.type === "agent") {
    const key = step.payload?.thinking_key;
    return key ? `agent-${String(key)}` : "agent";
  }
  if (step.type === "model") {
    return "model";
  }
  if (step.type === "verification") {
    return "verification";
  }
  return step.type;
}

function appendTextPart(
  parts: ChatMessagePart[] | undefined,
  content: string,
): ChatMessagePart[] {
  const next = [...(parts ?? [])];
  const last = next[next.length - 1];
  if (last?.type === "text") {
    next[next.length - 1] = { ...last, content: `${last.content}${content}` };
  } else {
    next.push({ id: createClientId("text"), type: "text", content });
  }
  return next;
}

function appendReasoningPart(
  parts: ChatMessagePart[] | undefined,
  content: string,
): ChatMessagePart[] {
  const next = [...(parts ?? [])];
  const last = next[next.length - 1];
  if (last?.type === "reasoning") {
    next[next.length - 1] = { ...last, content: `${last.content}${content}` };
  } else {
    next.push({ id: createClientId("reasoning"), type: "reasoning", content });
  }
  return next;
}

function upsertToolPart(
  parts: ChatMessagePart[] | undefined,
  tool: ToolCallView,
): ChatMessagePart[] {
  const next = [...(parts ?? [])];
  const index = next.findIndex(
    (part) => part.type === "tool" && part.tool.id === tool.id,
  );
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

function approvalToolId(approval: ApprovalRequestView) {
  return approval.tool_call_id || approval.id;
}

function resolveToolStatus(status: unknown): ToolCallView["status"] {
  const value = String(status ?? "ok");
  if (value === "pending_approval") return "pending_approval";
  return value === "error" ? "error" : "done";
}

function formatToolSummary(tool: ToolCallView) {
  return `[${tool.name}] ${tool.summary ?? tool.status}`;
}

function buildMessageCopyText(message: ChatMessage) {
  const parts = message.parts ?? [];
  const reasoningParts: string[] = [];
  const textParts: string[] = [];
  for (const part of parts) {
    if (part.type === "reasoning" && part.content.trim()) {
      reasoningParts.push(part.content.trim());
    }
    if (part.type === "text" && part.content.trim()) {
      textParts.push(part.content.trim());
    }
  }
  const reasoningText = reasoningParts.join("\n\n");
  const contentText =
    textParts.length > 0 ? textParts.join("\n\n") : message.content.trim();
  const tools = new Map<string, ToolCallView>();
  for (const part of parts) {
    if (part.type === "tool") {
      tools.set(part.tool.id, part.tool);
    }
  }
  for (const tool of message.tools ?? []) {
    tools.set(tool.id, tool);
  }
  const toolText = Array.from(tools.values()).map(formatToolSummary).join("\n");
  return [reasoningText, contentText, toolText].filter(Boolean).join("\n\n");
}

type ApiSessionListItem = {
  id: string;
  title: string;
  preview: string;
  pinned: boolean;
  archived: boolean;
  updated_at: string;
};

function isApiSessionListItem(value: unknown): value is ApiSessionListItem {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.title === "string" &&
    typeof value.preview === "string" &&
    typeof value.pinned === "boolean" &&
    typeof value.archived === "boolean" &&
    typeof value.updated_at === "string"
  );
}

type ApiMessage = {
  id: string;
  role: ChatMessage["role"];
  content: string;
  metadata?: Record<string, unknown>;
  created_at: string;
  run_summary?: ApiRunSummary | null;
};

function isChatMessageRole(value: unknown): value is ChatMessage["role"] {
  return value === "user" || value === "assistant" || value === "system";
}

function isApiMessage(value: unknown): value is ApiMessage {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    isChatMessageRole(value.role) &&
    typeof value.content === "string" &&
    typeof value.created_at === "string" &&
    (value.metadata === undefined || isRecord(value.metadata))
  );
}

type ApiAttachmentRef = {
  id: string;
  mime: string;
  byte_size: number;
  name: string;
  thumbnail_url?: string;
};

function isApiAttachmentRef(value: unknown): value is ApiAttachmentRef {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.mime === "string" &&
    typeof value.byte_size === "number" &&
    typeof value.name === "string" &&
    (value.thumbnail_url === undefined || typeof value.thumbnail_url === "string")
  );
}

type ApiRunSummary = {
  run_id: string;
  model?: string | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
  latency_ms?: number | null;
  finish_reason?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

type ApiSearchResult = {
  message_id: string;
  session_id: string;
  session_title: string;
  role: string;
  position: number;
  created_at: string;
  snippet: string;
};

function isApiSearchResult(value: unknown): value is ApiSearchResult {
  return (
    isRecord(value) &&
    typeof value.message_id === "string" &&
    typeof value.session_id === "string" &&
    typeof value.session_title === "string" &&
    typeof value.role === "string" &&
    typeof value.position === "number" &&
    typeof value.created_at === "string" &&
    typeof value.snippet === "string"
  );
}

type ApiRunEvent = {
  id: string;
  run_id?: string;
  type: string;
  label: string;
  status: RunStep["status"];
  payload?: Record<string, unknown>;
  sequence?: number;
  created_at: string;
};

function isRunStepStatus(value: unknown): value is RunStep["status"] {
  return value === "running" || value === "done" || value === "error";
}

function isApiRunEvent(value: unknown): value is ApiRunEvent {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.type === "string" &&
    typeof value.label === "string" &&
    isRunStepStatus(value.status) &&
    typeof value.created_at === "string" &&
    (value.run_id === undefined || typeof value.run_id === "string") &&
    (value.sequence === undefined || typeof value.sequence === "number") &&
    (value.payload === undefined || isRecord(value.payload))
  );
}

type ApiRun = {
  id: string;
  session_id: string;
  agent_id: string;
  status:
    | "queued"
    | "running"
    | "completed"
    | "cancelled"
    | "interrupted"
    | "error";
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

function isApiRun(value: unknown): value is ApiRun {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.session_id === "string" &&
    typeof value.agent_id === "string" &&
    typeof value.status === "string" &&
    typeof value.input === "string" &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

type ApiRunStartResponse = ApiRun | { run_id: string; status: string };

function runResponseId(run: ApiRunStartResponse) {
  return "id" in run ? run.id : run.run_id;
}

type ApiToolCall = {
  id: string;
  run_id: string;
  name: string;
  status: ToolCallView["status"];
  args?: Record<string, unknown>;
  result?: string;
};

function isToolCallStatus(value: unknown): value is ToolCallView["status"] {
  return (
    value === "running" ||
    value === "pending_approval" ||
    value === "done" ||
    value === "error"
  );
}

function isApiToolCall(value: unknown): value is ApiToolCall {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.run_id === "string" &&
    typeof value.name === "string" &&
    isToolCallStatus(value.status) &&
    (value.args === undefined || isRecord(value.args)) &&
    (value.result === undefined || typeof value.result === "string")
  );
}

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

function isApiSessionDetail(value: unknown): value is ApiSessionDetail {
  return (
    isRecord(value) &&
    Array.isArray(value.messages) &&
    value.messages.every(isApiMessage) &&
    Array.isArray(value.run_events) &&
    value.run_events.every(isApiRunEvent) &&
    Array.isArray(value.tool_calls) &&
    value.tool_calls.every(isApiToolCall) &&
    (value.latest_run === undefined || value.latest_run === null || isApiRun(value.latest_run)) &&
    (value.active_run === undefined || value.active_run === null || isApiRun(value.active_run))
  );
}

function sessionsFromPayload(value: unknown): ApiSessionListItem[] {
  if (!isRecord(value) || !Array.isArray(value.sessions)) return [];
  return value.sessions.filter(isApiSessionListItem);
}

function sessionIdFromPayload(value: unknown): string {
  if (isRecord(value) && typeof value.session_id === "string") return value.session_id;
  throw new Error("Session response returned an invalid payload");
}

function searchResultsFromPayload(value: unknown): ApiSearchResult[] {
  if (!isRecord(value) || !Array.isArray(value.results)) return [];
  return value.results.filter(isApiSearchResult);
}

function isToolCallView(value: unknown): value is ToolCallView {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    (value.status === "running" ||
      value.status === "pending_approval" ||
      value.status === "done" ||
      value.status === "error")
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
    if (part.type === "reasoning" && typeof part.content === "string") {
      parts.push({
        id: typeof part.id === "string" ? part.id : createClientId("reasoning"),
        type: "reasoning",
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

function attachmentUrl(pathOrUrl: string, id: string) {
  const fallback = `/api/attachments/${id}`;
  const value = pathOrUrl || fallback;
  if (/^https?:\/\//.test(value)) return value;
  return `${resolveApiBase()}${value.startsWith("/") ? value : `/${value}`}`;
}

function parseStoredAttachments(
  value: unknown,
): ComposerAttachment[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const attachments: ComposerAttachment[] = [];
  for (const item of value) {
    if (!isApiAttachmentRef(item)) continue;
    attachments.push({
      id: item.id,
      name: item.name,
      mime: item.mime,
      byteSize: item.byte_size,
      thumbnailUrl: attachmentUrl(
        item.thumbnail_url ?? "",
        item.id,
      ),
    });
  }
  return attachments.length > 0 ? attachments : undefined;
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
    throw new StreamHttpError(response.status, await response.text(), "API");
  }
  const payload: unknown = await response.json();
  // The generic API client is the app's dynamic JSON boundary; call sites
  // should validate payload shape before relying on untrusted fields.
  return payload as T;
}

function formatStreamError(error: unknown) {
  return classifyStreamError(error).message;
}

async function assertEventStream(response: Response) {
  const contentType = response.headers.get("content-type") ?? "";
  if (response.ok && contentType.includes("text/event-stream")) return;

  const body = await response
    .clone()
    .text()
    .catch(() => "");
  const detail =
    body.trim() || response.statusText || "Unexpected stream response";
  throw new StreamHttpError(response.status, detail);
}

function parseStreamEvent(event: EventSourceMessage): AgentEvent | null {
  if (!event.data) return null;
  try {
    const parsed: unknown = JSON.parse(event.data);
    if (isRecord(parsed) && typeof parsed.type === "string" && isRecord(parsed.data)) {
      return { type: parsed.type, data: parsed.data };
    }
    if (isRecord(parsed) && typeof event.event === "string" && event.event) {
      return { type: event.event, data: parsed };
    }
    throw new Error("event payload is missing type or data");
  } catch {
    throw new Error(
      `Invalid stream event payload: ${event.data.slice(0, 200)}`,
    );
  }
}

function toSessionListItem(item: ApiSessionListItem): SessionListItem {
  return {
    id: item.id,
    title: item.title,
    preview: item.preview,
    pinned: Boolean(item.pinned),
    archived: Boolean(item.archived),
    updatedAt: Date.parse(item.updated_at) || Date.now(),
  };
}

function toRunStep(event: ApiRunEvent): RunStep {
  const type =
    event.type === "verification_start" || event.type === "verification_end"
      ? "verification"
      : event.type === "model_start" ||
          event.type === "model_end" ||
          event.type === "model_error"
        ? "model"
        : (event.type as RunStep["type"]);
  return {
    id: event.id,
    type,
    label: event.label,
    status: event.status,
    at: Date.parse(event.created_at) || Date.now(),
    payload: event.payload,
  };
}

function maxRunEventSequence(events: ApiRunEvent[], runId: string) {
  return events.reduce((max, event) => {
    if (event.run_id && event.run_id !== runId) return max;
    return typeof event.sequence === "number"
      ? Math.max(max, event.sequence)
      : max;
  }, -1);
}

function attachTools(
  messages: ApiMessage[],
  tools: ApiToolCall[],
): ChatMessage[] {
  const groupedTools = new Map<string, ToolCallView[]>();
  for (const tool of tools) {
    const items = groupedTools.get(tool.run_id) ?? [];
    items.push({
      id: tool.id,
      name: tool.name,
      status: tool.status,
      summary:
        tool.result || (tool.args ? JSON.stringify(tool.args) : tool.status),
    });
    groupedTools.set(tool.run_id, items);
  }

  return messages.map((message) => {
    const runId = String(message.metadata?.run_id ?? "");
    const toolsForMessage =
      message.role === "assistant" ? groupedTools.get(runId) : undefined;
    const storedParts = parseStoredParts(message.metadata?.parts);
    const attachments = parseStoredAttachments(message.metadata?.attachments);
    const fallbackParts: ChatMessagePart[] = [
      ...(message.content
        ? [
            {
              id: `${message.id}-text`,
              type: "text" as const,
              content: message.content,
            },
          ]
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
      createdAt: message.created_at,
      tools: toolsForMessage,
      parts:
        storedParts ?? (fallbackParts.length > 0 ? fallbackParts : undefined),
      attachments,
      runId: runId || undefined,
      runSummary: message.run_summary ?? undefined,
    };
  });
}

export function AgentShell() {
  const { toast } = useToast();
  const [sessionId, setSessionId] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pendingAttachments, setPendingAttachments] = useState<
    ComposerAttachment[]
  >([]);
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [steps, setSteps] = useState<RunStep[]>([]);
  const [settings, setSettings] = useState<AgentSettings>(DEFAULT_SETTINGS);
  const [memoryStatus, setMemoryStatus] = useState("Ready");
  const [contextPact, setContextPact] = useState<ContextPactView>({});
  const [memoryProposals, setMemoryProposals] = useState<MemoryProposalView[]>(
    [],
  );
  const [compactionRuns, setCompactionRuns] = useState<CompactionRunView[]>([]);
  const [skills, setSkills] = useState<SkillSummaryView[]>([]);
  const [skillProposals, setSkillProposals] = useState<SkillProposalView[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<
    ApprovalRequestView[]
  >([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [mobileSessionsOpen, setMobileSessionsOpen] = useState(false);
  const [mobileInspectorOpen, setMobileInspectorOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const subscribeAbortRef = useRef<AbortController | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const stopRequestedRef = useRef(false);
  const currentRunIdRef = useRef<string | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const stepsRef = useRef<RunStep[]>([]);
  const pendingAssistantTokensRef = useRef("");
  const tokenFlushFrameRef = useRef<number | null>(null);
  const tokenFlushTimeoutRef = useRef<number | null>(null);
  const tokenLastFlushAtRef = useRef(0);
  const lastRunSequenceRef = useRef<Map<string, number>>(new Map());
  const pendingApprovalsRef = useRef<ApprovalRequestView[]>([]);
  const pendingReasoningRef = useRef("");
  const reasoningFlushFrameRef = useRef<number | null>(null);
  const reasoningFlushTimeoutRef = useRef<number | null>(null);
  const [, setCurrentRunId] = useState<string | null>(null);

  useEffect(() => {
    pendingApprovalsRef.current = pendingApprovals;
  }, [pendingApprovals]);

  useEffect(() => {
    let cancelled = false;
    const initialSettings = loadSettings();
    setSettings(initialSettings);
    applyTheme(initialSettings.theme);
    applyDensity(initialSettings.density ?? "comfortable");

    async function boot() {
      try {
        const nextSessions = await fetchSessions();
        let nextSessionId = window.localStorage.getItem(SESSION_ID_KEY) ?? "";
        if (
          !nextSessionId ||
          !nextSessions.some((session) => session.id === nextSessionId)
        ) {
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
      subscribeAbortRef.current?.abort();
      subscribeAbortRef.current = null;
      streamAbortRef.current?.abort();
      streamAbortRef.current = null;
      cancelPendingAssistantTokenFlush();
      resetReasoning();
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

  useEffect(() => {
    applyDensity(settings.density);
  }, [settings.density]);

  useEffect(() => {
    function isEditableTarget(target: EventTarget | null) {
      return (
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        (target instanceof HTMLElement && target.isContentEditable)
      );
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && isStreaming) {
        event.preventDefault();
        void stopStreaming();
        return;
      }

      if (
        event.key !== "ArrowUp" ||
        isEditableTarget(event.target) ||
        input.trim().length > 0
      ) {
        return;
      }

      const lastUser = [...messagesRef.current]
        .reverse()
        .find((message) => message.role === "user" && message.content.trim());
      if (!lastUser) return;

      event.preventDefault();
      setInput(lastUser.content);
      window.dispatchEvent(
        new CustomEvent("edit-last", {
          detail: { messageId: lastUser.id, content: lastUser.content },
        }),
      );
      window.requestAnimationFrame(() => {
        const textarea = document.getElementById(
          "agent-message",
        ) as HTMLTextAreaElement | null;
        textarea?.focus();
        textarea?.setSelectionRange(
          lastUser.content.length,
          lastUser.content.length,
        );
      });
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [input, isStreaming]);

  async function fetchSessions() {
    const result = await apiJson<unknown>("/api/sessions");
    return sessionsFromPayload(result).map(toSessionListItem);
  }

  async function createBackendSession() {
    const result = await apiJson<unknown>("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ title: "新对话" }),
    });
    return sessionIdFromPayload(result);
  }

  async function refreshSessions() {
    const nextSessions = await fetchSessions();
    setSessions(nextSessions);
    return nextSessions;
  }

  async function uploadAttachment(file: File): Promise<ComposerAttachment> {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("file", file);
    const response = await fetch(`${resolveApiBase()}/api/attachments`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      throw new StreamHttpError(response.status, await response.text(), "API");
    }
    const payload: unknown = await response.json();
    if (!isApiAttachmentRef(payload)) {
      throw new Error("Attachment upload returned an invalid payload");
    }
    return {
      id: payload.id,
      name: payload.name,
      mime: payload.mime,
      byteSize: payload.byte_size,
      thumbnailUrl: attachmentUrl(payload.thumbnail_url ?? "", payload.id),
    };
  }

  async function addAttachments(files: File[]) {
    if (!sessionId || files.length === 0) return;
    const pending = files.map((file) => ({
      id: createClientId("upload"),
      name: file.name,
      mime: file.type || "application/octet-stream",
      byteSize: file.size,
      thumbnailUrl: file.type.startsWith("image/")
        ? URL.createObjectURL(file)
        : "",
      uploading: true,
    }));
    setPendingAttachments((current) => [...pending, ...current]);
    const uploaded: ComposerAttachment[] = [];
    const failedIds = new Set<string>();
    await Promise.all(
      pending.map(async (placeholder, index) => {
        try {
          uploaded[index] = await uploadAttachment(files[index]);
          if (placeholder.thumbnailUrl.startsWith("blob:")) {
            URL.revokeObjectURL(placeholder.thumbnailUrl);
          }
        } catch (error) {
          failedIds.add(placeholder.id);
          if (placeholder.thumbnailUrl.startsWith("blob:")) {
            URL.revokeObjectURL(placeholder.thumbnailUrl);
          }
          toast(`Attachment upload failed: ${formatStreamError(error)}`, {
            tone: "error",
          });
        }
      }),
    );
    setPendingAttachments((current) =>
      current
        .filter((attachment) => !failedIds.has(attachment.id))
        .map((attachment) => {
          const index = pending.findIndex(
            (placeholder) => placeholder.id === attachment.id,
          );
          return index >= 0 && uploaded[index] ? uploaded[index] : attachment;
        }),
    );
    const successCount = uploaded.filter((item): item is ComposerAttachment =>
      Boolean(item),
    ).length;
    if (successCount > 0) {
      toast(
        `${successCount} attachment${successCount === 1 ? "" : "s"} uploaded`,
        {
          tone: "success",
        },
      );
    }
  }

  function removeAttachment(id: string) {
    setPendingAttachments((current) =>
      current.filter((attachment) => attachment.id !== id),
    );
  }

  function setActiveRunId(runId: string | null) {
    currentRunIdRef.current = runId;
    setCurrentRunId(runId);
  }

  async function loadSession(nextSessionId: string) {
    subscribeAbortRef.current?.abort();
    subscribeAbortRef.current = null;
    setActiveRunId(null);
    const payload = await apiJson<unknown>(
      `/api/sessions/${nextSessionId}`,
    );
    if (!isApiSessionDetail(payload)) {
      throw new Error("Session detail response returned an invalid payload");
    }
    const detail = payload;
    const loadedMessages = attachTools(detail.messages, detail.tool_calls);
    const loadedSteps = detail.run_events.map(toRunStep);
    window.localStorage.setItem(SESSION_ID_KEY, nextSessionId);
    setSessionId(nextSessionId);
    setInput("");
    setPendingAttachments([]);
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
    if ((detail.pending_approvals ?? []).length > 0) {
      setIsStreaming(true);
      setMemoryStatus("有操作等待审批");
      return;
    }
    const activeRun = detail.active_run;
    if (activeRun && ["queued", "running"].includes(activeRun.status)) {
      const afterSequence = maxRunEventSequence(
        detail.run_events,
        activeRun.id,
      );
      setActiveRunId(activeRun.id);
      setIsStreaming(true);
      setMemoryStatus("生成中，正在重新连接");
      void subscribeRunEvents(
        activeRun.id,
        afterSequence >= 0 ? afterSequence : undefined,
      );
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
    await apiJson<{ memory: MemoryProposalView }>(
      `/api/memory/${memoryId}/confirm`,
      {
        method: "POST",
      },
    );
    setMemoryStatus("记忆已确认");
    await refreshCurrentSession();
  }

  async function compactCurrentSession() {
    if (!sessionId || isStreaming) return;
    const result = await apiJson<{
      compaction: CompactionRunView | null;
      pact: ContextPactView;
    }>(`/api/sessions/${sessionId}/compact`, {
      method: "POST",
      body: JSON.stringify({ keep_recent: 18 }),
    });
    if (result.pact) setContextPact(result.pact);
    if (result.compaction) {
      setCompactionRuns((current) => [
        result.compaction as CompactionRunView,
        ...current,
      ]);
      persistStep(createRunStep("compaction", "手动压缩完成", "done", result));
      setMemoryStatus("会话已压缩");
    }
    await refreshCurrentSession();
  }

  async function applySkillProposal(proposalId: string) {
    await apiJson<{ proposal: SkillProposalView }>(
      `/api/skills/proposals/${proposalId}/apply`,
      {
        method: "POST",
      },
    );
    setMemoryStatus("Skill 已应用");
    await refreshCurrentSession();
  }

  async function rejectSkillProposal(proposalId: string) {
    await apiJson<{ proposal: SkillProposalView }>(
      `/api/skills/proposals/${proposalId}/reject`,
      {
        method: "POST",
      },
    );
    setMemoryStatus("Skill 提案已拒绝");
    await refreshCurrentSession();
  }

  async function approveRequest(approvalId: string) {
    setPendingApprovals((current) => {
      const next = current.filter((item) => item.id !== approvalId);
      pendingApprovalsRef.current = next;
      return next;
    });
    setMemoryStatus("审批执行中…");
    try {
      const response = await apiJson<{
        approval: ApprovalRequestView;
        result?: string;
        continuation_run_id?: string;
      }>(`/api/approvals/${approvalId}/approve`, { method: "POST" });
      updateAssistantTool({
        id: approvalToolId(response.approval),
        name: response.approval.tool_name,
        status: response.approval.status === "failed" ? "error" : "done",
        summary: response.result ?? response.approval.result ?? "审批已执行",
        approval: undefined,
      });
      streamAbortRef.current?.abort();
      subscribeAbortRef.current?.abort();

      if (response.continuation_run_id) {
        setMemoryStatus("审批已执行，继续生成中…");
        void subscribeRunEvents(response.continuation_run_id);
      } else {
        setMemoryStatus("审批已执行");
        setIsStreaming(false);
        setActiveRunId(null);
        void refreshCurrentSession();
      }
    } catch (error) {
      setMemoryStatus(`审批失败: ${String(error)}`);
      await refreshCurrentSession();
    }
  }

  async function rejectApprovalRequest(approvalId: string) {
    setPendingApprovals((current) => {
      const next = current.filter((item) => item.id !== approvalId);
      pendingApprovalsRef.current = next;
      return next;
    });
    setMemoryStatus("审批已拒绝");
    try {
      const response = await apiJson<{ approval: ApprovalRequestView }>(
        `/api/approvals/${approvalId}/reject`,
        {
          method: "POST",
        },
      );
      updateAssistantTool({
        id: approvalToolId(response.approval),
        name: response.approval.tool_name,
        status: "error",
        summary: response.approval.error ?? "审批已拒绝",
        approval: undefined,
      });
      streamAbortRef.current?.abort();
      subscribeAbortRef.current?.abort();
      setIsStreaming(false);
      setActiveRunId(null);
    } catch (error) {
      setMemoryStatus(`审批失败: ${String(error)}`);
      await refreshCurrentSession();
    }
  }

  async function resetSession() {
    if (isStreaming) return;
    const next = await createBackendSession();
    const nextSessions = await refreshSessions();
    window.localStorage.setItem(SESSION_ID_KEY, next);
    setSessionId(next);
    setSessions(nextSessions);
    setInput("");
    setPendingAttachments([]);
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
    if (nextSessionId === sessionId || isStreaming) return;
    subscribeAbortRef.current?.abort();
    subscribeAbortRef.current = null;
    setIsStreaming(false);
    setActiveRunId(null);
    await loadSession(nextSessionId);
  }

  async function deleteSession(targetSessionId: string) {
    if (isStreaming) return;
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

  async function renameSession(targetSessionId: string, title: string) {
    const updated = await apiJson<ApiSessionListItem>(
      `/api/sessions/${targetSessionId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ title }),
      },
    );
    setSessions((current) =>
      current.map((session) =>
        session.id === targetSessionId ? toSessionListItem(updated) : session,
      ),
    );
  }

  async function togglePinSession(targetSessionId: string, pinned: boolean) {
    const updated = await apiJson<ApiSessionListItem>(
      `/api/sessions/${targetSessionId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ pinned }),
      },
    );
    setSessions((current) =>
      current.map((session) =>
        session.id === targetSessionId ? toSessionListItem(updated) : session,
      ),
    );
  }

  async function toggleArchiveSession(
    targetSessionId: string,
    archived: boolean,
  ) {
    const updated = await apiJson<ApiSessionListItem>(
      `/api/sessions/${targetSessionId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ archived }),
      },
    );
    setSessions((current) =>
      current.map((session) =>
        session.id === targetSessionId ? toSessionListItem(updated) : session,
      ),
    );
  }

  function exportSession(targetSessionId: string, format: "md" | "json") {
    window.open(
      `${resolveApiBase()}/api/sessions/${targetSessionId}/export?format=${format}`,
    );
  }

  async function shareSession(targetSessionId: string) {
    const result = await apiJson<{ token: string; url: string }>(
      `/api/sessions/${targetSessionId}/share`,
      { method: "POST" },
    );
    const shareUrl = new URL(result.url, window.location.origin).toString();
    const copied = await copyToClipboard(shareUrl);
    toast(copied ? "Share URL copied" : "Share URL ready", { tone: "success" });
    return shareUrl;
  }

  async function revokeShare(targetSessionId: string) {
    await apiJson<{ status: string }>(
      `/api/sessions/${targetSessionId}/share`,
      {
        method: "DELETE",
      },
    );
    toast("Share link revoked", { tone: "success" });
  }

  const searchMessages = useCallback(
    async (query: string): Promise<SearchResultItem[]> => {
      const params = new URLSearchParams({ q: query, limit: "20" });
      const result = await apiJson<unknown>(
        `/api/search?${params}`,
      );
      return searchResultsFromPayload(result).map((item) => ({
        messageId: item.message_id,
        sessionId: item.session_id,
        sessionTitle: item.session_title,
        role: item.role,
        position: item.position,
        createdAt: item.created_at,
        snippet: item.snippet,
      }));
    },
    [],
  );

  async function selectSearchResult(
    targetSessionId: string,
    messageId: string,
  ) {
    if (isStreaming) return;
    await loadSession(targetSessionId);
    window.setTimeout(() => {
      document
        .getElementById(`message-${messageId}`)
        ?.scrollIntoView({ block: "center" });
    }, 50);
  }

  function persistMessageState(
    updater: (current: ChatMessage[]) => ChatMessage[],
  ) {
    setMessages((current) => {
      const next = updater(current);
      messagesRef.current = next;
      return next;
    });
  }

  function cancelPendingAssistantTokenFlush() {
    if (tokenFlushFrameRef.current !== null) {
      window.cancelAnimationFrame(tokenFlushFrameRef.current);
      tokenFlushFrameRef.current = null;
    }
    if (tokenFlushTimeoutRef.current !== null) {
      window.clearTimeout(tokenFlushTimeoutRef.current);
      tokenFlushTimeoutRef.current = null;
    }
  }

  function annotateLastAssistant(
    updates: Partial<
      Pick<ChatMessage, "id" | "streamError" | "runId" | "idempotencyKey">
    >,
  ) {
    persistMessageState((current) => {
      const next = [...current];
      let index = next.length - 1;
      while (index >= 0 && next[index]?.role !== "assistant") {
        index -= 1;
      }
      if (index < 0) return current;
      next[index] = { ...next[index], ...updates };
      return next;
    });
  }

  function setAssistantStreamError(error: StreamErrorInfo) {
    flushPendingAssistantTokens();
    annotateLastAssistant({ streamError: error });
  }

  async function persistedAssistantMessageId(message: ChatMessage) {
    if (message.id.startsWith("msg-")) return message.id;
    if (!message.runId) return null;
    const existing = await apiJson<{ run: ApiRun }>(
      `/api/runs/${message.runId}`,
    );
    return existing.run.assistant_message_id || null;
  }

  function clearAssistantStreamError(messageId: string) {
    persistMessageState((current) =>
      current.map((message) =>
        message.id === messageId ? { ...message, streamError: null } : message,
      ),
    );
  }

  function setMessageStreamError(messageId: string, error: StreamErrorInfo) {
    flushPendingAssistantTokens();
    persistMessageState((current) =>
      current.map((message) =>
        message.id === messageId ? { ...message, streamError: error } : message,
      ),
    );
  }

  function persistStep(step: RunStep) {
    setSteps((current) => {
      const normalized =
        step.type === "done"
          ? current.map((item) =>
              item.status === "running"
                ? { ...item, status: "done" as const }
                : item,
            )
          : current;
      const key = runStepKey(step);
      const existingIndex = normalized.findIndex(
        (item) => runStepKey(item) === key,
      );
      const next =
        existingIndex >= 0
          ? normalized.map((item, index) =>
              index === existingIndex
                ? {
                    ...item,
                    ...step,
                    id: item.id,
                    at: step.at,
                    payload: {
                      ...(item.payload ?? {}),
                      ...(step.payload ?? {}),
                    },
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
      .find(
        (message) => message.role === "assistant" && message.content.trim(),
      );
    const titleSource = firstUser?.content?.replace(/\s+/g, " ").trim();
    const previewSource = (lastAssistant ?? firstUser)?.content
      ?.replace(/\s+/g, " ")
      .trim();
    const currentSession = sessions.find((session) => session.id === sessionId);

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
        pinned: currentSession?.pinned ?? false,
        archived: currentSession?.archived ?? false,
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

  function flushPendingAssistantTokens() {
    if (tokenFlushFrameRef.current !== null) {
      window.cancelAnimationFrame(tokenFlushFrameRef.current);
      tokenFlushFrameRef.current = null;
    }
    if (tokenFlushTimeoutRef.current !== null) {
      window.clearTimeout(tokenFlushTimeoutRef.current);
      tokenFlushTimeoutRef.current = null;
    }
    tokenLastFlushAtRef.current = performance.now();
    const content = pendingAssistantTokensRef.current;
    pendingAssistantTokensRef.current = "";
    if (content) {
      appendAssistantToken(content);
    }
  }

  function scheduleAssistantToken(content: string) {
    if (!content) return;
    pendingAssistantTokensRef.current += content;
    if (
      tokenFlushFrameRef.current !== null ||
      tokenFlushTimeoutRef.current !== null
    )
      return;

    const elapsed = performance.now() - tokenLastFlushAtRef.current;
    if (elapsed >= 16) {
      tokenFlushFrameRef.current = window.requestAnimationFrame(
        flushPendingAssistantTokens,
      );
      return;
    }

    tokenFlushTimeoutRef.current = window.setTimeout(() => {
      tokenFlushTimeoutRef.current = null;
      tokenFlushFrameRef.current = window.requestAnimationFrame(
        flushPendingAssistantTokens,
      );
    }, 16 - elapsed);
  }

  function appendAssistantReasoning(content: string) {
    persistMessageState((current) => {
      const last = current[current.length - 1];
      if (last?.role === "assistant") {
        return [
          ...current.slice(0, -1),
          { ...last, parts: appendReasoningPart(last.parts, content) },
        ];
      }
      return [
        ...current,
        {
          id: createClientId("message"),
          role: "assistant",
          content: "",
          parts: [
            { id: createClientId("reasoning"), type: "reasoning", content },
          ],
        },
      ];
    });
  }

  function flushPendingReasoning() {
    if (reasoningFlushTimeoutRef.current !== null) {
      window.clearTimeout(reasoningFlushTimeoutRef.current);
      reasoningFlushTimeoutRef.current = null;
    }
    const content = pendingReasoningRef.current;
    pendingReasoningRef.current = "";
    reasoningFlushFrameRef.current = null;
    if (content) {
      appendAssistantReasoning(content);
    }
  }

  function scheduleReasoningChunk(content: string) {
    if (!content) return;
    pendingReasoningRef.current += content;
    if (
      reasoningFlushFrameRef.current !== null ||
      reasoningFlushTimeoutRef.current !== null
    ) {
      return;
    }
    reasoningFlushFrameRef.current = window.requestAnimationFrame(
      flushPendingReasoning,
    );
    reasoningFlushTimeoutRef.current = window.setTimeout(
      flushPendingReasoning,
      48,
    );
  }

  function resetReasoning() {
    pendingReasoningRef.current = "";
    if (reasoningFlushFrameRef.current !== null) {
      window.cancelAnimationFrame(reasoningFlushFrameRef.current);
      reasoningFlushFrameRef.current = null;
    }
    if (reasoningFlushTimeoutRef.current !== null) {
      window.clearTimeout(reasoningFlushTimeoutRef.current);
      reasoningFlushTimeoutRef.current = null;
    }
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
          ? tools.map((item) =>
              item.id === tool.id ? { ...item, ...tool } : item,
            )
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
    const runId =
      typeof data.run_id === "string" ? data.run_id : currentRunIdRef.current;
    const sequence =
      typeof data.sequence === "number" ? data.sequence : undefined;
    if (runId && sequence !== undefined) {
      lastRunSequenceRef.current.set(runId, sequence);
    }
    if (runId) {
      const assistantMessageId =
        typeof data.assistant_message_id === "string"
          ? data.assistant_message_id
          : "";
      const lastAssistant = [...messagesRef.current]
        .reverse()
        .find((message) => message.role === "assistant");
      if (
        lastAssistant &&
        (lastAssistant.runId !== runId || assistantMessageId)
      ) {
        annotateLastAssistant({
          runId,
          ...(assistantMessageId ? { id: assistantMessageId } : {}),
        });
      }
    }

    if (payload.type === "context") {
      const sectionCount = Number(data.section_count ?? 0);
      const totalChars = Number(data.total_chars ?? 0);
      setMemoryStatus(
        `上下文已构建：${sectionCount} sections / ${totalChars} chars`,
      );
      persistStep(
        createRunStep(
          "context",
          `上下文已构建 · ${sectionCount} sections · ${totalChars} chars`,
          "done",
          data,
        ),
      );
      return;
    }

    if (payload.type === "token") {
      const hasGeneratingStep = stepsRef.current.some(
        (step) =>
          step.type === "agent" &&
          step.payload?.thinking_key === "agent" &&
          step.status === "running",
      );
      if (!hasGeneratingStep) {
        persistStep(
          createRunStep("agent", "模型开始生成", "running", {
            thinking_key: "agent",
            node: "agent",
          }),
        );
      }
      scheduleAssistantToken(String(data.content ?? ""));
      return;
    }

    if (payload.type === "reasoning") {
      scheduleReasoningChunk(String(data.content ?? ""));
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
        createRunStep(
          "tool",
          `${String(data.tool ?? "工具")} 运行中`,
          "running",
          data,
        ),
      );
      return;
    }

    if (payload.type === "tool_end") {
      const id = String(data.tool_call_id ?? data.run_id ?? "");
      const status = resolveToolStatus(data.status);
      updateAssistantTool({
        id,
        name: String(data.tool ?? "tool"),
        status,
        summary: String(data.content ?? data.output ?? ""),
      });
      persistStep(
        createRunStep(
          "tool",
          `${String(data.tool ?? "工具")} ${
            status === "pending_approval"
              ? "待审批"
              : status === "error"
                ? "失败"
                : "完成"
          }`,
          status === "error"
            ? "error"
            : status === "pending_approval"
              ? "running"
              : "done",
          data,
        ),
      );
      if (status === "done") {
        setMemoryStatus("工具已完成，等待模型继续生成…");
        persistStep(
          createRunStep("agent", "等待模型继续生成", "running", {
            thinking_key: "agent",
            node: "agent",
          }),
        );
      }
      return;
    }

    if (payload.type === "model_start") {
      setMemoryStatus("模型调用中…");
      persistStep(createRunStep("model", "模型调用中", "running", data));
      return;
    }

    if (payload.type === "model_end") {
      setMemoryStatus("模型调用完成");
      persistStep(createRunStep("model", "模型调用完成", "done", data));
      return;
    }

    if (payload.type === "model_error") {
      setMemoryStatus(`模型调用失败: ${String(data.message ?? "Unknown error")}`);
      persistStep(createRunStep("model", "模型调用失败", "error", data));
      return;
    }

    if (payload.type === "verification_start") {
      const attempt = Number(data.attempt ?? 1);
      const maxAttempts = Number(data.max_attempts ?? data.maxAttempts ?? 1);
      setMemoryStatus(`验证中：第 ${attempt}/${maxAttempts} 次`);
      persistStep(
        createRunStep("verification", "验证中", "running", {
          ...data,
          attempt,
          max_attempts: maxAttempts,
        }),
      );
      return;
    }

    if (payload.type === "verification_end") {
      const status = String(data.status ?? "skipped");
      const failed = status === "failed";
      const skipped = status === "skipped";
      const label = failed ? "验证失败" : skipped ? "验证跳过" : "验证通过";
      setMemoryStatus(
        typeof data.summary === "string" && data.summary ? data.summary : label,
      );
      persistStep(
        createRunStep("verification", label, failed ? "error" : "done", data),
      );
      return;
    }

    if (payload.type === "node_end") {
      const thinkingKey = nodeStepKey(data);
      persistStep(
        createRunStep("agent", readableNodeUpdate(data), "done", {
          ...data,
          thinking_key: thinkingKey || readableNodeUpdate(data),
        }),
      );
      return;
    }

    if (payload.type === "approval_pending") {
      const approval = data.approval;
      if (approval && typeof approval === "object") {
        const view = approval as ApprovalRequestView;
        updateAssistantTool({
          id: approvalToolId(view),
          name: view.tool_name,
          status: "pending_approval",
          summary: view.summary,
          approval: view,
        });
        setPendingApprovals((current) => {
          const next = [view, ...current.filter((item) => item.id !== view.id)];
          pendingApprovalsRef.current = next;
          return next;
        });
      }
      setMemoryStatus("有操作等待审批");
      persistStep(createRunStep("approval", "等待用户审批", "running", data));
      return;
    }

    if (payload.type === "approval_resolved") {
      const approval = data.approval;
      if (approval && typeof approval === "object") {
        const view = approval as ApprovalRequestView;
        setPendingApprovals((current) => {
          const next = current.filter((item) => item.id !== view.id);
          pendingApprovalsRef.current = next;
          return next;
        });
      }
      setMemoryStatus("审批已处理");
      persistStep(createRunStep("approval", "审批已处理", "done", data));
      if (
        pendingApprovalsRef.current.length === 0 &&
        subscribeAbortRef.current === null &&
        streamAbortRef.current === null
      ) {
        setIsStreaming(false);
      }
      return;
    }

    if (payload.type === "subagent_start") {
      persistStep(
        createRunStep(
          "subagent",
          `子 Agent ${String(data.target_agent ?? "")} 启动`,
          "running",
          data,
        ),
      );
      return;
    }

    if (payload.type === "subagent_end") {
      persistStep(
        createRunStep(
          "subagent",
          `子 Agent ${String(data.target_agent ?? "")} 完成`,
          "done",
          data,
        ),
      );
      return;
    }

    if (payload.type === "memory") {
      setMemoryStatus("记忆状态更新");
      if (data.proposal && typeof data.proposal === "object") {
        setMemoryProposals((current) => [
          data.proposal as MemoryProposalView,
          ...current.filter(
            (item) => item.id !== (data.proposal as MemoryProposalView).id,
          ),
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
          ...current.filter(
            (item) => item.id !== (data.compaction as CompactionRunView).id,
          ),
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
      persistStep(
        createRunStep(
          "delegate",
          `委派给 ${String(data.target_agent ?? "agent")}`,
          "done",
          data,
        ),
      );
      return;
    }

    if (payload.type === "error") {
      flushPendingAssistantTokens();
      setMemoryStatus(`Error: ${String(data.message ?? "Unknown error")}`);
      persistStep(createRunStep("error", "请求出错", "error"));
      setIsStreaming(false);
      setActiveRunId(null);
      return;
    }

    if (payload.type === "cancelled" || payload.type === "interrupted") {
      flushPendingAssistantTokens();
      setMemoryStatus("已停止生成，内容已保存");
      setIsStreaming(false);
      setActiveRunId(null);
      persistStep(createRunStep("agent", "生成已停止", "done", data));
      void refreshSessions();
      return;
    }

    if (payload.type === "stopped") {
      flushPendingAssistantTokens();
      setMemoryStatus("已停止生成，内容已保存");
      setIsStreaming(false);
      setActiveRunId(null);
      persistStep(createRunStep("agent", "生成已停止", "done", data));
      void refreshSessions();
      return;
    }

    if (payload.type === "done") {
      flushPendingAssistantTokens();
      flushPendingReasoning();
      if (pendingApprovalsRef.current.length === 0) {
        setIsStreaming(false);
        setActiveRunId(null);
      }
      persistStep(createRunStep("done", "完成", "done"));
      updateSessionSummary(messagesRef.current);
      void refreshSessions();
      if (pendingApprovalsRef.current.length === 0) {
        void refreshCurrentSession();
      }
    }
  }

  async function subscribeRunEvents(runId: string, afterSequence?: number) {
    subscribeAbortRef.current?.abort();
    const controller = new AbortController();
    subscribeAbortRef.current = controller;
    stopRequestedRef.current = false;
    pendingAssistantTokensRef.current = "";
    cancelPendingAssistantTokenFlush();
    setActiveRunId(runId);
    setIsStreaming(true);

    const query =
      typeof afterSequence === "number"
        ? `?after_sequence=${encodeURIComponent(afterSequence)}`
        : "";

    try {
      await fetchEventSource(
        `${resolveStreamApiBase()}/api/runs/${runId}/events${query}`,
        {
          method: "GET",
          signal: controller.signal,
          onopen: assertEventStream,
          onmessage(event) {
            const parsed = parseStreamEvent(event);
            if (parsed) handleAgentEvent(parsed);
          },
          onerror(error) {
            if (controller.signal.aborted || stopRequestedRef.current) return;
            const streamError = classifyStreamError(error);
            setAssistantStreamError(streamError);
            if (pendingApprovalsRef.current.length === 0) {
              setIsStreaming(false);
            }
            setActiveRunId(null);
            setMemoryStatus(`Stream error: ${streamError.message}`);
            throw error;
          },
          onclose() {
            if (pendingApprovalsRef.current.length === 0) {
              setIsStreaming(false);
            }
          },
        },
      );
    } catch (error) {
      if (!controller.signal.aborted && !stopRequestedRef.current) {
        const streamError = classifyStreamError(error);
        setAssistantStreamError(streamError);
        if (pendingApprovalsRef.current.length === 0) {
          setIsStreaming(false);
        }
        setActiveRunId(null);
        setMemoryStatus(`Stream error: ${streamError.message}`);
      }
    } finally {
      if (subscribeAbortRef.current === controller) {
        subscribeAbortRef.current = null;
      }
      if (stopRequestedRef.current) {
        setIsStreaming(false);
      }
      stopRequestedRef.current = false;
    }
  }

  async function streamLegacyMessage({
    message,
    attachments = [],
    nextMessages,
    history = [],
    resetThread = false,
    idempotencyKey,
  }: {
    message: string;
    attachments?: ComposerAttachment[];
    nextMessages: ChatMessage[];
    history?: ChatMessage[];
    resetThread?: boolean;
    idempotencyKey: string;
  }) {
    streamAbortRef.current?.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    stopRequestedRef.current = false;
    pendingAssistantTokensRef.current = "";
    cancelPendingAssistantTokenFlush();
    setInput("");
    setIsStreaming(true);
    resetReasoning();
    stepsRef.current = [
      createRunStep("user", "收到输入", "done"),
      createRunStep("agent", "正在思考", "running"),
    ];
    setSteps(stepsRef.current);
    const preparedMessages = nextMessages.map((item, index) =>
      index === nextMessages.length - 1 && item.role === "assistant"
        ? { ...item, idempotencyKey, streamError: null }
        : item,
    );
    messagesRef.current = preparedMessages;
    setMessages(preparedMessages);
    updateSessionSummary(preparedMessages);

    try {
      await fetchEventSource(`${resolveStreamApiBase()}/api/chat/stream`, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          reset_thread: resetThread,
          idempotency_key: idempotencyKey,
          attachments: attachments.map((attachment) => ({
            id: attachment.id,
            mime: attachment.mime,
            byte_size: attachment.byteSize,
            name: attachment.name,
          })),
          metadata: {
            frontend_settings: runtimeSettings(settings),
          },
          history: history
            .filter((item) => item.role === "user" || item.role === "assistant")
            .filter((item) => item.content.trim())
            .map((item) => ({ role: item.role, content: item.content })),
        }),
        onopen: assertEventStream,
        onmessage(event) {
          const parsed = parseStreamEvent(event);
          if (parsed) handleAgentEvent(parsed);
        },
        onerror(error) {
          if (controller.signal.aborted || stopRequestedRef.current) return;
          const streamError = classifyStreamError(error);
          setAssistantStreamError(streamError);
          if (pendingApprovalsRef.current.length === 0) {
            setIsStreaming(false);
          }
          setActiveRunId(null);
          setMemoryStatus(`Stream error: ${streamError.message}`);
          throw error;
        },
        onclose() {
          if (pendingApprovalsRef.current.length === 0) {
            setIsStreaming(false);
          }
        },
      });
    } catch (error) {
      if (!controller.signal.aborted && !stopRequestedRef.current) {
        const streamError = classifyStreamError(error);
        setAssistantStreamError(streamError);
        if (pendingApprovalsRef.current.length === 0) {
          setIsStreaming(false);
        }
        setActiveRunId(null);
        setMemoryStatus(`Stream error: ${streamError.message}`);
      }
    } finally {
      if (streamAbortRef.current === controller) {
        streamAbortRef.current = null;
      }
      if (stopRequestedRef.current) {
        setIsStreaming(false);
      }
      stopRequestedRef.current = false;
    }
  }

  async function streamMessage({
    message,
    attachments = [],
    nextMessages,
    history = [],
    resetThread = false,
    idempotencyKey,
  }: {
    message: string;
    attachments?: ComposerAttachment[];
    nextMessages: ChatMessage[];
    history?: ChatMessage[];
    resetThread?: boolean;
    idempotencyKey: string;
  }) {
    await streamLegacyMessage({
      message,
      attachments,
      nextMessages,
      history,
      resetThread,
      idempotencyKey,
    });
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
    streamAbortRef.current?.abort();
    setActiveRunId(null);
    setIsStreaming(false);
    setMemoryStatus("已停止生成，内容已保存");
    persistStep(createRunStep("agent", "已停止生成", "done"));
    void refreshSessions();
  }

  async function sendMessage() {
    const message = input.trim();
    const attachments = pendingAttachments.filter(
      (attachment) => !attachment.uploading,
    );
    if ((!message && attachments.length === 0) || !sessionId || isStreaming)
      return;
    const idempotencyKey = createIdempotencyKey();
    setPendingAttachments([]);

    await streamMessage({
      message,
      attachments,
      nextMessages: [
        ...messagesRef.current,
        {
          id: createClientId("message"),
          role: "user",
          content: message,
          attachments,
        },
        {
          id: createClientId("message"),
          role: "assistant",
          content: "",
          parts: [],
          idempotencyKey,
          streamError: null,
        },
      ],
      idempotencyKey,
    });
  }

  async function copyMessage(message: ChatMessage) {
    const success = await copyToClipboard(buildMessageCopyText(message));
    if (success) {
      setCopiedMessageId(message.id);
      window.setTimeout(() => setCopiedMessageId(null), 1200);
    }
    toast(success ? "Copied" : "Copy failed", {
      tone: success ? "success" : "error",
    });
  }

  function startSubscribedRun(
    run: ApiRunStartResponse,
    nextMessages: ChatMessage[],
    options: { idempotencyKey?: string } = {},
  ) {
    const runId = runResponseId(run);
    streamAbortRef.current?.abort();
    stopRequestedRef.current = false;
    pendingAssistantTokensRef.current = "";
    cancelPendingAssistantTokenFlush();
    resetReasoning();
    stepsRef.current = [
      createRunStep("user", "收到输入", "done"),
      createRunStep("agent", "正在思考", "running"),
    ];
    setSteps(stepsRef.current);
    const preparedMessages = nextMessages.map((item, index) =>
      index === nextMessages.length - 1 && item.role === "assistant"
        ? {
            ...item,
            runId,
            idempotencyKey: options.idempotencyKey ?? item.idempotencyKey,
            streamError: null,
          }
        : item,
    );
    messagesRef.current = preparedMessages;
    setMessages(preparedMessages);
    updateSessionSummary(preparedMessages);
    setMemoryStatus("生成中");
    void subscribeRunEvents(runId);
  }

  async function editUserMessage(messageId: string, newContent: string) {
    if (isStreaming) return;
    try {
      const updated = await apiJson<ApiMessage>(`/api/messages/${messageId}`, {
        method: "PATCH",
        body: JSON.stringify({ content: newContent }),
      });
      persistMessageState((current) =>
        current.map((message) =>
          message.id === messageId
            ? { ...message, content: updated.content }
            : message,
        ),
      );
      updateSessionSummary(messagesRef.current);
      void refreshSessions();
    } catch (error) {
      toast(`Edit failed: ${formatStreamError(error)}`, { tone: "error" });
      throw error;
    }
  }

  async function editAndRerunUserMessage(
    messageId: string,
    newContent: string,
  ) {
    if (isStreaming || !sessionId) return;
    const current = messagesRef.current;
    const userIndex = current.findIndex((message) => message.id === messageId);
    if (userIndex < 0) return;
    const idempotencyKey = createIdempotencyKey();
    const nextMessages: ChatMessage[] = [
      ...current.slice(0, userIndex),
      { ...current[userIndex], content: newContent },
      {
        id: createClientId("message"),
        role: "assistant",
        content: "",
        parts: [],
        idempotencyKey,
        streamError: null,
      },
    ];
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
    updateSessionSummary(nextMessages);
    setIsStreaming(true);
    try {
      const run = await apiJson<ApiRun>(`/api/messages/${messageId}/rerun`, {
        method: "POST",
        body: JSON.stringify({
          content: newContent,
          idempotency_key: idempotencyKey,
          metadata: { frontend_settings: runtimeSettings(settings) },
        }),
      });
      startSubscribedRun(run, nextMessages, { idempotencyKey });
    } catch (error) {
      const streamError = classifyStreamError(error);
      setAssistantStreamError(streamError);
      setIsStreaming(false);
      setMemoryStatus(`Rerun failed: ${streamError.message}`);
      toast(`Rerun failed: ${formatStreamError(error)}`, { tone: "error" });
      throw error;
    }
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
    const idempotencyKey = createIdempotencyKey();
    const nextMessages: ChatMessage[] = [
      ...current.slice(0, lastUserIndex),
      lastUser,
      {
        id: createClientId("message"),
        role: "assistant",
        content: "",
        parts: [],
        idempotencyKey,
        streamError: null,
      },
    ];
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
    updateSessionSummary(nextMessages);
    setIsStreaming(true);

    try {
      const assistantMessageId = await persistedAssistantMessageId(
        current[lastAssistantIndex],
      );
      if (!assistantMessageId) {
        await streamMessage({
          message: lastUser.content,
          attachments: lastUser.attachments ?? [],
          nextMessages,
          history: current.slice(0, lastUserIndex),
          idempotencyKey,
        });
        return;
      }
      const run = await apiJson<ApiRun>(
        `/api/messages/${assistantMessageId}/regenerate`,
        {
          method: "POST",
          body: JSON.stringify({
            idempotency_key: idempotencyKey,
            metadata: { frontend_settings: runtimeSettings(settings) },
          }),
        },
      );
      startSubscribedRun(run, nextMessages, { idempotencyKey });
    } catch (error) {
      const streamError = classifyStreamError(error);
      setAssistantStreamError(streamError);
      setIsStreaming(false);
      setMemoryStatus(`Regenerate failed: ${streamError.message}`);
      toast(`Regenerate failed: ${formatStreamError(error)}`, {
        tone: "error",
      });
    }
  }

  async function retryAssistantMessage(messageId: string) {
    if (isStreaming || !sessionId) return;
    const current = messagesRef.current;
    const assistantIndex = current.findIndex(
      (message) => message.id === messageId,
    );
    const message = current[assistantIndex];
    if (!message || message.role !== "assistant") return;

    clearAssistantStreamError(messageId);
    setMemoryStatus("正在重试");

    if (message.runId) {
      try {
        const existing = await apiJson<{ run: ApiRun }>(
          `/api/runs/${message.runId}`,
        );
        if (["queued", "running"].includes(existing.run.status)) {
          const lastSequence = lastRunSequenceRef.current.get(message.runId);
          void subscribeRunEvents(message.runId, lastSequence);
          return;
        }
      } catch {
        // If the original run cannot be found, regenerate below with the same idempotency key.
      }
    }

    if (!message.idempotencyKey) {
      setMessageStreamError(messageId, {
        kind: "unknown",
        message: "缺少重试所需的请求标识，请重新生成上一条回复。",
        retryable: false,
      });
      setMemoryStatus("Retry failed: missing idempotency key");
      return;
    }

    const nextMessages = current.map((item) =>
      item.id === messageId
        ? {
            ...item,
            content: "",
            parts: [],
            runId: undefined,
            streamError: null,
          }
        : item,
    );

    try {
      const assistantMessageId = await persistedAssistantMessageId(message);
      if (!assistantMessageId) {
        const userIndex = current
          .slice(0, assistantIndex)
          .map((item, index) => ({ item, index }))
          .reverse()
          .find((entry) => entry.item.role === "user")?.index;
        const userMessage =
          userIndex === undefined ? undefined : current[userIndex];
        if (!userMessage || userMessage.role !== "user") {
          throw new Error("No user message available for retry");
        }
        await streamMessage({
          message: userMessage.content,
          attachments: userMessage.attachments ?? [],
          nextMessages,
          history: current.slice(0, userIndex),
          idempotencyKey: message.idempotencyKey,
        });
        return;
      }
      messagesRef.current = nextMessages;
      setMessages(nextMessages);
      setIsStreaming(true);
      const run = await apiJson<ApiRun>(
        `/api/messages/${assistantMessageId}/regenerate`,
        {
          method: "POST",
          body: JSON.stringify({
            idempotency_key: message.idempotencyKey,
            metadata: { frontend_settings: runtimeSettings(settings) },
          }),
        },
      );
      startSubscribedRun(run, nextMessages, {
        idempotencyKey: message.idempotencyKey,
      });
    } catch (error) {
      const streamError = classifyStreamError(error);
      setMessageStreamError(messageId, streamError);
      setIsStreaming(false);
      setMemoryStatus(`Retry failed: ${streamError.message}`);
    }
  }

  const activeSession = sessions.find((session) => session.id === sessionId);

  return (
    <div className="mobile-style-chatgpt-page h-[100dvh] overflow-hidden bg-transparent md:min-h-screen md:p-5">
      <div className="mx-auto flex h-full w-full max-w-[100rem] flex-col md:grid md:h-[calc(100dvh-2.5rem)] md:grid-cols-1 md:gap-4 lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[15rem_minmax(0,1fr)_20rem] 2xl:grid-cols-[16rem_minmax(0,1fr)_21rem]">
        {/* Mobile-only header */}
        <SessionMobileHeader
          sessionId={sessionId}
          title={activeSession?.title}
          isStreaming={isStreaming}
          settings={settings}
          settingsOpen={settingsOpen}
          tommyAvatarUrl={settings.tommyAvatarUrl}
          onNewSession={resetSession}
          onOpenSessions={() => setMobileSessionsOpen(true)}
          onOpenInspector={() => setMobileInspectorOpen(true)}
          onToggleSettings={() => setSettingsOpen((value) => !value)}
          onSettingsChange={updateSettings}
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
          onRename={renameSession}
          onTogglePin={togglePinSession}
          onToggleArchive={toggleArchiveSession}
          onExport={exportSession}
          onShare={shareSession}
          onRevokeShare={revokeShare}
          onSearchMessages={searchMessages}
          onSelectSearchResult={selectSearchResult}
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
          tommyAvatarUrl={settings.tommyAvatarUrl}
          onNewSession={resetSession}
          onSelectSession={selectSession}
          onDeleteSession={deleteSession}
          onRename={renameSession}
          onTogglePin={togglePinSession}
          onToggleArchive={toggleArchiveSession}
          onExport={exportSession}
          onShare={shareSession}
          onRevokeShare={revokeShare}
          onSearchMessages={searchMessages}
          onSelectSearchResult={selectSearchResult}
        />

        {/* Main chat column */}
        <div className="flex min-h-0 flex-1 flex-col md:gap-4">
          <MessageStream
            messages={messages}
            isStreaming={isStreaming}
          copiedMessageId={copiedMessageId}
          expandedTools={settings.expandedTools}
          userAvatarUrl={settings.userAvatarUrl}
          tommyAvatarUrl={settings.tommyAvatarUrl}
          headerAction={
            <SettingsNavCard
              open={settingsOpen}
              settings={settings}
              onToggle={() => setSettingsOpen((value) => !value)}
              onChange={updateSettings}
            />
          }
            onCopyMessage={copyMessage}
            onRegenerate={regenerateLastResponse}
            onRetry={retryAssistantMessage}
            onEditMessage={editUserMessage}
            onEditAndRerunMessage={editAndRerunUserMessage}
            onApproveRequest={approveRequest}
            onRejectApprovalRequest={rejectApprovalRequest}
          />
          <ChatComposer
            value={input}
            disabled={isStreaming}
            isStreaming={isStreaming}
            pendingAttachments={pendingAttachments}
            onChange={setInput}
            onAddAttachments={addAttachments}
            onRemoveAttachment={removeAttachment}
            onSubmit={sendMessage}
            onStop={stopStreaming}
          />
        </div>

        {/* Right panels — xl+ */}
        <aside className="right-panel-stack hidden min-h-0 overflow-y-auto pr-1 scrollbar-thin xl:flex xl:flex-col xl:gap-4">
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
        </aside>

        {/* Right panels — below xl */}
        <div className="right-panel-stack hidden max-h-[42dvh] min-h-0 gap-4 overflow-y-auto pr-1 scrollbar-thin lg:col-span-2 lg:grid xl:hidden">
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
        </div>
      </div>
    </div>
  );
}

function SettingsNavCard({
  open,
  settings,
  onToggle,
  onChange,
  compact = false,
}: {
  open: boolean;
  settings: AgentSettings;
  onToggle: () => void;
  onChange: (settings: AgentSettings) => void;
  compact?: boolean;
}) {
  const { t } = useI18n();

  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-label={compact ? t("settings.title") : undefined}
        className={`ios-glass-pill soft-focus-ring inline-flex items-center justify-center gap-2 text-[12px] font-semibold text-slate-600 dark:text-slate-200 ${
          compact ? "h-10 w-10 rounded-full p-0" : "min-h-11 px-3"
        } ${
          open ? "liquid-selected" : ""
        }`}
      >
        <Settings2 className="h-4 w-4" strokeWidth={2.1} />
        {!compact && t("settings.title")}
      </button>
      {open && (
        <div className="absolute right-0 top-full z-40 mt-3">
          <SettingsPanel settings={settings} onChange={onChange} chrome="card" />
        </div>
      )}
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
  settings,
  settingsOpen,
  tommyAvatarUrl,
  onNewSession,
  onOpenSessions,
  onOpenInspector,
  onToggleSettings,
  onSettingsChange,
}: {
  sessionId: string;
  title?: string;
  isStreaming: boolean;
  settings: AgentSettings;
  settingsOpen: boolean;
  tommyAvatarUrl: string;
  onNewSession: () => void;
  onOpenSessions: () => void;
  onOpenInspector: () => void;
  onToggleSettings: () => void;
  onSettingsChange: (settings: AgentSettings) => void;
}) {
  const { t } = useI18n();

  return (
    <div className="mobile-style-header pointer-events-none absolute inset-x-0 top-0 z-30 flex items-start justify-between gap-2 px-3 pt-[max(0.6rem,env(safe-area-inset-top)+0.6rem)] lg:hidden">
      <div className="pointer-events-auto ios-glass-pill flex min-w-0 flex-1 items-center gap-2 px-2.5 py-1.5">
        <button
          type="button"
          onClick={onOpenSessions}
          className="ios-glass-pill soft-focus-ring flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full text-slate-700 transition active:scale-95 dark:text-slate-200"
          aria-label={t("app.a11y.openSessions")}
        >
          <Menu className="h-4 w-4" strokeWidth={2.2} />
        </button>
        <img
          src={tommyAvatarUrl || "/tommy-avatar.png"}
          alt="Tommy"
          className="h-8 w-8 flex-shrink-0 rounded-full object-cover shadow-sm"
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold tracking-tight text-slate-700 dark:text-slate-200">
            {isStreaming ? (
              <span className="flex items-center gap-2">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--primary-color)] opacity-60" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--primary-color)]" />
                </span>
                {t("app.top.thinking")}
              </span>
            ) : (
              title || "Tommy"
            )}
          </p>
          <p className="truncate text-[10px] font-medium text-slate-400 dark:text-slate-500">
            {sessionId ? `Session ${sessionId.slice(-6)}` : "Tommy Agent"}
          </p>
        </div>
      </div>

      <div className="flex flex-shrink-0 items-center gap-1.5">
        <div className="pointer-events-auto">
          <SettingsNavCard
            open={settingsOpen}
            settings={settings}
            onToggle={onToggleSettings}
            onChange={onSettingsChange}
            compact
          />
        </div>
        <button
          type="button"
          onClick={onOpenInspector}
          className="ios-glass-pill pointer-events-auto flex h-10 w-10 items-center justify-center rounded-full text-slate-700 transition active:scale-95 dark:text-slate-200"
          aria-label={t("app.a11y.openInspector")}
        >
          <SlidersHorizontal className="h-4 w-4" strokeWidth={2.1} />
        </button>
        <button
          type="button"
          onClick={onNewSession}
          disabled={isStreaming}
          className="new-session-glass-button pointer-events-auto flex h-10 w-10 items-center justify-center rounded-full text-slate-700 transition active:scale-95 disabled:opacity-40 dark:text-slate-200"
          aria-label={t("app.a11y.newSession")}
        >
          <Plus className="h-4 w-4" strokeWidth={2.2} />
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
  const { t } = useI18n();

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <button
        type="button"
        className="absolute inset-0 bg-slate-950/20 dark:bg-black/40"
        onClick={onClose}
        aria-label={t("app.a11y.closeInspector")}
      />
      <section className="ios-glass-sheet absolute inset-x-0 bottom-0 mx-auto flex max-h-[88dvh] w-full flex-col rounded-t-[2.5rem] px-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] pt-3 shadow-2xl">
        <div className="mx-auto mb-4 h-1.5 w-12 rounded-full bg-slate-400/30 dark:bg-slate-600/40" />
        <div className="mb-4 flex items-center justify-between px-1">
          <div>
            <p className="text-[17px] font-semibold tracking-tight text-slate-800 dark:text-slate-100">
              Settings & State
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ios-glass-field soft-focus-ring flex h-9 w-9 items-center justify-center rounded-full text-slate-500 transition active:scale-95 dark:text-slate-300"
            aria-label={t("app.a11y.close")}
          >
            <X className="h-5 w-5" strokeWidth={2.4} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">
          <div className="space-y-4 pb-6">
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
  onRename,
  onTogglePin,
  onToggleArchive,
  onExport,
  onShare,
  onRevokeShare,
  onSearchMessages,
  onSelectSearchResult,
}: {
  open: boolean;
  sessionId: string;
  sessions: SessionListItem[];
  isStreaming: boolean;
  onClose: () => void;
  onNewSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onRename: (sessionId: string, title: string) => Promise<void> | void;
  onTogglePin: (sessionId: string, pinned: boolean) => Promise<void> | void;
  onToggleArchive: (
    sessionId: string,
    archived: boolean,
  ) => Promise<void> | void;
  onExport: (sessionId: string, format: "md" | "json") => void;
  onShare: (sessionId: string) => Promise<string>;
  onRevokeShare: (sessionId: string) => Promise<void> | void;
  onSearchMessages: (query: string) => Promise<SearchResultItem[]>;
  onSelectSearchResult: (sessionId: string, messageId: string) => void;
}) {
  const { t } = useI18n();
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResultItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");

  useEffect(() => {
    const query = searchQuery.trim();
    if (!open || !query) {
      setSearchResults([]);
      setSearching(false);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = window.setTimeout(() => {
      void onSearchMessages(query)
        .then((results) => {
          if (!cancelled) setSearchResults(results);
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [onSearchMessages, open, searchQuery]);

  if (!open) return null;

  function startRename(session: SessionListItem) {
    setRenameId(session.id);
    setRenameDraft(session.title);
    setOpenMenuId(null);
  }

  async function submitRename(session: SessionListItem) {
    const title = renameDraft.trim();
    if (!title || title === session.title) {
      setRenameId(null);
      return;
    }
    await onRename(session.id, title);
    setRenameId(null);
  }

  async function share(session: SessionListItem) {
    setOpenMenuId(null);
    await onShare(session.id);
  }

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <button
        type="button"
        className="absolute inset-0 bg-slate-950/28 dark:bg-black/45"
        onClick={onClose}
        aria-label={t("app.a11y.closeSessions")}
      />

      <aside className="ios-glass-drawer relative flex h-full w-[86vw] max-w-[22rem] flex-col rounded-r-[1.85rem]">
        <div className="flex items-center justify-between px-4 pb-3 pt-[calc(env(safe-area-inset-top)+1rem)]">
          <div>
            <p className="text-[17px] font-semibold tracking-tight">
              {t("app.sidebar.conversations")}
            </p>
            <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
              {isStreaming
                ? t("app.sidebar.subtitleStreaming")
                : t("app.sidebar.subtitleIdle")}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ios-glass-pill soft-focus-ring flex h-9 w-9 items-center justify-center rounded-full text-slate-500 transition active:scale-95 dark:text-slate-300"
            aria-label={t("app.a11y.close")}
          >
            <X className="h-5 w-5" strokeWidth={2.2} />
          </button>
        </div>

        <div className="p-4">
          <button
            type="button"
            onClick={() => {
              onNewSession();
              onClose();
            }}
            disabled={isStreaming}
            className="new-session-glass-button soft-focus-ring flex min-h-11 w-full items-center justify-center gap-2 px-4 py-3 text-[15px] font-medium disabled:opacity-45"
          >
            <Plus className="h-4 w-4" strokeWidth={2.4} />
            {t("app.sidebar.new")}
          </button>
          <label className="ios-glass-field soft-focus-ring mt-3 flex min-h-11 items-center gap-2 rounded-2xl px-3 text-slate-500">
            <Search className="h-4 w-4 flex-shrink-0" />
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={t("app.sidebar.search")}
              className="min-w-0 flex-1 bg-transparent text-[14px] text-slate-800 outline-none placeholder:text-slate-400 dark:text-slate-100 dark:placeholder:text-slate-600"
            />
          </label>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 scrollbar-thin">
          {searchQuery.trim() ? (
            <MobileSearchResults
              results={searchResults}
              searching={searching}
              onSelect={(nextSessionId, messageId) => {
                onSelectSearchResult(nextSessionId, messageId);
                onClose();
              }}
            />
          ) : sessions.length === 0 ? (
            <div className="ios-glass-field rounded-2xl px-4 py-3 text-sm text-slate-400">
              {t("app.sidebar.empty")}
            </div>
          ) : (
            <div className="space-y-1">
              {sessions.map((session) => (
                <div
                  key={session.id}
                  className={`group relative flex items-center gap-1 rounded-2xl transition-colors ${
                    session.id === sessionId
                      ? "liquid-selected"
                      : "liquid-hover"
                  }`}
                >
                  {renameId === session.id ? (
                    <form
                      className="min-h-[4.25rem] min-w-0 flex-1 px-3.5 py-2.5"
                      onSubmit={(event) => {
                        event.preventDefault();
                        void submitRename(session);
                      }}
                    >
                      <input
                        value={renameDraft}
                        onChange={(event) => setRenameDraft(event.target.value)}
                        autoFocus
                        className="ios-glass-field soft-focus-ring h-9 w-full rounded-xl px-3 text-[14px] font-medium outline-none"
                      />
                      <div className="mt-1.5 flex justify-end gap-2 text-[12px]">
                        <button
                          type="button"
                          onClick={() => setRenameId(null)}
                          className="admin-secondary-action px-2 py-1"
                        >
                          {t("app.sidebar.cancel")}
                        </button>
                        <button
                          type="submit"
                          className="premium-action px-2 py-1 font-semibold"
                        >
                          {t("app.sidebar.save")}
                        </button>
                      </div>
                    </form>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        onSelectSession(session.id);
                        onClose();
                      }}
                      className="min-h-[4.25rem] min-w-0 flex-1 px-3.5 py-2.5 text-left"
                    >
                      <p className="flex items-center gap-1 truncate text-[14px] font-medium text-slate-800 dark:text-slate-100">
                        {session.pinned && (
                          <Pin className="h-3 w-3 flex-shrink-0" />
                        )}
                        <span className="truncate">{session.title}</span>
                      </p>
                      <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-slate-500 dark:text-slate-500">
                        {session.preview ||
                          t("memory.sessionLabel", {
                            id: session.id.slice(-6),
                          })}
                      </p>
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() =>
                      setOpenMenuId(
                        openMenuId === session.id ? null : session.id,
                      )
                    }
                    className="admin-icon-action mr-2 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-slate-400 transition disabled:opacity-40 dark:text-slate-500"
                    aria-label={`${t("app.sidebar.moreActions")}：${session.title}`}
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </button>
                  {openMenuId === session.id && (
                    <MobileSessionMenu
                      session={session}
                      isStreaming={isStreaming}
                      onRename={() => startRename(session)}
                      onTogglePin={() => {
                        setOpenMenuId(null);
                        void onTogglePin(session.id, !session.pinned);
                      }}
                      onToggleArchive={() => {
                        setOpenMenuId(null);
                        void onToggleArchive(session.id, !session.archived);
                      }}
                      onExport={(format) => {
                        setOpenMenuId(null);
                        onExport(session.id, format);
                      }}
                      onShare={() => void share(session)}
                      onRevokeShare={() => {
                        setOpenMenuId(null);
                        void onRevokeShare(session.id);
                      }}
                      onDelete={() => {
                        setOpenMenuId(null);
                        onDeleteSession(session.id);
                      }}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function MobileSessionMenu({
  session,
  isStreaming,
  onRename,
  onTogglePin,
  onToggleArchive,
  onExport,
  onShare,
  onRevokeShare,
  onDelete,
}: {
  session: SessionListItem;
  isStreaming: boolean;
  onRename: () => void;
  onTogglePin: () => void;
  onToggleArchive: () => void;
  onExport: (format: "md" | "json") => void;
  onShare: () => void;
  onRevokeShare: () => void;
  onDelete: () => void;
}) {
  const { t } = useI18n();

  return (
    <div className="ios-menu-surface absolute right-2 top-12 z-20 w-52 overflow-hidden rounded-2xl p-1 text-[13px]">
      <MobileMenuButton
        icon={<Pencil className="h-3.5 w-3.5" />}
        label={t("app.sidebar.rename")}
        onClick={onRename}
      />
      <MobileMenuButton
        icon={<Pin className="h-3.5 w-3.5" />}
        label={session.pinned ? t("app.sidebar.unpin") : t("app.sidebar.pin")}
        onClick={onTogglePin}
      />
      <MobileMenuButton
        icon={<Archive className="h-3.5 w-3.5" />}
        label={
          session.archived
            ? t("app.sidebar.unarchive")
            : t("app.sidebar.archive")
        }
        onClick={onToggleArchive}
      />
      <MobileMenuButton
        icon={<Download className="h-3.5 w-3.5" />}
        label={t("app.sidebar.exportMd")}
        onClick={() => onExport("md")}
      />
      <MobileMenuButton
        icon={<FileJson className="h-3.5 w-3.5" />}
        label={t("app.sidebar.exportJson")}
        onClick={() => onExport("json")}
      />
      <MobileMenuButton
        icon={<Link2 className="h-3.5 w-3.5" />}
        label={t("app.sidebar.share")}
        onClick={onShare}
      />
      <MobileMenuButton
        icon={<X className="h-3.5 w-3.5" />}
        label={t("app.sidebar.unshare")}
        onClick={onRevokeShare}
      />
      <div className="my-1 h-px bg-slate-950/[0.04] dark:bg-white/[0.08]" />
      <MobileMenuButton
        icon={<Trash2 className="h-3.5 w-3.5" />}
        label={t("app.sidebar.delete")}
        onClick={onDelete}
        disabled={isStreaming}
        danger
      />
    </div>
  );
}

function MobileMenuButton({
  icon,
  label,
  danger = false,
  disabled = false,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`flex min-h-10 w-full items-center gap-2 rounded-xl px-3 text-left transition disabled:cursor-not-allowed disabled:opacity-40 ${
        danger
          ? "liquid-hover text-red-500"
          : "liquid-hover text-slate-600 dark:text-slate-200"
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function MobileSearchResults({
  results,
  searching,
  onSelect,
}: {
  results: SearchResultItem[];
  searching: boolean;
  onSelect: (sessionId: string, messageId: string) => void;
}) {
  const { t } = useI18n();

  if (searching) {
    return (
      <div className="ios-glass-field rounded-2xl px-4 py-3 text-sm text-slate-400">
        {t("app.sidebar.searching")}
      </div>
    );
  }
  if (results.length === 0) {
    return (
      <div className="ios-glass-field rounded-2xl px-4 py-3 text-sm text-slate-400">
        {t("app.sidebar.noResults")}
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      {results.map((result) => (
        <button
          key={`${result.messageId}-${result.position}`}
          type="button"
          onClick={() => onSelect(result.sessionId, result.messageId)}
          className="liquid-hover w-full rounded-2xl px-3.5 py-3 text-left transition"
        >
          <p className="truncate text-[13px] font-medium text-slate-800 dark:text-slate-100">
            {result.sessionTitle ||
              t("memory.sessionLabel", { id: result.sessionId.slice(-6) })}
          </p>
          <p
            className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-slate-500 [&_mark]:rounded [&_mark]:bg-yellow-200/80 [&_mark]:px-0.5 dark:text-slate-400 dark:[&_mark]:bg-yellow-400/25"
            dangerouslySetInnerHTML={{
              __html: sanitizeSearchSnippet(result.snippet),
            }}
          />
        </button>
      ))}
    </div>
  );
}

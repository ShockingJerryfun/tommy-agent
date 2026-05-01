import { test as base, expect, type Page, type Request, type Route } from "@playwright/test";

const NOW = "2026-04-28T15:00:00.000Z";
const SESSION_ID = "session-e2e-1";
const USER_MESSAGE_ID = "msg-user-1";
const ASSISTANT_MESSAGE_ID = "msg-asst-1";
const PNG_1X1 = Buffer.from(
  "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360000002000100ffff03000006000557bfab0d0000000049454e44ae426082",
  "hex",
);

export const FIRST_PROMPT_BODY = "Summarize this conversation into concise action items.";

type ApiMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  metadata?: Record<string, unknown>;
  created_at: string;
};

type ApiRunEvent = {
  id: string;
  run_id?: string;
  type: string;
  label: string;
  status: "running" | "done" | "error";
  payload?: Record<string, unknown>;
  sequence?: number;
  created_at: string;
};

type MockBackendState = {
  sessions: Array<{
    id: string;
    title: string;
    preview: string;
    pinned: boolean;
    archived: boolean;
    updated_at: string;
  }>;
  messages: ApiMessage[];
  runEvents?: ApiRunEvent[];
  streamBody?: string;
};

export function cannedMessages(): ApiMessage[] {
  return [
    {
      id: USER_MESSAGE_ID,
      role: "user",
      content: "测试 KaTeX 与代码：$x^2$",
      created_at: NOW,
    },
    {
      id: ASSISTANT_MESSAGE_ID,
      role: "assistant",
      content: [
        "这里是 GFM、代码和 LaTeX 的混合回复。",
        "",
        "| Item | Value |",
        "| --- | --- |",
        "| 测试 | $x^2$ |",
        "",
        "```python",
        "def square(x):",
        "    return x * x",
        "```",
        "",
        "$$x^2 + y^2 = z^2$$",
      ].join("\n"),
      metadata: { run_id: "run-asst-1" },
      created_at: NOW,
    },
  ];
}

export function longConversationMessages(count = 30): ApiMessage[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `msg-long-${index + 1}`,
    role: index % 2 === 0 ? "user" : "assistant",
    content: `测试 长消息 ${index + 1}\n\n${"这是一段用于撑开滚动区域的内容。".repeat(8)}`,
    created_at: NOW,
  }));
}

function createState(): MockBackendState {
  return {
    sessions: [
      {
        id: SESSION_ID,
        title: "E2E UX Parity",
        preview: "测试 KaTeX 与代码",
        pinned: false,
        archived: false,
        updated_at: NOW,
      },
    ],
    messages: cannedMessages(),
  };
}

function sessionDetail(state: MockBackendState) {
  return {
    session: state.sessions[0],
    messages: state.messages,
    run_events: state.runEvents ?? [],
    tool_calls: [],
    latest_run: null,
    active_run: null,
    runs: [],
    context_pact: {},
    skill_proposals: [],
    memory_proposals: [],
    compaction_runs: [],
    skills: [],
    pending_approvals: [],
  };
}

function sharedConversation(state: MockBackendState) {
  return {
    session: state.sessions[0],
    messages: state.messages.map(({ id, role, content, created_at }) => ({
      id,
      role,
      content,
      created_at,
    })),
  };
}

function prompts() {
  return {
    prompts: [
      {
        id: "prompt-summarize",
        kind: "builtin",
        name: "Summarize",
        shortcut: "summarize",
        body: FIRST_PROMPT_BODY,
      },
      {
        id: "prompt-actions",
        kind: "builtin",
        name: "Action Summary",
        shortcut: "actions",
        body: `${FIRST_PROMPT_BODY}\n\nInclude owners and deadlines.`,
      },
      {
        id: "prompt-debug",
        kind: "builtin",
        name: "Debug",
        shortcut: "debug",
        body: "Debug the issue and list likely root causes.",
      },
      {
        id: "prompt-review",
        kind: "builtin",
        name: "Review",
        shortcut: "review",
        body: "Review this change for correctness, regressions, and missing tests.",
      },
    ],
  };
}

function runPayload(message = "") {
  return {
    id: `run-${Date.now()}`,
    session_id: SESSION_ID,
    agent_id: "default",
    status: "running",
    input: message,
    metadata: {},
    assistant_message_id: ASSISTANT_MESSAGE_ID,
    created_at: NOW,
    updated_at: NOW,
  };
}

function backendPath(rawUrl: string) {
  const url = new URL(rawUrl);
  let pathname = url.pathname;
  if (pathname.startsWith("/agent-api")) {
    pathname = pathname.slice("/agent-api".length) || "/";
  }
  return { pathname, search: url.search };
}

function jsonResponse(payload: unknown, status = 200) {
  return {
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  };
}

function requestJson(request: Request) {
  try {
    return request.postDataJSON() as Record<string, unknown>;
  } catch {
    return {};
  }
}

async function fulfillBackend(route: Route, state: MockBackendState) {
  const request = route.request();
  const method = request.method();
  const { pathname, search } = backendPath(request.url());

  if (method === "GET" && pathname === "/api/sessions") {
    await route.fulfill(jsonResponse({ sessions: state.sessions }));
    return;
  }

  if (method === "POST" && pathname === "/api/sessions") {
    const id = `session-${Date.now()}`;
    state.sessions.unshift({
      id,
      title: "新对话",
      preview: "",
      pinned: false,
      archived: false,
      updated_at: NOW,
    });
    await route.fulfill(jsonResponse({ session_id: id }));
    return;
  }

  if (method === "GET" && pathname === `/api/sessions/${SESSION_ID}`) {
    await route.fulfill(jsonResponse(sessionDetail(state)));
    return;
  }

  if (method === "PATCH" && pathname.startsWith("/api/sessions/")) {
    const body = requestJson(request);
    state.sessions[0] = { ...state.sessions[0], ...body, updated_at: NOW };
    await route.fulfill(jsonResponse(state.sessions[0]));
    return;
  }

  if (method === "POST" && pathname.match(/^\/api\/sessions\/[^/]+\/share$/)) {
    await route.fulfill(jsonResponse({ token: "test-token", url: "/share/test-token" }));
    return;
  }

  if (method === "DELETE" && pathname.match(/^\/api\/sessions\/[^/]+\/share$/)) {
    await route.fulfill(jsonResponse({ status: "revoked" }));
    return;
  }

  if (method === "POST" && pathname === `/api/sessions/${SESSION_ID}/share`) {
    await route.fulfill(jsonResponse({ token: "test-token", url: "/share/test-token" }));
    return;
  }

  if (method === "DELETE" && pathname === `/api/sessions/${SESSION_ID}/share`) {
    await route.fulfill(jsonResponse({ status: "revoked" }));
    return;
  }

  if (method === "PATCH" && pathname.startsWith("/api/messages/")) {
    const body = requestJson(request) as { content?: string };
    const messageId = pathname.split("/")[3];
    const message = state.messages.find((item) => item.id === messageId);
    if (message && typeof body.content === "string") message.content = body.content;
    await route.fulfill(jsonResponse(message ?? state.messages[0]));
    return;
  }

  if (method === "POST" && pathname.match(/^\/api\/messages\/[^/]+\/(rerun|regenerate)$/)) {
    const body = requestJson(request) as { content?: string };
    await route.fulfill(jsonResponse(runPayload(body.content ?? "")));
    return;
  }

  if (method === "GET" && pathname.match(/^\/api\/runs\/[^/]+\/events$/)) {
    await new Promise((resolve) => setTimeout(resolve, 120));
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: state.streamBody ?? "event: done\ndata: {}\n\n",
      headers: { "Cache-Control": "no-cache" },
    });
    return;
  }

  if (method === "POST" && pathname === "/api/chat/stream") {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: state.streamBody ?? "event: done\ndata: {}\n\n",
      headers: { "Cache-Control": "no-cache" },
    });
    return;
  }

  if (method === "GET" && pathname === "/api/search" && search) {
    await route.fulfill(
      jsonResponse({
        results: [
          {
            message_id: USER_MESSAGE_ID,
            session_id: SESSION_ID,
            session_title: state.sessions[0].title,
            role: "user",
            position: 0,
            created_at: NOW,
            snippet: "测试 KaTeX 与代码：$x^2$",
          },
        ],
      }),
    );
    return;
  }

  if (method === "GET" && pathname === "/api/prompts") {
    await route.fulfill(jsonResponse(prompts()));
    return;
  }

  if (method === "GET" && pathname.startsWith("/share/")) {
    await route.fulfill(jsonResponse(sharedConversation(state)));
    return;
  }

  if (method === "POST" && pathname === "/api/attachments") {
    await route.fulfill(
      jsonResponse({
        id: "att-avatar",
        mime: "image/png",
        byte_size: PNG_1X1.byteLength,
        name: "avatar.png",
        thumbnail_url: "/api/attachments/att-avatar",
      }),
    );
    return;
  }

  if (method === "GET" && pathname.startsWith("/api/attachments/")) {
    await route.fulfill({ status: 200, contentType: "image/png", body: PNG_1X1 });
    return;
  }

  await route.fulfill(jsonResponse({ ok: true }));
}

async function installRoutes(page: Page, state: MockBackendState) {
  await page.route(/.*(\/agent-api\/|\/api\/).*/, (route) =>
    fulfillBackend(route, state),
  );
}

export const test = base.extend<{ mockBackend: MockBackendState }>({
  mockBackend: [
    async ({ page }, use) => {
      const state = createState();
      await installRoutes(page, state);
      await use(state);
    },
    { auto: true },
  ],
});

export { expect, SESSION_ID, USER_MESSAGE_ID, ASSISTANT_MESSAGE_ID, PNG_1X1 };

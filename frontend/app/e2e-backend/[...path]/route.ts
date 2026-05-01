const NOW = "2026-04-28T15:00:00.000Z";

const PNG_1X1 = Buffer.from(
  "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360000002000100ffff03000006000557bfab0d0000000049454e44ae426082",
  "hex",
);

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function ensureE2EEnabled() {
  return process.env.NEXT_PUBLIC_E2E === "1";
}

function sharedConversation() {
  return {
    session: {
      id: "session-e2e-1",
      title: "E2E UX Parity",
      created_at: NOW,
      updated_at: NOW,
    },
    messages: [
      {
        id: "msg-user-1",
        role: "user",
        content: "测试 KaTeX 与代码：$x^2$",
        created_at: NOW,
      },
      {
        id: "msg-asst-1",
        role: "assistant",
        content: "公开分享视图中的 Tommy 回复。\n\n$$x^2 + y^2 = z^2$$",
        created_at: NOW,
      },
    ],
  };
}

async function handle(request: Request, context: RouteContext) {
  if (!ensureE2EEnabled()) {
    return Response.json({ error: "Not found" }, { status: 404 });
  }

  const { path } = await context.params;
  const pathname = `/${path.join("/")}`;

  if (request.method === "GET" && pathname.startsWith("/share/")) {
    return Response.json(sharedConversation());
  }

  if (request.method === "GET" && pathname.startsWith("/api/attachments/")) {
    return new Response(PNG_1X1, {
      headers: { "Content-Type": "image/png", "Cache-Control": "private, max-age=300" },
    });
  }

  return Response.json({ ok: true });
}

export async function GET(request: Request, context: RouteContext) {
  return handle(request, context);
}

export async function POST(request: Request, context: RouteContext) {
  return handle(request, context);
}

export async function PATCH(request: Request, context: RouteContext) {
  return handle(request, context);
}

export async function DELETE(request: Request, context: RouteContext) {
  return handle(request, context);
}

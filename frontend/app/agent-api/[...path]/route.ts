const BACKEND_API_BASE = (
  process.env.AGENT_API_URL ??
  "http://127.0.0.1:8000"
).replace(/\/$/, "");

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function filteredRequestHeaders(request: Request) {
  const headers = new Headers(request.headers);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  return headers;
}

function filteredResponseHeaders(response: Response) {
  const headers = new Headers(response.headers);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  return headers;
}

async function proxy(request: Request, context: RouteContext) {
  const { path } = await context.params;
  const sourceUrl = new URL(request.url);
  const targetUrl = new URL(`/${path.join("/")}${sourceUrl.search}`, BACKEND_API_BASE);
  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer();

  let response: Response;
  try {
    response = await fetch(targetUrl, {
      method: request.method,
      headers: filteredRequestHeaders(request),
      body,
      cache: "no-store",
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return Response.json(
      {
        error: "Backend API unavailable",
        detail: message,
      },
      { status: 502 },
    );
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: filteredResponseHeaders(response),
  });
}

export async function GET(request: Request, context: RouteContext) {
  return proxy(request, context);
}

export async function POST(request: Request, context: RouteContext) {
  return proxy(request, context);
}

export async function DELETE(request: Request, context: RouteContext) {
  return proxy(request, context);
}

export async function PUT(request: Request, context: RouteContext) {
  return proxy(request, context);
}

export async function PATCH(request: Request, context: RouteContext) {
  return proxy(request, context);
}

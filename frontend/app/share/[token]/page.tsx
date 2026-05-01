import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { markdownComponents } from "../../../components/message-stream";

type SharedConversation = {
  session: {
    id: string;
    title: string;
    created_at: string;
    updated_at: string;
  };
  messages: Array<{
    id: string;
    role: "user" | "assistant" | "system";
    content: string;
    created_at: string;
  }>;
};

function apiBase() {
  return (process.env.AGENT_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

export default async function SharedConversationPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const response = await fetch(`${apiBase()}/share/${encodeURIComponent(token)}`, {
    cache: "no-store",
  });
  if (response.status === 404) {
    notFound();
  }
  if (!response.ok) {
    throw new Error("Failed to load shared conversation");
  }
  const data = (await response.json()) as SharedConversation;

  return (
    <main className="min-h-screen bg-[var(--primary-bg)] px-4 py-8 text-slate-950 dark:bg-slate-950 dark:text-slate-100">
      <div className="admin-card mx-auto max-w-3xl rounded-[var(--apple-corner-personal)] p-6 sm:p-8">
        <header className="admin-toolbar px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">
            公开只读视图
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">{data.session.title}</h1>
          <p className="mt-2 text-sm text-slate-400">
            Updated {data.session.updated_at}
          </p>
        </header>
        <div className="mt-6 space-y-8">
          {data.messages.map((message) => (
            <article key={message.id} className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
                {message.role === "user" ? "You" : "Tommy"} · {message.created_at}
              </p>
              <div className="markdown-body admin-card rounded-2xl px-4 py-3">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  components={markdownComponents}
                >
                  {message.content}
                </ReactMarkdown>
              </div>
            </article>
          ))}
        </div>
      </div>
    </main>
  );
}

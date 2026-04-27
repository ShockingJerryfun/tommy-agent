import { Plus, Trash2 } from "lucide-react";

export type SessionListItem = {
  id: string;
  title: string;
  preview: string;
  updatedAt: number;
};

type SessionSidebarProps = {
  sessionId: string;
  sessions: SessionListItem[];
  isStreaming: boolean;
  onNewSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
};

export function SessionSidebar({
  sessionId,
  sessions,
  isStreaming,
  onNewSession,
  onSelectSession,
  onDeleteSession,
}: SessionSidebarProps) {
  return (
    <aside className="hidden min-h-0 flex-col overflow-hidden rounded-panel bg-white/82 shadow-soft backdrop-blur-xl dark:bg-slate-950/62 lg:flex">
      {/* ── Brand header ── */}
      <div className="border-b border-slate-950/[0.06] px-5 py-4 dark:border-white/[0.07]">
        <div className="flex items-center gap-3">
          <div className="relative h-9 w-9 flex-shrink-0 overflow-hidden rounded-xl shadow-sm ring-1 ring-black/5 dark:ring-white/10">
            <img
              src="/tommy-avatar.svg"
              alt="Tommy Agent 标识"
              width={36}
              height={36}
              className="h-full w-full object-cover"
              draggable={false}
            />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold leading-tight tracking-tight">
              Tommy Agent
            </p>
            <p className="text-[11px] leading-tight text-slate-400 dark:text-slate-500">
              LangGraph Workbench
            </p>
          </div>
        </div>
      </div>

      {/* ── Status pill ── */}
      <div className="px-4 pt-4">
        <div className="flex items-center gap-2.5 rounded-xl bg-slate-950/[0.03] px-3.5 py-2.5 dark:bg-white/[0.05]">
          <StatusDot active={isStreaming} />
          <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
            {isStreaming ? "正在处理…" : "就绪"}
          </span>
        </div>
      </div>

      {/* ── Session history ── */}
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-4 scrollbar-thin">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
          对话
        </p>
        <div className="space-y-1.5">
          {sessions.length === 0 ? (
            <div className="rounded-xl bg-slate-950/[0.03] px-3.5 py-3 text-xs text-slate-400 dark:bg-white/[0.05]">
              还没有对话
            </div>
          ) : (
            sessions.map((session) => (
              <div
                key={session.id}
                className={`group flex items-start gap-1 rounded-xl transition-colors ${
                  session.id === sessionId
                    ? "bg-slate-950/[0.07] dark:bg-white/[0.08]"
                    : "hover:bg-slate-950/[0.04] dark:hover:bg-white/[0.05]"
                }`}
              >
                <button
                  type="button"
                  onClick={() => onSelectSession(session.id)}
                  className="min-w-0 flex-1 px-3.5 py-3 text-left"
                >
                  <p className="truncate text-[13px] font-medium text-slate-700 dark:text-slate-200">
                    {session.title}
                  </p>
                  <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-400 dark:text-slate-500">
                    {session.preview || shortSessionLabel(session.id)}
                  </p>
                </button>
                <button
                  type="button"
                  onClick={() => onDeleteSession(session.id)}
                  disabled={isStreaming}
                  aria-label={`删除对话：${session.title}`}
                  className="mr-2 mt-2 rounded-lg p-1.5 text-slate-300 opacity-0 transition hover:bg-red-500/10 hover:text-red-500 focus:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400/30 group-hover:opacity-100 disabled:cursor-not-allowed"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── New session button ── */}
      <div className="p-4">
        <button
          type="button"
          onClick={onNewSession}
          disabled={isStreaming}
          className="group flex w-full items-center justify-center gap-2 rounded-control bg-slate-950 px-4 py-2.5 text-sm font-medium text-white transition-all duration-200 hover:-translate-y-0.5 hover:bg-slate-800 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/40 disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-100"
        >
          <Plus
            className="h-4 w-4 transition-transform duration-300 group-hover:rotate-90"
            strokeWidth={2.5}
          />
          新建对话
        </button>
      </div>
    </aside>
  );
}

export function shortSessionLabel(sessionId: string) {
  if (!sessionId) return "加载中…";
  return `会话 ${sessionId.slice(-6)}`;
}

function StatusDot({ active }: { active: boolean }) {
  if (active) {
    return (
      <span className="relative flex h-2.5 w-2.5 flex-shrink-0">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
      </span>
    );
  }
  return (
    <span className="flex h-2.5 w-2.5 flex-shrink-0 rounded-full bg-slate-300 dark:bg-slate-600" />
  );
}

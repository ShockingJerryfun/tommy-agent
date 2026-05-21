import {
  Archive,
  Download,
  FileJson,
  Link2,
  MoreHorizontal,
  Pencil,
  Pin,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import type React from "react";
import { useEffect, useMemo, useState } from "react";

import { useI18n } from "../lib/i18n";
import { sanitizeSearchSnippet } from "../lib/snippetSanitize";

export type SessionListItem = {
  id: string;
  title: string;
  preview: string;
  pinned: boolean;
  archived: boolean;
  updatedAt: number;
};

export type SearchResultItem = {
  messageId: string;
  sessionId: string;
  sessionTitle: string;
  role: string;
  position: number;
  createdAt: string;
  snippet: string;
};

type SessionSidebarProps = {
  sessionId: string;
  sessions: SessionListItem[];
  isStreaming: boolean;
  tommyAvatarUrl?: string;
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
};

export function SessionSidebar({
  sessionId,
  sessions,
  isStreaming,
  tommyAvatarUrl = "",
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
}: SessionSidebarProps) {
  const { t } = useI18n();
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResultItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [shareUrls, setShareUrls] = useState<Record<string, string>>({});

  useEffect(() => {
    function closeMenu(event: MouseEvent) {
      if (!(event.target instanceof HTMLElement)) return;
      if (event.target.closest("[data-session-menu-root]")) return;
      setOpenMenuId(null);
    }
    document.addEventListener("mousedown", closeMenu);
    return () => document.removeEventListener("mousedown", closeMenu);
  }, []);

  useEffect(() => {
    const query = searchQuery.trim();
    if (!query) {
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
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [onSearchMessages, searchQuery]);

  const groups = useMemo(() => {
    const sorted = [...sessions].sort((a, b) => b.updatedAt - a.updatedAt);
    return {
      pinned: sorted.filter((session) => session.pinned && !session.archived),
      recent: sorted.filter((session) => !session.pinned && !session.archived),
      archived: sorted.filter((session) => session.archived),
    };
  }, [sessions]);

  async function submitRename(target: SessionListItem) {
    const title = renameDraft.trim();
    if (!title || title === target.title) {
      setRenameId(null);
      return;
    }
    await onRename(target.id, title);
    setRenameId(null);
  }

  async function share(target: SessionListItem) {
    const url = await onShare(target.id);
    setShareUrls((current) => ({ ...current, [target.id]: url }));
    setOpenMenuId(null);
  }

  async function revokeShare(target: SessionListItem) {
    await onRevokeShare(target.id);
    setShareUrls((current) => {
      const next = { ...current };
      delete next[target.id];
      return next;
    });
  }

  return (
    <aside className="ios-sidebar-surface hidden min-h-0 flex-col overflow-hidden rounded-[var(--radius-shell)] lg:flex">
      {/* ── Brand header ── */}
      <div className="px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="relative h-9 w-9 flex-shrink-0 overflow-hidden rounded-xl shadow-sm">
            <img
              src={tommyAvatarUrl || "/tommy-avatar.png"}
              alt="Tommy Agent"
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
            <p className="text-[11px] leading-tight text-slate-500 dark:text-slate-400">
              LangGraph Workbench
            </p>
          </div>
        </div>
      </div>

      {/* ── Status pill ── */}
      <div className="px-4 pt-4">
        <div className="ios-glass-field flex items-center gap-2.5 rounded-2xl px-3.5 py-2.5">
          <StatusDot active={isStreaming} />
          <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
            {isStreaming ? t("app.status.processing") : t("app.status.ready")}
          </span>
        </div>
        <label className="ios-glass-field soft-focus-ring mt-3 flex items-center gap-2 rounded-2xl px-3 py-2 text-slate-400 transition focus-within:text-slate-600 dark:focus-within:text-slate-200">
          <Search className="h-4 w-4" />
          <input
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder={t("app.sidebar.search")}
            className="min-w-0 flex-1 bg-transparent text-[13px] text-slate-700 outline-none placeholder:text-slate-400 dark:text-slate-100"
          />
        </label>
      </div>

      {/* ── Session history ── */}
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-4 scrollbar-thin">
        {searchQuery.trim() ? (
          <SearchResults
            results={searchResults}
            searching={searching}
            onSelect={onSelectSearchResult}
          />
        ) : (
          <div className="space-y-4">
            <SessionGroup
              title={t("app.sidebar.pinned")}
              sessions={groups.pinned}
              activeSessionId={sessionId}
              isStreaming={isStreaming}
              openMenuId={openMenuId}
              renameId={renameId}
              renameDraft={renameDraft}
              shareUrls={shareUrls}
              onSelect={onSelectSession}
              onMenuToggle={setOpenMenuId}
              onRenameStart={(session) => {
                setRenameId(session.id);
                setRenameDraft(session.title);
                setOpenMenuId(null);
              }}
              onRenameDraft={setRenameDraft}
              onRenameSubmit={submitRename}
              onRenameCancel={() => setRenameId(null)}
              onTogglePin={onTogglePin}
              onToggleArchive={onToggleArchive}
              onExport={onExport}
              onShare={share}
              onRevokeShare={revokeShare}
              onDelete={onDeleteSession}
            />
            <SessionGroup
              title={t("app.sidebar.recent")}
              sessions={groups.recent}
              activeSessionId={sessionId}
              isStreaming={isStreaming}
              openMenuId={openMenuId}
              renameId={renameId}
              renameDraft={renameDraft}
              shareUrls={shareUrls}
              onSelect={onSelectSession}
              onMenuToggle={setOpenMenuId}
              onRenameStart={(session) => {
                setRenameId(session.id);
                setRenameDraft(session.title);
                setOpenMenuId(null);
              }}
              onRenameDraft={setRenameDraft}
              onRenameSubmit={submitRename}
              onRenameCancel={() => setRenameId(null)}
              onTogglePin={onTogglePin}
              onToggleArchive={onToggleArchive}
              onExport={onExport}
              onShare={share}
              onRevokeShare={revokeShare}
              onDelete={onDeleteSession}
              emptyLabel={t("app.sidebar.empty")}
            />
            <details>
              <summary className="mb-2 cursor-pointer list-none text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 [&::-webkit-details-marker]:hidden">
                {t("app.sidebar.archived", { count: groups.archived.length })}
              </summary>
              <SessionRows
                sessions={groups.archived}
                activeSessionId={sessionId}
                isStreaming={isStreaming}
                openMenuId={openMenuId}
                renameId={renameId}
                renameDraft={renameDraft}
                shareUrls={shareUrls}
                onSelect={onSelectSession}
                onMenuToggle={setOpenMenuId}
                onRenameStart={(session) => {
                  setRenameId(session.id);
                  setRenameDraft(session.title);
                  setOpenMenuId(null);
                }}
                onRenameDraft={setRenameDraft}
                onRenameSubmit={submitRename}
                onRenameCancel={() => setRenameId(null)}
                onTogglePin={onTogglePin}
                onToggleArchive={onToggleArchive}
                onExport={onExport}
                onShare={share}
                onRevokeShare={revokeShare}
                onDelete={onDeleteSession}
              />
            </details>
          </div>
        )}
      </div>

      {/* ── New session button ── */}
      <div className="p-4">
        <button
          type="button"
          onClick={onNewSession}
          disabled={isStreaming}
          className="new-session-glass-button soft-focus-ring group flex w-full items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold disabled:translate-y-0"
        >
          <Plus
            className="h-4 w-4 transition-transform duration-300 group-hover:rotate-90"
            strokeWidth={2.5}
          />
          {t("app.sidebar.new")}
        </button>
      </div>
    </aside>
  );
}

type SessionRowsProps = {
  sessions: SessionListItem[];
  activeSessionId: string;
  isStreaming: boolean;
  openMenuId: string | null;
  renameId: string | null;
  renameDraft: string;
  shareUrls: Record<string, string>;
  onSelect: (sessionId: string) => void;
  onMenuToggle: (sessionId: string | null) => void;
  onRenameStart: (session: SessionListItem) => void;
  onRenameDraft: (value: string) => void;
  onRenameSubmit: (session: SessionListItem) => Promise<void> | void;
  onRenameCancel: () => void;
  onTogglePin: (sessionId: string, pinned: boolean) => Promise<void> | void;
  onToggleArchive: (
    sessionId: string,
    archived: boolean,
  ) => Promise<void> | void;
  onExport: (sessionId: string, format: "md" | "json") => void;
  onShare: (session: SessionListItem) => Promise<void>;
  onRevokeShare: (session: SessionListItem) => Promise<void>;
  onDelete: (sessionId: string) => void;
};

function SessionGroup({
  title,
  sessions,
  emptyLabel,
  ...props
}: SessionRowsProps & { title: string; emptyLabel?: string }) {
  return (
    <section>
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
        {title}
      </p>
      {sessions.length === 0 && emptyLabel ? (
        <div className="ios-glass-field rounded-2xl px-3.5 py-3 text-xs text-slate-400">
          {emptyLabel}
        </div>
      ) : (
        <SessionRows sessions={sessions} {...props} />
      )}
    </section>
  );
}

function SessionRows({
  sessions,
  activeSessionId,
  isStreaming,
  openMenuId,
  renameId,
  renameDraft,
  shareUrls,
  onSelect,
  onMenuToggle,
  onRenameStart,
  onRenameDraft,
  onRenameSubmit,
  onRenameCancel,
  onTogglePin,
  onToggleArchive,
  onExport,
  onShare,
  onRevokeShare,
  onDelete,
}: SessionRowsProps) {
  const { t } = useI18n();
  if (sessions.length === 0) {
    return null;
  }
  return (
    <div className="space-y-1.5">
      {sessions.map((session) => (
        <div
          key={session.id}
          data-session-menu-root
          className={`group relative rounded-2xl transition-colors ${
            openMenuId === session.id ? "z-50" : "z-0"
          } ${
            session.id === activeSessionId
              ? "liquid-selected"
              : "liquid-hover"
          }`}
        >
          <div className="flex items-start gap-1">
            {renameId === session.id ? (
              <form
                className="min-w-0 flex-1 px-2 py-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void onRenameSubmit(session);
                }}
              >
                <input
                  value={renameDraft}
                  onChange={(event) => onRenameDraft(event.target.value)}
                  autoFocus
                  className="ios-glass-field soft-focus-ring w-full rounded-xl px-2 py-2 text-[13px] outline-none"
                  maxLength={200}
                />
                <div className="mt-2 flex gap-2 text-[11px]">
                  <button
                    type="submit"
                    className="admin-secondary-action px-2 py-1 font-medium text-slate-700 dark:text-slate-200"
                  >
                    {t("app.sidebar.save")}
                  </button>
                  <button
                    type="button"
                    onClick={onRenameCancel}
                    className="admin-secondary-action px-2 py-1 text-slate-500"
                  >
                    {t("app.sidebar.cancel")}
                  </button>
                </div>
              </form>
            ) : (
              <button
                type="button"
                onClick={() => onSelect(session.id)}
                className="min-w-0 flex-1 px-3.5 py-3 text-left"
              >
                <p className="truncate text-[13px] font-medium text-slate-700 dark:text-slate-200">
                  {session.title}
                </p>
                <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-400 dark:text-slate-500">
                  {session.preview ||
                    t("memory.sessionLabel", { id: session.id.slice(-6) })}
                </p>
              </button>
            )}
            <button
              type="button"
              onClick={() =>
                onMenuToggle(openMenuId === session.id ? null : session.id)
              }
              disabled={isStreaming}
              aria-label={`${t("app.sidebar.moreActions")}：${session.title}`}
              className="admin-icon-action soft-focus-ring mr-2 mt-2 flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition disabled:cursor-not-allowed md:h-7 md:w-7 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100 dark:hover:text-slate-100"
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
          </div>
          {shareUrls[session.id] && (
            <div className="ios-glass-field mx-3 mb-2 rounded-xl px-2 py-1.5 text-[11px] text-slate-500">
              <span className="block truncate">{shareUrls[session.id]}</span>
              <button
                type="button"
                onClick={() => void onRevokeShare(session)}
                className="admin-secondary-action mt-1 px-2 py-1 font-medium text-red-500"
              >
                {t("app.sidebar.unshare")}
              </button>
            </div>
          )}
          {openMenuId === session.id && (
            <SessionMenu
              session={session}
              onRename={() => onRenameStart(session)}
              onTogglePin={() => void onTogglePin(session.id, !session.pinned)}
              onToggleArchive={() =>
                void onToggleArchive(session.id, !session.archived)
              }
              onExport={onExport}
              onShare={() => void onShare(session)}
              onDelete={() => onDelete(session.id)}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function SessionMenu({
  session,
  onRename,
  onTogglePin,
  onToggleArchive,
  onExport,
  onShare,
  onDelete,
}: {
  session: SessionListItem;
  onRename: () => void;
  onTogglePin: () => void;
  onToggleArchive: () => void;
  onExport: (sessionId: string, format: "md" | "json") => void;
  onShare: () => void;
  onDelete: () => void;
}) {
  const { t } = useI18n();

  return (
    <div
      className="ios-menu-surface absolute right-2 top-12 z-50 w-48 overflow-hidden rounded-2xl p-1 text-[13px]"
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <MenuButton
        icon={<Pencil className="h-3.5 w-3.5" />}
        label={t("app.sidebar.rename")}
        onClick={onRename}
      />
      <MenuButton
        icon={<Pin className="h-3.5 w-3.5" />}
        label={session.pinned ? t("app.sidebar.unpin") : t("app.sidebar.pin")}
        onClick={onTogglePin}
      />
      <MenuButton
        icon={<Archive className="h-3.5 w-3.5" />}
        label={
          session.archived
            ? t("app.sidebar.unarchive")
            : t("app.sidebar.archive")
        }
        onClick={onToggleArchive}
      />
      <MenuButton
        icon={<Download className="h-3.5 w-3.5" />}
        label={t("app.sidebar.exportMd")}
        onClick={() => onExport(session.id, "md")}
      />
      <MenuButton
        icon={<FileJson className="h-3.5 w-3.5" />}
        label={t("app.sidebar.exportJson")}
        onClick={() => onExport(session.id, "json")}
      />
      <MenuButton
        icon={<Link2 className="h-3.5 w-3.5" />}
        label={t("app.sidebar.share")}
        onClick={onShare}
      />
      <div className="my-1 h-px bg-slate-950/[0.04] dark:bg-white/[0.08]" />
      <MenuButton
        icon={<Trash2 className="h-3.5 w-3.5" />}
        label={t("app.sidebar.delete")}
        onClick={onDelete}
        danger
      />
    </div>
  );
}

function MenuButton({
  icon,
  label,
  danger = false,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex min-h-10 w-full items-center gap-2 rounded-xl px-3 text-left transition ${
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

function SearchResults({
  results,
  searching,
  onSelect,
}: {
  results: SearchResultItem[];
  searching: boolean;
  onSelect: (sessionId: string, messageId: string) => void;
}) {
  const { t } = useI18n();

  return (
    <div>
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
        {t("app.sidebar.searchResults")}
      </p>
      {searching ? (
        <div className="ios-glass-field rounded-2xl px-3.5 py-3 text-xs text-slate-400">
          {t("app.sidebar.searching")}
        </div>
      ) : results.length === 0 ? (
        <div className="ios-glass-field rounded-2xl px-3.5 py-3 text-xs text-slate-400">
          {t("app.sidebar.noResults")}
        </div>
      ) : (
        <div className="space-y-1.5">
          {results.map((result) => (
            <button
              key={`${result.messageId}-${result.position}`}
              type="button"
              onClick={() => onSelect(result.sessionId, result.messageId)}
              className="liquid-hover w-full rounded-xl px-3.5 py-3 text-left transition"
            >
              <p className="truncate text-[13px] font-medium text-slate-700 dark:text-slate-200">
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
      )}
    </div>
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

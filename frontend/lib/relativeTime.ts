export function formatRelative(ts: string): string {
  const time = Date.parse(ts);
  if (!Number.isFinite(time)) return "";
  const diffMs = Date.now() - time;
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (diffMs < minute) return "刚刚";
  if (diffMs < hour) return `${Math.floor(diffMs / minute)}分钟前`;
  if (diffMs < day) return `${Math.floor(diffMs / hour)}小时前`;
  if (diffMs < 7 * day) return `${Math.floor(diffMs / day)}天前`;

  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
  }).format(time);
}

export function absoluteFor(ts: string): string {
  const time = Date.parse(ts);
  if (!Number.isFinite(time)) return ts;
  return new Date(time).toISOString();
}

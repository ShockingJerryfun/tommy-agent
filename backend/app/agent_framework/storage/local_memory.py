from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..paths import DATA_ROOT

MEMORY_EXPORT_HEADER = "# MEMORY\n"


class LocalMemoryStore:
    def __init__(self, agent_id: str = "default", root: Path | None = None) -> None:
        self.agent_id = agent_id
        self.agent_root = (root or DATA_ROOT) / agent_id
        self.memory_root = self.agent_root / "memory"

    def ensure_layout(self) -> None:
        self.memory_root.mkdir(parents=True, exist_ok=True)
        for name, content in {
            "SOUL.md": "# SOUL\n",
            "MEMORY.md": "# MEMORY\n",
            "USER.md": "# USER\n",
            "DREAMS.md": "# DREAMS\n",
        }.items():
            path = self.agent_root / name
            if not path.exists():
                path.write_text(content, encoding="utf-8")

    def append_daily_memory(self, content: str) -> Path:
        self.ensure_layout()
        path = self.memory_root / f"{datetime.now(UTC).date().isoformat()}.md"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n- {datetime.now(UTC).isoformat()} {content}\n")
        return path

    def memory_file(self) -> Path:
        self.ensure_layout()
        return self.agent_root / "MEMORY.md"

    def append_memory_export(self, content: str) -> Path:
        path = self.memory_file()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n- {content}\n")
        return path

    def export_memories(self, memories: list[dict[str, object]]) -> Path:
        path = self.memory_file()
        lines = [MEMORY_EXPORT_HEADER.rstrip(), ""]
        for memory in memories:
            content = str(memory.get("content") or "").strip()
            if content:
                lines.append(f"- {content}")
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path

    def read_memory_seed_items(self) -> list[str]:
        path = self.memory_file()
        items: list[str] = []
        seen: set[str] = set()
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line.startswith(("- ", "* ")):
                continue
            content = line[2:].strip()
            if not content or content.casefold() in seen:
                continue
            seen.add(content.casefold())
            items.append(content)
        return items

    def index_memory_file(self, path: Path) -> None:
        path.read_text(encoding="utf-8", errors="replace")

    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        self.ensure_layout()
        normalized = query.casefold()
        results: list[dict[str, str]] = []
        for path in sorted(self.memory_root.glob("*.md"), reverse=True):
            content = path.read_text(encoding="utf-8", errors="replace")
            if normalized in content.casefold():
                results.append(
                    {"path": str(path.relative_to(self.agent_root)), "snippet": content[:240]}
                )
            if len(results) >= limit:
                break
        return results

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .paths import DATA_ROOT


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

    def index_memory_file(self, path: Path) -> None:
        # Kept as a compatibility hook while durable memory search lives in PostgreSQL.
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

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from .checkpointing import build_thread_config


class GraphRuntime:
    """Owns LangGraph graph access, checkpoint thread reset, and stream invocation."""

    def __init__(self, graph_factory: Callable[[], Awaitable[Any]] | None = None) -> None:
        self._graph_factory = graph_factory

    async def reset_thread(self, session_id: str) -> None:
        graph = await self._get_graph()
        try:
            await graph.checkpointer.adelete_thread(session_id)
        except Exception:
            pass

    async def stream(self, session_id: str, inputs: dict[str, Any]) -> AsyncIterator[Any]:
        graph = await self._get_graph()
        async for part in graph.astream(
            inputs,
            config=build_thread_config(session_id),
            stream_mode=["messages", "updates", "custom"],
        ):
            yield part

    async def _get_graph(self) -> Any:
        if self._graph_factory is not None:
            return await self._graph_factory()

        from ..agent import build_agent_graph
        from .checkpointing import create_async_checkpointer

        return build_agent_graph(
            checkpointer=await create_async_checkpointer(),
            async_model=True,
        )

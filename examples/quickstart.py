from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AGENT_WORKSPACE_ROOT", str(ROOT))

from app.agent_framework import build_agent_graph, build_thread_config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local LangGraph agent chat.")
    parser.add_argument("--session-id", default=f"cli-{uuid4().hex[:8]}")
    args = parser.parse_args()

    graph = build_agent_graph()
    config = build_thread_config(args.session_id)
    print(f"Session: {args.session_id}")
    print("Type 'exit' to quit.\n")

    while True:
        user_input = input("You> ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        inputs = {
            "session_id": args.session_id,
            "agent_id": "default",
            "messages": [HumanMessage(content=user_input)],
        }
        for state in graph.stream(inputs, config=config, stream_mode="values"):
            messages = state.get("messages", [])
            if not messages:
                continue
            last = messages[-1]
            if isinstance(last, AIMessage) and last.tool_calls:
                names = ", ".join(call["name"] for call in last.tool_calls)
                print(f"Agent is calling tools: {names}")
            elif isinstance(last, ToolMessage):
                print(f"Tool[{last.name}]> {last.content[:500]}")
            elif isinstance(last, AIMessage) and last.content:
                print(f"Agent> {last.content}")


if __name__ == "__main__":
    main()

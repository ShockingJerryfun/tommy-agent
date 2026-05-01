from __future__ import annotations

from .events import AgentEvent

TERMINAL_EVENT_TYPES = {"done", "error", "cancelled", "interrupted", "stopped"}
TERMINAL_RUN_STATUSES = {"completed", "cancelled", "interrupted", "error"}


def event_to_run_step(event: AgentEvent) -> tuple[str, str, str]:
    data = event.data
    if event.type == "token":
        return "agent", "Agent 正在生成", "running"
    if event.type == "message_delta":
        return "agent", "消息增量已保存", "done"
    if event.type == "tool_start":
        return "tool", f"{data.get('tool', '工具')} 运行中", "running"
    if event.type == "tool_end":
        failed = str(data.get("status", "ok")) == "error"
        return (
            "tool",
            f"{data.get('tool', '工具')} {'失败' if failed else '完成'}",
            "error" if failed else "done",
        )
    if event.type == "model_start":
        return "model_start", "模型调用开始", "running"
    if event.type == "model_end":
        return "model_end", "模型调用完成", "done"
    if event.type == "model_error":
        return "model_error", "模型调用失败", "error"
    if event.type == "node_end":
        updates = data.get("updates") if isinstance(data.get("updates"), list) else []
        if "action" in updates:
            return "agent", "工具调用完成", "done"
        if "agent" in updates:
            return "agent", "回复已更新", "done"
        return "agent", "状态已更新", "done"
    if event.type == "context":
        section_count = data.get("section_count", 0)
        total_chars = data.get("total_chars", 0)
        return "context", f"上下文已构建 · {section_count} sections · {total_chars} chars", "done"
    if event.type == "verification_start":
        return "verification_start", "开始验证", "running"
    if event.type == "verification_end":
        status = str(data.get("status") or "skipped")
        return (
            "verification_end",
            f"验证{'通过' if status == 'passed' else '失败' if status == 'failed' else '跳过'}",
            "error" if status == "failed" else "done",
        )
    if event.type == "error":
        return "error", "请求出错", "error"
    if event.type in {"cancelled", "interrupted", "stopped"}:
        return "agent", "生成已停止", "done"
    if event.type == "done":
        return "done", "完成", "done"
    if event.type == "skill":
        proposal = data.get("proposal") if isinstance(data.get("proposal"), dict) else {}
        label = f"Skill {proposal.get('name') or data.get('name') or 'proposal'}"
        return "skill", label, "done"
    if event.type == "pact":
        return "pact", "上下文 Pact 已更新", "done"
    if event.type == "delegate":
        return "delegate", f"委派给 {data.get('target_agent', 'agent')}", "running"
    if event.type == "compaction":
        return "compaction", "会话已压缩", "done"
    if event.type == "memory_recall":
        return "memory", "记忆召回", "done"
    if event.type == "memory_write":
        return "memory", "记忆写入", "done"
    if event.type == "approval_pending":
        approval = data.get("approval") if isinstance(data.get("approval"), dict) else {}
        return "approval", f"等待审批：{approval.get('tool_name', '工具')}", "running"
    if event.type == "approval_resolved":
        approval = data.get("approval") if isinstance(data.get("approval"), dict) else {}
        failed = str(approval.get("status") or "") in {"failed", "rejected"}
        return "approval", "审批已处理", "error" if failed else "done"
    if event.type == "subagent_start":
        return "subagent", f"子 Agent {data.get('target_agent', '')} 启动", "running"
    if event.type == "subagent_end":
        return "subagent", f"子 Agent {data.get('target_agent', '')} 完成", "done"
    return "agent", event.type, "done"

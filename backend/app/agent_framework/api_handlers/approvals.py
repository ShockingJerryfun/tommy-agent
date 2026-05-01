from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..runtime import RunCreatePayload
from ..tool_runtime.approvals import execute_approved_action


def _is_explicitly_cancelled(store, run_id: str) -> bool:
    """Check only the cancel_requested flag, NOT the run status.

    ``run_stop_requested`` / ``is_run_cancel_requested`` also return True when
    the run status is ``"interrupted"`` — but the approval flow itself sets
    the run to ``"interrupted"`` while waiting for user input, so that status
    must NOT block subsequent approval execution.
    """
    run = store.get_run(run_id)
    if run is None:
        return False
    return bool(run.get("cancel_requested"))


async def approve_action_impl(
    store,
    registry,
    approval_id: str,
    agent_id: str,
    run_manager=None,
) -> dict[str, Any]:
    approval = store.get_approval_request(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Approval is already {approval['status']}")

    run_id = str(approval["run_id"])
    session_id = str(approval["session_id"])
    if _is_explicitly_cancelled(store, run_id):
        rejected = store.resolve_approval_request(
            approval_id,
            status="rejected",
            error="Run was stopped by user",
        )
        store.append_run_event(
            session_id,
            run_id=run_id,
            type="approval",
            label=f"运行已停止，未执行：{approval['tool_name']}",
            status="error",
            payload={"approval": rejected},
        )
        raise HTTPException(status_code=409, detail="Run was stopped; approval was not executed.")

    approved = store.resolve_approval_request(approval_id, status="approved")
    if approved is None:
        raise HTTPException(status_code=404, detail="Approval request not found")

    store.append_run_event(
        session_id,
        run_id=run_id,
        type="approval",
        label=f"审批通过：{approval['tool_name']}",
        status="done",
        payload={"approval": approved},
    )

    try:
        if _is_explicitly_cancelled(store, run_id):
            raise RuntimeError("Run was stopped before the approved action could execute.")
        if approval["tool_name"] == "delegate_task":
            args = approval.get("args") or {}
            store.append_run_event(
                session_id,
                run_id=run_id,
                type="subagent",
                label=f"子 Agent {args.get('target_agent', 'researcher')} 启动",
                status="running",
                payload={
                    "approval": approval,
                    "target_agent": args.get("target_agent", "researcher"),
                },
            )
        result = execute_approved_action(
            approval, registry=registry, context={"agent_id": agent_id}
        )
        executed = store.resolve_approval_request(approval_id, status="executed", result=result)
        store.upsert_tool_call(
            session_id,
            run_id=run_id,
            tool_call_id=str(approval["tool_call_id"]),
            name=str(approval["tool_name"]),
            status="done",
            args=approval.get("args") or {},
            result=result,
        )
        if approval["tool_name"] == "delegate_task":
            args = approval.get("args") or {}
            store.append_run_event(
                session_id,
                run_id=run_id,
                type="subagent",
                label=f"子 Agent {args.get('target_agent', 'researcher')} 完成",
                status="done",
                payload={"approval": executed, "result": result},
            )
        store.append_run_event(
            session_id,
            run_id=run_id,
            type="approval",
            label=f"已执行：{approval['tool_name']}",
            status="done",
            payload={"approval": executed},
        )
        continuation_run = None
        if run_manager is not None:
            tool_name = str(approval["tool_name"])
            continuation_message = (
                f"[工具 {tool_name} 已批准执行]\n"
                f"结果：{result[:2000] if result else '执行成功'}"
            )
            continuation_run = await run_manager.create_and_start_run(
                RunCreatePayload(
                    session_id=session_id,
                    message=continuation_message,
                    agent_id=agent_id,
                    metadata={"continuation_after_approval": True},
                    reset_thread=True,
                    skip_user_persist=True,
                )
            )
        response: dict[str, Any] = {
            "approval": executed,
            "result": result,
        }
        if continuation_run is not None:
            response["continuation_run_id"] = str(continuation_run["id"])
        return response
    except Exception as exc:  # noqa: BLE001 - approval execution errors are user-visible.
        failed = store.resolve_approval_request(approval_id, status="failed", error=str(exc))
        store.append_run_event(
            session_id,
            run_id=run_id,
            type="approval",
            label=f"执行失败：{approval['tool_name']}",
            status="error",
            payload={"approval": failed, "error": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def reject_action_impl(store, approval_id: str) -> dict[str, Any]:
    approval = store.get_approval_request(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Approval is already {approval['status']}")
    rejected = store.resolve_approval_request(
        approval_id,
        status="rejected",
        error="Rejected by user",
    )
    store.append_run_event(
        str(approval["session_id"]),
        run_id=str(approval["run_id"]),
        type="approval",
        label=f"已拒绝：{approval['tool_name']}",
        status="error",
        payload={"approval": rejected},
    )
    return {"approval": rejected}

"""Declarative workflow runtime built on WorkerPool."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from ..runtime.background_tasks import CancellationToken
from ..runtime.event_bridge import EventBridge
from ..storage import PostgresAgentStore
from ..workers import WorkerRunner, WorkerTask
from ..workers.context import merge_child_parent_metadata
from .cache import workflow_worker_input_hash
from .models import WorkflowPhaseSpec, WorkflowRunResult, WorkflowSpec
from .phase_runner import PhaseRunner
from .reducers import join_outputs_for_reduce, truncate_text
from .summary import workflow_summary_markdown

_INPUT_TOKEN_RX = re.compile(r"{{\s*inputs\.([a-zA-Z0-9_]+)\s*}}")


class WorkflowRuntime:
    def __init__(
        self,
        store: PostgresAgentStore,
        *,
        worker_runner: WorkerRunner | None = None,
        event_bridge: EventBridge | None = None,
    ) -> None:
        self.store = store
        self._worker_runner = worker_runner
        self._events = event_bridge or EventBridge(store)

    async def run(
        self,
        spec: WorkflowSpec,
        *,
        parent_session_id: str,
        parent_run_id: str,
        inputs: dict[str, Any] | None = None,
        parent_metadata: dict[str, Any] | None = None,
        workflow_run_id: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> WorkflowRunResult:
        token = cancellation_token or CancellationToken()
        try:
            return await asyncio.wait_for(
                self._run_inner(
                    spec,
                    parent_session_id=parent_session_id,
                    parent_run_id=parent_run_id,
                    inputs=inputs,
                    parent_metadata=parent_metadata,
                    workflow_run_id=workflow_run_id,
                    cancellation_token=token,
                ),
                timeout=spec.budget.max_wall_seconds,
            )
        except TimeoutError:
            run = self._workflow_run_for_failure(
                spec=spec,
                parent_session_id=parent_session_id,
                parent_run_id=parent_run_id,
                inputs=inputs,
                workflow_run_id=workflow_run_id,
            )
            message = f"workflow timed out after {spec.budget.max_wall_seconds:g} seconds"
            self.store.workflow_runs.update(
                run["id"],
                status="failed",
                summary=message,
                error_type="TimeoutError",
                error_message=message,
                finished=True,
            )
            return WorkflowRunResult(
                workflow_run_id=run["id"],
                status="failed",
                summary=message,
                outputs=[],
            )

    async def _run_inner(
        self,
        spec: WorkflowSpec,
        *,
        parent_session_id: str,
        parent_run_id: str,
        inputs: dict[str, Any] | None,
        parent_metadata: dict[str, Any] | None,
        workflow_run_id: str | None,
        cancellation_token: CancellationToken,
    ) -> WorkflowRunResult:
        resolved_inputs = dict(spec.inputs)
        if inputs:
            resolved_inputs.update(inputs)
        self._validate_spec(spec)
        self.store.workflow_specs.upsert(
            spec_id=spec.id,
            name=spec.name,
            description=spec.description,
            spec=spec.as_dict(),
            metadata=spec.metadata,
        )
        if workflow_run_id:
            existing = self.store.workflow_runs.get(workflow_run_id)
            if existing is None:
                raise KeyError(f"unknown workflow run: {workflow_run_id}")
            run = existing
        else:
            run = self.store.workflow_runs.create(
                spec_id=spec.id,
                parent_session_id=parent_session_id,
                parent_run_id=parent_run_id,
                inputs=resolved_inputs,
            )
            workflow_run_id = run["id"]
        self.store.workflow_runs.update(workflow_run_id, status="running")
        self._events.emit_workflow_event(
            "workflow_run_started",
            session_id=parent_session_id,
            parent_run_id=parent_run_id,
            workflow_run_id=workflow_run_id,
            status="running",
        )

        phase_outputs: dict[str, list[str]] = {}
        existing_phase_runs = {
            phase_run["phase_id"]: phase_run
            for phase_run in self.store.workflow_phase_runs.list_for_run(workflow_run_id)
        }
        worker_count = 0
        workflow_status = "completed"
        try:
            for phase in spec.phases:
                cancellation_token.raise_if_cancelled()
                existing_phase_run = existing_phase_runs.get(phase.id)
                if existing_phase_run and existing_phase_run["status"] == "completed":
                    phase_outputs[phase.id] = list(existing_phase_run.get("outputs") or [])
                    self._events.emit_workflow_event(
                        "workflow_phase_skipped",
                        session_id=parent_session_id,
                        parent_run_id=parent_run_id,
                        workflow_run_id=workflow_run_id,
                        phase_run_id=existing_phase_run["id"],
                        workflow_phase_id=phase.id,
                        status="completed",
                        payload={"reason": "completed_phase_reused"},
                    )
                    continue

                phase_run = existing_phase_run or self.store.workflow_phase_runs.create(
                    workflow_run_id=workflow_run_id,
                    phase_id=phase.id,
                    kind=phase.kind,
                    agent=phase.agent,
                    metadata=phase.metadata,
                )
                self.store.workflow_phase_runs.update(
                    phase_run["id"],
                    status="running",
                    outputs=[],
                    error_type="",
                    error_message="",
                )
                self._events.emit_workflow_event(
                    "workflow_phase_started",
                    session_id=parent_session_id,
                    parent_run_id=parent_run_id,
                    workflow_run_id=workflow_run_id,
                    phase_run_id=phase_run["id"],
                    workflow_phase_id=phase.id,
                    status="running",
                )
                worker_tasks = self._build_worker_tasks(
                    phase=phase,
                    workflow_spec_id=spec.id,
                    phase_run_id=phase_run["id"],
                    workflow_run_id=workflow_run_id,
                    parent_session_id=parent_session_id,
                    parent_run_id=parent_run_id,
                    parent_metadata=parent_metadata,
                    inputs=resolved_inputs,
                    phase_outputs=phase_outputs,
                )
                worker_count += len(worker_tasks)
                if worker_count > spec.budget.max_workers:
                    message = f"workflow exceeds max_workers budget: {spec.budget.max_workers}"
                    self.store.workflow_phase_runs.update(
                        phase_run["id"],
                        status="failed",
                        outputs=[message],
                        finished=True,
                    )
                    self.store.workflow_runs.update(
                        workflow_run_id,
                        status="failed",
                        summary=message,
                        finished=True,
                    )
                    raise ValueError(message)

                results = await PhaseRunner(
                    store=self.store,
                    worker_runner=self._worker_runner,
                    max_concurrency=spec.max_concurrency,
                ).run(worker_tasks, cancellation_token=cancellation_token)
                outputs = [truncate_text(result.final_response, 2000) for result in results]
                for index, result in enumerate(results):
                    worker = self.store.workflow_worker_runs.create(
                        workflow_run_id=workflow_run_id,
                        phase_run_id=phase_run["id"],
                        worker_index=index,
                        task_id=result.task_id,
                        role=result.role_id,
                        status=result.status,
                        output=truncate_text(result.final_response, 2000),
                        subagent_run_id=result.subagent_id,
                        child_session_id=result.child_session_id,
                        cache_key=str(result.metadata.get("cache_key") or "")
                        if result.metadata
                        else "",
                        input_hash=str(result.metadata.get("input_hash") or "")
                        if result.metadata
                        else "",
                        cache_hit=bool(result.metadata.get("cache_hit"))
                        if result.metadata
                        else False,
                        error_type=str(result.metadata.get("error_type") or "")
                        if result.metadata
                        else "",
                        error_message="" if result.status == "completed" else result.final_response,
                        metadata=result.metadata,
                    )
                    self._events.emit_workflow_event(
                        "workflow_worker_completed"
                        if result.status == "completed"
                        else "workflow_worker_failed",
                        session_id=parent_session_id,
                        parent_run_id=parent_run_id,
                        workflow_run_id=workflow_run_id,
                        phase_run_id=phase_run["id"],
                        workflow_phase_id=phase.id,
                        worker_run_id=worker["id"],
                        status=result.status,
                    )
                phase_status = (
                    "completed"
                    if all(result.status == "completed" for result in results)
                    else "failed"
                )
                if phase_status == "failed":
                    workflow_status = "failed"
                phase_outputs[phase.id] = outputs
                self.store.workflow_phase_runs.update(
                    phase_run["id"],
                    status=phase_status,
                    outputs=outputs,
                    finished=True,
                )
                self._events.emit_workflow_event(
                    "workflow_phase_completed"
                    if phase_status == "completed"
                    else "workflow_phase_failed",
                    session_id=parent_session_id,
                    parent_run_id=parent_run_id,
                    workflow_run_id=workflow_run_id,
                    phase_run_id=phase_run["id"],
                    workflow_phase_id=phase.id,
                    status=phase_status,
                )
        except asyncio.CancelledError:
            self.store.workflow_runs.update(workflow_run_id, status="stopped", finished=True)
            self._events.emit_workflow_event(
                "background_run_cancelled",
                session_id=parent_session_id,
                parent_run_id=parent_run_id,
                workflow_run_id=workflow_run_id,
                status="cancelled",
            )
            raise
        except ValueError:
            raise

        summary = workflow_summary_markdown(
            workflow_name=spec.name,
            status=workflow_status,
            phase_outputs=phase_outputs,
        )
        self.store.workflow_runs.update(
            workflow_run_id,
            status=workflow_status,
            summary=summary,
            finished=True,
        )
        self._events.emit_workflow_event(
            "workflow_run_completed" if workflow_status == "completed" else "workflow_run_failed",
            session_id=parent_session_id,
            parent_run_id=parent_run_id,
            workflow_run_id=workflow_run_id,
            status=workflow_status,
        )
        final_outputs = phase_outputs.get(spec.phases[-1].id, []) if spec.phases else []
        return WorkflowRunResult(
            workflow_run_id=workflow_run_id,
            status=workflow_status,
            summary=summary,
            outputs=final_outputs,
        )

    def _workflow_run_for_failure(
        self,
        *,
        spec: WorkflowSpec,
        parent_session_id: str,
        parent_run_id: str,
        inputs: dict[str, Any] | None,
        workflow_run_id: str | None,
    ) -> dict[str, Any]:
        if workflow_run_id:
            existing = self.store.workflow_runs.get(workflow_run_id)
            if existing is not None:
                return existing
        resolved_inputs = dict(spec.inputs)
        if inputs:
            resolved_inputs.update(inputs)
        self.store.workflow_specs.upsert(
            spec_id=spec.id,
            name=spec.name,
            description=spec.description,
            spec=spec.as_dict(),
            metadata=spec.metadata,
        )
        return self.store.workflow_runs.create(
            spec_id=spec.id,
            parent_session_id=parent_session_id,
            parent_run_id=parent_run_id,
            inputs=resolved_inputs,
        )

    def _build_worker_tasks(
        self,
        *,
        phase: WorkflowPhaseSpec,
        workflow_spec_id: str,
        phase_run_id: str,
        workflow_run_id: str,
        parent_session_id: str,
        parent_run_id: str,
        parent_metadata: dict[str, Any] | None,
        inputs: dict[str, Any],
        phase_outputs: dict[str, list[str]],
    ) -> list[WorkerTask]:
        items = self._phase_items(phase, inputs=inputs, phase_outputs=phase_outputs)
        tasks = []
        for index, item in enumerate(items):
            prompt = self._render_prompt(phase.prompt, item=item, inputs=inputs)
            input_hash = workflow_worker_input_hash(
                role_id=phase.agent,
                prompt=prompt,
                workflow_spec_id=workflow_spec_id,
                workflow_phase_id=phase.id,
                item=item,
            )
            metadata = merge_child_parent_metadata(
                parent_metadata,
                {
                    "workflow_run_id": workflow_run_id,
                    "workflow_phase_id": phase.id,
                    "phase_run_id": phase_run_id,
                    "input_hash": input_hash,
                    "cache_key": input_hash,
                },
            )
            tasks.append(
                WorkerTask(
                    id=f"{phase_run_id}:{index}",
                    role_id=phase.agent,
                    task=prompt,
                    reason=f"Workflow phase {phase.id}",
                    parent_session_id=parent_session_id,
                    parent_run_id=parent_run_id,
                    agent_id=str(metadata.get("agent_id") or "default"),
                    metadata=metadata,
                    attempt_index=index,
                    approval_id=str(metadata.get("approval_id") or ""),
                )
            )
        return tasks

    def _phase_items(
        self,
        phase: WorkflowPhaseSpec,
        *,
        inputs: dict[str, Any],
        phase_outputs: dict[str, list[str]],
    ) -> list[Any]:
        value = self._resolve_ref(phase.input_ref, inputs=inputs, phase_outputs=phase_outputs)
        if phase.kind == "reduce":
            values = _as_list(value)
            return [join_outputs_for_reduce([str(item) for item in values])]
        if phase.kind == "single":
            return [value if value is not None else ""]
        return _as_list(value)

    @staticmethod
    def _resolve_ref(
        ref: str,
        *,
        inputs: dict[str, Any],
        phase_outputs: dict[str, list[str]],
    ) -> Any:
        if not ref:
            return ""
        if ref.startswith("inputs."):
            return inputs.get(ref.removeprefix("inputs."))
        if ref.startswith("phases.") and ref.endswith(".outputs"):
            phase_id = ref.removeprefix("phases.")[: -len(".outputs")]
            return phase_outputs.get(phase_id, [])
        return ref

    @staticmethod
    def _render_prompt(prompt: str, *, item: Any, inputs: dict[str, Any]) -> str:
        rendered = prompt.replace("{{ item }}", str(item))

        def replace_input(match: re.Match[str]) -> str:
            return str(inputs.get(match.group(1), ""))

        return _INPUT_TOKEN_RX.sub(replace_input, rendered)

    @staticmethod
    def _validate_spec(spec: WorkflowSpec) -> None:
        if spec.max_concurrency < 1:
            raise ValueError("workflow max_concurrency must be >= 1")
        if spec.budget.max_workers < 1:
            raise ValueError("workflow budget max_workers must be >= 1")
        phase_ids: set[str] = set()
        for phase in spec.phases:
            if phase.id in phase_ids:
                raise ValueError(f"duplicate workflow phase id: {phase.id}")
            phase_ids.add(phase.id)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]

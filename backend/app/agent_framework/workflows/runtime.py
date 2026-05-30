"""Declarative workflow runtime built on WorkerPool."""

from __future__ import annotations

import re
from typing import Any

from ..storage import PostgresAgentStore
from ..workers import WorkerPool, WorkerRunner, WorkerTask
from ..workers.context import merge_child_parent_metadata
from .models import WorkflowPhaseSpec, WorkflowRunResult, WorkflowSpec
from .reducers import join_outputs_for_reduce, truncate_text
from .summary import workflow_summary_markdown

_INPUT_TOKEN_RX = re.compile(r"{{\s*inputs\.([a-zA-Z0-9_]+)\s*}}")


class WorkflowRuntime:
    def __init__(
        self,
        store: PostgresAgentStore,
        *,
        worker_runner: WorkerRunner | None = None,
    ) -> None:
        self.store = store
        self._worker_runner = worker_runner

    async def run(
        self,
        spec: WorkflowSpec,
        *,
        parent_session_id: str,
        parent_run_id: str,
        inputs: dict[str, Any] | None = None,
        parent_metadata: dict[str, Any] | None = None,
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
        run = self.store.workflow_runs.create(
            spec_id=spec.id,
            parent_session_id=parent_session_id,
            parent_run_id=parent_run_id,
            inputs=resolved_inputs,
        )
        workflow_run_id = run["id"]
        self.store.workflow_runs.update(workflow_run_id, status="running")

        phase_outputs: dict[str, list[str]] = {}
        worker_count = 0
        workflow_status = "completed"
        try:
            for phase in spec.phases:
                phase_run = self.store.workflow_phase_runs.create(
                    workflow_run_id=workflow_run_id,
                    phase_id=phase.id,
                    kind=phase.kind,
                    agent=phase.agent,
                    metadata=phase.metadata,
                )
                self.store.workflow_phase_runs.update(phase_run["id"], status="running")
                worker_tasks = self._build_worker_tasks(
                    phase=phase,
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

                results = await WorkerPool(
                    store=self.store,
                    runner=self._worker_runner,
                    max_concurrency=spec.max_concurrency,
                ).run(worker_tasks)
                outputs = [truncate_text(result.final_response, 2000) for result in results]
                for index, result in enumerate(results):
                    self.store.workflow_worker_runs.create(
                        workflow_run_id=workflow_run_id,
                        phase_run_id=phase_run["id"],
                        worker_index=index,
                        task_id=result.task_id,
                        role=result.role_id,
                        status=result.status,
                        output=truncate_text(result.final_response, 2000),
                        subagent_run_id=result.subagent_id,
                        child_session_id=result.child_session_id,
                        metadata=result.metadata,
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
        final_outputs = phase_outputs.get(spec.phases[-1].id, []) if spec.phases else []
        return WorkflowRunResult(
            workflow_run_id=workflow_run_id,
            status=workflow_status,
            summary=summary,
            outputs=final_outputs,
        )

    def _build_worker_tasks(
        self,
        *,
        phase: WorkflowPhaseSpec,
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
            metadata = merge_child_parent_metadata(
                parent_metadata,
                {
                    "workflow_run_id": workflow_run_id,
                    "workflow_phase_id": phase.id,
                    "phase_run_id": phase_run_id,
                },
            )
            tasks.append(
                WorkerTask(
                    id=f"{phase_run_id}:{index}",
                    role_id=phase.agent,
                    task=self._render_prompt(phase.prompt, item=item, inputs=inputs),
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

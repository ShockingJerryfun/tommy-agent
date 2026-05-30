import { expect, test } from "./fixtures";

test("flushes streamed assistant tokens when animation frames are throttled", async ({
  mockBackend,
  page,
}) => {
  mockBackend.streamBody =
    'event: token\ndata: {"type":"token","data":{"content":"live-token"}}\n\n';

  await page.addInitScript(() => {
    window.requestAnimationFrame = () => 1;
    window.cancelAnimationFrame = () => {};
  });

  await page.goto("/");
  await page.locator("textarea#agent-message").fill("Stream a token");
  await page.getByRole("button", { name: "发送消息" }).click();

  await expect(page.getByText("live-token")).toBeVisible();
});

test("renders replayed run message deltas during regenerate subscriptions", async ({
  mockBackend,
  page,
}) => {
  mockBackend.streamBody =
    'event: message_delta\ndata: {"type":"message_delta","data":{"content":"delta-token","run_id":"run-retry","sequence":1}}\n\n';

  await page.goto("/");
  await page.getByRole("button", { name: "重新生成" }).click();

  await expect(page.getByText("delta-token")).toBeVisible();
});

test("leaves generating state when a run ends with a streamed error", async ({
  mockBackend,
  page,
}) => {
  mockBackend.streamBody = [
    'event: model_error\ndata: {"type":"model_error","data":{"message":"运行超过 150 秒未完成，已自动停止。","run_id":"run-timeout","sequence":1}}\n\n',
    'event: error\ndata: {"type":"error","data":{"message":"运行超过 150 秒未完成，已自动停止。","run_id":"run-timeout","sequence":2}}\n\n',
    'event: done\ndata: {"type":"done","data":{"status":"done","run_id":"run-timeout","sequence":3}}\n\n',
  ].join("");

  await page.goto("/");
  await page.locator("textarea#agent-message").fill("Trigger timeout");
  await page.getByRole("button", { name: "发送消息" }).click();

  await expect(page.getByText("生成中").first()).toBeHidden();
  await expect(page.getByRole("button", { name: "停止生成" })).toBeHidden();
  await expect(page.getByText("Ready").first()).toBeVisible();
});

test("renders multi-agent team and workflow progress from SSE", async ({
  mockBackend,
  page,
}) => {
  const replayEvents: NonNullable<typeof mockBackend.runEvents> = [
    {
      id: "evt-team-run-start",
      run_id: "run-asst-1",
      type: "team_run_started",
      label: "team_run_started",
      status: "running",
      payload: { team_run_id: "team-run-alpha", team_id: "team-alpha" },
      sequence: 1,
      created_at: "2026-04-28T15:00:00.000Z",
    },
    {
      id: "evt-team-task-done",
      run_id: "run-asst-1",
      type: "team_task_completed",
      label: "team_task_completed",
      status: "done",
      payload: {
        team_run_id: "team-run-alpha",
        team_id: "team-alpha",
        team_task_id: "team-task-review",
        child_session_id: "child-team-review",
      },
      sequence: 2,
      created_at: "2026-04-28T15:00:01.000Z",
    },
    {
      id: "evt-workflow-phase",
      run_id: "run-asst-1",
      type: "workflow_phase_started",
      label: "workflow_phase_started",
      status: "running",
      payload: {
        workflow_run_id: "workflow-beta",
        workflow_phase_id: "inspect",
        phase_run_id: "phase-inspect",
      },
      sequence: 3,
      created_at: "2026-04-28T15:00:02.000Z",
    },
    {
      id: "evt-workflow-worker",
      run_id: "run-asst-1",
      type: "workflow_worker_completed",
      label: "workflow_worker_completed",
      status: "done",
      payload: {
        workflow_run_id: "workflow-beta",
        workflow_phase_id: "inspect",
        phase_run_id: "phase-inspect",
        worker_run_id: "worker-1",
      },
      sequence: 4,
      created_at: "2026-04-28T15:00:03.000Z",
    },
    {
      id: "evt-workflow-phase-done",
      run_id: "run-asst-1",
      type: "workflow_phase_completed",
      label: "workflow_phase_completed",
      status: "done",
      payload: {
        workflow_run_id: "workflow-beta",
        workflow_phase_id: "inspect",
        phase_run_id: "phase-inspect",
      },
      sequence: 5,
      created_at: "2026-04-28T15:00:04.000Z",
    },
  ];
  mockBackend.streamBody = [
    'event: team_run_started\ndata: {"type":"team_run_started","data":{"team_run_id":"team-run-alpha","team_id":"team-alpha","status":"running","sequence":1}}\n\n',
    'event: team_task_started\ndata: {"type":"team_task_started","data":{"team_run_id":"team-run-alpha","team_id":"team-alpha","team_task_id":"team-task-review","status":"running","sequence":2}}\n\n',
    'event: team_task_completed\ndata: {"type":"team_task_completed","data":{"team_run_id":"team-run-alpha","team_id":"team-alpha","team_task_id":"team-task-review","child_session_id":"child-team-review","status":"done","sequence":3}}\n\n',
    'event: workflow_run_started\ndata: {"type":"workflow_run_started","data":{"workflow_run_id":"workflow-beta","status":"running","sequence":4}}\n\n',
    'event: workflow_phase_started\ndata: {"type":"workflow_phase_started","data":{"workflow_run_id":"workflow-beta","workflow_phase_id":"inspect","phase_run_id":"phase-inspect","status":"running","sequence":5}}\n\n',
    'event: workflow_worker_completed\ndata: {"type":"workflow_worker_completed","data":{"workflow_run_id":"workflow-beta","workflow_phase_id":"inspect","phase_run_id":"phase-inspect","worker_run_id":"worker-1","status":"done","sequence":6}}\n\n',
    'event: workflow_phase_completed\ndata: {"type":"workflow_phase_completed","data":{"workflow_run_id":"workflow-beta","workflow_phase_id":"inspect","phase_run_id":"phase-inspect","status":"done","sequence":7}}\n\n',
    'event: done\ndata: {"type":"done","data":{"status":"done","sequence":8}}\n\n',
  ].join("");

  await page.goto("/");
  await expect(page.getByText("这里是 GFM", { exact: false }).first()).toBeVisible();
  await page.locator("textarea#agent-message").fill("Run a multi-agent audit");
  mockBackend.runEvents = replayEvents;
  await page.getByRole("button", { name: "发送消息" }).click();

  await expect(page.getByText("Multi-agent", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Team alpha", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Workflow beta", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("review · done").first()).toBeVisible();
  await expect(page.getByText("inspect · done").first()).toBeVisible();
  await expect(page.getByText("child review").first()).toBeVisible();
});

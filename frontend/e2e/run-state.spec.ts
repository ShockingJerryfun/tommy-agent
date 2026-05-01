import { expect, test } from "./fixtures";

test("surfaces verification as an explicit run stage", async ({
  page,
  mockBackend,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "desktop run graph only");

  mockBackend.runEvents = [
    {
      id: "event-verification-start",
      run_id: "run-verification",
      type: "verification_start",
      label: "开始验证",
      status: "running",
      payload: { attempt: 1, max_attempts: 2 },
      sequence: 1,
      created_at: "2026-04-28T15:00:01.000Z",
    },
    {
      id: "event-verification-end",
      run_id: "run-verification",
      type: "verification_end",
      label: "验证通过",
      status: "done",
      payload: { status: "passed", summary: "验证通过：执行了 1 个 verifier 命令。" },
      sequence: 2,
      created_at: "2026-04-28T15:00:02.000Z",
    },
  ];
  await page.goto("/");

  await expect(page.getByText("任务验证").first()).toBeVisible();
  await expect(page.getByText("验证通过").first()).toBeVisible();
});

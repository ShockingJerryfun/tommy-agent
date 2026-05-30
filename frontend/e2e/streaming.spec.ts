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

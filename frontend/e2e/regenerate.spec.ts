import { ASSISTANT_MESSAGE_ID, expect, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

test("starts and resolves an assistant regeneration run", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(`#message-${ASSISTANT_MESSAGE_ID}`)).toBeVisible();

  const regenerateResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes(`/api/messages/${ASSISTANT_MESSAGE_ID}/regenerate`),
  );

  await page
    .locator(`#message-${ASSISTANT_MESSAGE_ID}`)
    .getByRole("button", { name: "重新生成" })
    .click();

  await regenerateResponse;
  await expect(page.getByText("生成中").first()).toBeHidden();
});

test("retries a failed client-only assistant response by resending the stream request", async ({ page }) => {
  let streamAttempts = 0;
  const streamRequests: string[] = [];
  const regenerateRequests: string[] = [];

  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/api\/messages\/.+\/regenerate$/.test(request.url())
    ) {
      regenerateRequests.push(request.url());
    }
  });

  await page.route(/.*\/api\/chat\/stream$/, async (route) => {
    streamAttempts += 1;
    streamRequests.push(route.request().url());
    if (streamAttempts > 1) {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: "event: done\ndata: {}\n\n",
      });
      return;
    }
    await route.fulfill({
      status: 500,
      contentType: "text/plain",
      body: "simulated stream failure",
    });
  });

  await page.goto("/");
  await page.locator("textarea#agent-message").fill("Trigger a retryable failure");
  await page.getByRole("button", { name: "发送消息" }).click();

  await expect(page.getByText("服务繁忙 (5xx)")).toBeVisible();

  await page.getByRole("button", { name: "重试" }).click();

  await expect.poll(() => streamAttempts).toBe(2);
  expect(regenerateRequests).toEqual([]);
  expect(streamRequests[1]).toContain("/agent-api/api/chat/stream");
});

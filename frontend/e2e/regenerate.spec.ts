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

test("retries a failed assistant response with the original idempotency key", async ({ page }) => {
  await page.route(/.*\/api\/chat\/stream$/, async (route) => {
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

  const retryResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/messages\/.+\/regenerate$/.test(response.url()),
  );

  await page.getByRole("button", { name: "重试" }).click();
  await retryResponse;
});

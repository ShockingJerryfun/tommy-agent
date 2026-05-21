import { expect, test } from "./fixtures";

test("composer is streamlined and enter sends", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("工作目录")).toHaveCount(0);
  await expect(page.getByText("命令范围")).toHaveCount(0);
  await expect(page.getByText(/Tommy 可能出错/)).toHaveCount(0);

  const composer = page.locator("textarea#agent-message");
  await composer.fill("Enter should send");

  const streamRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().includes("/api/chat/stream"),
  );
  await composer.press("Enter");
  await streamRequest;

  await expect(page.getByRole("log").getByText("Enter should send")).toBeVisible();
});

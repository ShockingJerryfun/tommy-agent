import { expect, test } from "./fixtures";

test("composer is streamlined and enter sends", async ({ page }, testInfo) => {
  await page.goto("/");

  await expect(page.getByText("工作目录")).toHaveCount(0);
  await expect(page.getByText("命令范围")).toHaveCount(0);
  await expect(page.getByText(/Tommy 可能出错/)).toHaveCount(0);
  await expect(page.getByText("5.5 高")).toHaveCount(0);

  const composer = page.locator("textarea#agent-message");
  const composerSurface = page.locator(".ios-composer-surface").first();
  await expect(composerSurface).toBeVisible();
  if (testInfo.project.name === "mobile-iphone-12") {
    const composerBox = await composerSurface.boundingBox();
    expect(composerBox?.height ?? 0).toBeGreaterThanOrEqual(110);
  }

  await composer.fill("Enter should send");

  const streamRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().includes("/api/chat/stream"),
  );
  await composer.press("Enter");
  await streamRequest;

  await expect(page.getByRole("log").getByText("Enter should send")).toBeVisible();
});

import { expect, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

test("renders shared conversation as read-only", async ({ page }) => {
  await page.goto("/share/test-token");

  await expect(page.getByText("公开只读视图")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("textarea#agent-message")).toHaveCount(0);
});

test("creates a share link from the session menu", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes("mobile"), "Session management menu is desktop-only.");

  await page.goto("/");

  await page.getByRole("button", { name: /更多操作：E2E UX Parity/ }).click();

  const shareResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes("/api/sessions/session-e2e-1/share"),
  );

  await page.getByRole("button", { name: "Share" }).click();
  await shareResponse;

  await expect(page.getByText("/share/test-token")).toBeVisible();
});

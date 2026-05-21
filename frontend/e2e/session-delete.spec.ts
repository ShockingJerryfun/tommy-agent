import { expect, test } from "./fixtures";

test("deletes a session directly from the menu", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name.includes("mobile"),
    "Session management menu is desktop-only.",
  );

  let sawDialog = false;
  page.on("dialog", async (dialog) => {
    sawDialog = true;
    await dialog.dismiss();
  });

  await page.goto("/");
  await page.getByRole("button", { name: /更多操作：E2E UX Parity/ }).click();

  const deleteResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "DELETE" &&
      response.url().includes("/api/sessions/session-e2e-1"),
  );

  await page.getByRole("button", { name: "删除" }).click();

  await deleteResponse;
  expect(sawDialog).toBe(false);
});

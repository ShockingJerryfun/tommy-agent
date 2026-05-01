import { expect, test, USER_MESSAGE_ID } from "./fixtures";

test.describe.configure({ mode: "serial" });

test("searches messages and jumps to the selected result", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes("mobile"), "Search UI is in the desktop sidebar.");

  await page.goto("/");

  await page.getByPlaceholder("搜索消息").fill("KaTeX");
  await expect(page.getByText("搜索结果")).toBeVisible();

  const result = page.getByRole("button").filter({ hasText: "测试 KaTeX 与代码" });
  await expect(result).toBeVisible();

  await result.click();

  const box = await page.locator(`#message-${USER_MESSAGE_ID}`).boundingBox();
  expect(box).not.toBeNull();
  expect(box?.y ?? 0).toBeGreaterThanOrEqual(0);
});

import { expect, test, USER_MESSAGE_ID } from "./fixtures";

test.describe.configure({ mode: "serial" });

test("edits a user message inline", async ({ page }) => {
  await page.goto("/");

  const userMessage = page.locator(`#message-${USER_MESSAGE_ID}`);
  await userMessage.getByRole("button", { name: "编辑消息" }).click();

  const editor = userMessage.locator('textarea[aria-label="编辑消息"]');
  await expect(editor).toBeVisible();
  await editor.fill("测试 KaTeX 与代码：$x^2$ 追加内容");
  await userMessage.getByRole("button", { name: "Save", exact: true }).click();

  await expect(editor).toHaveCount(0);
  await expect(userMessage.getByText("追加内容")).toBeVisible();
});

test("edits a historical message and reruns from that point", async ({ page }) => {
  await page.goto("/");

  const userMessage = page.locator(`#message-${USER_MESSAGE_ID}`);
  await userMessage.getByRole("button", { name: "编辑消息" }).click();

  const editor = userMessage.locator('textarea[aria-label="编辑消息"]');
  await editor.fill("从这条历史消息重新运行");

  const rerunResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes(`/api/messages/${USER_MESSAGE_ID}/rerun`),
  );

  await userMessage.getByRole("button", { name: "Save & Rerun" }).click();

  await rerunResponse;
  await expect(editor).toHaveCount(0);
  await expect(userMessage.getByText("从这条历史消息重新运行")).toBeVisible();
  await expect(page.getByText("生成中").first()).toBeHidden();
});

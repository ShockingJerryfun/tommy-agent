import { ASSISTANT_MESSAGE_ID, expect, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

test("copies assistant message and code block", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(`#message-${ASSISTANT_MESSAGE_ID}`)).toBeVisible();

  const assistant = page.locator(`#message-${ASSISTANT_MESSAGE_ID}`);
  await assistant.getByRole("button", { name: "复制消息" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Copied" }).first()).toBeVisible({
    timeout: 2_000,
  });

  await assistant.locator(".message-code-block").getByRole("button", { name: "复制代码" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Copied" }).first()).toBeVisible({
    timeout: 2_000,
  });
});

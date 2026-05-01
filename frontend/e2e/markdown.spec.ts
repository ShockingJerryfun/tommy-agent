import { ASSISTANT_MESSAGE_ID, expect, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

test("renders KaTeX, code labels, and code copy affordance", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".katex").first()).toBeVisible();

  const assistant = page.locator(`#message-${ASSISTANT_MESSAGE_ID}`);
  const codeBlock = assistant.locator(".message-code-block");
  await expect(codeBlock.locator(".message-code-block__header").getByText("python")).toBeVisible();

  await codeBlock.getByRole("button", { name: "复制代码" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Copied" })).toBeVisible({
    timeout: 2_000,
  });
});

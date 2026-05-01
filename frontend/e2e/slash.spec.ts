import { expect, FIRST_PROMPT_BODY, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

test("inserts a built-in slash prompt", async ({ page }) => {
  await page.goto("/");
  const composer = page.locator("textarea#agent-message");

  await composer.focus();
  await composer.fill("/");

  await expect(page.getByRole("listbox", { name: "内置提示" })).toBeVisible();
  await expect(page.getByRole("option").filter({ hasText: "Summarize" })).toHaveCount(1);

  await composer.press("ArrowDown");
  await composer.press("Enter");

  await expect(composer).toHaveValue(new RegExp(`^${escapeRegExp(FIRST_PROMPT_BODY)}`));
});

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

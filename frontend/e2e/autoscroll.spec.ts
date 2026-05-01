import { expect, longConversationMessages, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

test("shows jump-to-bottom pill after scrolling away from latest message", async ({
  mockBackend,
  page,
}) => {
  mockBackend.messages = longConversationMessages(30);

  await page.goto("/");
  const log = page.getByRole("log");
  await expect(log.getByText("测试 长消息 30")).toBeVisible();

  await log.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
    element.scrollTop -= 200;
    element.dispatchEvent(new Event("scroll", { bubbles: true }));
  });

  await expect(page.getByRole("button", { name: "跳到底部" })).toBeVisible();
  await page.getByRole("button", { name: "跳到底部" }).click();

  const distanceFromBottom = await log.evaluate(
    (element) => element.scrollHeight - element.scrollTop - element.clientHeight,
  );
  expect(Math.abs(distanceFromBottom)).toBeLessThanOrEqual(8);
});

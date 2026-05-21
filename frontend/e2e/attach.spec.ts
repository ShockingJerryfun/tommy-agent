import { writeFile } from "node:fs/promises";

import { expect, PNG_1X1, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

test("uploads an image attachment and shows a filename chip", async ({ page }, testInfo) => {
  await page.goto("/");

  const avatarPath = testInfo.outputPath("avatar.png");
  await writeFile(avatarPath, PNG_1X1);

  await page.locator('input[type="file"][accept]').setInputFiles(avatarPath);
  await expect(page.getByText("avatar.png")).toBeVisible();
});

test("sends an image attachment with a chat message", async ({ page }, testInfo) => {
  await page.goto("/");

  const avatarPath = testInfo.outputPath("avatar-send.png");
  await writeFile(avatarPath, PNG_1X1);

  await page.locator('input[type="file"][accept]').setInputFiles(avatarPath);
  await page.locator("textarea#agent-message").fill("What is in this image?");

  const streamRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().includes("/api/chat/stream"),
  );

  await page.getByRole("button", { name: "发送消息" }).click();
  await streamRequest;

  const messageLog = page.getByRole("log");
  await expect(messageLog.getByText("What is in this image?")).toBeVisible();
  await expect(messageLog.getByRole("link", { name: /打开附件 avatar\.png/ })).toBeVisible();
});

import type { Locator } from "@playwright/test";

import { expect, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

async function surfaceStyle(locator: Locator) {
  return locator.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      backgroundColor: style.backgroundColor,
      backdropFilter: style.backdropFilter,
      borderStyle: style.borderStyle,
      borderRadius: style.borderRadius,
      boxShadow: style.boxShadow,
    };
  });
}

test("desktop shell uses Apple admin surface tokens", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "desktop only");

  await page.goto("/");

  const tokens = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    return {
      page: root.getPropertyValue("--primary-bg").trim(),
      card: root.getPropertyValue("--card-bg").trim(),
      sidebarShadow: root.getPropertyValue("--sidebar-shadow").trim(),
      radius: root.getPropertyValue("--apple-corner-phone").trim(),
    };
  });

  expect(tokens).toEqual({
    page: "#F8F9FB",
    card: "#FFFFFF",
    sidebarShadow: "0 4px 20px rgba(0, 0, 0, 0.15)",
    radius: "16px",
  });

  const sidebar = page.locator("aside").first();
  await expect(sidebar).toBeVisible();
  const sidebarStyle = await sidebar.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      backgroundColor: style.backgroundColor,
      backdropFilter: style.backdropFilter,
      borderStyle: style.borderStyle,
      borderRadius: style.borderRadius,
      boxShadow: style.boxShadow,
    };
  });

  expect(sidebarStyle.backgroundColor).toBe("rgba(255, 255, 255, 0.82)");
  expect(sidebarStyle.backdropFilter).toContain("blur(24px)");
  expect(sidebarStyle.borderStyle).toBe("none");
  expect(sidebarStyle.borderRadius).toBe("16px");
  expect(sidebarStyle.boxShadow).toContain("rgba(15, 23, 42, 0.11)");
});

test("desktop components share borderless Apple admin card treatment", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "desktop only");

  await page.goto("/");

  const surfaces = [
    page.locator(".app-chat-surface").first(),
    page.locator(".ios-composer-surface").first(),
    page.locator(".message-code-block").first(),
  ];

  for (const surface of surfaces) {
    await expect(surface).toBeVisible();
    const style = await surfaceStyle(surface);
    expect(style.backgroundColor).toContain("rgba(255, 255, 255");
    expect(style.backdropFilter).toContain("blur(");
    expect(style.borderStyle).toBe("none");
    expect(style.boxShadow).toContain("rgba(15, 23, 42");
  }

  const rightPanel = page.locator(".right-panel-stack .resizable-inspector-panel").first();
  await expect(rightPanel).toBeVisible();
  const rightPanelStyle = await surfaceStyle(rightPanel);
  expect(rightPanelStyle.backgroundColor).toContain("rgba(255, 255, 255");
  expect(rightPanelStyle.backdropFilter).toContain("blur(");
  expect(rightPanelStyle.borderStyle).toBe("none");
  expect(rightPanelStyle.boxShadow).not.toContain("rgba(15, 23, 42");

  const toolbar = page.locator(".admin-toolbar").first();
  await expect(toolbar).toBeVisible();
  const toolbarStyle = await surfaceStyle(toolbar);
  expect(toolbarStyle.backgroundColor).toBe("rgba(0, 0, 0, 0)");
  expect(toolbarStyle.borderStyle).toBe("none");
  expect(toolbarStyle.boxShadow).toBe("none");
});

test("share page uses the same admin card system", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "desktop only");

  await page.goto("/share/test-token");

  const pageCard = page.locator("main > .admin-card").first();
  const messageCard = page.locator(".markdown-body.admin-card").first();
  const headerToolbar = page.locator(".admin-toolbar").first();

  for (const surface of [pageCard, messageCard, headerToolbar]) {
    await expect(surface).toBeVisible();
    const style = await surfaceStyle(surface);
    expect(style.borderStyle).toBe("none");
    expect(style.borderRadius).not.toBe("0px");
  }
});

test("mobile navigation aligns with desktop controls without oversized buttons", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-iphone-12", "mobile only");

  await page.goto("/");

  const menuButton = page.getByRole("button", { name: "打开对话列表" });
  await expect(menuButton).toBeVisible();
  await expect(page.getByRole("button", { name: "新建对话" })).toBeVisible();
  await expect(page.getByRole("button", { name: "打开状态和设置" })).toBeVisible();
  await expect(page.getByText(/Tommy|Session/).first()).toBeVisible();

  const style = await menuButton.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const computed = getComputedStyle(element);
    return {
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      backgroundColor: computed.backgroundColor,
      backdropFilter: computed.backdropFilter,
      borderRadius: computed.borderRadius,
      boxShadow: computed.boxShadow,
    };
  });

  expect(style.width).toBeGreaterThanOrEqual(52);
  expect(style.height).toBeGreaterThanOrEqual(52);
  expect(style.backgroundColor).toContain("rgba(255, 255, 255");
  expect(style.backdropFilter).toContain("blur(");
  expect(Number.parseInt(style.borderRadius, 10)).toBeGreaterThanOrEqual(24);
  expect(style.boxShadow).toContain("rgba(0, 0, 0");
});

test("mobile drawer and inspector sheet use white card surfaces", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-iphone-12", "mobile only");

  await page.goto("/");

  await page.getByRole("button", { name: "打开对话列表" }).click();
  const drawer = page.locator(".ios-glass-drawer");
  await expect(drawer).toBeVisible();
  let style = await surfaceStyle(drawer);
  expect(style.backgroundColor).toBe("rgba(255, 255, 255, 0.82)");
  expect(style.backdropFilter).toContain("blur(24px)");
  expect(style.borderStyle).toBe("none");
  expect(style.boxShadow).toContain("rgba(15, 23, 42, 0.11)");

  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("button", { name: "打开状态和设置" }).click();
  const sheet = page.locator(".ios-glass-sheet");
  await expect(sheet).toBeVisible();
  style = await surfaceStyle(sheet);
  expect(style.backgroundColor).toBe("rgba(255, 255, 255, 0.82)");
  expect(style.backdropFilter).toContain("blur(24px)");
  expect(style.borderStyle).toBe("none");
});

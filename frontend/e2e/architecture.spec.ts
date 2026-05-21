import { expect, test } from "./fixtures";

test("opens the system architecture page from settings", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes("mobile"), "Settings popover is desktop-only.");

  await page.goto("/");
  await page.getByRole("button", { name: "设置" }).click();
  await page.getByRole("link", { name: "系统设计图" }).click();

  await expect(page).toHaveURL(/\/architecture$/);
  await expect(page.getByRole("heading", { name: "Tommy 系统设计图" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Tommy C4 容器交互图" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Tommy LangGraph 流程可视图" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Tommy 数据与事件流图" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Tommy 工具审批与安全图" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "前端体验层" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "运行时编排层" })).toBeVisible();
  const langGraphDiagram = page.getByRole("img", { name: "Tommy LangGraph 流程可视图" });
  await expect(langGraphDiagram.getByText("pre_run", { exact: true })).toBeVisible();
  await expect(langGraphDiagram.getByText("planner", { exact: true })).toBeVisible();
  await expect(langGraphDiagram.getByText("critic", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("img", { name: "Tommy C4 容器交互图" }).getByText("事件流回传"),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "存储与知识层" })).toBeVisible();
});

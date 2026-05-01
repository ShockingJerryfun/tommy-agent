import AxeBuilder from "@axe-core/playwright";

import { expect, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

for (const path of ["/", "/share/test-token"] as const) {
  test(`has no critical accessibility violations on ${path}`, async ({ page }) => {
    await page.goto(path);

    const result = await new AxeBuilder({ page }).analyze();
    const criticalViolations = result.violations.filter(
      (violation) => violation.impact === "critical",
    );

    expect(criticalViolations).toEqual([]);
  });
}

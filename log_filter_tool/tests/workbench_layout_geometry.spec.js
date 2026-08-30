const { test, expect } = require("@playwright/test");

const baseURL = process.env.WORKBENCH_TEST_BASE_URL || "http://127.0.0.1:5127";

// 复用本机已安装的 Chrome，避免测试仓库新增浏览器二进制或依赖文件。
test.use({ baseURL, channel: "chrome" });

test("1280px viewport 的 End 状态应实际到达 55% 左栏轨道", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");

  const geometryBefore = await page.locator("#log-workbench").evaluate(workspace => {
    const pane = workspace.querySelector("#workbench-log-pane");
    return pane.getBoundingClientRect().width;
  });

  const resizer = page.locator("#workbench-resizer");
  await resizer.focus();
  await page.keyboard.press("End");

  const geometryAfter = await page.locator("#log-workbench").evaluate(workspace => {
    const styles = getComputedStyle(workspace);
    const bounds = workspace.getBoundingClientRect();
    const logPane = workspace.querySelector("#workbench-log-pane");
    const divider = workspace.querySelector("#workbench-resizer");
    const resultPane = workspace.querySelector("#workbench-result-pane");
    const contentLeft = bounds.left
      + parseFloat(styles.borderLeftWidth)
      + parseFloat(styles.paddingLeft);
    const contentWidth = bounds.width
      - parseFloat(styles.borderLeftWidth)
      - parseFloat(styles.borderRightWidth)
      - parseFloat(styles.paddingLeft)
      - parseFloat(styles.paddingRight);
    const dividerBounds = divider.getBoundingClientRect();

    return {
      ariaValueNow: divider.getAttribute("aria-valuenow"),
      leftTrackPercent: ((dividerBounds.left - contentLeft) / contentWidth) * 100,
      leftPaneWidth: logPane.getBoundingClientRect().width,
      resultPaneWidth: resultPane.getBoundingClientRect().width,
    };
  });

  expect(geometryAfter.ariaValueNow).toBe("55");
  expect(geometryAfter.leftTrackPercent).toBeGreaterThan(54.9);
  expect(geometryAfter.leftTrackPercent).toBeLessThan(55.1);
  expect(geometryAfter.leftPaneWidth).toBeGreaterThan(geometryBefore);
  expect(geometryAfter.resultPaneWidth).toBeGreaterThanOrEqual(540);
});

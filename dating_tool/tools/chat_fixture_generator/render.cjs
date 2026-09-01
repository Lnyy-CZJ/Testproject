/**
 * 使用 Playwright 把结构化聊天页确定性渲染为 430×932 PNG。
 *
 * 模块只负责浏览器生命周期、布局溢出检查和截图写入；消息生成与目录落盘由其他模块
 * 负责。Playwright 优先从项目依赖加载，在 Codex 桌面环境中可回退到只读的捆绑运行时。
 */
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const WIDTH = 430;
const HEIGHT = 932;
const SUPPORTED_STYLES = new Set([
  "azure-light",
  "sage-light",
  "midnight-dark",
  "plum-light",
  "mono-high-contrast",
]);

/**
 * 加载 Playwright。正常项目通过 package.json 安装；Codex 环境没有 node_modules 时，
 * 使用桌面应用提供的固定依赖目录，避免为一次性数据生成重复下载浏览器库。
 *
 * @returns {import("playwright")} Playwright 模块。
 * @throws {Error} 两种来源都不可用时给出明确的 npm install 提示。
 */
function loadPlaywright() {
  try {
    return require("playwright");
  } catch (projectError) {
    const configuredRoot = process.env.DATING_WORKSPACE_NODE_MODULES;
    const bundledRoot = path.join(
      os.homedir(),
      ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules",
    );
    for (const root of [configuredRoot, bundledRoot].filter(Boolean)) {
      const candidate = path.join(root, "playwright");
      if (fs.existsSync(candidate)) return require(candidate);
    }
    const error = new Error("Playwright is unavailable; run `npm install` in dating_tool first.");
    error.cause = projectError;
    throw error;
  }
}

/**
 * 启动本地浏览器。若 Playwright 自带 Chromium 尚未下载，则使用系统 Chrome；两者都
 * 不存在时保留原始异常，方便定位运行环境问题。
 *
 * @param {import("playwright").BrowserType} chromium Playwright Chromium 类型。
 * @returns {Promise<import("playwright").Browser>} 无界面浏览器实例。
 */
async function launchBrowser(chromium) {
  const bundledExecutable = chromium.executablePath();
  if (bundledExecutable && fs.existsSync(bundledExecutable)) {
    return chromium.launch({ headless: true });
  }
  const systemChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  if (fs.existsSync(systemChrome)) {
    return chromium.launch({ headless: true, executablePath: systemChrome });
  }
  return chromium.launch({ headless: true });
}

/**
 * 创建一次渲染页面并在操作完成后可靠释放浏览器资源。
 *
 * 截图生成和 QA 检查必须经过同一份 HTML、viewport 与控制台错误检查，否则测试可能
 * 验证了与正式产物不同的环境。该包装器把共同生命周期集中在一处。
 *
 * @template T
 * @param {string} rendererPath HTML 渲染模板绝对路径。
 * @param {(page: import("playwright").Page) => Promise<T>} operation 页面就绪后的操作。
 * @returns {Promise<T>} 操作返回值。
 */
async function withRendererPage(rendererPath, operation) {
  const { chromium } = loadPlaywright();
  const browser = await launchBrowser(chromium);
  const consoleErrors = [];
  let context;
  try {
    context = await browser.newContext({
      viewport: { width: WIDTH, height: HEIGHT },
      deviceScaleFactor: 1,
    });
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    await page.goto(pathToFileURL(rendererPath).href, { waitUntil: "load" });
    const result = await operation(page);
    if (consoleErrors.length > 0) {
      throw new Error(`Renderer console errors:\n${consoleErrors.join("\n")}`);
    }
    return result;
  } finally {
    if (context) await context.close();
    await browser.close();
  }
}

/**
 * 在同一个浏览器页面中顺序渲染多张截图，避免 448 次重复启动浏览器。
 *
 * @param {Array<{output_path: string, payload: object}>} tasks 有序截图任务。
 * @param {{renderer_path?: string}} [options] 可选 HTML 模板路径，测试可注入独立模板。
 * @returns {Promise<{rendered: number, width: number, height: number}>} 渲染统计。
 * @throws {TypeError|Error} 输入非法、页面溢出、浏览器控制台报错或 PNG 写入失败时抛出。
 */
async function renderScreenshots(tasks, options = {}) {
  if (!Array.isArray(tasks) || tasks.length === 0) {
    throw new TypeError("renderScreenshots requires at least one task");
  }
  const rendererPath = options.renderer_path || path.join(__dirname, "renderer.html");
  if (!fs.existsSync(rendererPath)) throw new Error(`Renderer not found: ${rendererPath}`);

  return withRendererPage(rendererPath, async (page) => {
    for (const task of tasks) {
      if (!task.output_path.endsWith(".png")) {
        throw new TypeError(`Output must end with .png: ${task.output_path}`);
      }
      if (!SUPPORTED_STYLES.has(task.payload.style_id)) {
        throw new TypeError(`Unsupported style: ${task.payload.style_id}`);
      }
      fs.mkdirSync(path.dirname(task.output_path), { recursive: true });
      const metrics = await page.evaluate((payload) => window.renderChat(payload), task.payload);
      if (metrics.messageCount !== 14 || metrics.overflow) {
        throw new Error(
          `Layout overflow for ${task.output_path}: ${JSON.stringify(metrics)}`,
        );
      }
      await page.screenshot({ path: task.output_path, type: "png" });
    }
    return { rendered: tasks.length, width: WIDTH, height: HEIGHT };
  });
}

/**
 * 通过正式渲染页读取时间与布局信息，供自动化 QA 验证 locale、时区和消息密度。
 * 本函数不写文件，不改变截图任务；它刻意复用 `window.renderChat`，避免测试复制格式化
 * 逻辑后产生“测试通过但实际图片错误”的分叉。
 *
 * @param {object} payload 单张截图的完整渲染数据。
 * @param {{renderer_path?: string}} [options] 可选 HTML 模板路径。
 * @returns {Promise<{clock: string, date_label: string, message_times: string[],
 *   avatar_count: number, metrics: object}>}
 *   页面中实际可见的时间文本与布局测量。
 */
async function inspectFixture(payload, options = {}) {
  if (!payload || !SUPPORTED_STYLES.has(payload.style_id)) {
    throw new TypeError(`Unsupported style: ${payload && payload.style_id}`);
  }
  const rendererPath = options.renderer_path || path.join(__dirname, "renderer.html");
  if (!fs.existsSync(rendererPath)) throw new Error(`Renderer not found: ${rendererPath}`);

  return withRendererPage(rendererPath, async (page) => {
    const metrics = await page.evaluate((fixture) => window.renderChat(fixture), payload);
    return page.evaluate((renderMetrics) => ({
      clock: document.getElementById("clock").textContent,
      date_label: document.getElementById("date-label").textContent,
      message_times: [...document.querySelectorAll(".message-time")].map(
        (element) => element.textContent,
      ),
      avatar_count: document.querySelectorAll(".avatar").length,
      metrics: renderMetrics,
    }), metrics);
  });
}

module.exports = {
  HEIGHT,
  WIDTH,
  inspectFixture,
  renderScreenshots,
};

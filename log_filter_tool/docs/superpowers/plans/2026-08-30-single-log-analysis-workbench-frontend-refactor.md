# 单日志分析工作台前端重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有日志过滤、People Insight 与 Dating 结构化分析整合为原型风格的单日志双栏分析工作台，同时保持所有后端接口、确定性分析结果和导出契约不变。

**Architecture:** 使用现有 Flask + Jinja 页面作为服务端入口，新增 Blueprint 静态资源并把 3,299 行单文件模板拆为语义化工作台模板、一个设计系统 CSS 和按职责分离的原生 JavaScript。工作台核心只管理共享状态、双栏布局、标签、日志定位、抽屉与通知；Filter、People、Dating 各自注册适配器并继续消费现有响应，不在前端重新实现业务规则。

**Tech Stack:** Python 3.12、Flask/Jinja2、原生 HTML/CSS/JavaScript、Python `unittest`、Playwright CLI、Docker Compose；不新增第三方依赖、构建器或前端框架。

**Spec:**

- 视觉与交互基准：`/Users/admin/.codex/visualizations/2026/08/29/01a04d3d-a6de-7702-b4b5-1e3d283061cc/log-analysis-workbench-prototype.html`
- 当前页面：`/Users/admin/Testproject/log_filter_tool/templates/index.html`
- People 产品契约：`/Users/admin/Testproject/log_filter_tool/Log_Tool_PRD/V4_People_Insight_检索日志分析_PRD.md`
- Dating 产品契约：`/Users/admin/Testproject/log_filter_tool/Log_Tool_PRD/V5_Dating_结构化接口日志分析_PRD.md`
- Dating 开发设计：`/Users/admin/Testproject/log_filter_tool/docs/V5_Dating_结构化接口日志分析_开发设计与计划.md`

## Global Constraints

- 首期只支持单日志工作台；不得渲染“双日志对比”入口、视图、状态或模拟数据。
- 原型决定布局、视觉层级和交互方式；现有 PRD、API 与分析器决定业务含义和数据真实性。
- 不新增统一分析 API，不修改 `/`、`/people-search/analyze`、`/dating/analyze`、`/export` 的请求或响应契约。
- 不提供“自动识别”模式；首期只展示现有可可靠执行的“通用接口”“People Insight”“Dating”三种模式，Dating 选项受现有 feature flag 控制。
- 原始日志 `textarea#log_text` 是唯一可编辑数据源；证据定位必须选择并滚动该 textarea 中的真实 1-based 行号。
- 10 MiB 日志不得拆成逐行 DOM；过滤结果同样使用只读 textarea，避免大量 `<span>`/`<mark>` 节点。
- 所有服务端值只允许通过 `textContent`、`createTextNode`、表单 `value` 或 Jinja 自动转义输出；JavaScript 静态资源不得出现 `innerHTML`、`insertAdjacentHTML` 或字符串事件处理器。
- 保留 Dating 完整 Poll 时间线，不采用原型中的轮询聚合展示；概览可以总结停滞次数，但时间线必须逐条可核对。
- 保留未知 Schema、未知字段、NULL/EMPTY/MISSING、解析警告、确定性规则、Markdown/JSON 导出和证据行号。
- 保持 `LOG_FILTER_BASE_PATH` 部署兼容；所有表单、API、导出和静态资源 URL 均由 `url_for` 生成。
- 仅面向 1280px 及以上桌面浏览器；主验收视口为 1440×1000，最小验收视口为 1280×800。
- 使用系统字体、原型色值和 8px 间距网格；不添加渐变、发光、Bento 卡片墙、虚构图表或循环动画。
- 现有 People、Dating、过滤、统计、复制、导出与平台 CSRF 行为必须回归通过。
- 所有测试、Node、Docker 命令从 `/Users/admin/Testproject/log_filter_tool` 执行；所有 `git add`/`git commit` 命令从仓库根目录 `/Users/admin/Testproject` 执行。

---

## 1. 交付结果与范围边界

### 1.1 首期交付

用户进入页面后看到一个固定桌面工作台：顶部是日志上下文与分析方式，左侧是可编辑日志/过滤结果，右侧是当前分析结论与按能力动态出现的标签页。People 与 Dating 分析完成后不再把长页面继续向下堆叠，而是在同一个右侧工作区中切换概览、接口链路、任务时间线、最终结果和检查结果。

### 1.2 明确不做

- 双日志上传、选择、对比、差异计算和对比导出。
- 自动判断并调用 People/Dating 的统一路由。
- 文件拖拽、文件持久化、分析历史、分享链接和数据库。
- People 或 Dating 后端规则、报告格式、字段模型和成本算法调整。
- 移动端或窄屏适配。
- 深色模式。

### 1.3 关键设计取舍

原型左侧使用逐行 `<div>` 展示日志，但当前产品允许 10 MiB 输入。首期保留 textarea 并将其视觉处理为原型日志窗格；行号证据通过文本选择、滚动和“已定位 Lx–y”提示表达。这样既保留原型的双栏排查路径，也不会让大日志生成数万至数十万个 DOM 节点。

---

## 2. 原型区域 → 现有功能 → 文件改动 → 交互与验收

| 原型区域 | 现有功能/真实数据 | 文件改动 | 首期交互 | 验收标准 |
| --- | --- | --- | --- | --- |
| `.app-header` 品牌区 | 当前标题“质量分析 · Log 过滤工具”、平台返回链接 | `templates/index.html`、`static/css/log-workbench.css` | 左侧显示“日志分析工作台 / 结构化接口分析”；存在 `platform_home_url` 时提供可聚焦的返回入口 | 页面只有一个产品主标题；返回链接使用真实配置，不显示虚构平台名称 |
| `.file-context` | `log_text` 可计算行数和 UTF-8 字节数；分析响应包含 domain/task | `workbench-core.js`、People/Dating JS | 初始显示“未命名日志”；输入时实时更新行数/字节数；分析后显示 General、People 或 Dating domain badge | 中文、emoji 按 UTF-8 字节正确统计；修改日志后显示“结果可能已过期” |
| 分析方式 + 主按钮 | 现有“解析日志”“分析检索链路”“Dating 结构化分析”三个入口 | `index.html`、三个适配器 JS | 下拉选择通用接口/People Insight/Dating，点击单一“分析日志”按钮；通用接口提交现有表单，People/Dating 调用现有 JSON API | 不出现自动识别；Dating flag 关闭时不出现 Dating option；重复点击 loading 期间被阻止 |
| `.log-pane` 左侧窗格 | `textarea#log_text`、过滤结果、method 多选、复制/导出 | `index.html`、core/filter JS、CSS | “原始日志/过滤结果”分段切换；原始日志可编辑，过滤结果只读；搜索作用于当前视图；method 多选仅提交通用接口分析 | 粘贴和编辑不丢失；过滤结果可复制/导出；无过滤结果时分段按钮禁用 |
| `.log-tools` | 当前 method 多选和结果搜索 | filter/core JS | 保留多选能力并改成紧凑工具栏；搜索 Enter/Shift+Enter 前后定位；重置仅清除搜索和当前选择，不清空日志 | 搜索不创建匹配 DOM；10 MiB 输入操作不会因标记所有匹配而冻结 |
| `.resizer` | 当前无对应功能 | core JS、CSS | 指针拖动改变左右宽度；键盘左右键每次 16px；比例限制在 32%–55%；不写本地存储 | `role=separator`、`aria-valuenow` 实时更新；1280px 下两侧仍可用 |
| `.result-summary` | People verdict/task、Dating verdict/lifecycle、通用接口统计 | core + 各适配器 | 统一显示状态符号、业务标题、解释、状态 badge 和可用的首要证据按钮 | 状态不只依赖颜色；0 候选/NO_RESULT 等业务状态不得被 UI 改写为成功 |
| `.tab-bar` | 当前长页面中的多个 section | core + 各适配器 | 标签按当前模式动态显示；隐藏不适用标签，不渲染空占位 | 通用接口至少有概览/接口链路；People 有概览/接口链路/最终结果/检查结果；Dating 有全部五类标签 |
| `分析概览` | 通用统计、People verdict/coverage/issues、Dating summary/verdict | filter/people/dating JS | 先显示结论和下一步，再显示指标；不复制整份报告 | 任何异常都能从概览进入检查结果或证据；指标来自响应字段 |
| `接口链路` | 通用 method 表、People provider timeline、Dating `calls` | 三个适配器、drawer | 通用显示聚合统计；People 显示 Provider 调用；Dating 显示三层状态和 PUT/Gateway 调用，点击行打开抽屉 | Dating HTTP/Gateway/SubResponse 分层展示；没有调用详情的行不伪装成可点击 |
| `任务时间线` | Dating `status_samples`、`progress_diagnostics`、上传链路 | dating JS | 展示上传链路和全部 Poll；概览补充进度变化、停滞次数、总耗时 | golden Reply 显示 11 Poll，Analysis 显示 21 Poll；顺序和行号不丢失 |
| `最终结果` | People diagnosis/cost/report；Dating schema/result_sections/result_fields/result_payload | people/dating JS | People 显示关键诊断、成本和完整报告折叠区；Dating 提供业务分组/字段列表/原始 JSON 三种视图 | Reply、Analysis 和 UNKNOWN_SCHEMA 均可用；空字符串、null、missing 文案不同 |
| `检查结果` | People/Dating `checks`、parse warnings | people/dating JS | outcome 分段筛选；每项展示 rule id、title、actual/expected、evidence；有行号时可定位 | FAIL/WARN/UNKNOWN/PASS/NA 不仅靠颜色；无 evidence 时显示“日志证据不足”而非虚构行号 |
| `.drawer` 接口详情 | Dating request/response、People result details；通用接口只有聚合值 | core + 各适配器 | 点击可展开行打开右侧抽屉；Esc、关闭按钮、遮罩关闭；恢复原焦点 | 抽屉打开后焦点进入标题/关闭按钮，Tab 不落入背景；日志值只以文本渲染 |
| `.loading-mask` / `.toast` | 当前 status 文案、action-message | core JS、CSS | loading 覆盖右侧结果区但不遮挡左侧日志；toast 用于复制、导出、行号定位；错误在结果摘要内持久展示 | loading、空态、错误态、成功态互斥；`aria-live` 可读；reduced motion 关闭过渡 |
| `.compare-view` | 当前不存在 | 不创建任何实现文件或 DOM | 首期完全移除 | 页面源码不得包含 `compareButton`、`compareView`、“双日志对比” |

---

## 3. 文件结构与职责

### 修改文件

- `app.py:425,596-613`：为 `tool` Blueprint 声明静态目录，继续传递现有模板上下文；不新增业务路由。
- `templates/index.html:8-3297`：替换内联 CSS/JS 和纵向 section 布局，保留 Jinja 表单数据、CSRF、feature flag 与服务端通用接口统计。
- `Dockerfile:26-31`：将 `static/` 复制到镜像。
- `tests/test_log_filter.py:733-840`：将旧按钮/纵向页面断言改为工作台和通用接口模式断言。
- `tests/test_people_search_phase3.py:225-250`：将 People 内联函数断言改为适配器静态资源与右侧标签映射断言。
- `tests/test_dating_log_routes.py:29-280`：保持响应/安全契约，更新 DOM、base path、静态资源和 Dating 标签视图断言。

### 新增文件

- `static/css/log-workbench.css`：原型 token、双栏布局、标签、表格、时间线、抽屉、状态和可访问性样式。
- `static/js/workbench-core.js`：共享状态、模式注册、主按钮分发、标签、日志搜索/定位、resizer、drawer、loading、toast、CSRF 请求辅助函数。
- `static/js/workbench-filter.js`：现有通用过滤表单、method 多选、原始/过滤结果切换、复制和日志导出。
- `static/js/workbench-people.js`：现有 People 请求与确定性响应渲染，映射到统一标签。
- `static/js/workbench-dating.js`：现有 Dating 请求、生命周期、Reply/Analysis、字段索引、规则和导出渲染，映射到统一标签。
- `tests/test_workbench_frontend.py`：统一工作台 DOM、静态资源、base path、安全写入和功能开关合同。

### 不修改文件

- `gateway_log_parser.py`
- `people_search_analyzer.py`
- `people_search_rules.py`
- `people_search_ai.py`
- `dating_log_analyzer.py`
- `dating_log_rules.py`
- `docker-compose.yml`

若实现过程中必须修改以上分析器才能渲染页面，说明前端适配方案发生越界，应停止并重新核对响应字段，而不是把展示需求写入业务分析器。

---

## 4. 共享前端接口

`workbench-core.js` 暴露唯一全局命名空间，其他脚本不得创建新的业务全局变量：

```javascript
window.LogWorkbench = (function () {
  'use strict';

  var modes = Object.create(null);
  var state = {
    activeMode: 'general',
    activeTab: 'overview',
    phase: 'idle',
    dirty: false,
    lastFocusedElement: null
  };

  function registerAnalysisMode(name, adapter) {
    if (!name || !adapter || typeof adapter.analyze !== 'function') {
      throw new TypeError('analysis mode requires name and analyze()');
    }
    modes[name] = adapter;
  }

  return {
    state: state,
    registerAnalysisMode: registerAnalysisMode,
    analyzeSelectedMode: analyzeSelectedMode,
    setAvailableTabs: setAvailableTabs,
    activateTab: activateTab,
    setResultHeader: setResultHeader,
    focusLogLines: focusLogLines,
    openInterfaceDrawer: openInterfaceDrawer,
    closeInterfaceDrawer: closeInterfaceDrawer,
    setLoading: setLoading,
    showToast: showToast,
    requestJson: requestJson,
    createTextElement: createTextElement,
    clearNode: clearNode
  };
}());
```

模式适配器合同固定为：

```javascript
LogWorkbench.registerAnalysisMode('people', {
  analyze: analyzePeopleSearch,
  reset: resetPeopleSearch
});
```

`context` 的稳定字段：

```javascript
{
  logText: document.getElementById('log_text').value,
  root: document.getElementById('log-workbench'),
  signal: AbortSignal
}
```

`index.html` 根节点只通过 `data-*` 提供真实 URL：

```html
<main id="log-workbench"
      data-index-url="{{ url_for('tool.index') }}"
      data-export-url="{{ url_for('tool.export_log') }}"
      data-people-url="{{ url_for('tool.analyze_people_search') }}"
      {% if dating_analyzer_enabled %}
      data-dating-url="{{ url_for('tool.analyze_dating') }}"
      {% endif %}>
```

脚本加载顺序固定为 core → filter → people → dating：

```html
<script defer src="{{ url_for('tool.static', filename='js/workbench-core.js') }}"></script>
<script defer src="{{ url_for('tool.static', filename='js/workbench-filter.js') }}"></script>
<script defer src="{{ url_for('tool.static', filename='js/workbench-people.js') }}"></script>
{% if dating_analyzer_enabled %}
<script defer src="{{ url_for('tool.static', filename='js/workbench-dating.js') }}"></script>
{% endif %}
```

---

### Task 1: 锁定工作台 DOM、静态资源和部署路径合同

**Files:**

- Create: `tests/test_workbench_frontend.py`
- Modify: `app.py:425`
- Modify: `templates/index.html:1-20,936-1285,3297`
- Create: `static/css/log-workbench.css`
- Create: `static/js/workbench-core.js`
- Modify: `Dockerfile:26-31`

**Interfaces:**

- Consumes: `url_for('tool.index')`、`url_for('tool.export_log')`、`url_for('tool.analyze_people_search')`、`url_for('tool.analyze_dating')`。
- Produces: `tool.static` endpoint、`#log-workbench`、`#analysis-mode`、`#analyze-log-btn`、五个标准 tab panel、静态资源加载顺序。

- [ ] **Step 1: 写出失败的工作台壳层测试**

```python
class WorkbenchShellTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_page_uses_single_log_workbench_shell(self):
        html = self.client.get("/").get_data(as_text=True)
        for marker in (
            'id="log-workbench"', 'id="analysis-mode"',
            'id="analyze-log-btn"', 'id="workbench-log-pane"',
            'id="workbench-result-pane"', 'id="overviewPanel"',
            'id="interfacesPanel"', 'id="timelinePanel"',
            'id="resultPanel"', 'id="checksPanel"',
        ):
            self.assertIn(marker, html)
        self.assertNotIn("双日志对比", html)
        self.assertNotIn('id="compareView"', html)

    def test_blueprint_static_assets_follow_base_path(self):
        app = create_app("/log-tool")
        app.config["TESTING"] = True
        client = app.test_client()
        html = client.get("/log-tool/").get_data(as_text=True)
        self.assertIn('/log-tool/static/css/log-workbench.css', html)
        self.assertEqual(
            client.get('/log-tool/static/js/workbench-core.js').status_code,
            200,
        )
```

- [ ] **Step 2: 运行测试并确认失败原因是工作台 DOM/静态 endpoint 尚不存在**

Run: `.venv/bin/python -m unittest tests.test_workbench_frontend.WorkbenchShellTest -v`

Expected: FAIL，缺少 `#log-workbench` 或 `tool.static` 资源返回 404。

- [ ] **Step 3: 为 Blueprint 增加受 base path 管理的静态目录**

```python
tool = Blueprint(
    "tool",
    __name__,
    static_folder="static",
    static_url_path="/static",
)
```

- [ ] **Step 4: 建立语义化壳层和真实 URL 数据属性**

模板必须包含 `header.app-header`、`main.workspace`、`section#workbench-log-pane`、键盘 resizer、`section#workbench-result-pane`、tablist、五个 panel、drawer、toast 和 loading mask；不得复制原型中的示例任务、ID、结果文本或比较数据。

- [ ] **Step 5: 建立可被后续任务扩展的实际静态资源**

`log-workbench.css` 在本任务写入完整 token；`workbench-core.js` 写入上节的 namespace、模式注册和 DOM ready 初始化，不创建空文件。

- [ ] **Step 6: Docker 镜像复制静态目录**

```dockerfile
COPY templates/ templates/
COPY static/ static/
```

- [ ] **Step 7: 验证壳层、根路径与 base path 静态资源**

Run: `.venv/bin/python -m unittest tests.test_workbench_frontend.WorkbenchShellTest -v`

Expected: PASS。

- [ ] **Step 8: 精确提交**

```bash
git add log_filter_tool/app.py log_filter_tool/templates/index.html \
  log_filter_tool/static/css/log-workbench.css \
  log_filter_tool/static/js/workbench-core.js \
  log_filter_tool/tests/test_workbench_frontend.py \
  log_filter_tool/Dockerfile
git commit -m "feat(log-tool): add single-log workbench shell"
```

### Task 2: 实现原型视觉系统、双栏布局和可访问标签导航

**Files:**

- Modify: `static/css/log-workbench.css`
- Modify: `static/js/workbench-core.js`
- Modify: `templates/index.html`
- Modify: `tests/test_workbench_frontend.py`

**Interfaces:**

- Consumes: Task 1 的工作台 DOM。
- Produces: CSS token、独立滚动双栏、32%–55% resizer、`setAvailableTabs(ids)`、`activateTab(id, focus)`。

- [ ] **Step 1: 添加失败测试，锁定视觉 token、语义角色和无对比视图**

```python
def test_assets_define_accessible_desktop_layout(self):
    css = Path("static/css/log-workbench.css").read_text(encoding="utf-8")
    js = Path("static/js/workbench-core.js").read_text(encoding="utf-8")
    html = self.client.get("/").get_data(as_text=True)
    for token in ("--page: #f5f5f7", "--text: #1d1d1f", "--accent: #0071e3", "--left-pane: 39%"):
        self.assertIn(token, css)
    self.assertIn("prefers-reduced-motion: reduce", css)
    self.assertIn('role="separator"', html)
    self.assertIn('role="tablist"', html)
    self.assertIn("function activateTab", js)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m unittest tests.test_workbench_frontend.WorkbenchShellTest.test_assets_define_accessible_desktop_layout -v`

Expected: FAIL，缺少布局 token 或标签函数。

- [ ] **Step 3: 按原型写入固定 token 和布局，不沿用旧页面卡片墙**

```css
:root {
  --page: #f5f5f7;
  --surface: #ffffff;
  --surface-subtle: #fafafa;
  --surface-selected: #f0f7ff;
  --text: #1d1d1f;
  --text-secondary: #6e6e73;
  --line: rgba(0, 0, 0, 0.11);
  --accent: #0071e3;
  --success: #147a3d;
  --warning: #8a5a00;
  --danger: #c6292e;
  --radius-control: 9px;
  --radius-panel: 14px;
  --left-pane: 39%;
  --font-ui: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
  --font-mono: "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
}

.workspace {
  display: grid;
  grid-template-columns: minmax(360px, var(--left-pane)) 8px minmax(620px, 1fr);
  height: calc(100vh - 72px);
  min-width: 1280px;
}
```

- [ ] **Step 4: 实现 WAI-ARIA 标签键盘行为**

左右方向键切换可见标签，Home/End 切换首尾；激活时同步 `aria-selected`、`tabindex` 和 panel `hidden`，隐藏模式不进入键盘序列。

```javascript
function activateTab(panelId, focusTab) {
  visibleTabButtons().forEach(function (button) {
    var active = button.getAttribute('aria-controls') === panelId;
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
    document.getElementById(button.getAttribute('aria-controls')).hidden = !active;
    if (active && focusTab) button.focus();
  });
  state.activeTab = panelId.replace('Panel', '');
}
```

- [ ] **Step 5: 实现可拖拽和键盘 resizer**

指针移动只修改 `--left-pane`，将百分比夹在 32–55；ArrowLeft/ArrowRight 每次 16px，Home=32%，End=55%，并更新 `aria-valuenow`。不写 Cookie 或 localStorage。

- [ ] **Step 6: 回归视觉合同和语法**

Run: `.venv/bin/python -m unittest tests.test_workbench_frontend -v`

Run: `node --check static/js/workbench-core.js`

Expected: 全部 PASS，Node 无语法错误。

- [ ] **Step 7: 提交**

```bash
git add log_filter_tool/static/css/log-workbench.css \
  log_filter_tool/static/js/workbench-core.js \
  log_filter_tool/templates/index.html \
  log_filter_tool/tests/test_workbench_frontend.py
git commit -m "feat(log-tool): implement workbench layout and tabs"
```

### Task 3: 实现日志窗格、模式分发、搜索、行号定位与共享状态

**Files:**

- Modify: `templates/index.html`
- Modify: `static/js/workbench-core.js`
- Create: `static/js/workbench-filter.js`
- Modify: `tests/test_workbench_frontend.py`
- Modify: `tests/test_log_filter.py:749-840`

**Interfaces:**

- Consumes: `textarea#log_text`、`textarea#result-text`、现有通用接口 POST 表单。
- Produces: `analyzeSelectedMode()`、`focusLogLines(start,end)`、`searchActiveLog(direction)`、原始/过滤结果分段控件。

- [ ] **Step 1: 添加失败测试，锁定单一分析按钮与日志性能边界**

```python
def test_log_pane_keeps_textareas_and_single_dispatch_button(self):
    html = self.client.get("/").get_data(as_text=True)
    self.assertIn('<textarea id="log_text"', html)
    self.assertIn('<textarea id="result-text"', html)
    self.assertIn('id="analyze-log-btn"', html)
    self.assertNotIn('onclick=', html)
    self.assertNotIn('class="log-line"', html)

def test_scripts_never_write_untrusted_html(self):
    for path in Path("static/js").glob("workbench-*.js"):
        source = path.read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", source)
        self.assertNotIn("insertAdjacentHTML", source)
```

- [ ] **Step 2: 运行测试确认旧 textarea/result 和 inline handler 合同失败**

Run: `.venv/bin/python -m unittest tests.test_workbench_frontend -v`

Expected: FAIL，仍存在 inline handler 或过滤结果不是只读 textarea。

- [ ] **Step 3: 把现有 method 多选和过滤表单移入左侧窗格**

保留 `name="log_text"`、`name="method"`、`data-is-all="1"`、CSRF hidden input 和 `url_for('tool.index')`；删除三个分散的分析按钮，用 `select#analysis-mode` + `button#analyze-log-btn` 代替。

- [ ] **Step 4: 实现模式分发，通用接口继续走现有 POST**

```javascript
function analyzeSelectedMode() {
  var mode = document.getElementById('analysis-mode').value;
  if (state.phase === 'loading') return;
  if (mode === 'general') {
    document.getElementById('log-filter-form').requestSubmit();
    return;
  }
  var adapter = modes[mode];
  if (!adapter) {
    showPersistentError('当前分析方式不可用');
    return;
  }
  runAsyncAnalysis(adapter);
}
```

- [ ] **Step 5: 实现不创建匹配节点的 textarea 搜索**

搜索基于当前可见 textarea 的字符串下标；Enter 查找下一项，Shift+Enter 查找上一项，选中真实文本并滚动。查询变化使用 150ms debounce 统计匹配数，空查询显示总行数。

- [ ] **Step 6: 将现有 `focusLogLines` 迁移到 core 并扩展工作台反馈**

行号计算沿用现有换行偏移算法；定位前自动切换“原始日志”，选择 `[startLine,endLine]`，状态区和 toast 同时显示真实范围。method 非“全部”时只提示可能隐藏过滤结果，不静默修改筛选。

- [ ] **Step 7: 将通用过滤相关函数迁入 `workbench-filter.js`**

迁移并去除 inline handler：`exportLog`、`copyResult`、method 全选/取消全选、dropdown 键盘行为、筛选自动提交。`result-text` 改为只读 textarea 后，删除旧的 `<mark>` 批量渲染逻辑；搜索统一调用 core 的 textarea 搜索。

- [ ] **Step 8: 输入变化标记结果过期而不立即清空**

```javascript
document.getElementById('log_text').addEventListener('input', function () {
  state.dirty = true;
  updateLogMetadata();
  markAnalysisStale('日志已修改，请重新分析以更新右侧结果。');
});
```

- [ ] **Step 9: 更新通用页面测试并运行回归**

Run: `.venv/bin/python -m unittest tests.test_workbench_frontend tests.test_log_filter -v`

Expected: PASS；现有接口统计、method 筛选、复制和导出测试保持通过。

- [ ] **Step 10: 提交**

```bash
git add log_filter_tool/templates/index.html \
  log_filter_tool/static/js/workbench-core.js \
  log_filter_tool/static/js/workbench-filter.js \
  log_filter_tool/tests/test_workbench_frontend.py \
  log_filter_tool/tests/test_log_filter.py
git commit -m "feat(log-tool): integrate log pane and general analysis"
```

### Task 4: 将 People Insight 映射到统一工作台

**Files:**

- Create: `static/js/workbench-people.js`
- Modify: `templates/index.html`
- Modify: `tests/test_people_search_phase3.py:225-250`
- Modify: `tests/test_workbench_frontend.py`

**Interfaces:**

- Consumes: `/people-search/analyze` 当前响应中的 `verdict`、`task`、`coverage`、`checks`、`diagnosis`、`timeline`、`cost`、`ai`、`report_markdown`。
- Produces: People 概览、接口链路、最终结果、检查结果四个工作台 surface；调用 `LogWorkbench.setAvailableTabs(...)`。

- [ ] **Step 1: 写失败测试，锁定 People 模式和四类真实视图**

```python
def test_people_mode_is_registered_without_inline_script(self):
    html = self.client.get("/").get_data(as_text=True)
    source = Path("static/js/workbench-people.js").read_text(encoding="utf-8")
    self.assertIn('<option value="people">People Insight</option>', html)
    self.assertIn("registerAnalysisMode('people'", source)
    for key in ("data.coverage", "data.timeline", "data.diagnosis", "data.checks", "data.cost"):
        self.assertIn(key, source)
    self.assertNotIn("innerHTML", source)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m unittest tests.test_people_search_phase3.PageRenderingTests tests.test_workbench_frontend -v`

Expected: FAIL，People 仍依赖模板内联函数或尚未注册。

- [ ] **Step 3: 迁移请求、复制和导出函数，保持 API/CSRF 不变**

适配器通过 `LogWorkbench.requestJson(root.dataset.peopleUrl, {log_text: context.logText})` 调用；错误响应继续展示后端 message，不修改原日志、过滤结果或 Dating 的最近结果。

- [ ] **Step 4: 重排现有 People DOM 到统一 panel**

- `overviewPanel`：`people-verdict-panel`、task summary、AI 状态、coverage、问题摘要。
- `interfacesPanel`：`people-timeline`，列保持 Provider/Operation/状态/业务结果/诊断/HTTP/缓存/成本。
- `resultPanel`：`people-diagnosis-list`、`people-cost-summary`、完整 Markdown 折叠区。
- `checksPanel`：新增 `people-check-list`，按 FAIL/WARN/UNKNOWN/PASS/NA 排序。
- `timelinePanel`：People 模式隐藏，避免把 Provider call 冒充任务状态 Poll。

- [ ] **Step 5: 使用统一 header 表达业务结论**

`setResultHeader` 的标题来自 verdict label，副标题包含姓名、task_id、终态、候选数、result_type、no_result_reason；AI 状态只作为说明，不覆盖确定性 verdict。

- [ ] **Step 6: 增加 People evidence 按钮的保守降级**

若 check evidence 提供有效 `line_start/line_end`，调用 `focusLogLines`；否则展示不可点击文本“日志证据不足”。不得根据 evidence path 猜测行号。

- [ ] **Step 7: 更新旧内联断言并运行 People 全量回归**

Run: `.venv/bin/python -m unittest tests.test_people_search_phase0 tests.test_people_search_phase1 tests.test_people_search_phase2 tests.test_people_search_phase3 tests.test_people_search_phase4 tests.test_people_search_phase5 tests.test_people_search_review_fixes -v`

Expected: 全部 PASS；People API 响应字节与分析规则不变。

- [ ] **Step 8: 提交**

```bash
git add log_filter_tool/static/js/workbench-people.js \
  log_filter_tool/templates/index.html \
  log_filter_tool/tests/test_people_search_phase3.py \
  log_filter_tool/tests/test_workbench_frontend.py
git commit -m "feat(log-tool): map People Insight into workbench"
```

### Task 5: 将 Dating 调用链和完整任务时间线映射到统一工作台

**Files:**

- Create: `static/js/workbench-dating.js`
- Modify: `templates/index.html`
- Modify: `tests/test_dating_log_routes.py:29-280`
- Modify: `tests/test_workbench_frontend.py`

**Interfaces:**

- Consumes: `/dating/analyze` 顶层固定对象及 `summary`、`calls`、`task_snapshot`、`checks`、`parse_warnings`、`report_markdown`。
- Produces: Dating 五标签、接口 drawer payload、完整 Poll timeline、Markdown/JSON 导出。

- [ ] **Step 1: 写失败测试，锁定五标签和完整 Poll 合同**

```python
def test_dating_mode_maps_all_workbench_tabs(self):
    source = Path("static/js/workbench-dating.js").read_text(encoding="utf-8")
    self.assertIn("registerAnalysisMode('dating'", source)
    for contract in (
        "renderDatingSummary", "renderDatingCalls", "renderDatingLifecycle",
        "renderDatingResult", "renderDatingFields", "renderDatingChecks",
        "taskSnapshot.status_samples", "taskSnapshot.result_payload",
    ):
        self.assertIn(contract, source)
    self.assertNotIn("aggregatePoll", source)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m unittest tests.test_dating_log_routes.DatingPageTest tests.test_workbench_frontend -v`

Expected: FAIL，Dating 仍在模板内联脚本或缺少五标签映射。

- [ ] **Step 3: 迁移 Dating 请求与状态机**

保留 `latestDatingAnalysis`、`latestDatingReport` 的语义但封装在模块闭包中；调用根节点 `data-dating-url`，沿用 EMPTY_LOG、LOG_TOO_LARGE、UNSUPPORTED_LOG、MULTIPLE_TASKS_FOUND、TASK_NOT_FOUND、ANALYZER_DISABLED、ANALYSIS_INTERNAL_ERROR 文案映射。

- [ ] **Step 4: 把 Dating 区域分配到五个标准 panel**

- Overview：verdict、next action、summary、lifecycle metrics、上传摘要。
- Interfaces：完整 `calls` 表和三层状态，不默认折叠整个标签。
- Timeline：上传链路、所有 `status_samples`、progress diagnostics。
- Result：业务分组/字段列表/原始 JSON、schema badge、未知 Schema 提示。
- Checks：checks 筛选、parse warnings、固定报告折叠区。

- [ ] **Step 5: 保持完整 Poll，不复制原型聚合行为**

```javascript
function renderDatingLifecycle(taskSnapshot) {
  var samples = Array.isArray(taskSnapshot.status_samples)
    ? taskSnapshot.status_samples : [];
  samples.forEach(function (sample, index) {
    appendTimelineItem(index + 1, sample);
  });
  renderProgressDiagnostics(taskSnapshot.progress_diagnostics || {});
}
```

golden Reply 必须创建 11 个 timeline item；Relationship Analysis 必须创建 21 个。进度停滞的摘要只来自 `progress_diagnostics`，不删除样本。

- [ ] **Step 6: 将接口详情从行内 `<details>` 移入共享 drawer**

Dating row 点击后传入：method/service、transport、result_class、parse_status、request/response line、HTTP、gateway、sub_response、elapsed_ms、request.params、response.data、headers。所有 JSON 使用 `JSON.stringify(value, null, 2)` 后赋给 `<pre>.textContent`。

- [ ] **Step 7: 保持 Schema 专属视图和字段 presence**

迁移现有 Reply role/top pick、Relationship overview/signals/events 渲染；保留 `sortDatingRolesByRank`、未知 Schema 通用降级、字段懒加载、每批字段数量限制和 parent path 展开。原始 JSON 仅来自已经脱敏的 `task_snapshot.result_payload`。

- [ ] **Step 8: 保持导出类型和后端二次脱敏**

Markdown 调用 `dating_analysis_report`，JSON 调用 `dating_analysis_json`；按钮在成功前 disabled，错误状态不得导出上一次任务结果。

- [ ] **Step 9: 运行 Dating 页面、API、报告和分析器回归**

Run: `.venv/bin/python -m unittest tests.test_gateway_log_parser tests.test_dating_fixtures tests.test_dating_log_analyzer tests.test_dating_log_rules tests.test_dating_log_routes tests.test_dating_report -v`

Expected: 全部 PASS；响应顶层键、规则顺序、报告和脱敏不变。

- [ ] **Step 10: 提交**

```bash
git add log_filter_tool/static/js/workbench-dating.js \
  log_filter_tool/templates/index.html \
  log_filter_tool/tests/test_dating_log_routes.py \
  log_filter_tool/tests/test_workbench_frontend.py
git commit -m "feat(log-tool): map Dating analysis into workbench"
```

### Task 6: 完成接口抽屉、检查筛选、loading/error/empty/stale 状态

**Files:**

- Modify: `static/js/workbench-core.js`
- Modify: `static/js/workbench-people.js`
- Modify: `static/js/workbench-dating.js`
- Modify: `static/css/log-workbench.css`
- Modify: `templates/index.html`
- Modify: `tests/test_workbench_frontend.py`

**Interfaces:**

- Consumes: 各适配器构造的 drawer view model 和 check 列表。
- Produces: `openInterfaceDrawer(model, trigger)`、`closeInterfaceDrawer()`、焦点恢复、结果状态互斥、outcome 筛选。

- [ ] **Step 1: 写失败测试锁定安全 drawer 与状态可访问性**

```python
def test_drawer_and_status_contracts_are_accessible(self):
    html = self.client.get("/").get_data(as_text=True)
    js = Path("static/js/workbench-core.js").read_text(encoding="utf-8")
    self.assertIn('role="dialog"', html)
    self.assertIn('aria-modal="true"', html)
    self.assertIn('role="status" aria-live="polite"', html)
    self.assertIn("event.key === 'Escape'", js)
    self.assertIn("lastFocusedElement", js)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m unittest tests.test_workbench_frontend -v`

Expected: FAIL，drawer 焦点或状态合同不完整。

- [ ] **Step 3: 实现 drawer 焦点管理和背景隔离**

打开时记录触发元素、设置 `aria-hidden=false`、聚焦关闭按钮并为主工作区设置 `inert`；关闭时移除 inert 并恢复触发元素。Esc、关闭按钮和 backdrop 都走同一个 close 函数。

- [ ] **Step 4: 统一四种主状态**

- idle：右侧标题“等待分析”，展示操作说明。
- loading：右侧 skeleton 和“正在分析…”，主按钮 disabled，左侧仍可滚动但编辑会先取消请求。
- success：隐藏 loading/错误，展示适用标签并聚焦结果标题。
- error：保留原日志，标题显示后端 error code/message，提供“重新分析”而不展示旧任务为当前结果。
- stale：成功结果仍可查看，但 header 标记“日志已修改，结果可能过期”，导出按钮 disabled。

- [ ] **Step 5: 统一检查筛选和非颜色语义**

按钮文案显示 outcome 和数量，例如 `WARN 2`；每项始终显示文字 badge、rule id、标题、actual、expected、evidence。键盘焦点样式使用 `:focus-visible`，不移除 outline。

- [ ] **Step 6: 运行静态、安全和全量前端合同测试**

Run: `.venv/bin/python -m unittest tests.test_workbench_frontend tests.test_log_filter tests.test_people_search_phase3 tests.test_dating_log_routes -v`

Run: `node --check static/js/workbench-core.js`

Run: `node --check static/js/workbench-filter.js`

Run: `node --check static/js/workbench-people.js`

Run: `node --check static/js/workbench-dating.js`

Expected: 全部 PASS，无 JS 语法错误。

- [ ] **Step 7: 提交**

```bash
git add log_filter_tool/static/css/log-workbench.css \
  log_filter_tool/static/js/workbench-core.js \
  log_filter_tool/static/js/workbench-filter.js \
  log_filter_tool/static/js/workbench-people.js \
  log_filter_tool/static/js/workbench-dating.js \
  log_filter_tool/templates/index.html \
  log_filter_tool/tests/test_workbench_frontend.py
git commit -m "feat(log-tool): finish workbench interaction states"
```

### Task 7: 浏览器验收、性能回归与容器部署验证

**Files:**

- Modify only if a verified defect is found: files owned by Tasks 1–6
- Generate untracked evidence: `output/playwright/workbench/*.png`

**Interfaces:**

- Consumes: 完整工作台、两个 Dating golden、一个 People fixture、通用接口示例。
- Produces: 自动测试记录、截图、容器健康检查和真实 HTTP 验收结果。

- [ ] **Step 1: 运行全部 Python 测试和编译检查**

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile app.py gateway_log_parser.py \
  people_search_analyzer.py people_search_rules.py people_search_ai.py \
  dating_log_analyzer.py dating_log_rules.py
git diff --check
```

Expected: 当前 335 个测试加新增工作台测试全部 PASS；无编译或空白错误。

- [ ] **Step 2: 运行 Dating 性能验收**

```bash
RUN_DATING_PERF=1 .venv/bin/python -m unittest \
  tests.test_dating_log_analyzer.DatingPerformanceAcceptanceTest -v
```

Expected: golden 中位数 ≤500ms，10 MiB 日志 ≤2s；前端没有逐行 DOM 生成逻辑。

- [ ] **Step 3: 启动本地服务并以 1440×1000 验收核心流程**

覆盖 idle、通用接口 POST、People 成功、Dating Reply、Dating Relationship Analysis、Dating 422、loading、stale、字段筛选、检查筛选、抽屉、证据定位、复制、Markdown/JSON 导出。

每个流程检查：

- console 无 error。
- 非静态 API 无意外 4xx/5xx。
- 页面无纵向堆叠旧 section。
- 左右 pane 独立滚动。
- 标签、drawer、select、按钮可用键盘操作。
- evidence 定位后 textarea 选区对应真实行。
- 页面不存在双日志对比入口。

- [ ] **Step 4: 以 1280×800 验收最小桌面视口**

确认 header 操作不重叠、左 pane ≥360px、右 pane ≥620px、表格在 pane 内横向滚动、页面 body 不产生额外横向滚动。

- [ ] **Step 5: 保存验收截图**

```text
output/playwright/workbench/01-idle-1440.png
output/playwright/workbench/02-general-overview.png
output/playwright/workbench/03-people-checks.png
output/playwright/workbench/04-dating-reply-overview.png
output/playwright/workbench/05-dating-interface-drawer.png
output/playwright/workbench/06-dating-timeline.png
output/playwright/workbench/07-dating-result-fields.png
output/playwright/workbench/08-error-422.png
output/playwright/workbench/09-min-width-1280.png
```

- [ ] **Step 6: 构建并启动本地 Docker**

```bash
docker compose build log-filter-tool
docker compose up -d log-filter-tool
docker compose ps
curl --fail http://127.0.0.1:5001/health
```

Expected: 容器 healthy/running，health 返回 `status=ok`，CSS/JS 资源 200。

- [ ] **Step 7: 通过真实 HTTP 重放三类分析**

分别提交 People fixture、Dating Reply fixture、Dating Analysis fixture；核对状态、标签数量、Poll 数、报告导出和脱敏。不调用 LLM 或网络 Provider。

- [ ] **Step 8: 请求代码评审并只修复可复现问题**

评审重点：原型区域覆盖、无 compare 残留、API 契约、10 MiB 性能、People/Dating 数据真实性、base path、XSS 安全和键盘可访问性。

- [ ] **Step 9: 最终提交**

```bash
git add log_filter_tool/app.py log_filter_tool/Dockerfile \
  log_filter_tool/templates/index.html \
  log_filter_tool/static/css/log-workbench.css \
  log_filter_tool/static/js/workbench-core.js \
  log_filter_tool/static/js/workbench-filter.js \
  log_filter_tool/static/js/workbench-people.js \
  log_filter_tool/static/js/workbench-dating.js \
  log_filter_tool/tests/test_workbench_frontend.py \
  log_filter_tool/tests/test_log_filter.py \
  log_filter_tool/tests/test_people_search_phase3.py \
  log_filter_tool/tests/test_dating_log_routes.py
git commit -m "feat(log-tool): complete single-log analysis workbench"
```

---

## 5. 验收清单

| ID | 验收项 | 通过条件 |
| --- | --- | --- |
| WB-001 | 工作台壳层 | 进入页面即为固定 header + 左日志 pane + resizer + 右结果 pane |
| WB-002 | 单日志范围 | 无 compare 文案、按钮、DOM、JS 状态和模拟数据 |
| WB-003 | 分析方式 | 仅通用接口、People、受 flag 控制的 Dating；主按钮单一 |
| WB-004 | 通用接口 | 原有 POST、method 多选、统计、过滤结果、复制和导出均正常 |
| WB-005 | People 概览 | verdict、task、coverage、AI 状态和问题摘要值与 API 一致 |
| WB-006 | People 深入排查 | Provider timeline、diagnosis、cost、checks、报告均可访问 |
| WB-007 | Dating 概览 | verdict、summary、lifecycle、上传摘要与 API 一致 |
| WB-008 | Dating 接口链路 | 所有 calls 可见，HTTP/Gateway/SubResponse 分层，详情 drawer 安全渲染 |
| WB-009 | Dating 时间线 | Reply 11 Poll、Analysis 21 Poll，逐条保留且可定位证据 |
| WB-010 | Dating 结果 | Reply/Analysis 业务视图、字段列表、原始 JSON 和未知 Schema 降级正常 |
| WB-011 | 字段语义 | PRESENT/NULL/EMPTY_STRING/EMPTY_ARRAY/EMPTY_OBJECT/MISSING/UNKNOWN 均可区分 |
| WB-012 | 检查结果 | outcome 可筛选，状态有文字，真实 evidence 可定位，无证据不猜测 |
| WB-013 | 日志定位 | 点击证据自动切原始日志并选择真实 1-based 行范围 |
| WB-014 | 大日志 | 不创建逐行 DOM；10 MiB 输入不因日志展示或搜索产生明显冻结 |
| WB-015 | 状态机 | idle/loading/success/error/stale 互斥，旧结果不会伪装成当前结果 |
| WB-016 | 导出 | Filter、People Markdown、Dating Markdown/JSON 类型和脱敏保持不变 |
| WB-017 | 安全渲染 | JS 无 `innerHTML`/`insertAdjacentHTML`；恶意日志文本不会执行 |
| WB-018 | base path | `/log-tool/` 下表单、API、导出和静态资源 URL 全部有效 |
| WB-019 | 可访问性 | 标签、resizer、drawer、筛选和按钮可键盘操作；焦点和 aria 状态正确 |
| WB-020 | 视觉 | 1440×1000 与 1280×800 无重叠/裁切；颜色、圆角、排版与原型同一系统 |
| WB-021 | 回归 | 全量 unittest、Node 语法、py_compile、diff-check、性能与容器验收通过 |

---

## 6. 实施风险与控制

| 风险 | 控制措施 |
| --- | --- |
| 从内联脚本拆分时丢失 Jinja URL | 所有 URL 放根节点 `data-*`，base path 测试覆盖 `/log-tool` |
| 统一标签后误改业务含义 | 适配器只读取现有响应；分析器与规则文件列入“不修改文件” |
| Dating Poll 被原型聚合逻辑吞掉 | WB-009 和 golden 精确断言 11/21 个 timeline item |
| 大日志逐行渲染卡顿 | textarea 为唯一日志展示/编辑模型；禁止 `.log-line` 列表 |
| 抽屉渲染任意 HTML | 统一 `textContent`/`createTextNode`；静态扫描禁止危险 API |
| 拆 JS 后脚本顺序错误 | defer 且固定 core→filter→people→dating；注册函数缺失时测试直接失败 |
| feature flag 关闭仍加载 Dating | Jinja 同时移除 option、DOM、script 和 data URL；页面测试覆盖 |
| 旧结果与新输入混淆 | input 标记 stale、禁用导出；新请求开始先清理当前模式结果 |
| 工作台窄屏不可用 | 明确只验收 ≥1280px；pane min width 与表格内部滚动 |

---

## 7. 计划自检结果

- 原型中除 compare 之外的 header、日志 pane、resizer、summary、tabs、drawer、loading 和 toast 均有明确任务与验收项。
- Filter、People、Dating 的现有入口、响应字段、证据、规则、报告与导出均映射到具体文件和测试。
- 新增全局接口名称在 Task 1–6 中保持一致：`LogWorkbench.registerAnalysisMode`、`analyzeSelectedMode`、`setAvailableTabs`、`activateTab`、`focusLogLines`、`openInterfaceDrawer`。
- 未引入后端统一分析、自动识别、逐行 DOM、双日志比较、移动端、依赖升级或分析规则修改。
- 每个开发任务均包含失败测试、最小实现、验证命令和精确提交范围。

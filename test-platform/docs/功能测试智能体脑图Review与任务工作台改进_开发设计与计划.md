# 功能测试智能体脑图 Review 与任务工作台改进——开发设计与计划

> 文档版本：V1.0  
> 文档状态：待开发评审  
> 编写日期：2026-08-14  
> 需求基线：[功能测试智能体脑图 Review 与任务工作台改进 PRD V1.1](./功能测试智能体脑图Review与任务工作台改进_PRD.md)  
> 当前代码基线：测试点在线 Review、测试用例在线 Review、两类 AI 辅助 Review、文件任务存储、持久化 FIFO  
> 适用项目：`AItestcase_Agents`、`test-platform`

---

## 1. 文档目的

本文将已评审 PRD 转换为可直接执行的技术设计与开发计划，明确：

- 当前代码与需求之间的差距；
- 脑图组件选型及接入方式；
- 浏览器内唯一数据源、树投影和命令模型；
- 测试点/测试用例脑图的层级与写回规则；
- 只读表格、版本、CAS、AI 和任务进度的集成方式；
- 服务端接口、公开字段、配置迁移和安全边界；
- 文件级影响范围；
- M01～M18 工作包、MR01～MR07 阶段和质量门槛；
- 自动化、浏览器、发布和回滚方案。

本文不重新讨论已确认的 18 项产品决策。实现出现局部路径差异时，以 PRD V1.1、现有权威 JSON 协议和最小兼容改动为准。

---

## 2. 设计结论

### 2.1 总体结论

本期不建设新的“脑图后端”。脑图仅是现有 Review JSON 的浏览器投影和编辑入口：

```text
现有 Review GET API
        ↓
浏览器 FlatReviewState（唯一可写数据源）
        ↓ O(n) 投影
Mind Elixir 树形画布 ── 操作事件 ── Domain Command
        │                                ↓
        └──────── 只读表格 ←──── 更新 FlatReviewState
                                         ↓
                              现有 Review PUT/confirm/resume API
```

关键约束：

1. Mind Elixir 内部树不是业务事实来源；
2. 只读表格不维护第二份数据；
3. 服务端继续只接收测试点数组或测试用例数组；
4. 不新增脑图文件、节点坐标字段、数据库表、队列或服务；
5. 当前表格 Review 代码保留为功能开关关闭时的回退实现；
6. 不重构 TaskStore、QueueManager、Runner 和 AI Adapter。

### 2.2 选定脑图库

固定使用：

```text
mind-elixir 5.14.0
License: MIT
接入方式：自托管 ESM/CSS，版本和 SHA-256 固定
运行依赖：0
```

选择原因：

- 框架无关，可直接接入现有 Flask/Jinja/原生 JavaScript；
- 自带节点编辑、拖拽、多选、快捷键和撤销/重做；
- 提供 `operation`、`selectNode`、`expandNode` 等事件；
- 提供 `before` 操作守卫，可阻止非法新增、删除和移动；
- `getData()/refresh()` 支持受控刷新；
- 无需给 Python 运行镜像增加 Node.js。

官方依据：

- [Mind Elixir 官方介绍](https://docs.mind-elixir.com/docs/getting-started/intro/)说明其为框架无关、零依赖的脑图内核；
- [官方节点操作文档](https://docs.mind-elixir.com/docs/guides/node-operation)提供操作事件、操作守卫和节点移动 API；
- [官方数据导入导出文档](https://docs.mind-elixir.com/docs/guides/data-export)提供初始化、刷新和数据读取协议。

### 2.3 使用边界

只使用 Mind Elixir 的：

- 树布局；
- 节点选择；
- 展开/折叠；
- 平移/缩放；
- 文本快捷编辑；
- 合法层级拖拽；
- 键盘基础操作；
- 操作事件和守卫。

明确禁用或不接入：

- Markdown 和富文本；
- 超链接和外部图片；
- 任意连线、关系箭头和摘要连线；
- PNG/SVG/HTML 导出；
- 第三方右键菜单插件；
- 任意主题编辑；
- Mind Elixir 数据直接提交服务端；
- CDN、远程字体和运行时外部资源；
- 库自带业务撤销栈作为权威历史。

用户文本必须通过纯文本节点属性和 `textContent` 呈现。若技术验证发现库在关闭 Markdown 后仍把 topic 解释为 HTML，M01 不得通过，必须在 Adapter 中编码文本并增加 XSS 回归后才能继续。

### 2.4 选型对现有架构的影响

- 不新增前端框架和打包器；
- 不增加生产构建网络依赖；
- 将官方发布的 ESM、CSS、LICENSE 和校验文件作为 vendored 静态资源提交；
- Python Dockerfile 继续使用现有 `COPY . .`，无需多阶段 Node 构建；
- 纯业务投影模块使用 `.mjs`，可同时被浏览器和 Node 内置测试运行器导入；
- 页面使用 `<script type="module">` 加载脑图模块；
- 旧表格工作台仍由现有 classic script 加载。

---

## 3. 当前基线与已识别差异

### 3.1 代码架构

当前功能智能体 Web 层：

```text
services/common/web.py
├── Flask/Jinja 页面
├── 任务 CRUD、权限、CSRF
├── 测试点 Review API
├── 测试用例 Review API
├── 两类 AI Review API
└── 日志与 artifact API

services/common/templates/
├── base.html
├── index.html
└── task_detail.html

services/common/static/
├── agent-workbench.js/css
├── review-workbench.js/css
└── case-review-workbench.js/css
```

功能智能体目前没有专属模板。`ChoiceLoader` 已优先读取 `services/functional_agent/templates/`，因此本期可新增两个独立 V2 模板，不改 API 智能体模板和公共回退模板。

### 3.2 当前可复用能力

可直接复用：

- `agentFetch` 的 CSRF 和统一错误处理；
- 任务创建、列表、详情、取消、日志和 artifact API；
- `ReviewService`、`CaseReviewService`；
- `VersionedReviewStore` 的原稿、草稿和不可变确认文件；
- `revision + sha256` CAS；
- 测试点完整校验和 diff；
- 用例引用、覆盖、重复、JSON/XLSX 发布；
- `review_ai`、`case_review_ai`；
- 所有权、`task.view.all`、`tool.execute`、`task.cancel`；
- 持久化 FIFO、取消、超时、重启恢复和 sequence 隔离；
- Prompt/模型/Release/应用版本公开字段。

### 3.3 需要新增或扩展

- 任务展示标题；
- 任务列表搜索、状态和时间筛选；
- 功能智能体 V2 首页与任务工作台模板；
- 任务阶段的安全展示模型；
- 平面 JSON 与树的双向命令投影；
- Mind Elixir Adapter；
- 测试点和用例脑图控制器；
- 共享只读表格；
- 当前预览/已保存版本切换；
- 版本元数据列表和按版本只读加载；
- 一个统一功能开关；
- vendored 第三方资源及许可文件；
- Node 内置测试和浏览器验收。

### 3.4 当前测试基线

2026-08-14 本地检查结果：

| 项目 | 结果 |
|---|---|
| `AItestcase_Agents` | 113 passed；1 个既有 Python SyntaxWarning |
| `test-platform/backend` | 16 passed、1 failed |
| 平台后端失败原因 | 新增 `0013` 后定义总数已为 100，既有迁移测试仍断言 98 |
| `test-platform/frontend` | 9 passed |
| 平台前端生产构建 | 通过 |
| 当前 Alembic head | `20260815_0013` |
| 历史 `output/` 摘要 | `0b5cc7ea69dbb6f552b3474b146c524f6637362763066d61454d3e0c47576cea` |

后端迁移测试失败来自当前工作区已存在的 `0013` 与测试断言不同步，不是本 PRD 修改产生。M01 必须先将当前 head 的基线断言修正为 100，再增加本期 0014 的断言 101；不得跳过该测试。

### 3.5 工作区保护

当前根工作区存在 `log_filter_tool`、Compose 等其他用户修改，本期不得还原、覆盖或顺带调整。`AItestcase_Agents` 在根仓库索引中表现为 gitlink，实施前需记录其文件摘要和实际版本管理边界；本任务不修复 Git 结构。

---

## 4. 总体架构

### 4.1 组件图

```text
浏览器
┌────────────────────────────────────────────────────────────┐
│ FunctionalWorkbenchController                              │
│ ├── TaskListController / CreateTaskDialog                  │
│ ├── TaskProgressPresenter                                  │
│ └── ReviewWorkspaceController                              │
│     ├── FlatReviewState（唯一可写状态）                     │
│     ├── MindmapDomain（投影、命令、历史）                   │
│     ├── MindElixirAdapter（画布事件、守卫、选择）           │
│     ├── ReadonlyTableView                                  │
│     ├── DetailInspector                                    │
│     └── AISuggestionView                                   │
└───────────────────────┬────────────────────────────────────┘
                        │ 现有 HTTP/JSON
Flask                   ▼
┌────────────────────────────────────────────────────────────┐
│ web.py                                                     │
│ ├── task list/detail/create/cancel                         │
│ ├── ReviewService / CaseReviewService                      │
│ ├── AI Review API                                          │
│ ├── artifact/log                                           │
│ └── 版本只读加载和安全进度扩展                             │
└───────────────────────┬────────────────────────────────────┘
                        │
                        ▼
TaskStore / VersionedReviewStore / QueueManager / Runner
```

### 4.2 浏览器状态是页面级单例

每个 Review 工作区只创建一个状态对象：

```javascript
{
  resource: "test_points" | "test_cases",
  taskId,
  editable,
  rows: [{ uiKey, value }],
  originalRows,
  confirmedPoints,
  revision,
  serverSha256,
  savedRowsDigest,
  validation,
  coverage,
  diff,
  dirty,
  selectedKeys,
  selectedNodeId,
  filters,
  view: "mindmap" | "table",
  source: "draft" | "generated" | "confirmed",
  undoStack,
  redoStack,
  ai
}
```

说明：

- `uiKey` 只存在浏览器包装对象，不写进业务 JSON；
- `serverSha256` 始终是最近一次服务端响应中的 CAS 基准；
- `rows` 是脑图和表格的唯一业务数据源；
- Mind Elixir 节点只保存 `uiKey/kind/level/path` 等投影元数据；
- `originalRows` 用于 diff，不随草稿修改；
- 版本只读加载创建新的只读 state，不覆盖未保存草稿。

### 4.3 服务端保持平面模型

服务端不接受 Mind Elixir 的 `nodeData/arrows/summaries/theme`。保存前浏览器调用：

```text
cleanRows(state.rows)
→ 去除 uiKey 和任何 `_` 开头字段
→ 保留未知业务扩展字段
→ PUT points/cases
```

服务端继续执行 `CLIENT_PRIVATE_FIELD`、结构、大小、重复、覆盖和引用校验。

---

## 5. 前端文件与加载策略

### 5.1 新增文件

```text
AItestcase_Agents/
├── services/functional_agent/templates/
│   ├── functional_index_v2.html
│   └── functional_task_v2.html
├── services/common/static/
│   ├── functional-workbench-v2.js
│   ├── functional-workbench-v2.css
│   ├── mindmap-domain.mjs
│   ├── mindmap-view.mjs
│   └── vendor/mind-elixir/5.14.0/
│       ├── MindElixir.js
│       ├── MindElixir.css
│       ├── LICENSE
│       └── SHA256SUMS
└── tests/ui/
    ├── test_mindmap_domain.mjs
    └── test_mindmap_commands.mjs
```

### 5.2 修改文件

```text
AItestcase_Agents/services/common/web.py
AItestcase_Agents/services/common/task_models.py
AItestcase_Agents/services/common/versioned_review.py
AItestcase_Agents/services/common/review.py
AItestcase_Agents/services/common/case_review.py
AItestcase_Agents/services/common/static/agent-workbench.js
AItestcase_Agents/services/common/static/review-workbench.js
AItestcase_Agents/services/common/static/case-review-workbench.js
AItestcase_Agents/tests/services/test_web_routes.py
AItestcase_Agents/tests/services/test_review_domain.py
AItestcase_Agents/tests/services/test_case_review_domain.py
test-platform/backend/tests/test_migrations.py
test-platform/README.md
```

### 5.3 平台新增文件

```text
test-platform/backend/alembic/versions/
└── 20260816_0014_add_functional_workbench_v2.py
```

`0014` 必须下接当前实际 head `20260815_0013`，不能继续使用 PRD 编写时的 `0012`。

### 5.4 明确不修改

- 两个 Runner 的 Prompt 内容；
- `TaskStore` 文件协议；
- QueueManager 和 execution kind；
- API 智能体服务、页面和安全开关；
- Dockerfile 和 Python requirements；
- Compose 服务拓扑；
- Nginx 路由与请求体上限；
- 历史 `output/`；
- 平台 React 首页设计系统。

若实施中发现必须修改上述项，必须先证明是完成 PRD 的必要条件，并把差异记录到最终报告。

---

## 6. 第三方资源供应链设计

### 6.1 获取与固定

开发阶段执行一次：

```text
npm pack mind-elixir@5.14.0 --ignore-scripts
```

从官方 npm 包中只提取运行需要的：

- `dist/MindElixir.js`；
- `dist/MindElixir.css`；
- `LICENSE`。

随后：

- 记录 npm 包完整 SHA-256；
- 记录每个 vendored 文件 SHA-256；
- 不提交 tarball 和 `node_modules`；
- 不在生产镜像构建时访问 npm；
- 不修改 vendored 源文件；
- 升级版本必须单独评审并重新完成浏览器、安全和性能验证。

### 6.2 加载

V2 模板使用：

```html
<link rel="stylesheet" href=".../static/vendor/mind-elixir/5.14.0/MindElixir.css">
<link rel="stylesheet" href=".../static/functional-workbench-v2.css">
<script src=".../static/functional-workbench-v2.js" defer></script>
<script type="module" src=".../static/mindmap-view.mjs"></script>
```

所有路径由 `settings.base_path` 生成，不使用绝对域名或 CDN。

### 6.3 运行隔离

- 不启用 Markdown 回调；
- 不把用户文本传入 `innerHTML`；
- 不加载外部图片和链接；
- 不注册导出插件和右键菜单插件；
- 画布容器之外的保存、确认和 AI 操作由平台代码控制；
- Adapter 必须捕获库异常，恢复最后一次可用投影，不能污染 `rows`。

---

## 7. 平面数据与树投影

### 7.1 通用包装

业务条目不增加 `_rowKey` 等私有字段，改用包装：

```javascript
{
  uiKey: crypto.randomUUID(),
  value: structuredClone(serverItem)
}
```

`uiKey` 用于：

- 节点选择；
- 重复 ID 下的稳定定位；
- 撤销/重做；
- AI 建议应用；
- 表格与脑图互相定位。

### 7.2 测试点投影

输入：平面测试点数组。

输出层级：

```text
root
└── module
    └── feature
        └── scenario
            └── test_point leaf
```

算法：

1. 单次遍历 `rows`；
2. 使用嵌套 `Map` 按原始首次出现顺序聚合；
3. 分组键使用规范化比较文本，显示值保留首条原始文本；
4. 分组节点保存后代 `uiKey` 集合；
5. 叶子节点保存唯一 `uiKey`；
6. 错误/警告按 `row_index` 先映射为 `uiKey`，再向祖先汇总；
7. 过滤只改变投影，不改变 `rows` 顺序。

复杂度：时间 O(n)，附加空间 O(n)。

### 7.3 测试用例投影

输入：平面用例数组 + 已确认测试点摘要。

输出层级：

```text
root
└── module
    └── feature
        └── confirmed test point
            └── test case leaf
```

规则：

- 测试点节点以确认测试点列表创建，即使没有用例也存在；
- 测试点节点标记 `readonly=true`；
- 用例按 `test_point_id` 放入对应节点；
- 无效引用放入“无效引用”只读错误分组，保存后仍由服务端阻塞；
- module/feature 显示值来自确认测试点；
- 用例自身扩展字段只保留在 `rows.value`，不展开到树。

### 7.4 节点模型

Adapter 只创建以下元数据：

```javascript
{
  id: "ui-only-node-id",
  topic: "纯文本摘要",
  data: {
    kind: "root|module|feature|scenario|test_point|case|invalid_group",
    level: 0,
    resource: "test_points|test_cases",
    uiKey: null,
    descendantKeys: [],
    readonly: false,
    issueCounts: { errors: 0, warnings: 0 }
  },
  children: []
}
```

不把完整测试正文、Prompt、文件路径、Secret 或扩展字段复制进节点 `data`。

### 7.5 树不反向整体解析

禁止使用 `mind.getData()` 整体覆盖 `rows`。原因：

- 库数据无法完整保留未知业务字段；
- 任意节点可能绕过业务层级；
- 组节点不是业务对象；
- 会把主题、样式和库字段混入权威 JSON。

所有操作必须转为显式 Domain Command 后作用于 `rows`。

---

## 8. Domain Command 设计

### 8.1 命令类型

```text
rename_node
add_child
add_sibling
duplicate_node
delete_node
move_node
edit_detail
apply_ai_suggestions
reset_to_server
```

统一输入：

```javascript
{
  type,
  resource,
  node,
  target,
  payload,
  expectedSelection
}
```

统一输出：

```javascript
{
  rows,
  affectedKeys,
  selectionKey,
  impact: {
    added,
    modified,
    deleted,
    changedFields
  },
  historyPatch
}
```

命令失败返回本地稳定错误，不修改原 state。

### 8.2 测试点命令规则

#### 重命名分组

- module：批量更新后代 `module`；
- feature：批量更新后代 `feature`；
- scenario：批量更新后代 `scenario`；
- 测试点叶子：更新 `test_point`；
- ID 和风险在详情面板更新。

#### 新增

- 根下新增 module 时先创建空分组 UI，必须继续添加测试点后才能保存；
- 空分组不进入 `rows`，离开选择后自动移除；
- 场景下新增测试点时才增加业务条目；
- 测试点 ID 使用现有 `nextId()` 规则；
- 默认风险 `P2`。

#### 删除

- 叶子删除一个条目；
- 分组删除其全部后代条目；
- 删除全部条目允许保存草稿但服务端标记不可确认；
- 批量删除前展示条目数。

#### 移动

- module 只能在根下排序；
- feature 只能移动到 module；
- scenario 只能移动到 feature；
- test point 只能移动到 scenario；
- 移动分组批量更新对应上下文字段；
- 同级排序改变 `rows` 的稳定顺序，但不改变字段。

### 8.3 测试用例命令规则

- module/feature/test point 节点只读；
- 只能新增、复制、删除和编辑 case；
- case 可移动到另一个确认测试点；
- 移动后更新 `test_point_id/module/feature/scenario`；
- 目标测试点不存在或已过期时拒绝；
- Case ID 使用现有 `nextId()`；
- 默认优先级继承测试点风险；
- `actual_result` 永远不进入可写 payload。

### 8.4 操作守卫

Mind Elixir `before` 守卫必须覆盖：

- `insertSibling`；
- `addChild`；
- `removeNode`；
- `moveNode`；
- `beginEdit/finishEdit`。

守卫检查：

- 当前用户是否可编辑；
- 当前版本是否为 draft；
- 资源状态是否允许编辑；
- 源/目标层级是否合法；
- 可见节点是否超过 500；
- 用例测试点节点是否只读；
- 父节点操作是否需要平台确认。

库守卫只负责即时拦截。保存时仍由服务端重新校验。

### 8.5 撤销/重做

不使用完整 state 快照，使用增量 patch：

```javascript
{
  label,
  before: [{ uiKey, index, value }],
  after: [{ uiKey, index, value }],
  selectionBefore,
  selectionAfter,
  estimatedBytes
}
```

规则：

- 最多 50 步；
- 总估算内存最多 20 MiB；
- 达到内存上限先删除最早记录；
- 不跨刷新或标签页；
- 保存后记录保存点，但不清空当前会话历史；
- 重载服务端版本、导入 JSON 或解决 CAS 冲突后清空历史；
- 库自带 `allowUndo` 关闭，避免双撤销栈。

---

## 9. Mind Elixir Adapter

### 9.1 职责

`mindmap-view.mjs` 负责：

- 初始化/销毁 Mind Elixir；
- 把 `MindmapDomain.project()` 的树传入 `init/refresh`；
- 注册操作守卫；
- 把操作事件转为 Domain Command；
- 同步选择、展开、筛选和详情面板；
- 维护画布缩放和适配；
- 处理库异常和安全回滚；
- 暴露 `locate(uiKey)` 给错误摘要和只读表格。

不负责：

- HTTP；
- CAS；
- 服务端校验；
- AI 请求；
- JSON 下载；
- 任务状态轮询。

### 9.2 初始化选项

设计目标选项：

```javascript
{
  el: mapElement,
  direction: MindElixir.RIGHT,
  draggable: editable,
  editable,
  allowUndo: false,
  overflowHidden: true,
  contextMenu: false,
  toolBar: false,
  nodeMenu: false,
  markdown: undefined,
  before: operationGuards
}
```

具体 option 名称必须以 5.14.0 类型定义为准；不存在的配置不能伪造。无法关闭的菜单或功能通过不加载插件、操作守卫和 CSS 隐藏处理。

### 9.3 刷新策略

- 文本或小范围字段修改：更新 state 后重投影并 `refresh`；
- 展开/折叠：仅更新 UI 状态，不重建业务 state；
- 保存成功：用服务端返回替换 `rows`，保留当前选择可定位时的选择；
- 筛选变化：重投影可见树；
- 版本变化：销毁并重新初始化，避免库历史串入新版本；
- 异常：恢复最近一次成功投影并显示 `MINDMAP_RENDER_FAILED`。

### 9.4 可见节点保护

投影结果生成前计算可见节点数：

- ≤ 500：正常刷新；
- > 500：不调用渲染，显示“请先筛选或折叠”；
- 搜索定位可临时展开目标祖先，但仍不能突破 500；
- 全部展开在预计超过上限时拒绝；
- 不截断 `rows`，只限制画布投影。

### 9.5 画布偏好

仅把以下内容写入 `sessionStorage`：

- `view`；
- 折叠节点的逻辑路径哈希；
- 缩放级别；
- 最后选择的资源类型。

键包含 `base_path + environment + task_id`。不保存节点正文、草稿、Prompt、用户 ID、Secret 或绝对坐标。

---

## 10. 功能任务首页 V2

### 10.1 模板选择

`web.py:index()`：

```text
functional + FUNCTIONAL_WORKBENCH_V2_ENABLED=true
→ functional_index_v2.html

其他情况
→ 现有 index.html
```

API 智能体始终使用现有模板。

### 10.2 页面结构

```text
页面标题 + 新建生成任务
使用说明（默认折叠）
搜索/状态/时间筛选
任务表格
分页
创建任务 dialog
```

不把创建表单永久放在列表上方。

### 10.3 任务标题兼容

新增公开字段 `title`：

- 新任务必须提交 1～100 字符标题；
- 旧任务没有标题时显示 `project_name / module_name`；
- `project_name`、`module_name` 继续传给 Runner；
- V2 创建弹窗把项目和模块放入“生成范围”分组，保持必填；
- 复制重跑只预填标题、项目、模块、operation、feature 和补充说明；
- 浏览器安全规则禁止自动填充旧文件，用户必须重新选择文档。

### 10.4 列表 API 扩展

`GET /api/v1/tasks` 增加可选参数：

```text
q                 最长 200，匹配 title/id/input_original_name
status            现有状态；允许逗号分隔白名单状态
created_since     ISO 日期，仅允许日期
page              现有
page_size         现有，最大 100
```

服务端过滤顺序：所有权 → 查询 → 状态 → 日期 → 分页。

仍使用 TaskStore 内存列表扫描。每个智能体最多 500 个终态任务，不增加搜索索引或数据库。

### 10.5 创建任务

继续使用 `POST /api/v1/tasks multipart/form-data`，新增：

```text
title: string
```

其他字段、上传类型、大小、CSRF、队列上限和环境固定规则不变。

防重复：提交期间禁用按钮。服务端不新增通用创建幂等键；任务创建成功后页面立即跳转，失败保留表单。

---

## 11. 任务工作台 V2

### 11.1 模板选择

`web.py:task_page()`：

```text
functional + FUNCTIONAL_WORKBENCH_V2_ENABLED=true
→ functional_task_v2.html

其他情况
→ 现有 task_detail.html
```

### 11.2 稳定页面区域

```text
TaskHeader
├── 返回、标题、状态、短 ID
├── 数量、版本、模型
└── 取消/保存/确认等状态相关操作

StageRail
├── 需求读取
├── 需求拆解
├── 测试点生成
├── 测试点 Review
├── 用例生成
├── 用例 Review
└── 已发布

WorkspaceTabs
├── 脑图
├── 表格 · 只读
├── 产物
└── 日志
```

### 11.3 安全进度模型

服务端新增纯派生函数 `public_progress(record)`：

```json
{
  "stage": "generating_test_points",
  "label": "正在生成测试点",
  "state": "running",
  "completed_items": 12,
  "total_items": null,
  "determinate": false
}
```

规则：

- `stage/label/state` 来自现有 task status/stage 白名单映射；
- `completed_items` 仅在 task/review/case_review 元数据已有真实数量时返回；
- `total_items` 未知时为 `null`；
- 不解析日志推算百分比；
- 不读取 Runner 私有路径或进程信息；
- 不新增 progress 文件。

### 11.4 轮询

- 复用 `agent-workbench.js`；
- `running/pending` 5 秒；
- 页面隐藏时 15 秒；
- `waiting_review/waiting_case_review/succeeded/failed/cancelled` 停止任务轮询；
- AI 子任务存在时使用现有 AI 轮询；
- 状态变化需要刷新 Review 数据时由 controller 精确加载，不整页强制刷新；
- 网络失败指数退避到 30 秒，恢复后先重新读取任务详情。

---

## 12. 测试点脑图集成

### 12.1 现有 JS 复用

`review-workbench.js` 继续负责：

- Review GET/PUT；
- 本地校验摘要；
- CAS 处理；
- resume；
- AI request/get/cancel；
- JSON 导入导出；
- beforeunload。

V2 下改为把 state 和回调传给 `mindmap-view.mjs`。旧模式继续执行现有可编辑表格渲染。

### 12.2 V2 初始化

```text
GET review
→ wrapRows(points)
→ createReviewState
→ projectTestPoints
→ mountMindmap
→ mountReadonlyPointTable
→ renderSummary/issues/actions
```

### 12.3 详情面板

选中测试点叶子显示：

- ID；
- 模块；
- 功能；
- 场景；
- 测试点正文；
- 风险等级；
- 扩展字段只读摘要；
- 原稿对照（有修改时）。

选中分组节点显示：

- 分组名称；
- 后代数量；
- 错误/警告汇总；
- 重命名；
- 批量删除影响预览。

### 12.4 保存与继续

保存和 resume payload 不变。新增 UI 行为：

- 保存前结束节点快捷编辑；
- 规范化树命令已写入 `rows`，无需解析 Mind Elixir 数据；
- 保存成功后用服务端响应重建树和只读表格；
- resume 前存在 dirty 时先保存；
- warnings 仍需确认；
- 队列满时保留确认版本和当前视图。

---

## 13. 测试用例脑图集成

### 13.1 现有 JS 复用

`case-review-workbench.js` 继续负责：

- Case Review GET/PUT/import/download/confirm；
- 测试点摘要；
- 覆盖和校验；
- AI；
- 本地副本；
- beforeunload。

V2 只替换列表/详情的布局与事件接入，服务端协议不变。

### 13.2 不可编辑测试点节点

- 确认测试点只用于分组和移动目标；
- 测试点节点的 `before.beginEdit/removeNode/moveNode` 返回 false；
- 新增子节点只允许产生 case；
- 测试点无用例时仍保留；
- 未覆盖数量由当前 `rows` 实时计算，并以服务端结果校正。

### 13.3 用例详情

复用当前详情控件逻辑，补齐：

- 前置条件、步骤的上移/下移；
- 多行粘贴确认；
- Test Point 下拉；
- JSON/纯文本测试数据模式明确切换；
- 扩展字段只读；
- `actual_result` disabled/readonly；
- 编辑后更新脑图节点摘要和只读表格。

### 13.4 确认发布

现有 `case-review/confirm` 和 Publisher 不变：

- Idempotency-Key 继续由客户端生成；
- 保存 dirty 草稿后再确认；
- 警告二次确认；
- 发布成功切换只读确认版本；
- 发布失败保留 `waiting_case_review` 和当前草稿；
- 不增加 FIFO execution kind，因为现有 2,000 条发布性能已远低于 30 秒门槛。

---

## 14. 只读表格设计

### 14.1 单一实现

`mindmap-view.mjs` 提供共享 `ReadonlyReviewTable`，通过列定义适配测试点和用例。不得复制两套表格分页、筛选和定位逻辑。

接口：

```javascript
new ReadonlyReviewTable({
  root,
  resource,
  getRows,
  getIssues,
  getDirty,
  onLocate
})
```

### 14.2 只读强约束

表格 DOM 允许：

- `<table>`；
- 文本；
- 只读状态按钮；
- 筛选 input/select；
- 分页和“在脑图定位”。

业务单元格中禁止：

- input/select/textarea；
- `contenteditable`；
- 拖拽；
- 粘贴处理；
- 行内保存。

自动化必须断言业务单元格无上述控件。

### 14.3 数据来源切换

默认：当前浏览器预览。

用户选择“已保存草稿”时：

- 不请求第二份可写 state；
- 使用最近一次服务端响应的 `savedRows` 快照；
- 显示只读标识；
- 返回当前预览时继续使用 `state.rows`；
- 该切换不影响 brain map、不触发 HTTP。

### 14.4 定位

表格行保存 `uiKey`：

```text
点击“在脑图定位”
→ view=brainmap
→ 清除冲突筛选或提示用户
→ 展开祖先
→ adapter.locate(uiKey)
→ focus selected node
```

---

## 15. 版本加载与只读模式

### 15.1 服务端扩展

现有 GET 接口增加可选参数，默认行为不变：

```text
GET review?kind=working
GET review?kind=generated
GET review?kind=confirmed&version=N

GET case-review?kind=working
GET case-review?kind=generated
GET case-review?kind=confirmed&version=N
```

`working` 为默认草稿优先逻辑。

响应增加：

```json
{
  "source": { "kind": "draft", "version": null, "editable": true },
  "versions": [
    { "kind": "generated", "label": "模型原稿" },
    { "kind": "draft", "revision": 3, "sha256": "..." },
    { "kind": "confirmed", "version": 1, "sha256": "...", "confirmed_at": "..." }
  ]
}
```

不返回 `relative_path`。

### 15.2 VersionedReviewStore 扩展

增加两个通用方法：

```python
list_version_metadata(task_id) -> list[dict]
load_confirmed_version(task_id, version) -> Any
```

要求：

- version 必须为正整数；
- 只扫描固定确认文件模式；
- 使用 containment、非 symlink 和 JSON 完整性检查；
- 元数据只返回类型、版本、SHA、时间、数量；
- 损坏版本不影响其他版本读取，但返回稳定错误。

### 15.3 未保存切换保护

- dirty 时切换版本弹确认；
- 用户选择取消则保留当前 state；
- 选择继续则丢弃未保存浏览器修改，不删除服务器草稿；
- 只读版本禁止命令、AI、保存和确认；
- 返回 draft 时重新 GET，不能复用可能过期的旧 revision。

---

## 16. AI 建议脑图集成

### 16.1 请求协议不变

继续提交：

```json
{
  "operation": "supplement|rewrite_selected|generate_from_instruction",
  "revision": 3,
  "sha256": "...",
  "selected_ids": [],
  "scope": {},
  "instruction": "..."
}
```

脑图节点选择转换为现有 `selected_ids/scope`：

- 测试点叶子 → ID；
- 模块/功能/场景 → scope；
- 用例叶子 → Case ID；
- 用例测试点节点 → scope test_point_id；
- 根节点 → 空 scope，即全任务。

### 16.2 建议投影

AI 建议不写 `rows`，单独保存：

```javascript
state.ai.preview = {
  baseRevision,
  baseSha256,
  suggestions,
  selectedSuggestionIds
}
```

新增建议投影为虚线临时节点；replace 建议只在差异面板展示，不直接替换正式节点。

### 16.3 应用

```text
校验 base revision/SHA
→ 过滤用户明确选择的建议
→ Domain Command: apply_ai_suggestions
→ 更新 rows
→ 记录一个可撤销历史 patch
→ dirty=true
→ 移除已应用临时节点
```

不新增“AI 建议应用”服务端接口。应用不是持久化事实；审计继续以 AI 请求、保存草稿和确认事件为准，避免记录一个刷新后即消失的客户端动作。

---

## 17. 服务端公开模型与安全字段

### 17.1 任务公开字段

`task_models.py` 增加白名单字段：

```text
title
progress
test_point_count
test_case_count
test_point_review_version
test_case_review_version
```

所有值从 task 元数据派生。不得公开：

- PID；
- execution 内部路径；
- request 相对路径；
- Secret；
- Prompt 全文；
- Client Token；
-异常对象。

### 17.2 title 保存

`_new_record()` 保存 `title`；旧任务 `public_task()` 使用显示 fallback，不批量改写历史 `task.json`。

### 17.3 readiness

功能智能体 readiness 增加：

```json
{
  "functional_workbench_v2_enabled": true
}
```

只返回布尔值。API 智能体不返回该字段或固定 false。

---

## 18. Flask 路由改造

### 18.1 `index()`

- 读取安全普通配置；
- 判断 `FUNCTIONAL_WORKBENCH_V2_ENABLED`；
- V2 不把前 20 个 task 直接硬编码到完整列表，服务端先渲染首屏，后续筛选调用 API；
- 所有权过滤保持在服务端；
- API 智能体路径不变。

### 18.2 `task_page()`

- 增加 V2 模板选择；
- 传入现有四个 Review/AI 开关和新工作台开关；
- 传入公开 task、artifact 和权限布尔值；
- 不传配置正文、Prompt、路径或 Secret。

### 18.3 `list_tasks()`

- 增加 q/status/date 白名单解析；
- 对 title、ID、原始文件名使用不区分大小写的内存匹配；
- 最大 500 条规模无需新增索引；
- 排序固定 `created_at desc, id desc`；
- 页码超过范围返回空 items，不返回 404。

### 18.4 Review GET

- 支持 `kind/version`；
- working 默认完全兼容现有响应；
- generated/confirmed 强制 `editable=false`；
- 校验、diff、coverage 按加载内容重新计算；
- artifact 过期仍返回 410；
- confirmed version 不存在返回 404。

### 18.5 写接口

PUT、import、resume、confirm、AI request/cancel 无协议变更。V2 不新增批量保存、节点保存或自动保存接口。

---

## 19. 配置迁移设计

### 19.1 迁移信息

```text
revision: 20260816_0014
down_revision: 20260815_0013
文件: 20260816_0014_add_functional_workbench_v2.py
```

### 19.2 配置定义

```text
ID: functional-test-agent.FUNCTIONAL_WORKBENCH_V2_ENABLED
key: FUNCTIONAL_WORKBENCH_V2_ENABLED
owner_type: tool
owner_id: functional-test-agent
group_key: ui
value_type: bool
sensitivity: normal
required: true
default_value: false
apply_mode: next_task
editable: true
```

虽然页面开关可立即影响新请求，但沿用平台 `next_task` 配置发布语义，避免运行中的页面跨 Release 读取不同 UI 能力。任务记录继续保存创建时的 Release；页面使用当前部署环境活动 Release 决定入口。

### 19.3 upgrade

- 只插入一个定义；
- 不自动启用 prod；
- 不创建 Secret；
- 不修改工具、角色和权限；
- 不自动发布 dev Release。

dev 开启通过部署步骤创建新 Release，自动化通过后再发布。

### 19.4 downgrade

- 删除所有引用该 definition 的 release item；
- 删除 definition；
- 不删除 Release、Activation、Secret、审计或任务文件；
- 不触碰 0013 的两个 Admin operator 定义；
- 不触碰 0012 及更早的 Review 配置。

### 19.5 迁移测试

当前 head 100 个定义；0014 后应为 101。必须覆盖：

1. 空库 upgrade head；
2. 重复 upgrade head；
3. 默认值 false；
4. prod 无 true Release；
5. downgrade 0013 后剩 100；
6. 0013 两个定义仍存在；
7. re-upgrade 后恢复 101；
8. 再执行既有 0012/0011/0010 降级链。

---

## 20. 安全设计

### 20.1 信任边界

不可信输入包括：

- 需求和 Review JSON 中所有文本；
- 节点 topic；
- 任务标题、文件名和补充说明；
- URL query；
- AI 建议；
- local/session storage；
- Mind Elixir 操作事件。

服务端身份头、当前 Release 和 TaskStore 固定目录仍是可信边界，但都必须按现有规则校验。

### 20.2 XSS

- 业务文本只通过 `textContent/value`；
- 禁用 Markdown；
- 不设置 `dangerouslySetInnerHTML`；
- 不允许节点图片、href、HTML 标签或 style 字符串；
- AI reason/source_basis 继续纯文本；
- 测试 `<img onerror>`, `<svg onload>`, `</script>`, `javascript:`；
- vendored 资源不从用户数据构造模块路径。

### 20.3 权限与状态

前端只用于交互提示。所有保存、导入、确认、AI 和取消仍执行：

- 可信身份；
- CSRF；
- RBAC；
- 所有权；
- 当前任务状态；
- 功能开关；
- revision/SHA 或 Idempotency-Key。

越权和不存在统一 404。

### 20.4 local/session storage

- 使用 `sessionStorage` 而非永久 localStorage；
- 只存视图偏好哈希；
- 不存任务正文、草稿、模型响应和认证信息；
- JSON 解析失败直接清除该 key；
- 页面加载不得信任其中的 node ID 绕过服务端数据。

### 20.5 供应链

- 固定版本与 SHA；
- 保留 LICENSE；
- 不执行 npm lifecycle scripts；
- 不在生产构建访问 npm；
- `npm audit --omit=dev` 仅用于技术验证记录；
- vendored 文件改变时校验测试必须失败。

### 20.6 API 智能体不变

回归必须继续确认：

```text
API_EXECUTION_ENABLED=false
DATABASE_PERSIST_ENABLED=false
ALLOWED_TARGETS=[]
```

---

## 21. 可访问性设计

### 21.1 语义结构

- TaskHeader 使用一个 `h1`；
- 阶段导航使用有序列表和 `aria-current`；
- 工作区标签使用 tablist/tab/tabpanel；
- 脑图容器使用 `role=tree` 的可访问节点镜像或库节点语义增强；
- 详情面板使用语义化 form/fieldset/label；
- 问题摘要使用 region 和可聚焦按钮；
- 只读表格使用真实 table/th/scope。

### 21.2 键盘

- `↑/↓` 在可见节点移动；
- `←/→` 折叠/展开；
- `Enter/F2` 编辑允许的节点；
- `Tab/Shift+Tab` 在工具栏、画布、详情和操作栏移动；
- Delete 仅在节点聚焦且可编辑时触发，并遵守确认；
- 所有移动提供“移动到……”按钮，不只依赖拖拽；
- Escape 关闭快捷编辑、菜单和对话框。

### 21.3 焦点恢复

- 新增后聚焦新节点；
- 删除后聚焦上一同级或父节点；
- 撤销后聚焦恢复节点；
- 表格定位后聚焦脑图节点；
- 对话框关闭后回到触发按钮；
- 切换版本后聚焦版本选择器或根节点；
- 保存后不抢走当前编辑焦点。

### 21.4 降级可用性

若 Mind Elixir 的 DOM 无法达到完整树语义：

- 提供可见的“节点导航”列表；
- 列表仅用于选择节点，不编辑；
- 选中后在可访问详情面板编辑；
- 只读表格仍提供完整内容读取。

该降级属于 M05 必须验证的实现，不允许仅依赖鼠标画布。

---

## 22. 视觉设计实现约束

### 22.1 Token

继续使用现有：

```text
--background / #F5F5F7
--surface / #FFFFFF
--text / #1D1D1F
--muted / #6E6E73
--border / rgba(0,0,0,.12)
--blue / #0071E3
--red / 清晰错误红
--green / 克制成功绿
```

Mind Elixir 主题通过 CSS variables 映射到同一 token，不使用其默认彩虹主题。

### 22.2 布局

- 工作区宽度使用视口，不受 1200px 内容阅读宽度限制；
- 最小目标 1280×800；
- TaskHeader 高度稳定；
- 画布高度使用 `calc(100vh - header/tabs/actions)`，最小 560px；
- 详情面板宽 360～440px；
- 表格固定表头；
- 操作栏在视口底部或工作区底部稳定存在；
- 不使用卡片墙。

### 22.3 动效

- 150～250ms 选择、展开和面板切换；
- 拖拽反馈由库提供但颜色覆盖为平台 token；
- 不使用循环呼吸、漂浮或渐变动画；
- reduced-motion 下关闭平滑居中和展开动画。

---

## 23. 性能设计

### 23.1 算法

- 投影 O(n)；
- diff/校验继续 O(n)；
- 过滤使用一次规范化搜索文本缓存；
- 问题映射先构建 `row_index → uiKey`；
- 覆盖使用 Set；
- 同级排序只重排受影响 keys；
- 不做递归深拷贝全量 state 历史。

### 23.2 渲染

- 只渲染展开节点；
- 可见节点硬上限 500；
- 只读表格只渲染当前页；
- 详情只渲染当前节点；
- 搜索输入 150ms debounce；
- 画布刷新在一次 animation frame 合并；
- 轮询不触发无关画布刷新。

### 23.3 基准数据

新增确定性 fixture 生成器，不提交大体积产物：

- 100 条测试点；
- 500 条测试点；
- 5,000 条测试点；
- 100 条用例；
- 500 条用例；
- 2,000 条用例；
- 每条含长文本和扩展字段变体。

### 23.4 性能门槛

沿用 PRD：

- 100 条首次可交互 ≤ 2 秒；
- 500 条筛选 ≤ 300ms；
- 500 可见节点交互 P95 ≤ 100ms；
- 5,000/2,000 条投影 ≤ 2 秒且不全部展开；
- 脑图/表格切换 ≤ 300ms；
- 服务端校验 ≤ 2 秒。

性能失败不得通过提高可见节点上限、删除字段或跳过校验解决。

---

## 24. 错误处理

### 24.1 客户端稳定错误

```text
MINDMAP_LIBRARY_LOAD_FAILED
MINDMAP_RENDER_FAILED
MINDMAP_INVALID_OPERATION
MINDMAP_VISIBLE_LIMIT_EXCEEDED
MINDMAP_VERSION_READONLY
MINDMAP_LOCAL_STATE_INVALID
```

客户端错误只用于可操作提示和脱敏遥测，不替代服务端错误码。

### 24.2 失败策略

| 失败 | 行为 |
|---|---|
| vendor 加载失败 | 显示错误，提供切换旧 Review 的当前页面回退入口，不自动开启表格编辑 |
| 投影失败 | 保留 flat rows，显示下载本地副本 |
| 库操作异常 | 回滚本次命令，重刷最后成功投影 |
| 保存失败 | 保留 dirty 和撤销栈 |
| CAS 冲突 | 禁止继续写，提供本地副本/重载 |
| 版本损坏 | 仅该版本失败，其他版本仍可切换 |
| 轮询失败 | 标记状态可能过期，恢复后重新 GET |
| AI 失败 | 返回原 Review，可继续人工编辑 |

“切换旧 Review”只能在 V2 页面加载失败时重新请求同一任务的 legacy 模板参数；服务端仍按同一权限检查。详细设计推荐通过 `?legacy=1` 只在 dev/admin 调试使用，普通 prod 回滚依赖功能开关，避免用户绕过产品入口。

---

## 25. 测试设计

### 25.1 Node 内置测试

命令：

```bash
node --test tests/ui/*.test.mjs
```

不引入 Jest、Vitest、jsdom 或前端构建依赖。覆盖：

- 测试点 O(n) 投影；
- 用例 O(n) 投影；
- 首次出现顺序；
- 未知字段往返；
- 重复 ID 的 uiKey 定位；
- 分组重命名；
- 父节点删除；
- 合法/非法移动；
- 用例引用同步；
- 命令原子失败；
- patch undo/redo；
- 50 步/20 MiB 历史上限；
- 500 可见节点限制；
- XSS 文本作为普通字符串保留。

### 25.2 Python 单元测试

- 版本列表元数据不含路径；
- 按 confirmed version 读取；
- 损坏版本隔离；
- title fallback；
- safe progress 映射；
- list q/status/date；
- readiness 开关；
- generated/draft/confirmed 只读加载；
- 旧 GET 默认响应兼容。

### 25.3 API 集成测试

- V2/legacy 模板开关；
- 普通用户、其他用户、管理员、只读用户；
- CSRF；
- IDOR 404；
- Review GET kind/version；
- PUT/confirm/resume 与现有协议；
- AI request/get/cancel；
- 任务列表查询；
- 创建 title；
- artifact 过期 410；
- Secret/路径/Prompt 不回显。

### 25.4 浏览器测试

实施阶段使用 Playwright，在真实页面验证：

1. 任务列表筛选和创建弹窗；
2. 创建后进入工作台；
3. pending/running 阶段；
4. 测试点脑图新增、重命名、移动、删除、撤销；
5. 测试点只读表格同步；
6. 保存、刷新、CAS 冲突；
7. AI 建议临时节点、应用、保存；
8. 确认并重新排队；
9. 用例脑图和覆盖；
10. 用例详情、移动引用、只读表格；
11. 确认发布和产物下载；
12. 版本切换；
13. 只读权限；
14. vendor 加载失败回退；
15. 最大可见节点提示；
16. 键盘、焦点、200% 缩放和 reduced-motion。

### 25.5 安全测试

- topic XSS payload；
- AI suggestion XSS payload；
- title/file name XSS；
- arbitrary Mind Elixir data injection；
- illegal move event forgery；
- path/version manipulation；
- local session data corruption；
- read-only DOM 强制调用写 API；
- CSRF 缺失；
- ownership/IDOR；
- vendored SHA 校验；
- 无远程静态请求。

### 25.6 性能测试

- Node 投影计时；
- 浏览器首屏和筛选计时；
- 500 可见节点交互采样；
- 内存快照观察 50 次父节点批量操作；
- 反复脑图/表格切换无持续增长；
- 任务轮询不触发重复实例和 listener 泄漏。

---

## 26. 完整回归命令

```bash
cd /Users/admin/Testproject/AItestcase_Agents
python3 -m pytest -q
node --test tests/ui/*.test.mjs

cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q

cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run
npm run build
npm audit --audit-level=high

cd /Users/admin/Testproject/test-platform
python3 -m unittest discover -s tests -v
docker compose config
docker compose exec -T platform-gateway nginx -t
```

此外：

- 校验 vendored SHA；
- 检查浏览器网络无第三方请求；
- 隔离数据库执行 0014 upgrade/downgrade/re-upgrade；
- 检查功能/API 智能体故障隔离；
- 重新计算历史 `output/` 摘要。

本地平台 smoke 若仍因既有管理员凭据返回 401，不得重置密码；使用隔离身份测试和已有有效浏览器会话完成等价验收，并在最终报告记录。

---

## 27. 工作包 M01～M18

### M01 基线冻结与技术验证

实施：

- 记录 Git、gitlink、用户修改和 `output/` 摘要；
- 运行当前完整回归；
- 修正 0013 引入后迁移测试的既有定义数量断言；
- 获取并校验 mind-elixir 5.14.0；
- 做最小页面验证：加载、纯文本、守卫、拖拽、键盘、500 节点、销毁重建；
- 验证无远程请求和无富文本执行。

完成标准：技术验证通过；当前 baseline 绿；用户修改和历史目录登记完成。

### M02 配置迁移

实施：

- 新增 0014；
- 定义 `FUNCTIONAL_WORKBENCH_V2_ENABLED=false`；
- 精确 downgrade；
- 修正迁移测试总数为 101；
- dev/prod 隔离测试。

完成标准：upgrade、重复 upgrade、downgrade 0013、re-upgrade 全通过。

### M03 共享投影内核

实施：

- `mindmap-domain.mjs`；
- row wrapper；
- 测试点/用例投影；
- issue/coverage 映射；
- 过滤和可见节点计数；
- Node 测试。

完成标准：往返不丢扩展字段，O(n) 与最大数据性能通过。

### M04 Domain Command 与历史

实施：

- 通用命令协议；
- 测试点命令；
- 用例命令；
- 增量 patch；
- 50 步/20 MiB 上限；
- 原子失败和 undo/redo 测试。

完成标准：每条命令可撤销，非法命令不改变 state。

### M05 Mind Elixir Adapter

实施：

- vendored 资源；
- 初始化、刷新、销毁；
- operation guards；
- 选择、定位、展开、缩放；
- 安全文本；
- 键盘语义增强；
- 渲染失败回滚。

完成标准：画布操作全部经 Domain Command，无法提交库内部数据。

### M06 任务首页 V2

实施：

- V2 模板；
- 列表筛选、分页；
- 创建 dialog；
- title 和旧任务 fallback；
- 复制重跑预填；
- 空、加载、错误、队列满状态。

完成标准：新建任务直接进入工作台，API 智能体页面无变化。

### M07 任务工作台壳与进度

实施：

- V2 task 模板；
- TaskHeader、StageRail、tabs；
- safe progress；
- 轮询与网络恢复；
- 取消；
- 产物和日志标签。

完成标准：所有状态有明确当前阶段和下一步，无虚假百分比。

### M08 测试点脑图

实施：

- 测试点投影接入；
- 增删改复制移动；
- 分组批量影响；
- 详情面板；
- 问题定位；
- 保存和 resume。

完成标准：完整测试点主流程通过，旧表格模式可回退。

### M09 测试点只读表格与版本

实施：

- 共享只读表格；
- 当前预览/已保存快照；
- 原稿/草稿/确认版本；
- 表格定位脑图；
- 业务单元格无编辑控件测试。

完成标准：脑图和表格一致，切换不写服务端。

### M10 测试点 AI 脑图集成

实施：

- 选择节点转 scope/IDs；
- 临时新增节点；
- replace 差异；
- 基准冲突；
- apply command；
- 取消/失败恢复。

完成标准：AI 不自动写草稿，应用可撤销且仍需保存。

### M11 测试用例脑图

实施：

- 确认测试点树；
- 未覆盖节点；
- 用例新增/复制/删除；
- 用例跨测试点移动；
- 引用和上下文同步；
- 问题定位。

完成标准：测试点节点不可编辑，移动用例后的服务端校验正确。

### M12 用例详情与只读表格

实施：

- 详情编辑；
- 条件/步骤排序和多行粘贴；
- 数据模式切换；
- actual_result 只读；
- 用例只读表格；
- 覆盖筛选和定位。

完成标准：复杂字段可编辑，表格永久只读，覆盖一致。

### M13 用例 AI 与发布

实施：

- 用例 AI 建议投影；
- add/replace 应用；
- 基准过期；
- 保存、confirm、Idempotency-Key；
- 成功后只读确认版本和下载。

完成标准：AI 与发布主流程通过，JSON/XLSX 同源。

### M14 服务端公开模型和版本 API

实施：

- title/progress/public counts；
- list 查询；
- readiness；
- VersionedReviewStore 版本元数据；
- GET kind/version；
- 模板选择；
- API 集成测试。

完成标准：默认接口向后兼容，新增响应不含路径和 Secret。

### M15 权限、安全和审计

实施：

- 所有角色矩阵；
- CSRF、IDOR；
- XSS 和非法事件；
- vendored SHA；
- sessionStorage；
- 审计脱敏；
- API 安全默认回归。

完成标准：安全测试全部通过，前端隐藏不作为唯一防线。

### M16 可访问性与性能

实施：

- 键盘、焦点、tree/tab/table 语义；
- 200% 缩放；
- reduced-motion；
- 最大数据基准；
- 内存和 listener 检查；
- 三种桌面视口。

完成标准：PRD 性能门槛和桌面可访问性验收通过。

### M17 集成、镜像与灰度

实施：

- 完整回归；
- Compose/Nginx 检查；
- 构建功能智能体镜像；
- non-root/健康检查；
- dev 发布开关；
- 故障隔离；
- 关闭开关回退演练。

完成标准：功能、API、网关健康，关闭开关可立即回到旧界面。

### M18 文档与交付

实施：

- README 使用、配置、运维和回滚；
- 第三方许可说明；
- 最终文件清单；
- 自动化和浏览器结果；
- 设计差异和风险；
- `output/` 摘要复核；
- Git diff 范围检查。

完成标准：交付报告完整，无无关修改、提交、推送或 PR。

---

## 28. 阶段 MR01～MR07

| 阶段 | 工作包 | 目标 | 质量门槛 |
|---|---|---|---|
| MR01 基线与内核 | M01～M05 | 锁定依赖、投影、命令和画布 Adapter | 纯数据与画布技术验证通过 |
| MR02 平台壳 | M02、M06、M07、M14 | 配置、任务列表、工作台和服务端扩展 | 旧接口/旧界面兼容 |
| MR03 测试点 | M08～M10 | 测试点脑图、只读表格、版本和 AI | 测试点完整流程通过 |
| MR04 测试用例 | M11～M13 | 用例脑图、详情、覆盖、AI 和发布 | JSON/XLSX 同源发布通过 |
| MR05 质量 | M15～M16 | 安全、权限、可访问性和性能 | 安全与性能门槛通过 |
| MR06 灰度 | M17 | 迁移、镜像、dev 开关和回滚 | 运行态与故障隔离通过 |
| MR07 交付 | M18 | 文档、最终回归和报告 | 完成定义全部满足 |

推荐执行顺序：

```text
M01 → M03 → M04 → M05
   ↘ M02 → M14 → M06 → M07
                    ↓
              M08 → M09 → M10
                    ↓
              M11 → M12 → M13
                    ↓
              M15 → M16 → M17 → M18
```

每个工作包执行：

```text
失败测试/技术验证
→ 最小实现
→ 局部回归
→ 阶段回归
→ 更新计划状态
```

---

## 29. 工作量估算

| 工作域 | 估算 |
|---|---:|
| 基线、依赖验证、迁移 | 1.5～2.5 人日 |
| 投影、命令、历史、Adapter | 5～7 人日 |
| 任务列表和工作台壳 | 2～3 人日 |
| 测试点脑图、表格、AI | 3～4 人日 |
| 用例脑图、详情、表格、AI | 4～6 人日 |
| 服务端版本扩展 | 1.5～2.5 人日 |
| 安全、可访问性、性能 | 2～3 人日 |
| E2E、灰度、文档 | 2～3 人日 |
| **总计** | **21～31 人日** |

最大不确定性是 Mind Elixir 对 500 个可见长文本节点、操作守卫和键盘语义的实际表现。M01 技术验证必须在正式 UI 开发前完成，用于收敛估算，不允许把风险推迟到 M16。

---

## 30. dev 发布步骤

1. 冻结工作区、当前 head、测试和 `output/` 摘要；
2. 完成 mind-elixir 获取、许可和 SHA 校验；
3. 完成 Node、Python、平台和浏览器自动化；
4. 在隔离数据库验证 0014 往返；
5. 本地 dev 数据库只执行 upgrade；
6. 构建功能智能体镜像；
7. 保持 `FUNCTIONAL_WORKBENCH_V2_ENABLED=false` 启动并检查旧界面；
8. 发布新的 dev Release，把开关设为 true；
9. 验收任务列表和生成工作台；
10. 验收测试点脑图/表格/AI/继续；
11. 验收用例脑图/表格/AI/发布；
12. 验收权限、CAS、最大数据、键盘和三种视口；
13. 停止功能智能体，确认 API 智能体继续健康，再恢复；
14. 关闭开关验证旧界面回退，再重新开启 dev；
15. 执行完整回归和 `output/` 最终摘要。

prod 不在本设计实施阶段自动开启。

---

## 31. 回滚

### 31.1 一级回滚：功能开关

```text
FUNCTIONAL_WORKBENCH_V2_ENABLED=false
```

效果：

- 新请求使用现有首页和任务详情；
- 已保存草稿、确认版本和产物不变；
- Review API 不变；
- 测试点/用例 AI 不变；
- 不需要删除静态资源。

### 31.2 二级回滚：镜像

- 恢复上一版功能智能体镜像；
- 保留任务卷；
- 平台、API 智能体和网关继续运行；
- 现有 JSON/XLSX 可下载。

### 31.3 迁移回滚

通常保留 0014。确需 downgrade：

1. 先关闭 V2 开关；
2. 确认没有活动 Release 依赖该定义；
3. 备份 dev 数据库；
4. downgrade 到 `20260815_0013`；
5. 验证 0013 两个定义和 0012 Review 配置仍在；
6. 不删除任务、审计、草稿、建议、确认版本或产物。

---

## 32. 已知风险与决策记录

### 32.1 已接受风险

- 浏览器不持久化自由坐标，刷新后使用自动布局；
- 不做多人协作和版本合并；
- 表格永远只读；
- 500 可见节点为硬保护，超量必须折叠/筛选；
- sessionStorage 中的折叠状态不是业务数据；
- title 是新增显示字段，旧任务使用 fallback；
- 创建任务仍保留项目和模块字段以兼容 Runner。

### 32.2 技术风险

| 风险 | 检测点 | 缓解 |
|---|---|---|
| 库渲染用户 HTML | M01 | 禁用 Markdown、XSS fixture、Adapter 编码 |
| 长文本/500 节点性能不足 | M01/M16 | 默认折叠、摘要、可见节点硬限制 |
| 库操作与 flat state 分叉 | M04/M05 | 全部事件转 Domain Command，禁止整体 getData 写回 |
| 父节点批量操作历史过大 | M04/M16 | 增量 patch + 20 MiB 上限 |
| 键盘语义不足 | M05/M16 | 节点导航和详情面板降级 |
| 0013 工作区测试已红 | M01 | 先修正既有数量断言再加 0014 |
| gitlink 导致变更不可见 | M01/M18 | 固定文件清单和 SHA，最终报告单列 |

---

## 33. 与 PRD 的实现细化与差异

### 33.1 实现细化

- 选定 `mind-elixir 5.14.0`，PRD 不再留下库选择分支；
- 使用自托管 vendored 资源，不引入 Node 生产构建；
- 使用 Domain Command 而非把库树反向整体解析成业务 JSON；
- 撤销历史增加 20 MiB 内存上限，同时保持最多 50 步；
- 视图偏好使用 `sessionStorage`，比 PRD 允许的 localStorage 更保守；
- 版本读取通过现有 GET 的可选 `kind/version` 扩展完成；
- 创建任务保留项目/模块字段，title 作为新增展示字段；
- 生成进度只从 task 元数据派生，不新增 progress 文件。

### 33.2 与 PRD 的局部差异

1. PRD 编写时 Alembic head 为 0012；当前代码已到 0013，因此本期使用 0014；
2. PRD 建议可审计 `mindmap_ai.suggestion_applied`，设计不新增纯客户端应用事件；以 AI 请求、草稿保存和确认审计形成持久事实链；
3. PRD 允许 localStorage，设计采用生命周期更短的 sessionStorage；
4. PRD 提到旧界面回退，prod 只通过功能开关实现；`?legacy=1` 仅允许 dev/admin 调试，不成为普通用户入口；
5. PRD 对脑图库保持中立，设计已选择并固定版本。

这些差异不改变产品行为、安全边界、权威数据或回滚能力。

---

## 34. 完成定义

全部满足才可交付：

1. M01～M18 全部完成；
2. MR01～MR07 质量门槛全部通过；
3. 任务列表、创建、生成、两类脑图、两类只读表格和发布主流程可用；
4. 脑图是唯一编辑入口，表格不存在业务编辑控件；
5. 脑图、表格和保存 JSON 内容一致；
6. 测试点/用例原稿、草稿、AI 建议、确认版本和产物隔离；
7. AI 不自动应用、保存或确认；
8. CAS、幂等、权限、CSRF、所有权和 IDOR 通过；
9. 最大数据性能、键盘、焦点和三种桌面视口通过；
10. vendored 依赖许可、版本、SHA 和无远程请求验证通过；
11. 0014 upgrade/downgrade/re-upgrade 通过；
12. API 智能体三个安全默认值不变；
13. 功能/API 智能体故障隔离通过；
14. 新开关关闭时旧界面完整可用；
15. prod 新开关保持 false；
16. 原 CLI、现有 Review、平台和相关工具回归通过；
17. 用户已有修改和历史 `output/` 未被覆盖、还原、删除或写入；
18. 未提交、推送、创建分支或 PR，除非用户另行授权；
19. 最终报告包含范围、文件、架构、迁移、配置、测试、浏览器、风险、部署、回滚和设计差异。

---

## 35. 最终实施结论

本设计选择的最短可靠路径是：

```text
保留现有后端和 Review 文件协议
+ 一个共享平面数据/命令内核
+ 一个受控 Mind Elixir 画布 Adapter
+ 两个功能智能体专属 V2 模板
+ 一个统一功能开关
```

没有引入新的业务数据库、任务状态机、队列、服务、前端框架或生产构建链。复杂性被限制在浏览器投影和交互层，任何时候都可以关闭一个配置开关回到当前已验证的 Review 页面。该方案满足 PRD 对“平台感、脑图唯一编辑、表格只读、AI 辅助和可靠版本”的全部要求，同时最大程度保护已完成的测试点/用例 Review 投资。

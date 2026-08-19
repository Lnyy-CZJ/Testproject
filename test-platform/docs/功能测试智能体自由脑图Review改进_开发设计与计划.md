# 功能测试智能体自由脑图 Review 改进——开发设计与计划

> 文档版本：V1.0
> 编写日期：2026-08-19
> 状态：已评审，执行中
> 需求基线：《功能测试智能体自由脑图 Review 改进 PRD》V1.1

---

## 1. 设计目标

本期在现有 Flask、Jinja、原生 JavaScript、Mind Elixir、文件任务存储和单槽 FIFO 上增量实现，不新增业务数据库表、队列、服务、前端框架或配置迁移。

核心改变是将 Review 编辑状态从“仅标准 rows”升级为“自由 mindmap + 编译后 rows”：

```text
脑图命令
→ 修改 mindmap
→ 确定性编译 rows
→ 生成质量问题
→ 统一 CAS 保存
→ 确认结构快照和标准 JSON
→ Runner 或 JSON/XLSX 发布
```

完成后：

- 所有可见节点具有一致的选择、定位和原位编辑行为；
- 非推荐层级不再被前端静默拦截，而是产生可定位问题；
- 测试点继续前可确认质量风险；
- 测试用例只要是安全的对象数组并能发布 JSON/XLSX，就不因质量问题被阻止；
- 已发布任务可继续修改并形成 v2、v3 等不可变版本。

## 2. 现状与根因

### 2.1 当前实现

- `mindmap-domain.mjs` 从 rows 生成标准树，命令直接更新 rows。
- `mindmap-view.mjs` 负责 Mind Elixir 实例、选择、拖动、原位编辑和定位。
- `ReviewService` 和 `CaseReviewService` 使用文件 CAS 保存 rows 草稿。
- 测试点和用例确认版本是不可变 JSON，用例 Publisher 从确认 JSON 生成 XLSX。

### 2.2 根因

rows 无法表达空分组、非推荐父子关系和根节点，因此旧命令必须在交互前限制结构。节点类型守卫又分散在 View、Controller 和 Domain Command，造成节点类型间行为不一致。

本设计保留 rows 作为下游标准输入，但不再要求它表达全部编辑中间状态。

## 3. 数据协议

### 3.1 草稿信封 V2

```json
{
  "schema_version": 2,
  "revision": 4,
  "content_sha256": "...",
  "rows": [],
  "mindmap": {
    "root": {
      "node_id": "root_xxx",
      "node_type": "root",
      "text": "登录功能测试"
    },
    "nodes": [
      {
        "node_id": "node_xxx",
        "node_type": "module",
        "parent_id": "root_xxx",
        "order": 0,
        "binding_id": null,
        "text": "登录"
      }
    ]
  }
}
```

字段约束：

| 字段 | 作用 | 约束 |
|---|---|---|
| `schema_version` | 草稿格式 | 新草稿固定为 2 |
| `revision` | CAS 版本 | 成功改变正文后递增 |
| `content_sha256` | 正文指纹 | 对稳定化 `rows + mindmap` 计算 |
| `rows` | 标准业务数据 | 由服务端从 mindmap 重新编译 |
| `mindmap.root` | 当前根 | 必须唯一，可编辑 |
| `mindmap.nodes` | 自由结构 | 节点 ID 在当前草稿中唯一 |

`mindmap` 不保存坐标、缩放、折叠、选择、焦点或小地图视口。

### 3.2 节点类型

```text
root
module
feature
scenario
test_point
case
preconditions_content
steps_content
expected_content
test_data_content
```

`node_type` 是语义和编译提示，不是前端编辑权限。所有可见节点使用同一选择和编辑管道。

### 3.3 旧数据兼容

- V1 草稿仅有 `points/cases` 或 rows 时，读取时投影为推荐结构。
- 兼容投影不写回原文件，用户首次显式保存时才写 V2。
- 确认数组 JSON 协议不变，Runner 和 CLI 不读取 mindmap 快照。
- 旧镜像降级时允许从 V2 信封中读取 `rows`；若稳定版本未携带该兼容，运行手册先将 `rows` 投影回 V1 信封。

## 4. 编译与校验

### 4.1 通用结构校验

以下为硬错误，不允许保存：

- 根或节点不是 JSON 对象；
- `node_id` 缺失或重复；
- `parent_id` 指向当前草稿外；
- 形成循环；
- 节点数、字节数、字符数或嵌套深度超限；
- 存在 NUL 或保留内部字段；
- 内容无法安全 UTF-8 JSON 序列化。

非推荐父子关系、空分组、缺少标准祖先和字段问题均是质量问题。

### 4.2 测试点编译

1. 按 `order + node_id` 稳定遍历树。
2. 对每个 `test_point` 节点生成一条 row。
3. 从最近的 `module/feature/scenario` 祖先提取标准字段。
4. 没有相应祖先时写空字符串并绑定节点问题。
5. `binding_id` 匹配旧 row 时保留 ID、风险等级和未知扩展字段。
6. 编译不为空分组伪造测试点。

### 4.3 测试用例编译

1. 对每个 `case` 节点生成一条对象 row。
2. 从最近的 `test_point` 祖先提取 `test_point_id`。
3. 从祖先分组提取可推导的模块、功能和场景。
4. 前置和步骤内容按非空行转为数组。
5. 预期结果保存完整文本。
6. `test_data` 优先安全解析 JSON，失败时保留原文字符串并产生提示。
7. 未知扩展字段按 `binding_id` 原样往返。

### 4.4 一键整理

“整理为推荐结构”只是一个预览后执行的领域命令：

- 按当前编译 rows 重建推荐树；
- 预览显示移动、合并、丢弃空分组的数量；
- 执行作为一个 patch，可一次撤销；
- 不自动执行，不修改原稿和历史版本。

## 5. 文件事务与版本

### 5.1 路径

```text
input/review-draft.json
input/review-test-points-vN.json
input/review-test-points-mindmap-vN.json
input/case-review-draft.json
input/review-test-cases-vN.json
input/review-test-cases-mindmap-vN.json
published/test-cases/vN/test-cases.json
published/test-cases/vN/test-cases.xlsx
```

### 5.2 草稿事务

- 服务端校验请求 revision/SHA。
- 服务端从 mindmap 重新编译 rows。
- 对稳定化 `rows + mindmap` 计算新 SHA。
- 内容未变时返回当前 revision。
- 内容变化时写临时文件、flush、fsync并原子替换。
- 任何失败不更新任务索引。

### 5.3 确认事务

1. 在临时文件中写入脑图快照并 fsync。
2. 原子创建 `*-mindmap-vN.json`。
3. 原子创建标准 `*-vN.json`，它是版本提交标记。
4. 更新 `task.json` 索引。
5. 索引失败时保留已提交文件，首次读取通过固定命名和 SHA 修复索引。
6. 已存在的版本文件不得覆盖。

## 6. 领域命令与撤销

统一命令包含：

```text
rename_node
insert_child
insert_sibling
delete_subtree
delete_root_and_reset
copy_subtree
move_subtree
reorder_sibling
bulk_move
normalize_structure
update_row_field
apply_ai_suggestion
```

命令执行流程：

1. 克隆当前草稿内存快照。
2. 验证节点存在、无循环、无越界引用且未超限。
3. 一次性应用结构变更。
4. 编译 rows 和质量问题。
5. 成功后才提交新状态和逆向 patch。
6. 任何异常返回稳定错误，原状态、dirty 和历史不变。

`delete_root_and_reset` 使用强确认，记录影响行数，清空当前树并创建新根；逆向 patch 保存整棵原树和 rows。

## 7. 画布事件模型

### 7.1 单一事件拥有者

- Mind Elixir 原生编辑器是唯一原位编辑入口。
- Controller 只处理 Domain Command，不再创建第二个文本编辑器。
- `click` 只选择和安全区定位。
- `dblclick`、`F2`、`Space` 只调用同一 `beginEdit(nodeId)`。
- Pointer 超过拖动阈值后才 capture，单击和双击不会被拖动抢占。
- 所有节点通过统一 `data-node-id` 解析，不按叶子/分组分支。

### 7.2 定位

脑图单击、表格“定位”、搜索、问题面板和版本差异均调用 `selectAndReveal(nodeId)`：

- 展开父链；
- 选中并显示非纯颜色高亮；
- 仅在节点离开安全可视区时平移；
- 不改变业务数据或 dirty。

## 8. 测试点继续状态机

```text
waiting_review/review_editing
  → PUT draft
  → POST resume
  → POINT_REVIEW_RISK_CONFIRMATION_REQUIRED（存在质量问题且未确认）
  → POST resume + acknowledge_quality_risks + validation_sha256
  → 不可变确认版本
  → pending/queued
  → running/generating_test_cases
```

`resume` 必须按 `queued_at + task_id` 重新参与 FIFO。队列满时保留草稿和确认版本，任务仍处于 `waiting_review`。

## 9. 测试用例发布状态机

```text
waiting_case_review/* 或 succeeded/case_review_published
  → PUT case draft
  → POST case confirm
  → 对象数组和安全边界校验
  → 不可变 review-test-cases-vN.json
  → 同源 JSON/XLSX
  → succeeded/case_review_published，指向最新 vN
```

质量问题不改变发布资格。相同正文 SHA 重试复用版本；不同 SHA 创建下一个版本。

## 10. XLSX 发布器

列顺序固定为：

```text
case_id, test_point_id, module, feature, scenario, case_name, priority,
preconditions, test_steps, test_data, expected_result, actual_result, 其他字段
```

转换规则：

- 缺失值为空单元格；
- 数字和布尔值使用明确文本；
- 数组按换行展开；
- 对象按键稳定 JSON 序列化；
- `test_steps` 数组输出编号文本；
- 非标准键汇总到“其他字段”的稳定 JSON；
- 所有单元格先执行公式注入防护；
- 字段类型异常不得使整份 XLSX 失败。

## 11. HTTP 协议扩展

不新增公共路由，只向现有 GET/PUT 增加兼容字段。

### 11.1 Review GET

返回 `rows`、`mindmap`、`schema_version`、revision/SHA、校验问题和当前版本。读取 V1 草稿时在响应中投影 V2，不回写文件。

### 11.2 Review PUT

```json
{
  "revision": 4,
  "sha256": "...",
  "rows": [],
  "mindmap": {"root": {}, "nodes": []}
}
```

- 旧客户端的 `points/cases` 请求仍可用，服务端自动投影 mindmap。
- 新客户端必须同时提交 rows 和 mindmap。
- 服务端重新编译，与客户端 rows 不一致时以编译结果为准并返回 `ROWS_RECOMPILED`提示。

### 11.3 测试点 Resume

```json
{
  "revision": 4,
  "sha256": "...",
  "acknowledge_quality_risks": true,
  "validation_sha256": "..."
}
```

风险摘要在草稿变化后必须失效，防止用户确认旧问题却继续新数据。

### 11.4 错误协议

新增稳定错误码：

- `MINDMAP_INVALID`
- `MINDMAP_CYCLE_DETECTED`
- `MINDMAP_NODE_LIMIT_EXCEEDED`
- `POINT_REVIEW_RISK_CONFIRMATION_REQUIRED`
- `CASE_ITEM_NOT_OBJECT`
- `ROWS_RECOMPILED`（响应提示，非 HTTP 错误）

响应只包含节点 ID、字段、问题码、revision/SHA、数量和容量信息，不回显路径、Prompt、Secret 或异常对象。

## 12. AI 建议适配

- AI 仍输出 add/replace 建议，不直接写草稿。
- 建议通过 `binding_id` 匹配业务行，应用时产生普通 Domain Command。
- AI 不能修改 `node_id`、确认快照、历史版本、`actual_result` 或内部字段。
- 建议应用可撤销，仍需用户显式保存和确认/发布。

## 13. 安全、权限与审计

- GET 继续要求 `tool.result.view`；编辑、整理、继续和发布要求 `tool.execute`。
- 所有写请求继续验证可信身份、双提交 CSRF、所有权和任务状态。
- 越权和不存在统一 404。
- 用户文本以 `textContent` 或表单 value 呈现，不渲染 HTML、Markdown、图片或链接。
- 根删除、风险继续、宽松发布和一键整理写审计事件；只记录数量、版本、SHA 和稳定错误码。
- 不改变 API 智能体的执行、数据库和目标网络默认值。

## 14. 恢复策略

| 故障 | 处理 |
|---|---|
| mindmap 缺失 | 从 rows 投影推荐结构 |
| mindmap 损坏但 rows 完整 | 回退投影并记录恢复提示 |
| rows 损坏但 mindmap 完整 | 重新编译 rows；硬结构错误时提供草稿下载 |
| 结构快照已写、确认 JSON 失败 | 未提交版本，下次重试可复用或清理孤立快照 |
| 确认 JSON 已写、索引失败 | 首次读取自动修复索引 |
| XLSX 部分发布失败 | 不登记任何本次 Artifact，已发布版本不受影响 |
| 浏览器 CAS 冲突 | 保留完整本地 rows+mindmap 下载和重载入口 |

## 15. 性能与可访问性

- 平面节点索引、编译、循环检测和 rows 生成均为 O(n)。
- 同时可见节点最多 500，超限通过折叠、搜索或聚焦显示。
- 原位编辑支持键盘提交/取消，所有按钮有可见焦点和中文可访问名称。
- 错误、警告、选中和只读状态不只依赖颜色。
- 200% 缩放下主操作不重叠；`prefers-reduced-motion` 下禁用非必要动画。
- 500 可见节点交互 P95 ≤ 100ms，500 条搜索 ≤ 300ms，5000 条编译与服务端校验各 ≤ 2s。

## 16. 实施工作包

| 工作包 | 交付内容 | 质量门槛 |
|---|---|---|
| FR01 | PRD V1.1、本设计文档、Git/测试/output 基线 | 文档决策无待确认项，基线可复核 |
| FR02 | V2 草稿、稳定 SHA、V1 投影、结构快照 | CAS、原子写和兼容测试通过 |
| FR03 | 树检查、两类编译器、质量/硬错误分级 | 循环、孤立、非标准结构和扩展字段通过 |
| FR04 | 统一命令、根删除、自由移动、撤销 | 命令原子性和 50 步历史通过 |
| FR05 | 单一画布事件内核 | 所有节点 click/dblclick/F2/Space 真实指针验证通过 |
| FR06 | 测试点自由编辑和三视图同步 | 非标准结构可保存并定位问题 |
| FR07 | 风险确认 resume、快照确认、FIFO | 风险 SHA 和重新排队测试通过 |
| FR08 | 用例四内容节点和 `test_data` 编辑 | 脑图往返不再按步骤拆节点 |
| FR09 | 对象数组宽松发布、XLSX 稳健转换、多版本 | 质量问题可发布，非对象元素拒绝 |
| FR10 | 表格/详情/脑图共享命令与 CAS 冲突恢复 | 三视图与保存 JSON 一致 |
| FR11 | AI 建议 V2 适配 | 不自动保存/确认/发布，应用可撤销 |
| FR12 | 身份、CSRF、RBAC、所有权、IDOR 和审计 | 安全矩阵和脱敏测试通过 |
| FR13 | 旧草稿/旧确认/旧 multipart、损坏恢复和 CLI | 不批量改写旧数据，Runner 只读标准数组 |
| FR14 | 全量回归、Chrome 验收、本机 8080、README 和报告 | 历史 output 摘要不变，无无关修改 |

固定顺序：

```text
FR01
→ FR02 → FR03 → FR04 → FR05
→ FR06 → FR07
→ FR08 → FR09 → FR10
→ FR11 → FR12 → FR13
→ FR14
```

## 17. 测试设计

### 17.1 Python

- V1/V2 草稿读写、CAS、稳定 SHA、结构快照和索引恢复。
- 树循环、孤立节点、重复 ID、扩展字段和最大数据量。
- 测试点风险确认 SHA 过期、幂等确认和 FIFO 重入。
- 用例对象数组、非对象元素、异常字段、未知键和多版本。
- JSON/XLSX 同源、其他字段、换行、稳定 JSON 和公式注入。
- 权限、CSRF、所有权、IDOR、容量、路径和过期行为。

### 17.2 Node UI

- 两类树投影和编译。
- 所有节点统一命令、根删除/重建/撤销、自由移动和整理。
- 用例四内容节点和 `test_data` JSON/文本往返。
- click/dblclick/F2/Space、拖动阈值、定位共用和销毁监听器。
- 表格、详情、脑图、AI 建议和 dirty SHA 同步。

### 17.3 真实浏览器

在 1280×800、1440×900、1920×1080 与 200% 缩放验证：

- 根和全部业务/内容节点的选择、定位、编辑和删除；
- 根删除强确认、空根重建和撤销；
- 测试点非标准结构保存、问题定位和带风险继续；
- 用例四内容节点、宽松发布和 v2/v3；
- 双标签 CAS、权限角色、键盘、reduced-motion 和控制台错误。

## 18. 发布与回滚

### 18.1 本机发布

1. 完成全部自动化。
2. 确认未新增 Alembic 迁移或配置开关。
3. 仅重建 `functional-test-agent` 镜像。
4. 保持 API 智能体和平台其他容器不变。
5. 在本机 8080 完成真实 Chrome 回归。
6. 复核 Git diff 和历史 `output/` 摘要。

### 18.2 回滚

- 恢复上一版功能智能体镜像，不删除任务卷。
- 不需要 Alembic downgrade。
- 保留 V2 草稿、结构快照、确认版本、产物和审计。
- 如旧镜像无法读取 V2，执行运行手册中的 V2 `rows` 到 V1 草稿的可逆转换，不改写原文件。
- 不操作生产环境；生产部署需单独授权。

## 19. 完成标准

- FR01～FR14 全部达到质量门槛。
- 脑图不再因节点类型出现选择、定位和编辑差异。
- 测试点质量问题可定位且确认后可继续。
- 测试用例对象数组可安全发布 JSON/XLSX，不因质量问题被拦截。
- 测试步骤只占一个内容节点，`test_data` 可在脑图编辑。
- 根节点可删除、重建和撤销，历史数据不受影响。
- 已发布任务可生成多个不可变版本。
- 原 CLI、既有 Review、平台和 API 智能体回归通过。
- 无独立开关、无新数据库迁移、无生产变更。
- 用户既有修改和历史 `output/` 未被覆盖、删除或写入。

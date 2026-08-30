# Dating 多图片 Analysis Flow 设计说明

> 日期：2026-08-28  
> 状态：已由用户确认，进入实施  
> 适用项目：`dating`  
> 运行边界：AI 测试工作台 dev 平台固定执行 Dating test 环境

## 1. 目标与成功标准

本次在现有 Gateway 接口自动化工具中新增一个可交互的 Dating Analysis Flow，使测试工程师可以在创建任务时选择本机图片，并按照图片顺序完成多媒体上传和关系分析。

成功标准：

1. Web 创建 Flow 任务时，仅在所选 Flow 声明文件输入契约时展示图片选择区。
2. 支持一次选择 1～9 张 JPEG、PNG 或 WebP；浏览器先做基础校验，服务端重新校验真实文件。
3. 图片按选择顺序逐张执行 `PrepareMediaUpload -> PUT -> CompleteMediaUpload`，随后一次性将全部 `asset_ids` 提交给 `CreateAnalysisTask`。
4. 仅当 `GetAnalysisTask` 返回成功终态后调用 `GetAnalysisResult`；失败或拒绝终态使任务失败。
5. 不调用 `DeleteTaskData`，任务输入图片和远端分析数据均保留。
6. 任务重试创建新任务并复制原任务图片；原图缺失时以 `TASK_INPUTS_MISSING` 明确失败。
7. 现有 `single_image_analysis_happy_path` 固定 fixture Flow 保持不变，默认 smoke/regression 不自动执行新交互 Flow。
8. 用户提供的 `example_02` 九张图片可完成本机页面选择、任务持久化、顺序上传和结果展示验收。

## 2. 已确认的产品行为

### 2.1 创建任务

创建页继续沿用现有左右双栏结构：左侧为任务参数，右侧为只读运行上下文和 Flow 预览。选择 `multi_image_analysis` 后，在 Flow 与标签之间展开“分析图片”输入块：

- 原生文件选择控件支持多选，`accept` 限定 JPEG、PNG、WebP。
- 展示已选数量、总大小、按顺序排列的文件名、类型、大小和移除按钮。
- 图片数量、格式或单图大小不满足前端边界时，提交按钮保持禁用，并在字段附近给出可恢复的中文错误。
- 任务预览同步显示“图片 9 张”等输入摘要，但不展示或生成可公开访问的图片 URL。
- 切换到不需要图片的 Flow 时，清空浏览器中的已选文件，避免误提交到其他 Flow。

现有 Apple-inspired 页面语言、卡片、间距、按钮、状态提示与焦点样式继续复用；不增加素材管理页，不引入新的前端框架。

### 2.2 任务提交契约

普通任务保持现有 JSON 请求。仅含文件输入的 Flow 使用：

```http
Content-Type: multipart/form-data

task_payload=<原任务 JSON 字符串>
media_files=<文件 1>
media_files=<文件 2>
...
```

客户端仍只能提交项目和测试资产选择，不得提交或覆盖 `target_env`、Gateway、Release、Secret、Credential、超时和轮询参数。运行上下文继续由平台解析。

### 2.3 文件校验与持久化

服务端是文件输入边界的最终裁决者：

- 数量：1～9 张。
- 允许格式：`image/jpeg`、`image/png`、`image/webp`。
- 初始单图保护上限：7 MB；实际业务上限还需在执行阶段使用 `GetMediaUploadConfig` 返回值再次校验。
- 根据文件头识别真实类型，并与声明 MIME 对照，不能只信浏览器文件名或 Header。
- 文件流式写入并计算 SHA-256，超过上限立即停止。
- 原文件名仅作为展示元数据；磁盘文件名使用顺序号、摘要前缀和受控扩展名，不接受用户路径片段。
- 文件和输入清单使用 `0600` 权限。

持久化位置：

```text
runtime/<project_id>/<task_id>/inputs/
├── manifest.json
├── 001-<sha256-prefix>.png
├── 002-<sha256-prefix>.png
└── ...
```

任务 V2 记录只保存非敏感元数据：原始显示名、安全文件名、MIME、大小、SHA-256、任务相对路径。图片内容不写入任务 JSON、日志、JUnit、Allure 或浏览器存储。

删除任务时，现有 `TaskStore.delete()` 删除整个 `runtime/<project>/<task>`，因此附件随任务清理；本次不改变该生命周期。正常任务完成后不自动删除。

### 2.4 重试

重试沿用“新任务 + 新快照”语义，同时把旧任务输入复制到新任务专属目录：

- 新任务获得新的任务 ID、平台快照和输入清单。
- 复制顺序与原任务一致，复制后重新校验大小和摘要。
- 旧任务目录和记录不修改。
- 任一源文件缺失或摘要不匹配时，不创建不可执行的新任务，返回 `TASK_INPUTS_MISSING`。

## 3. Flow 执行模型

### 3.1 业务步骤

```text
GetMediaUploadConfig（一次）
  -> 使用实时配置校验全部图片
  -> foreach 图片（保持用户选择顺序）
       PrepareMediaUpload
       PUT 签名地址
       CompleteMediaUpload
       收集 asset_id
  -> CreateAnalysisTask（一次，传全部 asset_ids）
  -> GetAnalysisTask（轮询）
       succeeded -> GetAnalysisResult
       failed/rejected -> 整个任务失败
       timeout -> 整个任务失败
```

该 Flow 不包含 `DeleteTaskData`，也不配置终止清理步骤。

### 3.2 通用 DSL 扩展

为避免把 Dating 业务写死在公共引擎中，Flow DSL 增加三个通用能力：

1. `foreach`
   - 只支持一层非嵌套循环。
   - `items` 解析为列表，`item` 定义当前元素变量。
   - 子步骤复用既有 API/action/wait 语义。
   - `collect` 按迭代顺序收集指定运行时表达式，写回列表变量。

2. 受控点路径变量
   - 支持 `{{media_file.relative_path}}` 这类仅由字母、数字、下划线和点组成的路径。
   - 逐层读取字典键，不支持任意表达式、方法调用、数组脚本或属性反射。
   - 完整占位符保留原始类型；混合字符串仍转成文本。

3. 任务输入文件上传
   - `signed_binary_upload` 的 `fixture` 和 `input_file` 二选一。
   - `input_file` 只能解析到当前任务 `inputs/` 内的普通文件；拒绝绝对路径、`..`、符号链接和目录。
   - 旧 `fixture` 行为保持兼容。

另增加通用 `validate_binary_inputs` action，在任何外部上传发生前，用 Flow 从 API 响应提取出的允许类型、数量和大小限制校验完整输入列表。

### 3.3 运行时输入传递

任务执行进程通过 `API_AUTOTEST_TASK_INPUT_MANIFEST_FILE` 获得当前任务输入清单的绝对路径。该变量只指向任务私有文件，不承载平台配置或 Secret。

`test_gateway_flow.py` 读取并校验清单中的 project/task 归属，把 `media_files` 元数据作为初始运行时变量，并把清单父目录作为 FlowRunner 的唯一任务输入根目录。没有输入清单时，默认执行集合会跳过声明必填文件输入的交互 Flow；显式选择该 Flow 却缺少输入时必须失败。

## 4. Dating 资产

新增：

```text
projects/dating/data/flows/multi_image_analysis.yaml
projects/dating/data/scenarios/multi_image_analysis.yaml
```

Flow 标签只包含 `interactive`，不包含 `smoke` 或 `regression`。Flow 的文件输入契约是 Web、服务端和 catalog 的共同声明源；页面不得按 Flow ID 硬编码图片控件。

现有 11 个 Dating API 定义继续作为唯一接口资产来源，不复制协议字段，不使用 REST mock 路径。

## 5. 日志、报告与可观察性

遵循用户已确认的日志策略：执行日志不脱敏。为避免图片泄漏，附件内容本身仍不写日志；上传日志记录既有请求信息和每张图片的顺序、名称、大小、摘要，Flow 报告按“第 i/n 张”展开。

Flow 业务步骤统计以声明步骤为准；`foreach` 每次迭代可以在 Allure 中展开，但不会把 9 张图片误显示为 9 个不同业务 Flow。

任务详情展示输入图片元数据和保留状态，不提供任意下载路径。任务、日志、JUnit 和 Allure 仍沿用项目/环境/任务隔离规则。

## 6. 错误契约

主要错误码：

- `TASK_INPUTS_REQUIRED`：Flow 需要图片但未提交。
- `TASK_INPUT_COUNT_INVALID`：数量不在 1～9 范围。
- `TASK_INPUT_TYPE_INVALID`：声明或真实文件类型不支持/不一致。
- `TASK_INPUT_TOO_LARGE`：单图超过服务端保护上限或实时上传配置上限。
- `TASK_INPUTS_MISSING`：重试或执行时原输入丢失、摘要不一致。
- `FLOW_INPUT_CONSTRAINT_FAILED`：实时媒体上传配置与任务输入不匹配。
- `FLOW_TERMINATED`：分析任务进入失败或拒绝终态。

错误响应不包含文件内容、绝对路径、Secret 或平台快照值。

## 7. 风险与控制

- **磁盘增长**：用户明确要求保留输入；继续使用现有任务删除能力做显式清理，暂不增加自动保留期。
- **恶意文件**：以文件头、大小、路径边界和普通文件校验阻断伪造 MIME 与路径穿越。
- **部分上传**：完整输入必须在第一次外部上传前通过实时配置校验；上传中途失败时不创建 Analysis 任务，已上传远端对象按用户要求不主动清理。
- **平台配置隔离**：新 Flow 不增加本地环境配置；Gateway、轮询、超时和 Credential 继续来自 Dating/test 的平台 Release/Scope。
- **回归风险**：新 DSL 保持旧 step 语义；现有固定单图 Flow、单接口任务与 JSON 提交路径均通过回归测试保护。

## 8. 验收范围

自动化验收覆盖：Flow/Scenario 静态校验、受控变量解析、路径边界、文件头校验、顺序复制、重试、multipart 路由、页面状态、FlowRunner 完整假 Gateway 调用序列和现有回归。

本机验收使用 `example_02/chat_01.png` 至 `chat_09.png`：

1. 页面选择 9 张图片并保持文件名顺序。
2. 提交后确认任务记录只含元数据，磁盘有 9 个 `0600` 文件。
3. 确认执行日志和报告按 1～9 顺序展开。
4. 在 dev/test 具备有效平台登录态与 Gateway 可用时运行真实 Analysis，并确认不调用 `DeleteTaskData`。


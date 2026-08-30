# 接口自动化“仅本次运行参数修改”PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 产品版本 | V2.1 |
| 文档版本 | V1.2 |
| 日期 | 2026-08-29 |
| 文档状态 | 已实施并发布到本机 dev 平台 |
| 适用仓库 | `Truthy_ApiAutoTest2` |
| 适用入口 | 测试开发平台中的 `api-autotest` Web 工具 |
| 上位需求 | `接口自动化多项目支持与Dating接入-PRD.md` V1.3 |
| 核心决策 | YAML 继续作为 Case、Flow、Scenario 的唯一真源；Case 与 Flow 自动开放安全静态请求叶子，显式声明仅用于增强元数据和约束，修改仅作用于本次新任务 |

### 1.0.2 V1.2 Flow 通用能力实施修订（优先于 V1.1 与下文 V1.0 冲突描述）

- 多接口 Flow 不再要求为普通静态步骤参数逐项编写 `runtime_inputs`；框架按 Flow API 步骤顺序自动读取同名 Scenario 的 `step_data.<step>.params`；
- 自动开放 `string`、`integer`、`number`、`boolean` 类型的安全静态叶子，并用“步骤 ID + 参数路径”生成跨步骤不冲突的稳定逻辑键；
- 依赖前序接口或运行时上下文的模板值，以及 Token、Secret、Gateway、Header、`client_request_id`、`task_id`、`asset_id(s)`、上传 URL 和文件路径等字段继续跳过；
- Scenario 顶层显式 `runtime_inputs` 保留为可选增强，用于友好标签、枚举或额外约束，并替代同一步骤、同一路径的自动字段；
- Flow 创建页按步骤展示自动字段；若当前 Flow 没有安全静态参数，则显示明确空态；任务快照、重试、日志和报告契约保持不变。

### 1.0.1 V1.1 实施修订（优先于下文 V1.0 冲突描述）

- 单接口 Case 不再要求为每个普通请求参数重复编写 `runtime_inputs`；框架自动读取 `request.params` 中已有的安全静态标量叶子并生成输入控件；
- 自动字段根据 YAML 默认值推断 `string`、`integer`、`number` 或 `boolean`，字符串不预设候选值，用户可以输入任意通过服务端校验的同类型值；
- Case 的显式 `runtime_inputs` 保留为可选增强，只用于自定义标签、枚举或额外约束，并覆盖同一路径的自动定义；
- Flow/Scenario 的显式最小白名单规则已由 V1.2 自动发现能力替代；
- 动态模板、数组、null、超长字符串、非安全数值及凭证、环境、Gateway、Header、任务/素材 ID 等字段不会被自动开放；
- 无可编辑参数的单接口 Case 显示明确空态；覆盖值仍只进入任务快照，不写回 YAML。

### 1.1 文档目的

当前接口自动化的 Case、Flow 和 Scenario 由项目包中的 YAML 维护。该方式适合代码评审、Git 版本管理和批量维护，但在联调或快速排查时，测试人员往往只想临时改变 `locale`、业务枚举、开关或普通数值等请求参数。如果每次都修改 YAML、提交代码并在执行后还原，调试成本较高，也容易将临时数据误提交为正式用例。

本 PRD 定义“仅本次运行参数修改”能力：用户在创建单接口任务或 Flow 任务时均可修改框架自动发现的安全静态请求参数；显式 `runtime_inputs` 只作为可选元数据和约束。系统完成服务端校验后，将结果固化为当前任务的不可变执行快照。该修改不会写回 YAML、不会写入平台配置、不会影响后续任务，也不会改变历史任务。

本文档同时回答一个关键问题：**本需求涉及接口自动化工具框架的有限改造**，包括资产声明、目录返回、Web 表单、预检、任务快照和执行入口；但**不涉及测试开发平台配置模型、平台数据库、Runtime Scope、Release、Secret/Credential 或环境映射的改造**。

### 1.2 与上位 PRD 的关系

本 PRD 是多项目接口自动化 PRD 的增量需求，未明确修改的规则继续沿用上位 PRD。

以下原则保持不变：

- 测试开发平台仍是 Runtime Scope、Release、Gateway、公共 `comm`、Header、超时、轮询、Secret/Credential 和会话配置的唯一真源；
- `projects/<project_id>/` 中的 API、Case、Flow、Scenario 和 fixture 仍是测试资产唯一真源；
- dev 平台只能执行 test 接口，prod 平台只能执行 prod 接口，Web 不提供接口环境切换；
- 平台模式必须使用平台物化快照并 fail-closed，不允许回退 YAML、`.env` 或继承的配置环境变量；
- 不允许浏览器覆盖 Gateway、环境、Release、Profile、Token、Secret、超时或轮询配置；
- 项目、任务、日志和报告仍按 `project_id` 隔离。

上位 PRD 中“在线创建或编辑 API、Case、Flow、Scenario”仍属于后续能力。本期只是**任务级参数覆盖**，不构成在线编辑或第二套资产真源。

### 1.3 名词定义

| 名词 | 定义 |
| --- | --- |
| 基础资产 | 当前任务选中的 Case，或 Flow 与其对应 Scenario 的 YAML 内容 |
| 静态请求参数 | YAML 中直接保存的普通业务值，例如 `locale: en-US`、`dating_goal: serious_relationship` |
| 动态请求参数 | 由运行过程生成、提取或注入的值，例如 `client_request_id`、`task_id`、`asset_ids`、Token、签名 URL 和上传文件路径 |
| 可运行时修改参数 | Case 或 Flow/Scenario 中自动发现或显式增强的安全静态请求参数 |
| 运行时覆盖值 | 用户本次提交的逻辑字段名和值集合，即 `runtime_overrides` |
| 资产版本 | 服务端根据本次选中资产的规范化内容生成的 SHA-256 摘要，用于发现预检与提交之间的 YAML 变化 |
| 执行资产快照 | 服务端将基础资产与运行时覆盖值合并并校验后，为当前任务固化的不可变执行数据 |

---

## 2. 背景与问题

### 2.1 当前方式的优势

YAML 继续作为 Case、Flow 和 Scenario 的唯一真源，具有以下优势：

- 可通过 Git 追踪每次修改、评审差异并回滚；
- 可与代码、接口定义和执行引擎一起进行分支管理；
- 适合批量编辑、复制、检索和代码评审；
- 不依赖数据库即可离线执行；
- 不会形成 Web 数据与仓库数据不一致的双真源。

### 2.2 当前方式的不足

- 快速尝试一个参数值也需要修改 YAML；
- 临时修改容易污染正式资产或被误提交；
- 非代码用户无法在任务提交前直观看到可调参数；
- 任务记录只能看到所选 Case/Flow，难以还原该次任务到底使用了哪些临时值；
- 在 Flow 中，用户无法安全地只修改某一步的普通业务参数，而不触碰步骤拓扑、动态变量和断言。

### 2.3 要解决的核心问题

在不引入数据库、不改变唯一真源、不开放任意 YAML 编辑的前提下，为单接口 Case 和 Flow 提供安全、可追踪、可复现的本次运行参数修改能力。

---

## 3. 产品目标与成功标准

### 3.1 产品目标

1. 用户可在 Web 创建任务时快速修改框架安全识别或资产显式增强的请求业务参数；
2. 临时值只影响当前新任务，不修改 YAML、平台配置、其他任务或历史任务；
3. Case 与 Flow 使用同一套逻辑字段、校验、预检、快照和审计规则；
4. 动态变量、环境配置、凭证、接口定义、断言和 Flow 拓扑保持只读；
5. 任务详情能准确展示基础值、覆盖值、最终执行值和资产版本；
6. 旧资产、旧客户端和历史任务保持兼容。

### 3.2 成功标准

| 编号 | 成功标准 |
| --- | --- |
| S-01 | 未声明 `runtime_inputs` 的 Case 与 Flow 均自动展示安全静态参数；没有安全静态参数时显示空态并按 YAML 默认值执行 |
| S-02 | Case 自动字段和 Flow 声明字段均显示 YAML 默认值，用户可输入并通过预检执行 |
| S-03 | 客户端提交非当前资产可修改字段、目标路径或禁止字段时，在启动 pytest 和请求 Gateway 前被拒绝 |
| S-04 | 修改 Case 参数只影响所选 Case；修改 Flow 参数只影响所选 Flow 的指定步骤 |
| S-05 | 动态占位符、Token、Secret、Gateway、环境、Release、Profile、Header、超时和轮询值无法通过该功能修改 |
| S-06 | 任务记录保存原始覆盖值和最终执行快照，任务启动后不可修改 |
| S-07 | 重试创建新任务，不修改原任务；参数定义发生不兼容变化时明确提示重新确认 |
| S-08 | 执行前后对应 YAML 文件内容和修改时间均保持不变 |
| S-09 | Truthy 与 Dating 的同名逻辑字段只解析各自项目资产，不能跨项目读取或应用 |
| S-10 | 已有文件上传 Flow 可同时接收图片和本次运行普通参数，两个输入通道互不覆盖 |

### 3.3 产品指标

- 参数覆盖任务提交成功率；
- 参数校验失败原因分布；
- 因临时调试而直接修改正式 YAML 的次数下降；
- 覆盖任务中资产版本冲突的数量；
- 覆盖任务与普通任务的执行结果、任务记录和报告完整率。

---

## 4. 用户与核心场景

### 4.1 目标用户

- 测试工程师：在接口联调或回归前快速改变本次请求数据；
- 测试开发工程师：维护 Case 默认请求值，并在确有需要时补充 Case 约束或 Flow 白名单；
- 研发人员：从任务详情确认该次失败实际使用的请求业务值；
- 平台管理员：继续维护运行配置和凭证，不参与测试资产参数管理。

### 4.2 场景一：修改单接口 Case 参数

1. 用户选择项目、API 和 Case；
2. 系统自动发现该 Case 的安全静态 `request.params`，并合并可选 `runtime_inputs` 元数据；
3. 页面展示 YAML 当前值及按默认值类型生成的自由输入控件；
4. 用户修改一个或多个字段；
5. 预检展示“本次修改 2 项”，并校验字段、类型、范围和资产版本；
6. 用户提交后创建新任务；
7. 执行器使用合并后的快照，YAML 保持不变；
8. 任务详情展示基础值、覆盖值和最终值。

### 4.3 场景二：修改 Flow 某一步参数

1. 用户选择 `multi_image_analysis` Flow；
2. 系统从对应 Scenario 加载可运行时修改参数；
3. 页面将字段按 Flow 步骤分组，例如“创建 Analysis 任务 / locale”；
4. 用户修改 `locale` 并选择图片；
5. 服务端只把该值应用到 `create_analysis` 的请求参数；
6. 上传文件、`client_request_id`、`asset_ids` 和 `task_id` 仍由原有运行流程生成；
7. 整个 Flow 使用同一个不可变执行快照完成。

### 4.4 场景三：恢复默认值

用户修改参数后，可恢复单个字段或全部字段。恢复后该字段不进入 `runtime_overrides`，执行时直接使用当前 YAML 基础值。

### 4.5 场景四：按原参数重试

用户在任务详情点击“按原运行参数重试”时，系统创建新任务并复制原任务的逻辑覆盖值。新任务仍重新解析当前 Runtime Scope、Release 和 Credential，并使用当前资产定义重新校验覆盖值；原任务和原快照不变。

如果当前资产已删除字段、修改类型或不再允许该字段，系统拒绝直接重试并提示用户进入任务创建页重新确认。

---

## 5. 产品原则与边界

### 5.1 Case 自动发现，Flow 显式允许

单接口 Case 根据 `request.params` 自动生成可编辑字段，但只接受已有的安全静态标量叶子；动态模板和框架保留语义由服务端统一跳过。这样新增普通 Case 参数即可直接调试，不需要复制字段路径或预设候选值。

Case 与 Flow 的 `runtime_inputs` 均是可选增强：显式声明可为某一路径提供更友好的名称、枚举和约束，并替代同一路径的自动字段。Flow 仅扫描真实 API 步骤的 `step_data.<step>.params`；模板依赖和保留语义字段不会自动开放。

### 5.2 只修改请求业务参数

P0 只允许修改：

- 单接口 Case 的 `request.params` 中的静态叶子值；
- Flow 对应 Scenario 中 `step_data.<step_id>.params` 的静态叶子值。

P0 不允许修改：

- API ID、`service_name`、`method_name`、请求方法或传输路径；
- HTTP/Gateway Header、公共 `comm`、设备公共参数和协议信封；
- `project_id`、平台环境、`target_env`、Runtime Scope 或 Release；
- Credential Profile、Token、Secret、账号、会话和管理员凭证；
- 超时、轮询间隔、重试策略或并发策略；
- Case/Scenario 的断言、提取规则、标签或名称；
- Flow 步骤、顺序、条件、循环、清理策略、Action 或拓扑；
- fixture 路径、签名上传 URL 或文件元数据；
- 由模板、提取、文件上传或执行器生成的动态值。

### 5.3 只影响当前任务

- Web 不提供“保存到用例”“覆盖 YAML”或“发布参数”入口；
- 服务端不得修改项目包文件；
- 任务提交后覆盖值和执行快照不可变；
- 后续任务仍从当前 YAML 默认值开始；
- 历史任务始终显示其创建时的快照，不随 YAML 或配置变化。

### 5.4 服务端决定目标位置

客户端只提交逻辑字段名和值，不能提交 YAML 路径、步骤 ID 或目标 Scope。Case 与 Flow 的目标位置均由服务端自动发现结果或可选声明解析。

### 5.5 动态值不可配置

如果目标的 YAML 基础值包含 `{{...}}` 模板，或目标值由前序步骤提取、文件上传、会话或 Runtime Context 注入，则该字段不得声明为可运行时修改参数。项目校验命令和服务端预检都必须拒绝此类声明。

---

## 6. YAML 资产声明契约

### 6.1 单接口 Case 自动字段与可选声明

通常只需在 `request.params` 保存正式默认值，框架会自动生成自由输入控件，无需增加 YAML 字段。确有枚举、标签或范围约束时，`runtime_inputs` 可位于具体 Case 内，与 `request`、`assert`、`extract` 同级；显式字段键是提交 API 使用的稳定逻辑键，并替代其目标路径的自动字段。

```yaml
api: UpdateUserPreferences
cases:
  - id: update_user_preferences_success
    name: 更新 Dating 用户偏好
    tags: [dating, preferences]
    request:
      params:
        dating_goal: serious_relationship
        your_voice: warm_direct
    runtime_inputs:
      dating_goal:
        label: 约会目标
        description: 仅影响本次 UpdateUserPreferences 请求
        type: enum
        options:
          - serious_relationship
          - casual_dating
        target:
          scope: case_request
          path: $.dating_goal
        required: true
      your_voice:
        label: 回复语气
        type: enum
        options:
          - warm_direct
          - playful
        target:
          scope: case_request
          path: $.your_voice
        required: true
    assert:
      http_status: 200
```

### 6.2 Flow 声明

Flow 的请求数据归属 Scenario。通常只需在 `step_data.<step>.params` 保存正式默认值，框架会自动生成输入控件；需要额外枚举、标签或范围约束时，`runtime_inputs` 可位于同名 Scenario YAML 顶层，与 `name`、`variables`、`step_data` 同级。Flow YAML 中现有的 `inputs.media_files` 继续只负责文件输入，不改变其契约。

```yaml
name: Dating 多图关系分析并保留任务数据
variables: {}
runtime_inputs:
  analysis_locale:
    label: Analysis 结果语言
    description: 修改 CreateAnalysisTask 的 locale
    type: enum
    options: [en-US, zh-CN]
    target:
      scope: flow_step_request
      step_id: create_analysis
      path: $.locale
    required: true
step_data:
  create_analysis:
    params:
      client_request_id: "{{client_request_id}}"
      asset_ids: "{{asset_ids}}"
      locale: en-US
```

### 6.3 P0 字段类型

| 类型 | Web 控件 | 支持约束 |
| --- | --- | --- |
| `string` | 单行文本框 | `min_length`、`max_length`、可选 `pattern` |
| `integer` | 整数输入框 | `minimum`、`maximum` |
| `number` | 数值输入框 | `minimum`、`maximum` |
| `boolean` | 开关或单选 | 固定为 `true/false` |
| `enum` | 单选下拉框 | 必填 `options`，提交值必须精确命中 |

P0 不支持对象、数组、任意 JSON 编辑、日期控件、空值删除或新增 YAML 中不存在的字段。复杂对象应在 YAML 中拆成经过评审的静态叶子字段；确有普遍需求后再进入 P1。

### 6.4 默认值与空值规则

- 默认值直接读取目标 `request.params` 或 `step_data.<step>.params` 的当前 YAML 值，不在 `runtime_inputs` 中重复保存；
- 未提交某字段时使用 YAML 默认值；
- 用户将字段恢复为默认值后，该字段不写入 `runtime_overrides`；
- P0 不提供“删除字段”语义；
- `required: true` 表示最终值不能是空字符串或 `null`，不表示用户每次都必须手工输入；
- 元数据声明的类型必须与 YAML 默认值兼容，否则项目静态校验失败。

### 6.5 目标路径限制

- `case_request` 的路径相对于所选 Case 的 `request.params`；
- `flow_step_request` 的路径相对于指定步骤的 `params`；
- P0 路径只允许 `$` 开头的对象字段链，例如 `$.locale`、`$.preferences.voice`；
- 不支持通配符、递归查找、过滤表达式、脚本表达式或数组索引；
- 目标字段必须已经存在，且必须是静态叶子值；
- `step_id` 必须存在于当前 Flow，且对应 Scenario 中必须存在该步骤数据；
- 一个目标只能被一个逻辑字段绑定，避免覆盖顺序不确定。

### 6.6 保留字段拒绝规则

即使项目 YAML 错误声明，以下字段或语义也必须由框架级拒绝规则兜底：

- `auth_token`、`refresh_token`、`token`、`secret`、`password`、`credential`；
- `gateway`、`base_url`、`url`、`service_name`、`method_name`、`headers`、`comm`；
- `project_id`、`target_env`、`scope_id`、`release_id`、`profile`；
- `timeout`、`poll_interval`、`retry`、`concurrency`；
- `client_request_id`、`task_id`、`asset_id`、`asset_ids`、`upload_url`、`required_headers`；
- 文件路径、文件内容、签名请求参数和执行器内部变量。

拒绝规则按字段名、目标上下文和基础值来源共同判断，不能只依赖字符串名称。

---

## 7. Web 产品需求

### 7.1 影响页面

| 页面 | 改动 |
| --- | --- |
| 创建单接口任务 `/tasks/new/single` | 选择 Case 后展示“本次运行参数”卡片 |
| 创建 Flow 任务 `/tasks/new/flow` | 展示文件输入及按步骤分组的普通参数 |
| 任务预检区域 | 展示资产版本、已修改数量、校验状态和只读差异摘要 |
| 任务详情 `/tasks/<task_id>` | 展示该任务的覆盖值、最终值和资产版本 |
| 用例库 `/catalog` | 只读展示 Case/Flow 是否支持本次参数修改及可修改字段数量 |
| 任务记录 `/tasks` | 可选显示“参数修改”标识，不新增复杂筛选项 |

概览、项目切换和平台配置控制面无需新增编辑能力。

### 7.2 创建任务页布局

任务选择区下方新增“本次运行参数”卡片：

- 标题：`本次运行参数`；
- 辅助文案：`仅影响本次新任务，不修改用例文件和平台配置`；
- 每个字段展示标签、说明、当前 YAML 默认值和对应控件；
- Flow 字段按业务步骤分组，并展示步骤名称和 API ID；
- 已修改字段显示“已修改”文本标识，不能只依赖颜色；
- 支持“恢复此项默认值”和“全部恢复默认值”；
- 未声明字段时展示：`该用例未开放临时参数，将按 YAML 默认值执行`；
- 参数定义加载失败时禁止提交，并显示可操作的刷新提示；
- 不提供保存、发布、写回 YAML 或复制为新 Case/Flow 的按钮。

### 7.3 文件输入与普通参数

现有 Flow 图片上传继续使用 `inputs.media_files` 和 multipart 文件字段。普通业务参数使用 `runtime_overrides`。页面可以将两者放在同一“运行输入”区域中，但提交协议和服务端校验必须分开，禁止把文件路径或文件元数据放入 `runtime_overrides`。

### 7.4 预检交互

当用户修改字段、恢复默认值、重新选择 Case/Flow 或变更图片后，页面调用统一 `/api/preflight`：

- 通过：显示当前项目、test/prod 固定环境、Scope、Release、Profile、资产版本和本次修改数量；
- 参数错误：定位到具体字段，提交按钮禁用；
- 资产版本变化：清空已失效定义，重新加载并提示用户确认；
- Scope/Release/Profile 错误：沿用现有平台配置错误和深链，不把它误显示为参数错误；
- 切换项目、API、Case 或 Flow 时，清空不属于新资产的覆盖值。

### 7.5 差异展示

预检和任务详情以只读表格展示：

| 字段 | 步骤 | YAML 基础值 | 本次覆盖值 | 最终值 |
| --- | --- | --- | --- | --- |
| Analysis 结果语言 | `create_analysis` | `en-US` | `zh-CN` | `zh-CN` |

没有修改的字段默认不进入预检差异表；任务详情可展开查看全部已声明字段。

### 7.6 可访问性和错误恢复

- 所有字段必须有可关联的 `<label>`、说明和字段级错误；
- 错误信息使用文本表达，不能只改变边框颜色；
- 键盘可完成选择、编辑、恢复、预检和提交；
- 焦点在校验失败后移动到首个错误摘要，并可跳转到具体字段；
- 网络重试不得丢失用户尚未提交的输入；
- 页面刷新可以保留资产选择，但未提交的临时参数不写入浏览器长期存储。

---

## 8. 业务 API 契约

### 8.1 Catalog 返回

`GET /api/catalog` 在已有 API/Case/Flow 数据上增量返回服务端解析后的只读字段定义和资产版本。客户端不得直接读取或解析 YAML。

```json
{
  "id": "multi_image_analysis",
  "name": "Dating 多图 Analysis 保留结果链路",
  "asset_revision": "sha256:...",
  "runtime_inputs": [
    {
      "key": "analysis_locale",
      "label": "Analysis 结果语言",
      "description": "修改 CreateAnalysisTask 的 locale",
      "type": "enum",
      "options": ["en-US", "zh-CN"],
      "required": true,
      "default_value": "en-US",
      "group": {
        "step_id": "create_analysis",
        "step_name": "CreateAnalysisTask"
      }
    }
  ]
}
```

响应不得向客户端返回内部目标路径或允许客户端回传目标路径。

### 8.2 Preflight 请求

在现有请求上增加两个可选字段：

```json
{
  "project_id": "dating",
  "run_type": "flow",
  "flow_id": "multi_image_analysis",
  "tag": "interactive",
  "asset_revision": "sha256:...",
  "runtime_overrides": {
    "analysis_locale": "zh-CN"
  },
  "inputs": {
    "media_files": [
      {"name": "01.png", "size_bytes": 123456, "content_type": "image/png"}
    ]
  }
}
```

规则：

- `runtime_overrides` 缺省或 `{}` 表示不修改；
- 存在覆盖值时必须携带最近一次 Catalog/Preflight 返回的 `asset_revision`；
- `run_type=single` 必须精确选择 `api_id + case_id`；
- `run_type=flow` 必须精确选择 `flow_id`；
- P0 的 `run_type=all` 和仅按 tag 批量执行不接受 `runtime_overrides`；
- 客户端提交目标路径、步骤映射或禁止的环境/配置覆盖字段时直接拒绝。

### 8.3 创建任务请求

单接口示例：

```json
{
  "project_id": "dating",
  "run_type": "single",
  "api_id": "UpdateUserPreferences",
  "case_id": "update_user_preferences_success",
  "tag": "preferences",
  "asset_revision": "sha256:...",
  "runtime_overrides": {
    "dating_goal": "casual_dating",
    "your_voice": "playful"
  }
}
```

Flow multipart 请求继续只包含：

- `task_payload`：JSON 字符串，其中包含 `runtime_overrides` 和 `asset_revision`；
- `media_files`：一个或多个实际文件。

不得新增任意表单字段或把普通参数拆成不受控的 multipart 字段。

### 8.4 请求大小限制

- 单个任务最多 32 个覆盖字段；
- `runtime_overrides` 规范化 JSON 总大小不得超过 32 KiB；
- `string` 单字段最大 4096 个 Unicode 字符，资产声明可设置更小限制；
- 字段名最长 128 字符，只允许字母、数字、下划线和短横线；
- 超限必须在写入任务记录和启动子进程前失败。

### 8.5 错误码

| 错误码 | HTTP | 含义 |
| --- | --- | --- |
| `RUNTIME_OVERRIDE_NOT_SUPPORTED` | 400 | 当前执行类型或资产不支持临时参数 |
| `RUNTIME_OVERRIDE_UNKNOWN_KEY` | 400 | 提交了未声明的逻辑字段 |
| `RUNTIME_OVERRIDE_TYPE_INVALID` | 400 | 字段类型不正确 |
| `RUNTIME_OVERRIDE_CONSTRAINT_FAILED` | 400 | 长度、范围、正则或枚举校验失败 |
| `RUNTIME_OVERRIDE_TARGET_INVALID` | 400 | 资产声明目标不存在、重复、动态或被禁止 |
| `RUNTIME_OVERRIDE_PAYLOAD_TOO_LARGE` | 400 | 字段数或请求大小超限 |
| `RUNTIME_OVERRIDE_SCHEMA_CHANGED` | 409 | 客户端资产版本与服务端当前版本不一致 |

所有错误响应沿用现有统一错误结构，并返回字段级错误列表。错误内容不能包含平台 Secret/Credential 值。

---

## 9. 服务端合并与执行规则

### 9.1 处理顺序

```text
选择项目与资产
    ↓
服务端加载当前 Case，或 Flow + Scenario
    ↓
校验项目隔离、资产版本和 runtime_inputs 声明
    ↓
校验客户端逻辑字段和值
    ↓
深拷贝基础资产并按服务端声明应用覆盖值
    ↓
重新执行 Case/Flow/Scenario 完整静态校验
    ↓
固化任务记录和不可变执行资产快照
    ↓
通过任务专属 0600 临时文件交给 pytest
    ↓
执行期间只读快照，不重新读取可覆盖参数的当前 YAML
```

### 9.2 合并规则

- 先完整加载并校验基础资产，再在深拷贝上应用覆盖；
- 每个逻辑字段只能写入声明中的唯一目标；
- 不允许创建 YAML 中不存在的对象路径；
- 应用后重新运行现有 Case/Flow/Scenario 校验，不能绕过类型、步骤引用和模板检查；
- 同一任务不得在执行过程中再次修改覆盖值；
- 执行器不接受来自进程环境变量的覆盖值；
- 参数覆盖不能改变当前 Runtime Scope、Release 或 Credential 快照。

### 9.3 任务记录

保持现有任务记录 `schema_version=2`，以向后兼容的可选字段增量保存：

```json
{
  "input": {
    "project_id": "dating",
    "run_type": "flow",
    "flow_id": "multi_image_analysis",
    "runtime_overrides": {
      "analysis_locale": "zh-CN"
    }
  },
  "asset_snapshot": {
    "asset_type": "flow",
    "asset_id": "multi_image_analysis",
    "asset_revision": "sha256:...",
    "runtime_input_schema_revision": "sha256:...",
    "applied_overrides": [
      {
        "key": "analysis_locale",
        "step_id": "create_analysis",
        "base_value": "en-US",
        "override_value": "zh-CN",
        "resolved_value": "zh-CN"
      }
    ],
    "resolved_execution_asset": {}
  }
}
```

规则：

- `asset_snapshot` 不保存 Runtime Scope Secret、Token 或 Credential 明文；这些继续由现有平台运行快照机制管理；
- 覆盖值属于请求业务数据，按当前“执行日志不脱敏”规则原样出现在任务详情、任务 JSON 和执行日志中；
- 页面必须提醒用户不要将密码、Token 或其他凭证作为业务参数输入；框架同时通过保留字段规则拒绝此类值的配置入口；
- 历史 V1/V2 任务缺少 `asset_snapshot` 时按“未使用临时参数”展示；
- 任务终态后不可修改该快照。

### 9.4 执行输入文件

- TaskManager 为子进程生成任务专属 JSON 文件，权限必须为 `0600`；
- 文件只包含执行所需资产快照和普通运行输入，不包含平台配置之外的第二套环境配置；
- 子进程通过内部参数读取该文件，公共 Web/CLI 不开放任意路径参数；
- 任务结束后删除临时传输文件；用于历史展示的受控快照保留在任务记录中；
- 命令行不得直接拼接用户值，避免转义错误和进程列表泄漏。

### 9.5 日志要求

- 日志明确记录任务 ID、项目、资产 ID、资产版本以及哪些逻辑字段被覆盖；
- 按当前项目约定，请求业务参数和响应内容不脱敏；
- 不额外打印 YAML 内部目标路径或整份未使用资产；
- 上传二进制内容仍不得写入文本日志；
- 日志目录和任务目录继续沿用现有按项目、环境和日期隔离规则，本需求不调整日志目录结构。

---

## 10. 重试与并发变更

### 10.1 按原运行参数重试

- 重试始终创建新的任务 ID，并记录 `retry_of`；
- 复制原任务的 `runtime_overrides`，不修改原任务；
- 按现有规则重新解析当前 Runtime Scope、Release 和 Credential；
- 重新加载当前 YAML 资产，并校验其是否仍接受这些逻辑字段和值；
- 校验通过后生成新资产快照，因此新任务的资产版本可以与旧任务不同；
- 校验不通过时返回 `RUNTIME_OVERRIDE_SCHEMA_CHANGED`，引导用户进入创建页重新确认；
- 需要上传文件的 Flow 若原文件不可用，必须要求重新选择文件，不能仅凭历史路径静默重试。

### 10.2 修改参数后重试

任务详情提供“修改参数后重试”，进入对应创建页并预填原覆盖值。用户确认后按普通新任务提交；页面不得原地编辑历史任务。

### 10.3 资产并发修改

如果 Catalog/Preflight 后 YAML 被修改，任务提交时 `asset_revision` 不一致：

1. 不创建任务；
2. 返回 409 和当前资产版本；
3. 页面重新加载字段定义；
4. 仅保留仍存在且类型兼容的用户输入，并要求用户再次确认；
5. 不自动将旧值应用到新定义后直接执行。

---

## 11. 多项目与配置边界

### 11.1 项目隔离

- Catalog、Preflight 和 Task API 都必须先解析当前授权 Scope 与本地有效项目包的交集；
- `project_id` 与 Case/Flow 必须来自同一个项目注册表上下文；
- 服务端不能按资产 ID 在所有项目中全局查找；
- Truthy 和 Dating 可存在同名逻辑字段，但其声明、默认值和目标独立；
- 任意跨项目目标引用、Scenario 引用或路径穿越在网络请求前失败。

### 11.2 平台配置不受影响

本需求不新增或修改：

- `tool_project_scopes`；
- ConfigDefinition、ConfigRelease 或 ConfigActivation；
- Secret、Credential、UserCredential；
- Runtime Context、配置物化、配置确认或会话回写接口；
- dev/test、prod/prod 固定映射；
- 平台配置控制面页面。

运行时业务参数不能以“配置草稿”形式保存到平台，也不能复用平台配置字段来实现。

---

## 12. 兼容与迁移

### 12.1 资产兼容

- 现有 YAML 不要求一次性迁移；
- 不含 `runtime_inputs` 的 Case 与 Flow 自动开放安全静态请求参数；无安全字段的资产继续按原默认值执行；
- 可按实际调试需求为 Case 或 Flow 增加可选标签、枚举或约束；
- 项目校验命令增加声明检查，但不因缺少声明而失败；
- 根目录和其他项目资产不得因此重新引入兼容扫描。

### 12.2 API 兼容

- 老客户端不提交 `asset_revision` 和 `runtime_overrides` 时行为不变；
- 只有提交非空 `runtime_overrides` 时才强制要求 `asset_revision`；
- 已有文件上传 multipart 字段保持不变；
- 现有禁止环境与配置覆盖字段列表继续生效，并优先于本需求新增字段。

### 12.3 任务兼容

- 保持任务记录 V2，新增字段均为可选；
- 历史任务详情显示“该任务未记录本次运行参数”；
- 现有列表、取消、恢复、单槽执行、JUnit 和 Allure 逻辑不得回归；
- 普通重试没有覆盖值时继续使用当前行为。

---

## 13. 范围

### 13.1 P0 必须包含

- Case 和 Flow/Scenario 的 `runtime_inputs` YAML 契约；
- `string`、`integer`、`number`、`boolean`、`enum` 五种类型；
- 项目静态校验和服务端运行时校验；
- Catalog 返回字段定义、默认值和资产版本；
- 单接口与 Flow 创建页的参数控件、恢复默认值和字段错误；
- Preflight 的参数与资产版本校验；
- Task API 的 `runtime_overrides` 与 `asset_revision`；
- 服务端安全合并和不可变执行资产快照；
- pytest/Case/Flow 执行读取任务快照；
- 任务详情差异展示；
- 按原参数重试及修改参数后重试；
- 文件上传 Flow 与普通参数并存；
- 多项目隔离、兼容和回归测试；
- 至少为一个 Dating 单接口 Case、`multi_image_analysis` 和 `multi_image_reply` 各开放一个真实静态业务字段作为验收样例。

### 13.2 P1 候选能力

- 对象或数组 JSON 编辑器及 JSON Schema 校验；
- 日期、日期时间、多选枚举和可空字段；
- 从任务详情将参数复制为本地 YAML 变更建议；
- 参数模板或个人最近值；
- 批量执行中按 Case 分别提供覆盖值；
- 将成熟的本次参数提升为 Web 资产草稿。

P1 不自动进入开发范围，必须重新评审数据治理、权限和唯一真源边界。

### 13.3 明确不包含

- 在 Web 新增、删除或永久修改 Case、Flow、Scenario；
- 将 Case/Flow 存入数据库；
- YAML 在线编辑器；
- 修改断言、提取、标签、步骤或 Flow 拓扑；
- 跨项目 Flow 或批量执行参数覆盖；
- 保存个人参数模板或浏览器长期记忆；
- 修改平台配置、环境、Secret/Credential；
- 新增公共 CLI 的任意 YAML 路径或 JSON 覆盖入口；
- 调整日志脱敏策略、日志目录或报告目录；
- 引入新的前端框架、数据库、消息队列或任务队列。

---

## 14. 框架影响范围

### 14.1 需要修改的工具模块

| 模块 | 预期改动 |
| --- | --- |
| `utils/custom/case_loader.py` | 校验 Case `runtime_inputs`、目标、类型和约束 |
| `utils/custom/flow_loader.py` | 联合校验 Flow、Scenario、步骤和 `runtime_inputs` |
| `utils/custom/flow_runner.py` | 使用已解析的任务快照，不允许执行中覆盖或回读基础值 |
| `web/catalog.py` | 返回只读字段定义、默认值、分组和资产版本 |
| `web/app.py` | 扩展 Preflight、Task、Retry 请求及错误响应 |
| `web/task_manager.py` | 合并资产、固化快照、生成 0600 执行输入文件 |
| `web/task_store.py` | 在任务 V2 中增量保存覆盖值和资产快照 |
| `web/templates/task_form.html` | 新增本次运行参数区域 |
| `web/templates/task_detail.html` | 新增只读差异、资产版本和重试入口 |
| `web/templates/catalog.html` | 展示可修改参数数量和只读信息 |
| `web/static/app.js` | 动态控件、恢复默认、预检、提交和版本冲突恢复 |
| `web/static/app.css` | 复用现有视觉 Token 增加字段状态与差异样式 |
| `test_cases/conftest.py` 及执行入口 | 读取内部任务输入快照并注入选中 Case/Flow |

详细设计阶段应以实际调用链为准收敛文件清单，不得为本需求创建第二套 Loader 或 Runner。

### 14.2 不需要修改的范围

- `test-platform/backend` 数据库模型和迁移；
- `test-platform/frontend` 配置控制面；
- Jenkins 项目和环境参数；
- Project Manifest 配置契约；
- Gateway 客户端协议；
- Runtime Scope/Release/Secret/Credential 物化链路；
- 日志和报告目录结构。

### 14.3 改动性质结论

该需求不是纯前端表单改动。若只在浏览器改值而没有服务端白名单、任务快照和执行器消费，会造成参数可伪造、任务不可复现或执行仍读取 YAML 默认值。

因此必须完成以下端到端最小闭环：

```text
YAML 显式声明 → Catalog → Web 表单 → Preflight → Task 快照 → pytest/Runner
```

这属于**有限、通用、向后兼容的框架能力新增**，不改变多项目架构和平台配置唯一真源。

---

## 15. 测试与验收

### 15.1 单元测试

- Case/Scenario 合法声明可加载；
- 未知类型、缺失枚举、默认值类型不匹配时失败；
- 目标不存在、重复、动态或命中保留字段时失败；
- 字符串、整数、数值、布尔和枚举校验覆盖边界值；
- 资产版本对规范化内容稳定，对有效内容变更敏感；
- 合并使用深拷贝，不修改 Loader 缓存或基础对象；
- 项目 A 的声明不能应用到项目 B。

### 15.2 API 测试

- 无覆盖值的旧请求保持成功；
- 合法覆盖值通过 Catalog、Preflight 和 Task；
- 未知逻辑键、类型错误、越界、超限和目标伪造被拒绝；
- 资产版本不一致返回 409；
- `run_type=all` 携带覆盖值被拒绝；
- multipart 文件和 `task_payload.runtime_overrides` 同时工作；
- 环境、Gateway、Release、Profile 和 Secret 覆盖仍被拒绝。

### 15.3 执行测试

- 单接口最终请求使用覆盖值；
- Flow 只有指定步骤使用覆盖值；
- 动态 `client_request_id`、`asset_ids` 和 `task_id` 仍由运行时产生；
- 一个任务运行中修改 YAML 不影响该任务快照；
- 下一个普通任务重新使用 YAML 默认值；
- YAML 内容和文件修改时间在执行前后完全一致；
- JUnit、Allure、任务详情和日志可关联同一任务与资产版本。

### 15.4 Web 验收

- 单接口和 Flow 页面能正确显示、编辑、恢复和校验字段；
- 未开放参数的资产显示只读空状态；
- 切换项目或资产会清空不兼容值；
- 字段错误可通过键盘定位和恢复；
- 预检与提交使用同一错误模型；
- 任务详情准确展示基础值、覆盖值和最终值；
- 按原参数重试创建新任务，原任务不变；
- `/api-autotest` Base Path 下访问和刷新正常；
- 1280px 与 1440px 桌面宽度可完整操作。

### 15.5 真实链路验收

真实 Gateway 验收只在 dev/test 执行：

1. Dating 单接口使用一个与 YAML 不同的允许值完成请求；
2. `multi_image_analysis` 选择图片并修改 `locale`，请求链路完成且结果保留；
3. `multi_image_reply` 选择图片并修改一个静态业务字段，动态上传和任务轮询不受影响；
4. 紧接着重新创建同一 Flow 且不修改参数，确认恢复使用 YAML 默认值；
5. 检查任务 JSON、日志和报告中的项目、资产版本及最终请求值一致。

本期不向 prod 发业务测试请求。prod 只验证页面无环境切换入口、固定映射和非法覆盖请求拒绝。

### 15.6 Definition of Done

- P0 功能全部完成；
- 新增测试先失败后通过，现有完整测试无未解释回归；
- 普通任务、文件上传任务、重试、取消和历史任务展示均正常；
- 没有新增平台数据库迁移或第二套配置来源；
- 没有新增 YAML 写入 API；
- 没有把用户值拼接进 shell 命令；
- 项目静态校验、后端、前端构建和目标页面浏览器验收通过；
- PRD、详细设计、实现和页面文案保持一致。

---

## 16. 实施建议与发布顺序

详细开发设计应按以下顺序拆分：

1. 先补资产声明和合并器的失败测试，锁定白名单、动态值和保留字段边界；
2. 实现 Case/Flow/Scenario 静态校验及资产版本；
3. 扩展 Catalog 和 Preflight；
4. 扩展任务记录、TaskManager 和 pytest/Runner 执行快照；
5. 实现创建页、详情页和重试交互；
6. 为 Dating 验收资产添加最小 `runtime_inputs`；
7. 运行局部测试、完整回归、Base Path 浏览器测试和 dev/test 真实链路；
8. 先对内部测试账号启用，再面向全部授权用户开放。

如果需要功能开关，应使用工具版本级开关控制页面入口，不能将其建成用户可覆盖的运行配置。关闭功能时，旧任务详情仍应能只读展示已经保存的覆盖快照。

---

## 17. 风险与缓解

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| 自动发现误暴露字段 | 用户误改动态依赖或敏感字段 | Case 与 Flow 都只开放已有静态标量叶子，并由 API 步骤范围、动态模板、类型、路径和框架保留语义多重过滤 |
| 前端校验被绕过 | 非法值进入执行器 | Catalog、Preflight、Task、项目校验共享服务端规则 |
| 预检后 YAML 变化 | UI 定义与执行资产不一致 | `asset_revision` 比较，不一致返回 409 并重新确认 |
| 临时值污染正式用例 | 后续任务行为变化 | 禁止 YAML 写回，使用深拷贝和任务快照 |
| Flow 改错步骤 | 多接口链路产生误导结果 | 服务端声明目标，客户端不提交路径或步骤映射 |
| 动态变量被覆盖 | 上传、轮询或幂等链路失效 | 模板值、提取值和框架保留字段禁止声明 |
| 任务不可复现 | 排查时不知道实际值 | 任务 V2 保存资产版本、基础值、覆盖值和最终快照 |
| 业务敏感数据进入原始日志 | 数据可见范围扩大 | 明确原始日志策略、RBAC 沿用现状，并禁止凭证类字段进入功能 |
| 首期类型过多导致复杂 | 开发和交互成本失控 | P0 只支持五种标量类型，对象/数组进入 P1 |

---

## 18. 待后续决策

以下事项不阻塞 P0，本期不预设实现：

1. 是否在 P1 支持对象和数组的结构化编辑；
2. 是否允许将一次成功调试的参数生成 Git 变更建议；
3. 是否建设带审批和发布流程的 Web 资产管理；
4. 如果未来建设数据库草稿，Git/YAML 与数据库之间采用何种发布和回写机制；
5. 是否允许批量任务为不同 Case 分别设置覆盖值。

在这些问题完成单独 PRD 和数据治理评审前，P0 不得扩展为在线 Case/Flow 编辑器。

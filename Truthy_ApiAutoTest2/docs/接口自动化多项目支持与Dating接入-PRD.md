# Gateway 通用接口自动化多项目支持与 Dating 首期接入 PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 产品版本 | V2.0 |
| 文档版本 | V1.3 |
| 日期 | 2026-08-27 |
| 文档状态 | 方案已确认，需求待评审 |
| 适用仓库 | `Truthy_ApiAutoTest2` |
| 关联平台工具 | `api-autotest`（接口自动化） |
| 核心决策 | 采用集中式单仓库，并实行“平台配置唯一真源 + 工具测试资产唯一真源” |
| 实施边界 | 测试开发平台负责运行作用域、配置发布、Secret/Credential、统一身份与入口；`Truthy_ApiAutoTest2` 负责 Project Manifest、API/Case/Flow/Scenario/Fixture、执行引擎及接口自动化 Web 业务能力 |

### 1.1 文档目的

本文档定义 `Truthy_ApiAutoTest2` 从 Truthy 单项目接口自动化框架升级为通用多项目接口自动化工具的产品需求，并明确 Dating 项目的首期接入范围。

本期需求包含接口自动化 Web 界面的开发，不是仅改造 CLI 或执行引擎。页面、页面调用的任务/目录/运行前校验接口、任务状态与报告逻辑均由 `Truthy_ApiAutoTest2` 交付；测试开发平台负责展示 `api-autotest` 入口，并作为运行配置控制面，统一管理项目运行作用域、接口环境、配置 Release、Secret/Credential、身份权限与配置快照下发。平台不复制接口自动化页面、用例资产、执行逻辑或任务状态机，工具也不再提供第二套可编辑的项目运行配置。

两类唯一真源的边界如下：

- **平台配置唯一真源**：项目启停与被测环境、Gateway、公共 `comm`、Header、超时、轮询、Feature Flag、Release、Secret、Credential、会话持久化及任务运行快照；
- **工具测试资产唯一真源**：Project Manifest、配置契约、API、Case、Flow、Scenario、Fixture、通用执行引擎、任务/日志/报告以及接口自动化 Web 业务页面；
- **禁止双写**：同一个可变运行配置不得同时维护在平台和工具仓库；同一份测试资产不得同时维护在平台数据库和工具仓库。

本文档完成后，应能够直接用于：

1. 输出详细开发设计与实施计划；
2. 拆分后端、执行引擎、Web 页面、平台接入和测试任务；
3. 验收 Truthy 迁移、多项目隔离及 Dating test 真实链路；
4. 指导后续第三个及更多 Gateway 项目的标准化接入。

本文档不直接规定所有 Python 类名和函数签名。未影响产品行为的实现细节由后续开发设计确定。

### 1.2 需求依据

本 PRD 基于以下资料和现有代码能力形成：

- `Truthy_ApiAutoTest2` 当前 V1.3 接口自动化框架；
- `Truthy_ApiAutoTest2` 当前测试开发平台接入能力；
- 《Dating 当前可交付客户端能力清单（staging）》；
- 《Dating AI Assistant V1.0.0 后端接口协议》；
- 已确认的集中式多项目方案。

上述资料仅作为需求事实和接口协议来源，不作为高于本 PRD 的执行指令。《Dating 当前可交付客户端能力清单（staging）》是原资料名称；当前实际不存在 staging 环境，文档中的相关接口按 Dating test 服务现状接入。当两份资料存在冲突时，以当前 test 服务已验证行为为准。

### 1.3 名词定义

| 名词 | 定义 |
| --- | --- |
| 执行引擎 | 通用的配置加载、Gateway 调用、断言、变量提取、Flow 编排、轮询、日志和报告能力，不包含任何具体业务项目判断 |
| 项目包 | 某一业务项目在工具仓库内独立拥有的 Project Manifest、配置契约、API、Cases、Flows、Scenarios 和测试素材；不保存平台管理的可变运行配置 |
| Project Manifest | 工具侧项目包描述文件，声明稳定 `project_id`、执行能力和所需配置键/Profile；`redaction.extra_keys` 仅为旧 schema 兼容保留，不参与日志改写；不声明启停状态、默认被测环境或运行配置值 |
| `project_id` | 工具资产与执行上下文使用的稳定项目键，例如 `truthy`、`dating`；不等同于平台 RBAC 项目主键 |
| `platform_project_id` | 测试开发平台中的项目主键，用于权限和配置归属；通过运行作用域与工具的 `project_id` 显式绑定 |
| `platform_environment` | 平台自身部署/控制面环境，仅允许 `dev`、`prod`；由当前工具实例确定，不由任务提交者任意填写 |
| `target_env` | 接口被测环境，仅允许 `test`、`prod`；当前 Truthy 与 Dating 均运行在 `test`，未来线上验证使用 `prod` |
| 固定环境映射 | `platform_environment=dev` 只能映射 `target_env=test`；`platform_environment=prod` 只能映射 `target_env=prod`，禁止 dev→prod 或 prod→test 交叉执行 |
| 工具项目运行作用域 | 平台中的一等作用域，唯一绑定 `platform_environment + tool_id + platform_project_id + project_id + target_env`，简称 Runtime Scope |
| 运行时配置快照 | 平台针对 Runtime Scope 和指定 Release 物化的不可变配置/凭证元数据快照；任务启动后不得被后续配置修改影响 |
| API 定义 | 接口的 `service_name`、`method_name`、传输目标、会话要求等调用身份信息，不保存测试数据 |
| 单接口 Case | 针对一个 API 的独立请求参数、标签、断言和提取规则 |
| Flow | 多接口调用步骤、等待、条件轮询、变量提取和终止规则 |
| Scenario | 与 Flow 对应的各步骤业务请求数据和断言 |
| 平台配置模式 | Web、平台任务或连接平台配置中心的本机 CLI，通过 Runtime Scope 获取已发布快照；不得读取本地 YAML/`.env` 回退 |
| 独立调试模式 | 开发者显式选择 `config_source=local` 的离线调试模式；不属于平台配置管理范围，不得与平台配置混合或在平台 Web 中使用 |

---

## 2. 项目背景

### 2.1 当前能力

`Truthy_ApiAutoTest2` 当前已经具备：

- Python、pytest、requests、PyYAML 驱动的 Gateway 接口执行能力；
- API 定义、单接口 Cases、多接口 Flows 与 Scenarios 分层；
- 运行时变量模板、响应字段提取、固定等待和条件轮询；
- HTTP、Gateway、子请求和业务数据的分层断言；
- 匿名会话创建、Token 刷新和运行时注入；
- Prepare、签名地址上传、Complete 类型的媒体上传流程；
- JUnit、Allure、原始执行日志和任务结果；
- CLI、Jenkins 和测试开发平台触发入口；
- Web 用例目录、任务列表、任务详情、取消和报告查看。

因此，多项目改造不需要重新建设测试框架，重点是增加统一的项目选择、项目资产隔离和项目运行上下文。

### 2.2 当前问题

虽然现有框架具备通用测试能力，但部分实现仍隐含“仓库根目录就是 Truthy 项目”的前提：

1. `config/`、`data/`、测试素材和本地 `.env` 默认只有一套，现有加载器还会合并环境 YAML 与 `.env`，存在平台配置与工具本地配置双真源风险；
2. CLI 没有 `--project` 参数；
3. Web 用例目录、环境列表和 Flow 列表只扫描一个固定项目根目录；
4. 平台配置模型尚未把 `project_id + target_env` 建模为一等作用域，任务模型、日志和报告也缺少完整的 Scope 快照；
5. 会话字段和 Admin 凭证映射包含 Truthy 专属约定；
6. 媒体上传动作对 Truthy 返回字段存在硬编码；
7. 平台环境与接口环境曾被同一个 `env` 字段混用，且缺少 `dev→test`、`prod→prod` 的强制约束；
8. 新业务项目若直接复制仓库，会产生多套引擎、重复修复和版本不一致问题。

### 2.3 Dating 接入机会

Dating 与 Truthy 使用相同的 Gateway 调用架构：

- 固定 Gateway HTTP 入口；
- 通过 `service_name + method_name` 路由业务接口；
- access token 放入 Gateway 请求信封的 `comm.auth_token`；
- 业务链路包含身份会话、媒体上传、异步任务创建、状态轮询、结果查询和数据删除；
- 可以直接复用现有单接口和多接口 Flow 能力。

差异主要体现在 Gateway 地址、公共 `comm`、接口集合、字段名称、凭证需求、业务断言和测试素材，不构成另建框架的理由。

---

## 3. 产品目标与成功标准

### 3.1 产品目标

1. 将现有框架升级为一个执行引擎支持多个业务项目的通用接口自动化工具；
2. 在同一仓库集中管理 Truthy、Dating 以及后续项目的独立项目包；
3. 支持按项目执行单接口测试、多接口 Flow、全量测试和标签筛选；
4. 确保项目之间的配置、会话、Secret、素材、任务、日志和报告相互隔离；
5. 保持 Truthy 现有 CLI、Jenkins 和平台执行行为兼容；
6. 完成 Dating 当前 test 可交付能力的首批自动化接入；
7. 使标准 Gateway 新项目无需修改执行引擎即可完成接入；
8. 以 `Truthy_ApiAutoTest2` 自带 Web 工具页承载完整操作体验，并通过测试开发平台入口访问；
9. 将平台确立为可变运行配置唯一真源，将 `Truthy_ApiAutoTest2` 确立为测试资产唯一真源，彻底消除双配置和静默回退。

### 3.2 成功标准

| 编号 | 成功标准 |
| --- | --- |
| S-01 | 仓库内至少存在 `truthy` 和 `dating` 两个可独立加载的项目包 |
| S-02 | CLI 通过 `--project` 选择项目；平台配置模式中的 `--target-env` 仅用于校验当前固定映射，不能切换环境，旧 `--env` 仅作兼容别名 |
| S-03 | Web 和平台任务提交支持项目选择；环境由当前平台实例固定映射，任务全过程保留 `platform_project_id`、`project_id`、`platform_environment`、`target_env`、Runtime Scope 和配置 Release 快照 |
| S-04 | 单接口 Case 和多接口 Flow 只能读取当前项目包内的 API、Scenario 和素材，并只能读取平台为当前 Runtime Scope 物化的运行配置 |
| S-05 | Dating 任务不会因为未配置 Truthy Admin 凭证而被拒绝 |
| S-06 | 不需要 Admin 接口的 Truthy 用例也不会被全局 Admin 凭证预检误拦截 |
| S-07 | Truthy 现有测试行为、断言、调用顺序和 Jenkins/平台执行结果无功能回归 |
| S-08 | Dating 首期单接口和核心 Analysis Flow 可以在 test 真实运行并生成独立报告 |
| S-09 | 日志、任务、JUnit 和 Allure 产物可按项目区分，且不存在跨项目覆盖 |
| S-10 | 完成一次通用 Runtime Scope 能力建设后，新增标准 Gateway 项目只需增加项目包和平台配置数据，不修改公共引擎或平台业务代码即可被发现和执行 |
| S-11 | 无效项目、无效被测环境、缺失/无效配置 Release、配置契约不满足或越界文件路径均在发起网络请求前失败 |
| S-12 | 文件日志、终端、Web 日志、失败摘要、JUnit 和 Allure 保留请求/响应、Header、Token、签名 URL、异常及业务结果原文；上传二进制内容仍不写入任何文本产物 |
| S-13 | Web 页面与任务业务接口均由 `Truthy_ApiAutoTest2` 提供；平台提供通用配置控制面但不形成第二套接口自动化页面、用例库或任务实现 |
| S-14 | 平台配置模式不读取项目环境 YAML、本地 Secret 文件或根 `.env`；平台快照不可用时必须 fail-closed |
| S-15 | 工具不提供独立“项目配置”“配置状态”或“配置异常”页面；仅在概览和任务提交位置内联展示必要的 Scope/Release/Profile 校验结果，配置维护统一进入平台配置中心 |
| S-16 | dev 平台只能执行 test 接口，prod 平台只能执行 prod 接口；任何跨环境请求均在发起网络请求前被拒绝 |

### 3.3 产品指标

本期不以用例数量作为唯一完成指标，使用以下可验证指标：

- 项目识别正确率：所有任务均能唯一归属一个 `project_id`；
- 项目资产隔离：自动化隔离测试全部通过，不允许跨项目读取；
- Truthy 回归：改造前已有自动化测试及核心真实冒烟无新增失败；
- Dating 可交付链路：在外部 test、额度和 COS 可用的前提下，核心流程可完成；
- 新项目接入：通用 Runtime Scope 上线后，标准 Gateway 项目仅新增工具项目包和平台作用域/Release 数据，不新增项目专属执行分支或平台代码。

---

## 4. 用户与核心场景

### 4.1 目标用户

- 测试工程师：在对应平台实例中选择项目，执行该平台固定接口环境的单接口或多接口回归；
- 测试开发工程师：维护项目包、公共引擎和项目级自定义断言；
- 研发人员：查看指定项目的失败原因、任务结果和 Allure 报告；
- 平台管理员：为不同项目和环境维护运行时配置与 Secret；
- 新项目接入人员：按照统一规范增加项目包，不复制测试框架。

### 4.2 核心场景

#### 场景一：执行 Dating 单接口测试

1. 用户在 CLI 或 Web 选择 `dating`；
2. 系统根据当前 dev 平台自动解析 `target_env=test`，用户选择单接口执行方式；
3. 按 API、Case、模块或标签筛选；
4. 系统仅加载 Dating 项目包；
5. 系统按所选用例实际需要检查会话或凭证；
6. 执行完成后，在 Dating 任务和报告范围内查看结果。

#### 场景二：执行 Dating Chat Analysis 多接口 Flow

1. 创建或复用 Dating 匿名会话；
2. 获取实时媒体上传限制；
3. 为一张或多张测试图片申请上传地址；
4. 直接向 COS 执行签名 PUT；
5. 确认媒体上传完成；
6. 创建 Analysis 任务；
7. 轮询任务直到成功、拒绝、失败或超时；
8. 成功时查询结果，拒绝或失败时按终止规则结束；
9. 清理任务私密数据；
10. 输出每一步可定位的原始测试结果；仅媒体二进制内容不进入文本日志和报告。

#### 场景三：继续执行现有 Truthy 回归

1. 原有调用方未传 `project_id`；
2. 兼容层将本次执行解析为 `truthy`；
3. 原有环境、标签、Flow 和报告流程保持有效；
4. 任务详情明确显示该任务实际归属 Truthy。

#### 场景四：接入后续新项目

1. 接入人员复制空白项目包结构；
2. 在 Project Manifest 声明唯一 `project_id`、配置契约、通用能力和凭证 Profile；
3. 添加 API、Cases、Flows、Scenarios 和 Fixture；
4. 通过项目包静态校验；
5. 在平台创建 `platform_project_id + project_id + target_env` 绑定，发布运行配置并配置 Secret/Credential；
6. 项目在“平台已启用 Scope”与“工具有效项目包”的交集中出现；
7. 无需复制或修改 Gateway、Flow、报告等执行引擎代码，也无需增加项目专属平台代码。

#### 场景五：项目配置或凭证不完整

1. 用户提交任务；
2. 系统先解析 Runtime Scope、配置 Release 和本次选中用例的能力需求；
3. 系统只检查当前执行实际需要的凭证；
4. 缺失时返回项目、被测环境、Scope、配置/Profile 缺项和平台配置中心修复入口，不启动 pytest 子进程；
5. 错误信息不得包含 Secret 值。

---

## 5. 范围

### 5.1 P0：本期必须包含

#### 通用多项目能力

- 项目注册、发现、启停和配置校验；
- `platform_project_id`、`project_id`、`target_env`、Runtime Scope 与配置 Release 在 CLI、Web、平台 API、任务、日志和报告中的端到端传递；
- 平台通用 Runtime Scope 模型、配置 Release、Secret/Credential 绑定、快照选择与物化能力；
- 平台配置唯一真源与工具测试资产唯一真源的边界及 fail-closed 执行模式；
- 平台侧项目级被测环境、Gateway、`comm`、会话、Secret/Credential 隔离；
- 工具侧 API、Cases、Flows、Scenarios 和素材隔离；
- 按需凭证预检，不再全局强制 Truthy Admin 凭证；
- 单接口与多接口 Flow 在项目上下文中执行；
- 通用签名二进制上传动作；
- 项目级用例目录、当前固定接口环境、Flow 列表、任务和报告；
- 在 `Truthy_ApiAutoTest2` 内完成概览、项目切换、执行任务、用例库、任务记录和任务详情页面，并提供内联运行前校验；
- Truthy 项目包迁移与兼容入口；
- Dating 首期项目包；
- CLI、Web、平台任务接口和 Jenkins 参数的项目选择；
- 测试开发平台完成一次通用的 Runtime Scope 数据模型/API、配置 Release/Secret/Credential 作用域化，以及 `api-autotest` 入口、路由代理和身份上下文适配；
- 项目包、Runtime Scope/Release、隔离、兼容和 Dating 核心链路测试。

#### Dating 首期接口

| 领域 | `service_name` | `method_name` | 鉴权 |
| --- | --- | --- | --- |
| Identity | `tool.identity.IdentityService` | `CreateAnonymousSession` | 无 access token |
| Identity | `tool.identity.IdentityService` | `RefreshSession` | refresh token |
| Identity | `tool.identity.IdentityService` | `GetMe` | access token |
| Media | `tool.dating.DatingMediaService` | `GetMediaUploadConfig` | access token |
| Media | `tool.dating.DatingMediaService` | `PrepareMediaUpload` | access token |
| Media | `tool.dating.DatingMediaService` | `CompleteMediaUpload` | access token |
| Analysis | `tool.dating.DatingAssistantService` | `CreateAnalysisTask` | access token |
| Analysis | `tool.dating.DatingAssistantService` | `GetAnalysisTask` | access token |
| Analysis | `tool.dating.DatingAssistantService` | `GetAnalysisResult` | access token |
| Analysis | `tool.dating.DatingAssistantService` | `DeleteTaskData` | access token |
| Subscription | `tool.subscription.SubscriptionService` | `GetQuotaStatus` | access token |

### 5.2 P1：本期应包含

- Web 任务列表按项目筛选；
- 项目级最近一次执行结果和最新报告入口；
- 项目包校验命令及可读错误汇总；
- Dating 1 张图片和 9 张图片 Analysis 场景；
- Dating `rejected`、`failed`、超时和删除后不可访问场景；
- Dating `client_request_id` 幂等重试场景；
- 需要预置额度状态的场景支持独立标签和显式前置条件；
- 旧配置或旧任务请求触发兼容路径时记录弃用提示。

### 5.3 P2：后续可扩展

- 项目级定时任务；
- 项目级并发配额和队列；
- 在线创建或编辑 API、Case、Flow、Scenario；
- 项目包模板生成器；
- 项目级测试覆盖率和趋势分析；
- 将公共执行引擎发布为独立软件包并允许项目包迁移到其他仓库。

### 5.4 本期明确不包含

- 为 Dating 复制一套执行框架或部署一套独立 Web 壳；
- 在测试开发平台仓库内复制或长期维护接口自动化页面、项目目录、API/Case/Flow/Scenario、任务状态机、执行逻辑或报告业务逻辑；
- 在 `Truthy_ApiAutoTest2` 中建立与平台平行的项目运行配置中心，或在线编辑平台拥有的 Gateway、`comm`、超时、轮询、Secret/Credential；
- 将 API、Case、Flow、Scenario 或 Fixture 存入平台配置表；
- 除通用 Runtime Scope、配置/Secret/Credential 作用域化、入口、路由和统一身份外，对测试开发平台无关模块进行重构；
- 将 `api-autotest` 与 `api-test-agent` 合并；
- 修改稳定工具 ID `api-autotest`；
- 重命名 `Truthy_ApiAutoTest2` 仓库；
- 支持非 Gateway 协议的任意 HTTP、GraphQL、WebSocket 或 RPC 框架；
- 跨项目 Flow 或跨项目变量共享；
- 在一个 Gateway 请求信封中自动批量合并整个 Flow；
- Dating Goal、Your Voice、Help Me Reply、Practice Mode、Person/历史记录、完整购买链路和 Evaluation API；
- 将 `ReportAcquisitionChannel` 纳入首期强制回归；
- 将外部 test/prod、COS、LLM Worker 或订阅服务的可用性问题包装为框架成功；
- 为多项目改造引入数据库、消息队列或动态插件系统；
- 长期维护两套项目目录格式。

---

## 6. 产品与架构原则

### 6.1 一个引擎，多个项目包

执行引擎负责通用机制，项目包负责业务事实。执行引擎不得依赖 Truthy、Dating 或其他具体项目。

禁止在公共执行路径出现以下类型的项目判断：

```python
if project_id == "dating":
    ...
elif project_id == "truthy":
    ...
```

项目差异必须优先通过 Project Manifest 的配置契约、平台 Runtime Scope 配置、API 定义、通用动作参数、Case/Scenario 或项目级声明式校验表达。

### 6.2 项目包自包含

一个项目包必须包含完成测试收集所需的全部非敏感测试资产和配置契约。项目包不得引用另一个项目包的文件，也不得保存 Gateway、公共 `comm`、超时、轮询或被测环境等平台运行配置值。

### 6.3 项目选择显式化

- 新入口必须显式使用 `project_id`；
- 旧 CLI、Jenkins 和平台任务仅在兼容期允许缺省为 `truthy`；
- 系统必须在任务记录中保存最终解析后的 `project_id`，不能只保存用户原始输入。

### 6.4 按需能力与按需凭证

凭证需求由本次实际选择的 API 或 Flow 决定，而不是由工具内的全局固定列表决定。

例如：

- Dating Analysis 需要匿名会话，不需要 Truthy Admin 凭证；
- Truthy 普通用户接口不应因为 Admin 凭证缺失而失败；
- 只有选中的接口或 Flow 声明了 Admin 能力，才检查 Admin Secret。

### 6.5 一次迁移，不保留双实现

Truthy 数据迁移到标准项目包后，公共加载器只维护标准项目包格式。兼容层只负责补充缺省 `project_id=truthy`，不长期保留“根目录数据”和“项目包数据”两套加载逻辑。

### 6.6 外部依赖如实呈现

外部服务不可用、额度不足、签名过期和异步任务超时必须被准确归类，不能被框架吞掉或错误标记为断言失败。

### 6.7 Web 工具与测试开发平台职责边界

`Truthy_ApiAutoTest2` 是接口自动化测试资产、执行与 Web 业务能力所有者；测试开发平台是统一入口、权限和运行配置控制面。职责按下表划分：

| 能力 | `Truthy_ApiAutoTest2` | 测试开发平台 |
| --- | --- | --- |
| Web 界面 | 实现概览、项目切换、任务创建、用例库、任务记录和任务详情；配置问题仅在相关操作位置内联提示 | 提供菜单/工具卡片入口和可编辑配置中心，不复制接口自动化业务页面 |
| 页面业务 API | 提供项目资产目录、任务、日志、报告和运行前校验接口 | 按约定路由到工具；提供通用 Runtime Scope、Release、Secret/Credential 管理 API，不实现同名任务业务 API |
| 项目与用例 | 管理并校验 `projects/` 中的 Project Manifest、API、Case、Flow、Scenario 和 Fixture | 管理平台项目与工具 `project_id` 的绑定、Scope 启停和 `target_env`，不读取或解析测试资产 YAML |
| 任务执行 | 负责参数校验、任务状态机、pytest/Flow 执行、取消、重试和结果快照 | 不执行 pytest，不维护接口自动化任务状态 |
| 结果与报告 | 负责日志、JUnit、Allure、下载权限和项目隔离 | 提供入口所需的通用访问能力，不重建报告索引 |
| 身份与配置 | 声明所需配置键/Profile，消费并校验平台下发的不可变快照；不得编辑、双写或静默回退运行配置 | 提供统一登录/RBAC、Runtime Scope、配置 Release/回滚、Secret/Credential 生命周期和快照物化 |
| 健康与发现 | 暴露工具健康状态及可用性信息 | 注册并展示 `api-autotest` 工具状态 |

集成要求：

1. Web 前端路由、静态资源、业务 API 和报告链接必须支持可配置 Base Path，不能假设部署在站点根路径；
2. 从平台入口进入、浏览器刷新以及直接打开任务详情时均不得出现路由 404；
3. 平台传入的身份、平台项目、`platform_environment` 和可访问 Runtime Scope 属于受控上下文；工具只允许用户选择授权 `project_id`，`target_env` 按当前平台实例固定映射，并在任务启动前固化快照；
4. 平台不可直接传递或记录 Secret 明文，工具也不得通过浏览器查询 Secret 明文；
5. 工具不得提供“项目配置”“配置状态”或“配置异常”独立页面；配置校验失败时在概览或提交区内联展示原因和平台配置中心深链；
6. 平台配置模式必须以平台快照为唯一来源，快照不可用、Release 无效或契约不满足时直接失败，禁止回退项目 YAML、进程环境变量或 `.env`；
7. 新增第三个项目时，平台只新增平台项目绑定、Scope、Release 和 Secret/Credential 数据，不新增该项目专属页面或执行分支；
8. 若平台与工具需要修改同一协议，应先定义版本化的 Runtime Scope、快照和任务契约，再由双方按职责实现，禁止靠项目名前缀配置键或伪造 Tool ID 绕过作用域建模。

### 6.8 双唯一真源与运行模式

#### 数据归属

| 数据类别 | 唯一真源 | 工具运行时行为 |
| --- | --- | --- |
| Gateway、公共 `comm`、Header、超时、轮询、Feature Flag | 测试开发平台的 Scope 配置 Release | 启动任务时按 Release 物化并只读使用 |
| Secret、Credential、用户会话 | 测试开发平台 Secret/Credential Store | 仅按所需 Profile 获取或更新，不落入项目资产 |
| 项目启停、固定环境映射、默认 Scope、平台项目绑定 | 测试开发平台 | 项目列表取当前平台固定环境下的授权 Scope 与本地有效项目包的交集 |
| Project Manifest、配置键/Profile 契约 | `Truthy_ApiAutoTest2/projects/` | 校验平台快照是否满足执行需求，不保存运行值 |
| API、Case、Flow、Scenario、Fixture | `Truthy_ApiAutoTest2/projects/` | 收集、执行和展示，平台不得复制或在线编辑 |
| 任务、日志、JUnit、Allure | `Truthy_ApiAutoTest2` | 记录 Scope/Release 快照并按项目、任务隔离 |

#### 配置来源模式

1. **平台配置模式**：Web、平台任务和连接平台的本机 CLI 必须使用 `config_source=platform`。运行配置只来自指定 Runtime Scope 的已发布快照，任何本地配置均被忽略。
2. **独立调试模式**：仅允许开发者显式使用 `config_source=local`；其配置属于临时离线调试输入，不纳入平台状态、不在 Web 暴露，也不得与平台快照合并。
3. **禁止自动降级**：两种模式必须互斥且在任务/日志中可见。平台配置获取失败时不得自动切换独立调试模式。
4. **禁止双写**：变更平台管理的配置必须经平台配置中心形成新 Release；不得要求开发者同步修改项目 YAML 或工具内表单。
5. **固定环境映射**：dev 平台只加载 `target_env=test` 的 Scope；prod 平台只加载 `target_env=prod` 的 Scope。Web 不提供接口环境切换控件。

---

## 7. 信息架构与项目包规范

### 7.1 目标目录

本期保留现有公共 Python 模块的总体结构，避免为了目录名称进行无收益重构；逻辑上将其视为执行引擎。业务资产统一迁入 `projects/`：

首批标准项目包路径为 `projects/truthy/` 和 `projects/dating/`。

```text
Truthy_ApiAutoTest2/
├── api/                         # 通用 Gateway 客户端
├── utils/custom/                # 通用加载、断言、Flow 和配置能力
├── test_cases/                  # 通用 pytest 收集与执行入口
├── web/                         # Web 页面、页面业务 API 与平台挂载适配，功能实现归属本仓库
├── config/                      # 现有启动/独立调试兼容配置；平台配置模式不从此处读取项目运行配置
├── projects/
│   ├── truthy/
│   │   ├── project.yaml         # Project Manifest：只声明资产与配置契约，不保存运行值
│   │   ├── data/
│   │   │   ├── api/
│   │   │   ├── apis/
│   │   │   ├── cases/
│   │   │   ├── flows/
│   │   │   └── scenarios/
│   │   └── fixtures/
│   └── dating/
│       ├── project.yaml         # Project Manifest：只声明资产与配置契约，不保存运行值
│       ├── data/
│       │   ├── api/
│       │   ├── apis/
│       │   ├── cases/
│       │   ├── flows/
│       │   └── scenarios/
│       └── fixtures/
├── runtime/                     # 运行时会话，禁止提交 Git
├── logs/                        # 按项目隔离
├── reports/                     # 按项目隔离
└── runtest.py
```

### 7.2 项目标识规则

- `project_id` 必填、唯一且稳定；
- 仅允许小写字母、数字和短横线；
- 必须以小写字母开头；
- 建议正则：`^[a-z][a-z0-9-]{1,31}$`；
- `project_id` 不随展示名称变化；
- 不允许包含 `/`、`..`、空格或绝对路径片段；
- 已产生任务记录后不得复用已删除项目的 `project_id` 表示其他项目。

### 7.3 `project.yaml`（Project Manifest）最小契约

项目描述至少应表达以下信息：

```yaml
schema_version: 1
project_id: dating
display_name: Dating AI Assistant

capabilities:
  - gateway
  - signed_binary_upload

config_contract:
  required_keys:
    - gateway.base_url
    - gateway.path
    - gateway.comm
    - flow.analysis.poll_interval_seconds
    - flow.analysis.timeout_seconds
  credential_profiles:
    - anonymous_session

redaction:
  extra_keys: []
```

规则：

- `project.yaml` 不保存 Gateway 地址、环境名、默认环境、Token、Secret、签名信息、超时或轮询值；
- `schema_version` 不支持时必须失败，不能猜测解析；
- 项目声明的能力必须是执行引擎已支持的通用能力；
- 未知能力必须在收集阶段报错；
- `required_keys` 与 `credential_profiles` 是契约，不是运行值；平台快照必须满足本次选中资产实际需要的契约；
- 项目启停、展示名覆盖、固定环境映射和默认 Scope 由平台管理，不在 Manifest 双写；
- `redaction.extra_keys` 为 schema 兼容字段，当前版本不据此改写任何日志或报告内容；
  新项目仍保留空数组，避免破坏既有 Manifest 契约。

### 7.4 平台 Runtime Scope 与配置边界

平台必须新增通用“工具项目运行作用域”模型（逻辑名 `tool_project_scope`，最终表名由开发设计确定），唯一键至少包含：

```text
platform_environment + tool_id + platform_project_id + project_id + target_env
```

Scope 至少包含：

- `scope_id`：不可变唯一标识；
- `platform_environment`：例如 `dev`、`prod`；
- `tool_id`：本工具固定为 `api-autotest`；
- `platform_project_id`：平台 RBAC 项目主键；
- `project_id`：工具稳定项目键；
- `target_env`：被测系统环境；
- 环境映射必须满足 `dev→test` 或 `prod→prod`，不允许其他组合；
- 启用状态、默认 Scope 标志和必要审计字段；
- 当前配置 Release 选择器，以及与 Scope 绑定的 Secret/Credential。

配置 Release 负责 Gateway URL/path/method、非敏感 Header、公共 `comm`、超时、轮询、Feature Flag、产品/包/entitlement 标识和可选 transport target。Secret/Credential Store 负责 Token、operator 身份、签名所需凭证和会话材料。项目包不得再创建 `projects/<project_id>/env/<target_env>.yaml` 作为平台配置的副本。

禁止以下替代方案：

- 用 `DATING_TEST_*`、`DATING_PROD_*`、`TRUTHY_TEST_*` 等键名前缀模拟作用域；
- 为每个项目注册一个伪 Tool ID；
- 将所有项目配置塞入无 Schema 的单个 JSON Blob；
- 让浏览器或工具 Web 页面读取、保存 Secret 明文；
- 在平台模式中继续合并根 `.env`、项目 YAML 和平台快照。

### 7.5 项目资产引用规则

- API、Case、Flow 和 Scenario 的相对路径必须解析在当前项目包内；
- `fixtures` 只能访问当前项目的测试素材；
- 路径解析后若越过项目根目录，必须以项目范围错误终止；
- Flow 只能引用同一项目 `data/apis` 中的 API ID；
- 项目之间允许出现相同 API ID、Case ID 或 Flow 名称；
- 在任务和报告中，资源唯一键应包含 `project_id`。

---

## 8. 功能需求

### 8.1 FR-001 项目注册与发现（P0）

系统必须：

1. 从受控的 `projects/` 根目录发现项目；
2. 只加载目录名与 `project.yaml.project_id` 一致的项目；
3. 校验项目 ID、Manifest 版本、配置契约和必要资产目录；
4. 对重复 ID、未知版本、项目包损坏和配置契约错误给出稳定错误；
5. 平台配置模式下，项目列表必须取“当前用户有权限、已启用且符合当前固定环境映射的 Runtime Scope”与“工具本地有效项目包”的交集；
6. 单个项目包损坏时，不得静默使用另一个项目包或配置；
7. Scope 存在但项目包缺失、项目包存在但 Scope 未配置必须返回不同错误，不得静默隐藏根因；
8. 项目列表不得返回 Secret 内容；
9. 项目启停、默认 Scope 和当前平台固定映射的 `target_env` 以平台为准，不得从 Project Manifest 覆盖。

### 8.2 FR-002 CLI 项目选择（P0）

CLI 新增：

```bash
python runtest.py --project dating --target-env test
python runtest.py --project dating --target-env test --module GetMe
python runtest.py --project dating --target-env test --flow DatingAnalysisHappyPath
python runtest.py --project truthy --target-env test --tag smoke
```

要求：

- `--project` 必须同时作用于测试收集、配置加载、会话、日志和报告；
- 未传 `--project` 时，兼容期默认解析为 `truthy` 并输出一次明确的弃用提示；
- 未知或禁用项目必须在 pytest 执行前失败；
- 平台配置模式下 `target_env` 由当前 `platform_environment` 固定解析；CLI 如显式传入 `--target-env`，该参数只用于一致性校验，不能切换环境；
- dev 平台只接受 `--target-env test`，prod 平台只接受 `--target-env prod`；不匹配时必须在网络请求前失败；
- 旧 `--env` 仅作为 `--target-env` 的兼容别名，禁止解释或覆盖 `platform_environment`；
- `--flow` 必须在选定项目范围内校验；
- 禁止使用路径形式绕过项目和 Flow 名称校验；
- 配置来源必须是显式且互斥的 `platform` 或 `local`；平台配置模式下由 CLI 获取 Runtime Scope 快照，禁止读取本地配置作为回退。

### 8.3 FR-003 单接口测试（P0）

多项目改造后必须完整保留 V1.3 单接口能力：

- 一个 API 定义可供多个 Case 使用；
- 每条 Case 独立维护参数、标签、断言和提取；
- 同名 API 可存在于不同项目；
- pytest ID、日志和 Allure 标题应包含或附带项目信息；
- 单接口执行不得读取 Flow 或其他项目 Case；
- 所有断言仍按 HTTP、Gateway、子请求、业务字段顺序执行。

### 8.4 FR-004 多接口 Flow（P0）

多项目改造后必须完整保留：

- 步骤顺序；
- 模板变量替换；
- 必填和可选字段提取；
- 固定等待；
- 条件轮询、间隔、超时；
- `terminate_on`；
- `run_on_termination` 清理步骤；
- 每一步独立参数和断言；
- Flow 与同名 Scenario 一一对应。

补充规则：

- 一个 Flow 只能在一个项目中执行；
- Flow 的多个步骤可以使用同一 Runtime Scope 快照中声明的不同 transport target；
- Flow 仍按步骤发起请求，不自动合并成一个 Gateway `requests` 数组；
- 提取变量只在当前测试实例中生效，不跨 Case、任务或项目共享。

### 8.5 FR-005 Gateway 项目化（P0）

Gateway 执行必须从任务固化的 Runtime Scope 快照获得：

- 当前 `target_env` 的 base URL、path、method 和 headers；
- 公共 `comm`；
- `device_id`；
- 当前会话的 `auth_token`；
- API 定义声明的 target 和会话要求。

要求：

- access token 按项目协议进入 `comm.auth_token`，不得擅自改为 HTTP `Authorization` Header；
- Gateway 顶层、子请求和业务错误继续分层处理；
- 业务分支只依赖稳定错误码，不依赖 `message` 文本；
- 请求 ID 在单次 Gateway 调用内唯一；
- `comm`、Header、Token、请求体、响应体与异常均按原文写入授权范围内的执行日志和报告，
  不做字段级脱敏。

### 8.6 FR-006 会话与凭证策略（P0）

系统应将“会话生命周期”和“凭证来源”从 Truthy 专属硬编码中抽离为可复用策略。

首期至少支持：

| Profile | 用途 | 典型项目 |
| --- | --- | --- |
| `anonymous_session` | 创建匿名会话、刷新 Token、向 Gateway 注入 access token | Truthy、Dating |
| `admin_session` | 注入 Admin session/operator 信息 | 仅声明 Admin API 的 Truthy 场景 |

凭证检查要求：

1. 根据当前项目和实际选择的 API/Flow 计算所需 Profile；
2. 只校验所需 Profile 的字段；
3. 缺失时明确返回 `project_id`、`target_env`、Runtime Scope、Profile 和缺失键名；
4. 不得在错误中返回 Secret 值；
5. Dating 项目不得默认继承 Truthy Admin Profile；
6. 不包含 Admin API 的任务不得强制检查 `ADMIN_SESSION_TOKEN`、`ADMIN_OPERATOR_ID`、`ADMIN_OPERATOR_NAME`。

平台配置模式：

- 只使用平台针对当前 Runtime Scope 与配置 Release 物化的运行时快照；
- 本机运行但连接平台配置中心时仍属于平台配置模式；
- 不读取 `config/env/*.yaml`、项目环境 YAML、进程环境变量、Secret 文件或根 `.env` 作为补偿；
- Scope/Release/Secret 查询必须同时绑定 `platform_project_id`、`project_id` 和 `target_env`；
- Secret 状态“可用”必须表示对当前 Scope、执行身份和实际所需 Profile 可解析，而不是仅表示平台中存在一个同名 Secret；
- 平台快照不可用时返回稳定错误并终止，禁止自动切换本地来源。

会话选择规则固定为：

1. access token 存在、过期时间合法且剩余时间 **大于 2 小时**时直接复用，不调用会话 API；
2. access token 尚未过期且剩余时间 **小于或等于 2 小时**时，refresh token 有效则调用一次 `RefreshSession`；
3. access token 已过期、缺失或过期时间无效时，直接调用 `CreateAnonymousSession`；
4. 临期刷新失败、refresh token 无效或缺少刷新接口时，只回退调用一次 `CreateAnonymousSession`。

边界按毫秒比较，恰好剩余 2 小时属于刷新区间。该判断在发送业务 API 前执行，
不得因为存在 refresh token 就在 access token 已过期时先请求 `RefreshSession`。

独立调试模式：

- 仅供离线开发者显式启用，入口和任务记录必须显示 `config_source=local`；
- 本地值不得回写平台，也不得宣称为平台 Release 或“配置可用”；
- 不得同时读取或合并平台快照；
- 平台 Web、平台任务与正式 Jenkins 任务禁止使用该模式；
- 旧 Truthy 根 `.env` 仅允许在迁移窗口内由独立调试兼容入口读取，并必须输出弃用提示；Dating 和新项目禁止读取。

会话持久化：

- 会话按 `scope_id + credential profile + 授权主体` 隔离；
- 一个项目刷新 Token 不得覆盖另一个项目；
- 平台配置模式通过平台 Credential/会话接口持久化；工具只允许使用任务级内存或 Scope 隔离的短期缓存，不得把本地缓存当作凭证真源；
- 独立调试模式如使用会话文件，该文件仅属于本地运行时数据，不得进入 Git；
- 写入或回写必须具备并发控制和原子性，避免刷新竞争或中断后产生半写状态。

### 8.7 FR-007 通用签名上传动作（P0）

执行引擎提供一个业务无关的签名二进制上传动作，项目通过声明式参数指定：

- 上传 URL 的运行时变量或响应路径；
- 必需 Headers 的运行时变量或响应路径；
- 当前项目 `fixtures` 内的文件；
- HTTP method，首期默认支持 `PUT`；
- 允许的成功状态码；
- 可选的输出变量。

要求：

- 动作不得硬编码 `upload_headers`、`required_headers`、`media_asset_id` 或 `asset_id`；
- Truthy 现有 `prepared_media_upload` 行为必须通过兼容映射保持有效；
- Dating 新 Flow 使用通用动作和 Dating 实际字段；
- 上传 URL（含查询签名）、签名 Header、HTTP 状态、耗时和原始异常应写入授权范围内的
  日志及 Allure 附件；上传文件二进制内容不得写入文本日志或报告附件；
- 上传失败时应保留完整目标 URL、Header、HTTP 状态、耗时和异常原文，便于定位；
- 签名过期应明确归类为外部上传失败，不得伪装成 Gateway 断言失败。

### 8.8 FR-008 Web 项目选择与用例目录（P0）

Web 工具首页增加项目选择器，并满足：

1. 只展示当前用户有权限、Scope 已启用、配置 Release 可解析且项目包合法的项目；
2. 默认选择平台标记的默认 Scope；兼容期仅在用户有权访问 Truthy 时可回退选择 `truthy`，不得越权默认；
3. 切换项目后从当前平台环境加载唯一匹配的 Runtime Scope，并从工具项目包加载 API、Cases 和 Flows；
4. 切换项目时清空不属于新项目的 Flow、标签等筛选条件；
5. 用例目录中的 API、Case、Flow 均显示所属项目；
6. 项目包错误、Scope 错误、配置 Release 错误和凭证错误必须分类展示，不泄漏服务器绝对路径或 Secret；
7. 项目选择结果必须随任务提交，而不是只存在浏览器页面状态中。
8. 页面中 API、Case、Flow 和预计执行数量必须来自当前项目运行时目录，不能写死；Dating 首期目录应展示本 PRD 定义的 11 个 API；
9. “全部”执行类型必须明确说明统计口径，并分别展示将执行的单接口 Case 数与 Flow 数；
10. 任务记录页若允许跨项目查看，必须明确显示“全部项目”作用域，不能与“页面只展示当前项目数据”的文案冲突；
11. Web 路由、静态资源、业务 API 和报告链接必须遵守可配置 Base Path，以支持从测试开发平台入口挂载。

### 8.9 FR-009 任务模型（P0）

Web/平台任务提交只接收 `project_id` 和测试资产选择；`platform_environment`、`target_env` 与 `platform_project_id` 均由受控上下文及固定映射解析，不接受普通表单覆盖：

```json
{
  "project_id": "dating",
  "run_type": "flow",
  "flow": "DatingAnalysisHappyPath",
  "tag": null
}
```

任务记录至少保存：

- `platform_project_id`、`project_id` 和项目展示名称快照；
- `platform_environment`、`target_env` 和 `runtime_scope_id`；
- 执行类型、Flow、标签；
- 任务状态、创建/开始/结束时间；
- `config_source`、配置 Release/版本、快照标识和所需 Credential Profile 版本元数据；
- JUnit、Allure 和日志位置；
- 取消、超时和错误信息；
- 外部 CI 关联信息（如适用）。

规则：

- 任务启动后不得因用户切换页面项目而改变归属；
- 历史任务使用保存的项目快照展示；
- 缺失 `project_id` 的旧任务提交在兼容期映射为 `truthy`；
- 新平台调用必须显式传入 `project_id`，但不得传入可改变当前平台目标环境的参数；
- 旧请求中的 `env`/`target_env` 仅用于与固定映射结果做兼容校验；不一致时拒绝请求，不得覆盖平台部署环境；
- 服务端必须验证 `project_id + target_env` 对应当前用户可访问的 Runtime Scope；
- 任务创建成功后，Scope、Release 和 Credential/Profile 版本元数据不可变；配置变更或“重试”必须创建新任务；
- 任务 ID 在所有项目间保持全局唯一；
- 取消操作不得误取消其他项目任务。

### 8.10 FR-010 日志、结果和报告隔离（P0）

产物路径必须至少包含项目维度，建议逻辑结构：

```text
logs/<project_id>/<target_env>/<YYYY-MM-DD>/<timestamp>_<target_env>_<pid>.log
reports/junit/<project_id>/<task_id>.xml
reports/task-reports/<project_id>/<task_id>/current
runtime/<project_id>/<task_id>/...
```

要求：

- 同一时间执行 Truthy 和 Dating 不得覆盖文件；
- 任务详情只能打开自身项目和任务目录内的文件；
- “最新报告”必须按项目计算；
- JUnit 和 Allure 元数据应包含项目、环境和任务 ID；
- JUnit、Allure 与结构化日志中的“环境”必须明确为 `target_env`，并额外记录 `runtime_scope_id` 与配置 Release；
- 日志检索和下载接口必须校验项目与任务归属；
- 每次任务通过任务记录中的 `log_file` 关联当日目录下的唯一进程日志，不再额外创建
  `<task_id>` 日志目录；
- 清理策略按 `project_id + target_env` 下的日期目录安全枚举目标，禁止宽路径删除。

### 8.11 FR-011 Jenkins 与外部触发（P0）

Jenkins 增加 `PROJECT_ID` 参数并满足：

- 默认值在兼容期为 `truthy`；
- 执行命令显式传递 `--project`；
- `TARGET_ENV` 不作为可切换参数：dev Jenkins 固定为 test，prod Jenkins 固定为 prod；旧 `ENV`/`TARGET_ENV` 仅在兼容期做一致性校验；
- 产物发布携带 `project_id + task_id`；
- 外部平台任务 ID 与项目 ID 均写入报告元数据；
- 未知项目在开始安装或执行测试前失败；
- Truthy 现有流水线参数继续有效。

### 8.12 FR-012 项目包静态校验（P0）

系统必须能够在不调用真实接口的情况下校验：

- 项目描述与目录名；
- Project Manifest、配置键/Profile 契约；
- API 声明的 transport target 名称及其配置键契约；
- API ID 唯一性和字段完整性；
- Case 对 API 的引用；
- Flow 对 API 的引用；
- Flow 与 Scenario 对应关系；
- step ID 与 `step_data` 对应关系；
- 通用动作参数；
- fixture 文件存在性和路径范围；
- 未知会话或凭证 Profile；
- 敏感值误写入项目 YAML 的明显风险项。

校验错误必须包含项目、相对文件路径、字段位置和可执行修复说明。

平台配置模式还必须在不发起业务网络请求的情况下校验：Runtime Scope 存在且已启用、Release 可物化、必需配置键齐全、所选资产要求的 Credential Profile 可解析。该运行就绪度校验与项目包静态校验必须分别报告。

### 8.13 FR-013 平台 Runtime Scope 与快照契约（P0）

平台必须提供项目无关、可复用于后续工具项目的通用能力：

1. 创建、查询、启停 Runtime Scope，并校验唯一键；
2. 将配置定义、Release、激活记录、Secret、Credential 和用户 Credential 绑定到 `scope_id`，或提供等价且可验证的复合作用域；
3. 根据认证用户、`tool_id`、`platform_project_id`、`project_id`、`target_env` 和 Release selector 规划快照；
4. 在服务端物化正常配置和所需 Secret/Credential，向浏览器仅返回状态，向受信任工具运行时返回最小必要值；
5. 支持配置校验、发布、回滚和审计；历史任务可按快照标识追溯，但不得读取后来修改后的值替代历史值；
6. 配置契约不满足、Scope 未授权或 Release 无效时返回稳定错误；
7. 新增项目只新增 Scope/Release/Secret/Credential 数据，不修改平台项目专属代码。

平台必须在 Scope 创建、激活、快照规划和任务提交四个阶段校验固定环境映射；`dev + prod` 或 `prod + test` Scope 不得被激活或执行。

快照中至少包含：`runtime_scope_id`、`platform_environment`、`tool_id`、`platform_project_id`、`project_id`、`target_env`、`config_release_id/version`、普通配置值、Credential Profile 元数据和快照时间。Secret 明文不得进入浏览器配置响应或普通任务 JSON；执行过程中实际进入请求、响应、Header 或异常的值可以按原文进入已授权任务的日志和报告。

### 8.14 FR-014 运行前校验与内联修复提示（P0）

`Truthy_ApiAutoTest2` 提供运行前校验接口，供概览页和任务提交区域内联使用：

- 当前 Runtime Scope 是否存在、启用且授权；
- Project Manifest 与平台快照的配置契约是否匹配；
- 当前激活 Release/版本与发布时间；
- 本次选择实际需要的 Credential Profile 是否可用、缺失或不适用；
- 当前平台环境与接口环境是否符合固定映射；
- 配置来源是 `platform` 还是显式独立调试的 `local`；
- 可安全展示的缺失逻辑键和标准错误码；
- 跳转平台配置中心当前 Scope 的受控深链。

该接口不得返回 Secret 值，不得提供运行配置编辑/保存 API。工具不设置独立配置页面或侧栏入口；校验失败时在用户当前操作位置展示简短原因和“前往平台配置中心”，修复配置必须在平台形成新 Release。

---

## 9. Dating 首期项目需求

### 9.1 环境与 Gateway

Dating 当前 test 固定入口：

```text
POST ${TEST_GATEWAY_BASE_URL}/dating/gateway/invoke
```

要求：

- 客户端和测试框架只调用 Gateway，不直连 Dating 内部业务服务；
- 上述有效地址由 dev 平台 Dating `test` Runtime Scope 的已发布配置组合得到，不写入 Dating 项目包；
- 未来验证线上接口时，必须进入 prod 平台并使用 Dating `prod` Scope 的 Gateway、Release、Secret/Credential 和会话；禁止从 dev 平台切换到 prod 地址；
- `comm.auth_token` 保存 access token；
- 同一安装身份稳定复用 `comm.device_id`；
- 客户端不得提供应由 Gateway 注入的可信 `app_id`、`user_id`；
- Flow 每一步默认使用一个子请求，便于变量提取、轮询和错误定位。

### 9.2 接口协议裁决

首期 API 定义必须使用：

- `GetAnalysisTask`；
- `GetAnalysisResult`。

不得使用旧评审稿中的：

- `GetTask`；
- `GetTaskResult`。

如果 test 或未来 prod 服务再次变更方法名，应修改 Dating 项目包 API 定义和协议版本记录，不得在公共引擎加入方法名判断。

### 9.3 Dating 单接口 Cases

P0 至少覆盖：

| API | 最低覆盖 |
| --- | --- |
| `CreateAnonymousSession` | 成功创建、关键 Token 字段存在 |
| `RefreshSession` | 成功刷新、整组 Token 可提取 |
| `GetMe` | 有效会话成功、无会话或无效会话失败 |
| `GetMediaUploadConfig` | 成功、限制字段存在且类型正确 |
| `PrepareMediaUpload` | 合法图片成功、关键上传字段存在、非法参数失败 |
| `CompleteMediaUpload` | 已上传资源成功、无效资源失败 |
| `CreateAnalysisTask` | 合法资产成功、缺失或无效资产失败、额度错误可识别 |
| `GetAnalysisTask` | 有效 task 成功、无效或无权限 task 失败 |
| `GetAnalysisResult` | 成功任务可获取、未成功任务不可获取 |
| `DeleteTaskData` | 删除成功、重复删除满足幂等协议 |
| `GetQuotaStatus` | 正确产品和 entitlement 查询成功 |

所有依赖已有资源 ID 或特殊账户状态的单接口 Case，必须显式标注前置条件，不得伪装成可独立运行用例。

### 9.4 Dating 多接口 Flows

#### P0 Flow A：匿名会话验证

```text
CreateAnonymousSession
→ GetMe
→ RefreshSession
→ GetMe
```

验证会话创建、字段提取、刷新后覆盖及再次调用。

#### P0 Flow B：单图 Analysis 成功链路

```text
CreateAnonymousSession / 复用有效会话
→ GetMediaUploadConfig
→ PrepareMediaUpload
→ COS PUT
→ CompleteMediaUpload
→ CreateAnalysisTask
→ 轮询 GetAnalysisTask
→ succeeded 后 GetAnalysisResult
→ DeleteTaskData
→ 验证删除后不可访问
```

#### P1 Flow C：九图边界

使用 9 张合法测试图片，验证：

- `asset_ids` 顺序保持不变；
- 不超过实时配置限制；
- 任务可以进入合法终态；
- 流程结束后执行隐私数据清理。

#### P1 Flow D：拒绝或失败终态

验证：

- `queued`、`processing` 继续轮询；
- `rejected`、`failed` 终止轮询；
- `rejected`、`failed` 不查询结果；
- `run_on_termination` 清理步骤仍执行；
- 记录稳定 `error_code` 和 `retryable`，不依赖 message。

#### P1 Flow E：创建任务幂等

验证同一 `client_request_id`：

- 使用相同参数重试不会创建不受控的重复任务；
- 使用不同参数时可以识别 `IDEMPOTENCY_CONFLICT`；
- `client_request_id` 不超过 128 个字符。

### 9.5 轮询规则

Dating `test` 首个配置 Release 建议设置：

- 前 10 秒每 1 秒轮询一次；
- 之后每 2 秒轮询一次；
- 客户端侧总等待上限默认 90 秒；后续调整必须通过平台发布新 Release；
- 客户端超时仅表示本次测试停止等待，不得断言服务端任务已经失败；
- 超时后仍应按 Flow 清理策略执行可安全执行的清理步骤。

以上数值是平台运行配置的初始建议值，不是公共引擎或项目包内的常量。任务详情必须展示实际快照解析值及其 Release。执行引擎若首期只支持固定轮询间隔，Dating 首个 Release 必须能通过固定间隔完成 P0；分段退避列为 P1，不得阻塞多项目基础能力上线。

### 9.6 Analysis 结果断言

成功结果至少验证：

- `schema_version == dating.relationship_analysis.v1`；
- 存在 `overview`、`chat_signals`、`key_events`；
- 关键集合和字段类型符合协议；
- 未知 schema version 明确失败，不能按旧结构强行解析；
- 证据不足返回 `UNCLEAR` 时，对应分数允许且应为 `null`，不得断言为 `0`；
- 完整分析结果按原文写入已授权任务的日志和报告，便于复现断言；不得扩大任务访问权限。

### 9.7 媒体与隐私约束

自动化必须遵循当前接口环境的实时配置，同时支持 test 当前已知约束：

- `image/jpeg`、`image/png`、`image/webp`；
- 当前单张最大 7,000,000 字节；
- 当前每个 Analysis 任务 1 至 9 张图片；
- 当前上传 URL 默认有效 600 秒；
- 当前资产默认有效 86,400 秒。

上述数值不得作为不可变业务常量写入公共引擎。测试应优先读取 `GetMediaUploadConfig` 实际返回；固定边界 Case 必须明确其依赖的协议版本和环境。

禁止记录：

- 原始图片或其 Base64；
- 聊天截图内容；
- 上传文件的二进制正文。

允许按原文记录：

- 项目、环境、API ID；
- access token、refresh token、Authorization/Cookie 等 Header；
- COS 完整 URL、查询签名和 required headers；
- asset/task/result ID、完整分析文本、回复建议或证据消息；
- status、phase、schema version；
- 数量、耗时、HTTP 状态和稳定错误码。

这些日志与报告属于受限测试产物，必须经过任务归属/RBAC 校验后查看，并遵循保留期；
“原文记录”不代表可公开分享或写入浏览器长期存储。

### 9.8 外部测试前置条件

Dating test 真实链路要求：

- Gateway、Identity、Dating、Worker、Subscription 和 COS 可用；
- 具备合法测试图片；
- 测试账户存在足够 Analysis 额度，或用例明确使用额度耗尽专用账户；
- 异步 Worker 在测试超时范围内完成任务；
- 测试数据符合允许上传和处理的隐私要求。

外部条件不满足时应标记为环境阻塞或跳过原因，不应误判为框架缺陷。

---

## 10. 配置、Release 与 Secret 隔离

### 10.1 唯一真源矩阵

| 内容 | 唯一真源 | 变更方式 | 工具仓库是否保存运行值 |
| --- | --- | --- | --- |
| 项目启停、固定环境映射、平台项目绑定 | 测试开发平台 Runtime Scope | 平台配置中心审计变更 | 否 |
| Gateway、`comm`、Header、超时、轮询、Feature Flag | 测试开发平台配置 Release | 校验、发布、回滚 | 否 |
| Secret、Credential、用户会话 | 测试开发平台 Secret/Credential Store | 受权限控制的创建、轮换、禁用 | 否 |
| Project Manifest、配置契约 | `Truthy_ApiAutoTest2/projects/` | 代码评审与版本发布 | 仅保存键/Profile 契约，不保存值 |
| API、Case、Flow、Scenario、Fixture | `Truthy_ApiAutoTest2/projects/` | 代码评审与版本发布 | 是 |

P0 不允许任务表单任意覆盖平台运行配置或选择接口环境。需要修改 Gateway、超时、轮询等值时，必须在平台配置中心形成新 Release；任务仅选择已授权的 `project_id` 和测试资产，`target_env` 由当前平台实例固定解析。

### 10.2 运行作用域

普通配置、Release、激活记录、Secret 和 Credential 的基础作用域为：

```text
platform_environment
+ tool_id
+ platform_project_id
+ project_id
+ target_env
```

Credential/会话在此基础上增加 `credential_profile` 和必要的用户/授权主体维度。平台不得再只按 `tool_id + platform_environment` 选择配置，否则 Truthy 与 Dating 会发生碰撞。

有效环境组合仅有：

| 当前平台 | 接口环境 | 当前/未来用途 |
| --- | --- | --- |
| `dev` | `test` | 当前 Truthy、Dating 等项目的日常接口自动化 |
| `prod` | `prod` | 未来明确开展线上接口验证时使用全套 prod 配置与凭证 |

`dev→prod` 和 `prod→test` 均为非法组合。进入不同平台实例才代表切换接口环境，工具 Web 内不提供环境切换。

### 10.3 配置来源与 fail-closed

平台配置模式的唯一取值链路为：

```text
受控用户/平台上下文
→ 授权 Runtime Scope
→ 激活的配置 Release
→ 服务端物化快照
→ 工具按 Project Manifest/所选资产校验
→ 固化到任务
```

以下来源在平台配置模式一律忽略：

- `projects/<project_id>/env/*.yaml`；
- 根或项目 `.env`；
- 容器中同名进程环境变量；
- 工具 Web 表单保存的配置副本；
- 其他项目或其他 `target_env` 的 Release/Secret。

平台快照请求失败、Release 未激活、配置契约不满足或 Credential 不可解析时，任务必须在启动 pytest 前失败。不得以“提高可用性”为由自动使用本地旧值继续执行。

独立调试模式没有来源优先级：使用者必须显式选择单一本地输入集合，运行记录标记 `config_source=local`，且完全不请求/合并平台快照。该模式不影响平台中的“配置可用”状态。

### 10.4 Release 与任务快照

- 普通配置必须经过校验和发布后成为可执行 Release；草稿不可用于正式任务；
- 激活、回滚和发布均记录操作人、时间、Scope 和版本；
- 工具创建任务时先选择 Release，再物化配置与所需 Credential Profile；
- 任务至少保存 `runtime_scope_id`、`config_release_id/version`、快照标识及 Credential Profile 版本元数据；
- Secret 值仅由平台物化到受信任运行进程内存或权限为 `0600` 的任务短期文件，
  不写入普通任务 JSON、命令行参数、配置响应或浏览器长期存储；实际请求、响应、
  Header 和异常中的值按用户确认保留在已授权任务的原始日志与报告中；
- Release 或 Credential 后续变化不得改变历史任务展示；重试必须新建任务并重新解析当前有效配置。

### 10.5 Secret 状态语义

平台和工具展示 Secret/Credential“可用”前，应至少确认：

- 属于当前 Runtime Scope，而不是仅属于同一工具；
- 适用于本次实际需要的 Credential Profile；
- 当前执行身份有权限使用；
- 逻辑键能够映射到执行引擎所需会话字段；
- 值非空、未被禁用且版本有效；
- 运行时物化可以取得对应键。

仅在数据库中存在一条 Secret 记录，不足以判定当前任务可用。浏览器只能获得“可用/缺失/不适用”等状态和缺失逻辑键，不得获得 Secret 值。

### 10.6 凭证错误信息

推荐错误结构：

```json
{
  "code": "PROJECT_CREDENTIAL_MISSING",
  "runtime_scope_id": "scope_xxx",
  "project_id": "truthy",
  "target_env": "test",
  "profile": "admin_session",
  "missing_keys": [
    "ADMIN_SESSION_TOKEN",
    "ADMIN_OPERATOR_ID",
    "ADMIN_OPERATOR_NAME"
  ],
  "config_center_url": "/config/scopes/scope_xxx"
}
```

Dating 普通任务中不得出现上述 Truthy Admin 缺失提示。`config_center_url` 必须是受控相对路径或平台生成的允许域名链接，不得由用户输入拼接。

---

## 11. 页面与平台交互要求

本章定义的接口自动化页面均由 `Truthy_ApiAutoTest2` 的 `web/` 模块实现。测试开发平台提供工具入口、通用配置中心及第 6.7 节定义的控制面能力。工具不提供独立配置页面；配置维护统一在平台完成，工具仅在当前操作位置展示必要的运行前校验结果。

### 11.1 工具首页

首页至少包含：

- 项目选择器；
- 当前项目说明；
- 只读运行环境摘要：当前平台和由其固定映射的接口环境；
- 执行类型：全部、单接口、Flow；
- Flow、标签或模块筛选；
- 当前 Runtime Scope、配置 Release 和所需凭证 Profile 的精简状态摘要；
- 最近任务和最新报告。

页面统计要求：

- API、Case、Flow 和预计执行数量从当前项目目录及当前筛选结果实时计算；
- 选择“全部”时，分别显示单接口 Case 数和 Flow 数，禁止只用一个无法解释的总数；
- 切换执行类型后，隐藏或禁用不适用的筛选项，不能保留会影响提交但用户不可见的条件；
- 当前运行校验必须反映选中项目、`target_env`、Runtime Scope、Release 和实际执行 Profile，不使用全局 Secret 存在状态替代；
- 页面必须明确显示固定映射，例如“平台：DEV · 接口环境：TEST”，不得提供可编辑下拉框；
- 平台配置模式显示“配置来源：平台”及 Release；显式独立调试页面若存在，必须醒目标记“LOCAL，仅调试”，且不能从平台入口访问。

### 11.2 项目切换

项目切换后：

- 切换项目后只加载当前平台固定接口环境下授权并启用的 Runtime Scope；
- Flow 和用例目录重新加载；
- 不兼容的旧筛选条件被清空；
- 页面 URL 或状态中保留项目选择，刷新后可恢复；
- 不自动提交任务；
- 不展示上一个项目的 Scope、Release、Secret 状态和报告；
- 项目包存在但当前环境 Scope 缺失，或 Scope 存在但项目包缺失时，在项目切换区域内联显示不同阻塞状态和修复责任方；
- Fixture Project 等验证项目只在 dev/test 展示，prod/prod 不作为普通业务项目暴露。

### 11.3 任务列表与详情

- 每条任务显示项目名称或项目标识；
- 支持按项目筛选；
- 任务详情显示提交时的项目快照；
- 任务详情显示提交时不可变的 Runtime Scope、`platform_environment`、`target_env`、配置 Release/版本和 Credential Profile 元数据；
- 日志、JUnit 和 Allure 链接必须属于该任务项目；
- 历史 Truthy 任务缺少项目字段时显示为“Truthy（历史任务）”；
- 项目被禁用后，历史任务仍可查看，但不能新建任务；
- “当前项目”和“全部项目”必须作为明确、可见且可恢复的列表作用域；侧栏说明、筛选器和空状态文案保持一致；
- 任务列表支持分页，并提供项目、状态、执行类型和时间范围筛选；当前实例只展示对应平台环境任务，环境作为只读列而不是切换筛选器；P1 支持按任务 ID、API、Case 或 Flow 搜索及按时间排序；
- Flow 详情中的步骤总数、成功数和步骤行必须采用同一统计口径。若界面合并展示轮询等内部步骤，必须标注“已合并展示”，并可展开查看原始步骤；
- “重试”必须创建新任务，使用当前可用 Scope/Release/Credential 重新校验并执行；原任务的项目、环境、配置版本、日志和结果快照保持不可变，详情页展示新旧任务关联关系。

### 11.4 用例目录

- 默认只展示当前项目资产；
- API、Case、Flow ID 仅需在项目内唯一；
- 测试资产错误按工具仓库相对路径展示；平台运行配置错误按 Scope、Release 和逻辑配置键展示；
- 不提供跨项目 Flow 编排入口；
- 本期保持只读，不支持在线编辑 YAML；
- Dating 首期必须展示 11 个 API，包括 `RefreshSession`、`GetMe` 和 `GetQuotaStatus`，不得以 8 个核心 Analysis 接口代替项目完整目录；
- API 列表至少显示 API ID、名称、Service、鉴权/会话 Profile 和可用状态；
- Case 与 Flow 标签页应分别显示对应数量，不将 Flow 数混入 Case 数。

### 11.5 创建单接口与 Flow 任务

- 单接口任务只提交当前 `project_id`、API、Case 和标签；`target_env` 由服务端按平台环境解析，P0 不允许表单覆盖环境或超时等运行配置；
- 任务预览必须展示最终 `project_id`、`target_env`、Runtime Scope、配置来源、Release 和实际所需 Profile；
- Flow 任务必须展示按实际定义生成的步骤预览，轮询间隔和超时显示平台快照解析值及配置 Release；
- `run_on_termination` 清理步骤应标识为“终止后仍执行”，避免被误解为仅成功时执行；
- 提交前只校验本次 API 或 Flow 实际需要的 Profile，并把解析结果展示为可用、缺失或不适用；
- “保存为草稿”不属于 P0，首期界面应隐藏。若后续作为 P1 引入，必须补充草稿归属、权限、有效期、配置变更和恢复规则；
- 提交成功后进入任务详情，新建任务与历史任务的选择状态不得相互污染。

### 11.6 内联运行前校验与异常反馈

- 删除侧栏“项目配置”入口以及独立“配置状态/配置异常/运行就绪度”页面；
- 概览页仅保留一张精简的当前运行上下文卡片，展示“平台环境 → 接口环境”、Release 和 Profile 总体结果；
- 单接口与 Flow 提交区在提交前校验当前 Scope/Release/Profile；正常时用一行状态表示，异常时在原位置展开错误和修复操作；
- 运行配置错误展示稳定错误码、Scope、Release、逻辑配置键、影响范围和“前往平台配置中心”入口；
- 测试资产错误才展示 `projects/<project_id>/...` 相对路径；运行配置错误不得提示创建任何本地配置文件；
- 深链必须定位当前 Runtime Scope，并在平台再次执行 RBAC 校验；不得把 Secret 或配置值放入 URL；
- 至少区分 Scope 缺失、项目包缺失、Release 无效、Credential 缺失、Scope 禁用和平台快照不可用；
- 项目包/配置契约错误、凭证错误、外部上传失败和异步 Flow 超时采用不同错误分类；
- 内联错误保留用户当前项目和筛选状态，修复返回或重试后继续原操作；
- 被禁用项目不得新建任务，但仍可按原任务权限访问其历史任务和原始报告。

### 11.7 页面状态与可用性

- 概览、项目切换、单接口任务、Flow 任务、用例库、任务记录和任务详情七类页面均需提供加载、空数据、错误和无权限状态；
- 所有交互控件具备可见焦点、键盘操作、禁用状态和明确文本标签，状态信息不能只依赖颜色；
- 表格在常用桌面宽度下不得截断关键操作；内容超出时优先固定关键列并提供受控横向滚动；
- 页面视觉与交互以《接口自动化工具.png》为基线，优先修正本章列出的数据口径、状态和流程问题，不要求重新设计测试开发平台主框架。
- 概览、项目切换和任务预览中的内联校验必须使用同一个 Runtime Scope 状态模型，不能各自推断“配置可用”。

---

## 12. 错误模型

新增或标准化以下错误：

| 错误码 | 场景 |
| --- | --- |
| `PROJECT_REQUIRED` | 新接口未提供项目且不适用兼容默认值 |
| `PROJECT_NOT_FOUND` | 项目不存在 |
| `PROJECT_DISABLED` | 项目已禁用 |
| `PROJECT_PACKAGE_NOT_FOUND` | 平台 Scope 已存在，但当前工具版本没有对应项目包 |
| `PROJECT_CONFIG_INVALID` | Project Manifest、配置契约或测试资产配置非法 |
| `TARGET_ENV_NOT_FOUND` | 当前用户可访问 Scope 中不存在指定被测环境 |
| `RUNTIME_SCOPE_NOT_FOUND` | 平台未建立匹配的工具项目运行作用域 |
| `RUNTIME_SCOPE_FORBIDDEN` | Runtime Scope 存在，但当前用户无权使用 |
| `CONFIG_RELEASE_INVALID` | 当前 Scope 无已激活 Release，或 Release 无法满足配置契约 |
| `CONFIG_SNAPSHOT_MATERIALIZE_FAILED` | 平台无法按选定 Scope/Release 物化运行时快照 |
| `PROJECT_ASSET_NOT_FOUND` | 当前项目内找不到 API、Case、Flow、Scenario 或 fixture |
| `PROJECT_SCOPE_VIOLATION` | 路径或引用越过当前项目范围 |
| `PROJECT_CAPABILITY_UNSUPPORTED` | 项目声明了执行引擎不支持的能力 |
| `PROJECT_CREDENTIAL_MISSING` | 当前项目实际需要的凭证不完整 |
| `PROJECT_RUNTIME_CONFIG_UNAVAILABLE` | 平台无法下发当前项目运行时配置 |
| `EXTERNAL_UPLOAD_FAILED` | 签名上传请求失败、签名过期或外部存储服务异常 |
| `FLOW_ASYNC_TIMEOUT` | 异步 Flow 在运行时配置的轮询超时内未进入终态 |

要求：

- 错误发生层次明确；
- 项目配置错误不得被包装为接口断言失败；
- Scope、Release、项目包和凭证错误必须保持可区分，不能统一包装为“配置异常”；
- 外部服务失败不得被包装为项目不存在；
- `EXTERNAL_UPLOAD_FAILED` 和 `FLOW_ASYNC_TIMEOUT` 必须作为执行错误展示，不能被包装为用例断言失败或项目配置错误；
- 配置控制面和预检错误不返回 Secret 值；任务执行错误、失败摘要和日志在任务归属
  校验通过后保留绝对路径、Token、签名、原始请求体及响应原文，并继续执行长度限制。

---

## 13. 兼容与迁移要求

### 13.1 Truthy 数据迁移

将当前根目录测试资产一次性迁入 `projects/truthy/`：

- `data/api/`；
- `data/apis/`；
- `data/cases/`；
- `data/flows/`；
- `data/scenarios/`；
- `data/photo/` 等测试素材。

当前 `config/env/test.yaml` 和 `config/settings.yaml` 中的 Truthy Gateway、公共 `comm`、Header、超时、轮询、会话及其他可变运行配置不得迁入 `projects/truthy/env/`，而应迁移到平台 Truthy/test Runtime Scope 的首个配置 Release。Secret/Credential 迁入该 Scope 的受控存储。

根 `config/settings.yaml` 只允许暂时保留与项目无关的启动/独立调试兼容项；平台配置模式必须忽略其中的项目运行值。待平台迁移和兼容期结束后，应删除已迁移的重复值与旧加载分支。

平台中现有仅按 `tool_id + platform_environment` 管理的 `api-autotest` 配置、Release、Secret 和 Credential 也必须执行一次性作用域迁移：

- 经人工确认属于 Truthy 的现有记录绑定到 `platform_environment + api-autotest + <Truthy 平台项目> + truthy + test`；
- Dating 当前使用独立的 `dev + api-autotest + <Dating 平台项目> + dating + test` Scope，不复用或复制 Truthy Credential；
- 未来需要线上验证时，Truthy、Dating 分别在 prod 平台建立各自 `target_env=prod` 的 Scope、Release、Secret/Credential 和会话，不从 dev/test Scope 复制运行态 Credential；
- 迁移应保留可追溯的版本、状态和审计信息；无法确定归属的记录不得自动激活；
- 切换完成后，平台模式停止使用旧的工具级选择路径，避免新旧作用域同时生效；
- 整个迁移过程不要求把平台配置导出回 `Truthy_ApiAutoTest2` 仓库。

迁移不得改变：

- API 的 `service_name` 和 `method_name`；
- Case 请求参数和断言；
- Flow 步骤顺序、变量名称、提取路径和终止规则；
- 当前 Gateway target 行为；
- 当前原始日志输出范围、保留期与访问控制。

### 13.2 兼容入口

兼容期要求：

- `python runtest.py --env test` 等价于显式指定 `--project truthy --target-env test`；
- 旧 Jenkins 任务未传 `PROJECT_ID` 时按 Truthy 执行；
- 旧平台任务请求未传 `project_id` 时按 Truthy 执行；
- 任务落库或文件记录必须补全实际 `project_id=truthy`；
- 旧 `env` 字段只补全为 `target_env`，`platform_environment` 始终来自受控工具实例；
- 兼容路径输出弃用提示，但不影响退出码和测试结果；
- 平台配置模式的兼容仅限字段映射，不得保留根 YAML/`.env` 作为配置回退。

### 13.3 不长期保留的兼容

- 不同时扫描根 `data/` 和 `projects/truthy/data/`；
- 不为 Dating 复制 Truthy 加载器；
- 不保留两个同义的项目字段；
- 不允许新项目依赖根目录 `.env`；
- 不在 `projects/<project_id>/env/` 长期保存平台运行配置副本；
- 不允许同一任务同时合并平台快照、本地 YAML 和进程环境变量；
- 通用上传动作稳定后，旧动作名称只作为 Truthy 数据迁移期别名。

兼容默认值的移除时间由后续版本规划决定，本期不直接删除。

---

## 14. 非功能需求

### 14.1 安全与隐私

- 平台配置模式的所有 Secret 由平台 Secret/Credential Store 提供，只能物化到运行进程内存或平台允许的短期受控文件；
- 独立调试模式的本地 Secret 必须被 Git 忽略，且不得与平台快照混合；
- 仓库不得提交真实 Secret；
- 项目路径必须经过白名单和解析后范围校验；
- 文件日志、终端、任务失败摘要、JUnit、Allure 附件和 Web 日志 API 统一保留文本原文；
- Dating 图片二进制不得自动附加到 Allure；分析结果文本允许按原文附加；
- 报告下载和日志查看必须校验任务归属；
- 原始日志与报告可能含凭证，必须执行最小权限访问、保留期清理并禁止公开分发；
- 清理命令不得对未解析项目根、仓库根或用户目录执行递归删除。

### 14.2 可靠性

- 项目包静态校验与 Runtime Scope 运行就绪度校验均在发起网络请求前完成；
- 任务启动时固定项目、Runtime Scope、`target_env`、配置 Release 和 Credential Profile 版本元数据；
- 会话写入必须原子化；
- Flow 终止后按规则执行允许的清理步骤；
- 单项目失败不能污染其他项目任务状态；
- Dating 异步任务超时与服务端失败必须区分。

### 14.3 可维护性

- 新项目不得要求复制公共 Python 模块；
- 公共执行引擎不得包含业务项目名称判断；
- 项目差异优先声明式配置；
- 配置 Schema 必须版本化；
- 平台 Runtime Scope/快照契约与工具 Project Manifest/资产 Schema 分别版本化，职责不可交叉；
- 固定环境映射必须由平台与工具双重校验，不允许通过 Web 参数、CLI 参数或旧兼容字段绕过；
- 公共接口和关键隔离逻辑必须有清晰中文注释；
- 项目包必须提供最小 README 或在统一接入文档中登记。

### 14.4 性能

- 一次任务只加载当前项目包，不扫描和解析所有项目用例；
- 项目列表可以扫描项目描述，但不得解析全部 Case/Flow 才能返回；
- 多项目改造不得显著增加单次 Gateway 调用耗时；
- 项目级报告隔离不得改变 pytest 与 Allure 的核心生成机制。

### 14.5 可观测性

所有任务级结构化日志至少包含：

- `task_id`；
- `project_id`；
- `platform_project_id`；
- `platform_environment`；
- `target_env`；
- `runtime_scope_id`；
- `config_release_id/version`；
- `config_source`；
- `run_type`；
- API、Case 或 Flow 标识；
- 阶段、耗时、状态和稳定错误码。

---

## 15. 测试与验收

### 15.1 静态验收

1. 项目注册表可以识别 Truthy 和 Dating；
2. Project Manifest、配置契约、API、Case、Flow 和 Scenario 校验通过，项目包中不存在平台运行配置值；
3. Dating API 定义使用 `GetAnalysisTask`、`GetAnalysisResult`；
4. 仓库扫描不存在真实 Token、COS 签名或 Dating 原始隐私数据；
5. 新增测试项目包可在不修改执行引擎的情况下通过收集。

### 15.2 CLI 验收

1. 使用 `--project truthy --target-env test` 和平台快照显式执行 Truthy 成功；
2. 省略项目仍按 Truthy 执行并提示兼容默认值；
3. 显式执行 Dating 单接口成功；
4. 显式执行 Dating Flow 成功或准确报告外部阻塞；
5. 未知项目、无效 `target_env`、无权限/无效 Scope 和跨目录 Flow 在网络请求前失败；
6. 同名 API 或 Flow 在两个项目中不会串用。

### 15.3 凭证隔离验收

1. 仅配置 Dating 匿名会话凭证时，Dating 任务不提示缺少 Admin 凭证；
2. Truthy 普通用户接口不需要 Admin Profile；
3. Truthy Admin Flow 缺少 Admin Secret 时准确列出缺失键；
4. Truthy Secret 不会被 Dating 读取；
5. 平台配置模式忽略容器残留 `.env`、进程环境变量和项目环境 YAML；
6. 切换项目后 Secret 状态随当前固定环境的 Runtime Scope 刷新；
7. 独立调试模式必须显式启用且不得获取/合并平台快照。

### 15.4 配置唯一真源与 Scope 验收

1. dev 平台上的 Truthy/test 与 Dating/test 使用不同 Runtime Scope、Release 和 Secret/Credential 绑定；
2. 同名配置键在两个 Scope 中不会串值；
3. 平台配置模式缺少 Release 或快照物化失败时 fail-closed，不读取本地旧值；
4. 修改平台配置并发布新 Release 后，新任务使用新版本，历史任务仍展示原快照版本；
5. 平台回滚 Release 后，新任务使用回滚版本且审计记录完整；
6. 工具项目包中不包含 `env/<target_env>.yaml` 运行配置副本；
7. 概览、项目切换和任务预览的内联校验对同一 Scope 返回一致状态；
8. “前往平台配置中心”定位当前 Scope，且无权限用户仍会被平台拒绝；
9. dev 平台提交 prod 接口请求、prod 平台提交 test 接口请求均在网络请求前被拒绝；
10. prod 平台任务只能使用 prod Scope 下的 Gateway、Release、Secret/Credential 和会话。

### 15.5 资产隔离验收

1. Case 不能引用其他项目 API；
2. Flow 不能引用其他项目 Scenario；
3. 上传动作不能读取其他项目 fixture；
4. 路径遍历被拒绝；
5. 运行时变量不会跨任务或项目保留；
6. 一个项目的 Token 刷新不修改另一个项目会话。

### 15.6 任务与报告验收

1. 任务记录包含最终解析后的平台项目、工具项目、`target_env`、Runtime Scope、配置来源和 Release；
2. Web 可按项目筛选任务；
3. 同时运行 Truthy 和 Dating 不覆盖日志或 JUnit；
4. “最新报告”按项目独立计算；
5. 报告、日志和下载链接不能跨项目访问；
6. 历史 Truthy 任务可继续查看。

### 15.7 Truthy 回归验收

- 现有自动化单元测试和集成测试通过；
- 现有单接口收集数量与迁移前一致，除非有经评审的用例调整；
- 现有三个核心 Flow 的步骤、参数、断言和变量保持一致；
- CLI、Jenkins 和平台执行链路至少各完成一次冒烟；
- Admin 与普通会话场景分别验证；
- Allure、JUnit、文件日志、终端和 Web 日志均保留原文，且项目/任务访问隔离无回归。

### 15.8 Dating test 验收

在外部依赖可用时：

1. Identity Flow 通过；
2. 媒体配置、Prepare、COS PUT、Complete 通过；
3. 单图 Analysis 创建、轮询、结果和清理通过；
4. `succeeded`、`rejected`、`failed` 和客户端超时规则至少通过自动化或可控桩验证；
5. `GetAnalysisResult` 只在成功终态后调用；
6. 删除后任务和结果不可访问；
7. 额度查询成功，额度耗尽时可识别 `QUOTA_EXHAUSTED`；
8. 日志和报告不包含图片二进制；签名、Token、Header 和完整分析文本按原文保留，
   且只有具备该任务权限的用户能够访问。

### 15.9 新项目接入验收

使用测试 fixture 项目模拟第三个 Gateway 项目：

1. 工具侧仅新增标准项目包，平台侧仅新增项目绑定、Runtime Scope、Release 和 Secret/Credential 数据；
2. 不修改 Gateway、Case Loader、Flow Runner、TaskManager 的项目业务分支；
3. 不修改测试开发平台项目专属代码；
4. 只有当平台 Scope 与有效项目包同时存在时才出现在项目列表；
5. 可以收集并执行至少一个单接口 Case；
6. 可以收集并执行至少一个两步骤 Flow；
7. 产物进入该项目独立目录。

### 15.10 Web 与平台集成验收

1. 用户从测试开发平台的 `api-autotest` 入口进入由 `Truthy_ApiAutoTest2` 提供的 Web 工具页；
2. 在配置的 Base Path 下，首页、任务记录和任务详情可直接访问并在刷新后正常恢复；
3. 概览、项目切换、单接口任务、Flow 任务、用例库、任务记录和任务详情七类页面均可用，侧栏不存在项目配置或配置异常入口；
4. Dating 用例库展示 11 个首期 API，API、Case 和 Flow 数量与实际项目包一致；
5. “全部”执行类型分别显示将执行的 Case 数和 Flow 数；
6. 任务记录页的“当前项目/全部项目”作用域与侧栏说明、筛选条件和返回结果一致；
7. Flow 预览、执行进度和任务详情的步骤统计口径一致，合并步骤可展开查看；
8. 重试创建关联的新任务，原任务快照与结果不被覆盖；
9. 概览和任务提交区内联展示 Scope/Release/Profile 校验结果，不存在独立配置页面或运行配置编辑入口；
10. 测试资产异常展示仓库相对路径，平台配置异常内联展示 Scope/Release/逻辑键，均不泄漏绝对路径或 Secret；
11. 配置中心深链可以定位当前 Scope，配置修改经发布后才影响新任务；
12. dev 平台页面固定显示“接口环境：TEST”且没有环境切换控件；prod 平台固定显示“接口环境：PROD”；
13. 接口自动化页面、资产、任务 API 和执行业务逻辑位于 `Truthy_ApiAutoTest2`；平台改动归属于通用 Runtime Scope、配置/Secret/Credential 控制面、工具注册、路由和身份能力。

---

## 16. 发布与迁移策略

### 16.1 阶段一：平台通用作用域与快照契约

- 在测试开发平台增加通用 Runtime Scope 及唯一约束；
- 将配置定义、Release/激活、Secret/Credential 与 Scope 绑定；
- 提供授权 Scope 列表、快照规划/物化、发布、回滚和审计 API；
- 明确 `platform_environment` 与 `target_env` 两类字段，并强制 `dev→test`、`prod→prod`；
- 在 `Truthy_ApiAutoTest2` 建立版本化平台快照消费契约和 fail-closed 模式。

退出条件：可以为 Truthy/test 创建 Scope 和 Release，工具在不读取本地配置的情况下取得并校验快照；错误 Scope、Release 和 Credential 可区分。

### 16.2 阶段二：多项目基础与 Truthy 迁移

- 增加项目上下文和项目注册；
- 参数化加载器、CLI、TaskManager 和用例目录；
- 将 Truthy 测试资产迁入标准项目包；
- 将 Truthy 可变运行配置迁入平台 Truthy/test Scope 的首个 Release；
- 保留 Truthy 命令/字段兼容入口，但不保留平台模式本地配置回退；
- 完成 Truthy 全量回归。

退出条件：显式和缺省 Truthy 执行均通过；公共加载器只读取标准项目资产，平台配置模式只读取平台快照。

### 16.3 阶段三：Dating 项目包与配置

- 添加 Dating Project Manifest、API 定义和测试资产；
- 在 dev 平台创建 Dating/test Scope、配置 Release 和 Credential Profile；
- 添加 P0 单接口 Cases；
- 添加身份、媒体和单图 Analysis P0 Flows；
- 完成通用签名上传动作；
- 完成 Dating 配置、隐私和真实链路验证。

退出条件：Dating 不依赖 Truthy 配置或 Admin Secret，核心链路可独立执行。

### 16.4 阶段四：多项目 Web 体验

- 在 `Truthy_ApiAutoTest2` 内增加项目列表、项目选择器及七类 Web 页面状态；
- 在 `Truthy_ApiAutoTest2` 内扩展任务提交、任务展示、目录、运行前校验和报告接口；
- 完成项目级 Scope/Release/Profile 状态、报告和日志隔离；
- 删除原“项目配置/配置异常”界面和侧栏入口，在概览与任务提交区提供内联校验和平台配置中心深链；
- 完成 Web Base Path 适配及浏览器刷新、深链接验证；
- 在测试开发平台完成工具注册、路由代理、身份和 Runtime Scope 上下文对接；
- 更新 Jenkins 的项目参数传递。

退出条件：用户可在一个 `api-autotest` 工具页面中独立执行和查看 Truthy、Dating。

### 16.5 阶段五：扩展验收

- 补充 P1 Dating 边界与异常场景；
- 使用第三个 fixture 项目验证零引擎修改接入；
- 输出新项目接入说明；
- 清理仅用于迁移的临时兼容代码。

---

## 17. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| Truthy 资产迁移导致路径失效 | CLI、测试、Jenkins 或报告失败 | 一次迁移所有调用点，保留命令级兼容，并执行完整回归 |
| 公共引擎继续出现项目硬编码 | 第三个项目仍需改代码 | 代码评审检查项目名判断，使用 fixture 项目做扩展验收 |
| 平台与工具继续各存一份运行配置 | 值漂移、任务不可复现、维护责任不清 | 平台配置模式删除项目环境 YAML 路径、本地回退和工具配置页面，发布检查扫描重复配置 |
| 平台现有配置模型缺少项目/被测环境作用域 | Truthy 与 Dating 同名配置、Secret 或 Credential 串用 | 一次性增加通用 Runtime Scope，并将 Release/Secret/Credential 绑定 Scope，不使用键名前缀或伪 Tool ID |
| Secret 显示可用但运行时未下发 | 任务错误提示缺少凭证 | 将可用状态定义为当前 Scope/Profile 的端到端可解析状态 |
| Dating 原资料仍使用 staging 名称 | 环境选择和配置归属错误 | PRD 与实现统一按 test；保留原资料名仅用于追溯，不创建该旧名称的 Scope 或别名 |
| dev 平台误调用 prod 接口 | 线上数据、安全和成本风险 | 平台和工具同时校验固定环境映射，Web 不提供环境切换，非法组合在网络请求前失败 |
| Dating 额度或异步 Worker 不稳定 | 真实 E2E 偶发失败 | 区分框架测试、契约测试和真实集成标签，报告外部阻塞原因 |
| 原始日志中的 Token/COS 签名被越权读取 | 凭证与隐私风险 | 按确认需求保留文本原文；通过任务归属/RBAC、最小暴露面、7 天日志清理和禁止公开分发控制风险；图片二进制仍不附加 |
| 并发任务共享会话 | Token 覆盖或身份串用 | 会话按 Scope、Profile 和授权主体隔离，写入原子化 |
| 项目越来越多导致页面混乱 | 选择和定位成本上升 | 项目列表、任务、报告均支持项目筛选，后续增加分组而非复制工具 |
| 双目录长期存在 | 维护两套加载逻辑 | Truthy 一次迁移，兼容层只补项目 ID，不保留旧资产加载器 |
| Web 业务逻辑进入测试开发平台 | 形成两套页面和任务逻辑，后续项目接入需双改 | 以第 6.7 节职责表约束：平台保留通用配置中心，工具保留接口自动化业务页面和任务逻辑 |
| 本机调试被误认为平台配置 | 本机“能跑”但平台任务失败，或残留 `.env` 掩盖缺项 | 配置来源显式、互斥并写入任务；平台模式 fail-closed，LOCAL 状态醒目标识且不从平台入口开放 |
| 平台挂载路径与本地根路径不一致 | 静态资源、刷新或报告链接 404 | 所有前端路由和链接统一使用可配置 Base Path，并纳入集成验收 |

---

## 18. 交付物

本需求完成后的产品交付物包括：

- 通用多项目执行能力；
- Truthy 标准项目包；
- Dating test 首期项目包；
- 项目选择 CLI；
- `Truthy_ApiAutoTest2` 内的多项目 Web 页面、页面业务 API 与任务能力；
- 测试开发平台通用 Runtime Scope 数据模型/API，以及配置 Release、Secret/Credential 的 Scope 绑定与迁移；
- 测试开发平台的 `api-autotest` 入口、路由、身份、配置中心和运行时快照对接；
- 概览与任务提交区的内联运行前校验及平台配置中心深链；
- 项目级配置 Release、Secret、会话、日志和报告隔离；
- 通用签名上传动作；
- Truthy 回归测试；
- Dating 单接口和 Flow 测试；
- 多项目隔离与第三项目扩展测试；
- 新项目接入说明；
- 对应详细开发设计与实施计划。

---

## 19. Definition of Done

只有同时满足以下条件，才能认为本需求完成：

- [ ] 所有 P0 功能需求实现；
- [ ] Truthy 与 Dating 均作为标准项目包运行；
- [ ] CLI、Web、平台任务和 Jenkins 均能传递/固化 `project_id + target_env`，并记录授权 Runtime Scope；
- [ ] Web 的七类页面和相关业务 API 均在 `Truthy_ApiAutoTest2` 内实现，测试开发平台未形成重复实现；
- [ ] 平台通用 Runtime Scope、Release、Secret/Credential 作用域化和快照 API 完成，dev 平台上的 Truthy/test 与 Dating/test 不串值；
- [ ] 平台入口、Base Path、刷新、统一身份、配置中心深链和运行时快照联调通过；
- [ ] 平台配置模式只读取平台快照且 fail-closed，不读取项目环境 YAML、本地 `.env` 或进程环境变量回退；
- [ ] 工具不存在“项目配置/配置状态/配置异常”独立页面或侧栏入口，平台是唯一可编辑运行配置入口；
- [ ] dev 平台只执行 test 接口，prod 平台只执行 prod 接口，Web 不提供跨环境切换且非法组合均被拒绝；
- [ ] Project Manifest 只保存配置契约，工具仓库不存在平台运行配置副本；
- [ ] Dating 用例库展示的 11 个 API 及 API/Case/Flow 数量与项目包一致；
- [ ] “全部”执行统计、Flow 步骤统计、任务列表作用域和重试语义均符合第 11 章要求；
- [ ] Dating 不再错误依赖 Truthy Admin 凭证；
- [ ] 单接口、多接口 Flow、会话和签名上传能力在项目上下文中工作；
- [ ] 配置 Release、Secret/Credential、会话、素材、任务、日志和报告隔离测试通过；
- [ ] Truthy 回归无未解释失败；
- [ ] Dating P0 test 链路完成真实验证，或对不可控外部阻塞留下可复现证据；
- [ ] 原始日志契约测试通过：请求/响应/Header/Token/签名 URL/异常不被改写，
  图片二进制不落盘，Web/报告访问仍受任务归属与 RBAC 约束；
- [ ] 第三个 fixture 项目只新增工具项目包和平台 Scope/Release 数据，无需修改公共引擎或平台代码即可执行；
- [ ] 开发设计、实施计划和新项目接入说明与最终实现一致。

---

## 20. 后续文档

本 PRD 评审通过后，应继续输出：

1. 《Gateway 通用接口自动化多项目支持与 Dating 接入详细开发设计》；
2. 《Gateway 通用接口自动化多项目支持与 Dating 接入实施计划》；
3. 《Gateway 接口自动化新项目接入指南》；
4. Runtime Scope、配置快照、Project Manifest、任务接口及迁移映射说明。

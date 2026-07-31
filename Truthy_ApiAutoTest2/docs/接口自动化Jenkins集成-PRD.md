# Gateway 接口自动化 Jenkins 集成 PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 能力版本 | Jenkins 集成 J1.0 |
| 项目基线 | Gateway 接口自动化 V1.3 + Allure 报告 R1.0 |
| 日期 | 2026-07-31 |
| 技术栈 | Jenkins Pipeline + Python + pytest + Allure 3 |
| 核心目标 | 通过 Jenkins 手动或定时执行接口自动化，并集中展示 JUnit、Allure 和运行日志 |
| 文档状态 | 待 Review |

## 2. 背景

当前接口自动化项目已经具备：

- 单接口 YAML 数据驱动执行。
- Flow YAML 多接口流程编排。
- 接口间数据提取和引用。
- 自动会话创建及刷新。
- 请求、响应和耗时日志。
- 日志敏感字段脱敏。
- pytest 统一执行入口。
- JUnit XML 生成能力。
- Allure Pytest 原始结果生成能力。
- 单接口与 Flow 的 Allure 标题、层级、步骤和脱敏附件。

当前项目已经存在基础 `Jenkinsfile`，支持：

- `all`、`single`、`flow` 三种运行方式。
- 手动参数化构建。
- 每天定时构建。
- JUnit 结果发布。
- 日志归档。

但是，现有 `Jenkinsfile` 尚未向 pytest 传入 `--alluredir`，也没有在 Jenkins 构建完成后发布 Allure 报告。因此当前 Jenkins 集成即使能够执行测试，也只能看到 JUnit 和日志，无法看到已经开发完成的 Allure 结构化报告。

## 3. Allure 对 Jenkins 的影响结论

Allure 不改变接口请求、Flow 编排、断言或 pytest 退出码，只影响 Jenkins 的报告生成和展示环节。

需要增加的 Jenkins 能力：

1. 测试执行时生成 `allure-results`。
2. Jenkins 构建结束后根据 `allure-results` 生成并发布 Allure 报告。
3. Jenkins 构建节点能够执行 Allure 3 CLI。
4. Jenkins 安装并启用 Allure Report 插件时，可在构建页面直接查看报告。
5. Allure 原始结果需要设置合理的归档和保留策略。

保持不变的能力：

- pytest 仍然是唯一测试执行器。
- pytest 退出码仍然决定 Jenkins 构建成功或失败。
- JUnit 继续保留，用于 Jenkins 原生测试统计。
- 日志继续用于查看完整请求和响应。
- Allure 只负责更直观地展示用例、步骤、附件和失败信息。

## 4. 用户与使用场景

### 4.1 目标用户

- 接口自动化测试开发人员。
- 负责手动回归和定时回归的测试人员。
- 需要查看测试结果但不直接阅读代码的项目成员。
- 需要定位单接口或 Flow 失败步骤的开发人员。

### 4.2 核心使用场景

1. 在 Jenkins 页面选择参数并手动运行全部接口测试。
2. 只运行全部单接口测试。
3. 运行全部 Flow。
4. 指定一个 Flow 进行调试。
5. 每天自动执行全部接口测试。
6. 在 Jenkins 页面查看用例通过、失败、跳过和耗时。
7. 在 Allure 报告中查看单接口请求、响应和断言结果。
8. 在 Allure 报告中按顺序查看 Flow 每个步骤。
9. 测试失败时下载日志或 Allure 原始结果进一步排查。

## 5. 产品目标

### 5.1 核心目标

1. 新建独立 Jenkins Pipeline，不修改已有 Jenkins 任务。
2. 支持手动参数化构建。
3. 支持每天定时构建。
4. 支持单接口、Flow 和全部接口三种运行范围。
5. 支持指定单个 Flow。
6. 每次接口测试同时生成 JUnit 和 Allure 结果。
7. Jenkins 页面能够查看 Allure 报告入口。
8. 每次构建能够查看或下载运行日志。
9. 测试失败时 Jenkins 构建必须标记为失败。
10. 报告和日志不得泄露 token、签名 URL 或 `.env` 内容。

### 5.2 成功标准

- Jenkins 可以从 Git 仓库读取项目 `Jenkinsfile`。
- Jenkins 节点可以创建 Python 虚拟环境并安装依赖。
- Jenkins 节点可以访问测试 Gateway。
- 手动构建可以选择 `all`、`single` 或 `flow`。
- 定时构建默认执行 `all`。
- pytest 成功生成 JUnit XML。
- pytest 成功生成非空 `allure-results`。
- Jenkins 成功发布 Allure 3 报告。
- Allure 中可以看到单接口和 Flow 的业务名称。
- Flow 报告中可以看到有序步骤和脱敏附件。
- JUnit、Allure 和日志均与同一次构建对应。
- 不操作或影响任何已有 Jenkins 任务。

## 6. 范围

### 6.1 J1.0 包含

- 使用独立 Jenkins Pipeline 任务。
- 从 Git `dev` 分支加载项目代码。
- Jenkins 参数化构建。
- 每日定时构建。
- Python 虚拟环境准备。
- Python 依赖安装。
- `all`、`single`、`flow` 执行模式。
- 指定 Flow 执行。
- JUnit XML 生成和发布。
- Allure 原始结果生成。
- Jenkins Allure 3 报告发布。
- 请求与响应日志归档。
- 构建记录和产物保留策略。
- 同一任务禁止并发构建。
- Jenkins 节点和 Allure CLI 运行条件检查。

### 6.2 J1.0 不包含

- 修改、复制或触发已有 Jenkins 任务。
- Jenkins 多节点并行执行。
- 多环境并行执行。
- 单接口 Case 下拉选择。
- Allure 跨构建历史趋势。
- Allure 重试趋势。
- Allure TestOps。
- 飞书、邮件、Slack 等通知。
- 自动创建缺失的 Jenkins 插件。
- 自动修改 Jenkins 全局工具和系统 PATH。
- 自动升级 Jenkins、插件、Node.js 或 Allure CLI。
- Web 测试平台接入。

## 7. 当前状态与差距

| 能力 | 当前状态 | J1.0 要求 |
| --- | --- | --- |
| Pipeline 定义 | 已有 `Jenkinsfile` | 保留并补充 Allure |
| 手动参数 | 已支持 | 保持 |
| 每日定时 | 已配置 | 保持 |
| 单接口执行 | 已支持 | 保持 |
| Flow 执行 | 已支持 | 保持 |
| JUnit | 已生成和发布 | 保持 |
| 日志归档 | 已支持 | 保持 |
| `allure-pytest` | 已加入依赖 | 保持 |
| Allure 元数据和步骤 | 已完成 | 保持 |
| Allure 脱敏附件 | 已完成 | 保持 |
| `allure-results` | Jenkins 尚未生成 | 必须生成 |
| Jenkins Allure 报告 | 尚未发布 | 必须发布 |
| Jenkins Allure 插件 | 尚待确认 | 使用前必须确认 |
| Jenkins 节点 Allure 3 CLI | 尚待确认 | 使用前必须确认 |

## 8. Jenkins 任务需求

### 8.1 任务隔离

| 编号 | 需求 |
| --- | --- |
| JEN-001 | 必须创建独立 Jenkins 任务 |
| JEN-002 | 不得复制已有任务作为模板 |
| JEN-003 | 不得修改已有任务的配置、凭据、工作空间或触发器 |
| JEN-004 | 新任务名称存在冲突时必须停止创建 |
| JEN-005 | 新任务必须使用独立工作空间 |
| JEN-006 | 新任务不得配置已有任务为上游或下游 |

建议任务名称：

```text
truthy-api-autotest
```

### 8.2 SCM 配置

| 配置项 | 需求值 |
| --- | --- |
| Definition | Pipeline script from SCM |
| SCM | Git |
| Repository URL | `https://github.com/Lnyy-CZJ/Testproject.git` |
| Branch Specifier | `*/dev` |
| Script Path | `Truthy_ApiAutoTest2/Jenkinsfile` |

私有仓库必须通过 Jenkins Credentials 绑定 Git 凭据，不允许把 Token 写入 URL 或 Jenkinsfile。

## 9. 构建参数需求

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `ENVIRONMENT` | Choice | `test` | 运行环境 |
| `RUN_TYPE` | Choice | `all` | 运行全部、单接口或 Flow |
| `FLOW` | String | 空 | 指定 Flow 文件名，不含 `.yaml` |

### 9.1 参数规则

| RUN_TYPE | FLOW | 预期执行范围 |
| --- | --- | --- |
| `single` | 任意 | 全部单接口，忽略 FLOW |
| `flow` | 空 | 全部 Flow |
| `flow` | 指定值 | 指定 Flow |
| `all` | 空 | 全部单接口和全部 Flow |
| `all` | 指定值 | 全部单接口和指定 Flow |

### 9.2 默认收集要求

提交 Jenkins 使用的代码必须满足：

```python
RUN_CASE_IDS: tuple[str, ...] = ()
RUN_FLOW_IDS: tuple[str, ...] = ()
```

本地调试时可以临时选择 Case 或 Flow，但进入 Jenkins 的版本不得固化本地调试筛选。

## 10. 构建流程需求

### 10.1 总体流程

```text
拉取 Git 代码
    ↓
准备 Python 虚拟环境
    ↓
安装 requirements.txt
    ↓
清理本次旧报告目录
    ↓
根据 RUN_TYPE 执行 pytest
    ↓
生成 JUnit XML
    ↓
生成 allure-results
    ↓
pytest 退出并确定构建状态
    ↓
发布 JUnit
    ↓
发布 Allure 报告
    ↓
归档日志和必要结果
```

### 10.2 环境准备

| 编号 | 需求 |
| --- | --- |
| ENV-001 | Jenkins 节点必须存在 `python3` |
| ENV-002 | Python 必须支持 `venv` 和 `pip` |
| ENV-003 | 必须使用项目 `.venv` 安装依赖 |
| ENV-004 | 必须使用 `requirements.txt` 安装 `allure-pytest` |
| ENV-005 | Jenkins 节点必须可以访问 Git 仓库 |
| ENV-006 | Jenkins 节点必须可以访问测试 Gateway |
| ENV-007 | Python 环境准备失败时不得继续发送接口请求 |

### 10.3 报告目录清理

每次构建开始前必须清理：

```text
reports/junit*.xml
allure-results/
```

清理只允许发生在当前任务的独立工作空间内。

不允许清理：

- 其他 Jenkins 任务工作空间。
- 项目 `.env`。
- 当前日志保留周期内的 `logs/YYYY-MM-DD`。
- Jenkins 全局目录。

## 11. 测试执行需求

### 11.1 通用要求

| 编号 | 需求 |
| --- | --- |
| RUN-001 | pytest 必须是唯一测试执行器 |
| RUN-002 | pytest 退出码必须决定 Jenkins 构建结果 |
| RUN-003 | 所有模式必须生成 JUnit XML |
| RUN-004 | 所有模式必须生成 Allure 原始结果 |
| RUN-005 | 所有模式必须启用 `--allure-no-capture` |
| RUN-006 | 构建开始时必须使用 `--clean-alluredir` |
| RUN-007 | Console Output 必须保留请求、响应和失败日志 |
| RUN-008 | 不得执行与真实接口入口无关的框架单元测试 |

### 11.2 pytest Allure 参数

所有真实接口执行命令必须包含：

```text
--alluredir=allure-results
--clean-alluredir
--allure-no-capture
```

原因：

- `--alluredir` 生成 Jenkins 发布所需的原始结果。
- `--clean-alluredir` 防止当前构建混入历史结果。
- `--allure-no-capture` 避免 stdout、stderr 和日志作为重复附件写入报告。

### 11.3 JUnit 与 Allure 分工

| 报告 | 主要用途 |
| --- | --- |
| JUnit | Jenkins 原生测试数量、失败状态和趋势基础 |
| Allure | 业务层级、Flow 步骤、请求响应附件和详细诊断 |
| 日志 | 完整运行过程、网络异常和深度排查 |

JUnit 和 Allure 必须同时保留，不以 Allure 替换 JUnit。

## 12. Allure Jenkins 发布需求

### 12.1 插件要求

| 编号 | 需求 |
| --- | --- |
| ALJ-001 | 发布前必须确认 Jenkins 已安装 Allure Report 插件 |
| ALJ-002 | 未安装插件时不得自动安装，必须先获得用户确认 |
| ALJ-003 | 插件安装或升级不得影响正在运行的其他任务 |
| ALJ-004 | 需要重启 Jenkins 时必须提前确认无构建正在运行 |

### 12.2 Allure 3 CLI 要求

当前项目使用 Allure 3。Jenkins 构建节点必须满足：

```bash
allure --version
```

能够正常返回版本。

要求：

| 编号 | 需求 |
| --- | --- |
| ALC-001 | Jenkins 服务用户的 PATH 中必须存在 `allure` |
| ALC-002 | 不得假设本地终端的 npm PATH 会自动传给 Jenkins |
| ALC-003 | Allure CLI 缺失时，测试仍应先保留 JUnit 和原始结果 |
| ALC-004 | 安装或修改 Jenkins 节点 PATH 前必须获得用户确认 |
| ALC-005 | Allure CLI 版本必须固定并记录 |

当前本地使用的 Allure 3 CLI 安装路径只能作为参考，Jenkins 服务进程是否可见必须重新验证。

### 12.3 报告发布

Jenkins 应使用 Allure 3 模式读取：

```text
Truthy_ApiAutoTest2/allure-results
```

发布要求：

- 无论 pytest 成功或失败，都尝试发布报告。
- `allure-results` 为空时不得覆盖测试阶段原始错误。
- Allure 报告入口应显示在当前构建页面。
- 报告必须只读取当前任务工作空间结果。
- 不合并其他 Jenkins 任务的结果。

## 13. 定时执行需求

当前定时策略：

```groovy
cron('TZ=Asia/Shanghai\nH 2 * * *')
```

需求：

| 编号 | 需求 |
| --- | --- |
| SCH-001 | 每天北京时间凌晨 2 点所在小时自动执行 |
| SCH-002 | 具体分钟由 Jenkins `H` 自动分配 |
| SCH-003 | 定时构建使用 `ENVIRONMENT=test` |
| SCH-004 | 定时构建使用 `RUN_TYPE=all` |
| SCH-005 | 定时构建的 `FLOW` 默认为空 |
| SCH-006 | 首次手动构建后必须确认定时器已加载 |
| SCH-007 | 定时构建必须生成 JUnit、Allure 和日志 |

## 14. 日志与产物需求

### 14.1 产物目录

```text
Truthy_ApiAutoTest2/
├── reports/
│   └── junit-*.xml
├── allure-results/
├── allure-report/       # Jenkins 插件发布时不要求项目主动生成
└── logs/
    └── YYYY-MM-DD/
        └── *.log
```

### 14.2 归档要求

| 编号 | 需求 |
| --- | --- |
| ART-001 | JUnit XML 由 Jenkins JUnit 功能发布 |
| ART-002 | Allure 结果由 Jenkins Allure 功能发布 |
| ART-003 | `logs/**/*` 必须归档 |
| ART-004 | `allure-results/**/*` 可归档用于报告恢复和问题排查 |
| ART-005 | `.env` 不得归档 |
| ART-006 | `.venv` 不得归档 |
| ART-007 | `allure-report` 静态目录不重复归档，除非 Jenkins 插件方案不可用 |

### 14.3 保留策略

| 产物 | 默认保留 |
| --- | --- |
| Jenkins 构建记录 | 最近 15 次 |
| Jenkins 归档产物 | 最近 7 次构建 |
| 项目日志目录 | 超过 7 天自动清理 |

Allure 原始结果可能包含大量 JSON 和附件，必须跟随 Jenkins 归档保留策略，避免无限增长。

## 15. 并发与会话需求

| 编号 | 需求 |
| --- | --- |
| CON-001 | 同一 Jenkins 任务必须禁止并发构建 |
| CON-002 | 不允许两个构建同时写入 `.env` |
| CON-003 | 不允许两个构建同时清理 `allure-results` |
| CON-004 | 工作空间被删除后允许框架重新创建匿名会话 |
| CON-005 | 不清理工作空间时允许复用有效会话 |

Allure 增加了结果目录清理操作，因此禁止并发比只使用 JUnit 时更重要。

## 16. 安全需求

| 编号 | 需求 |
| --- | --- |
| SEC-001 | Jenkins 登录密码不得写入代码、文档或构建参数 |
| SEC-002 | Git 和业务凭据必须保存在 Jenkins Credentials |
| SEC-003 | Allure 请求和响应附件必须复用现有脱敏规则 |
| SEC-004 | token、refresh token、Authorization 必须显示为 `***` |
| SEC-005 | 预签名 URL 查询参数必须脱敏 |
| SEC-006 | `.env`、媒体文件二进制和完整运行时上下文不得进入报告 |
| SEC-007 | Allure 原始结果不得公开对外分享 |
| SEC-008 | Jenkins 日志和归档访问权限不得高于任务访问权限 |
| SEC-009 | 安装 Jenkins 插件或修改节点环境必须单独确认 |

## 17. 构建结果规则

| 场景 | Jenkins 结果 |
| --- | --- |
| pytest 全部通过，报告发布成功 | SUCCESS |
| pytest 存在失败用例 | FAILURE |
| pytest 收集失败 | FAILURE |
| Python 环境准备失败 | FAILURE |
| Gateway 无法连接 | FAILURE |
| pytest 通过但 Allure 发布失败 | UNSTABLE，保留测试已通过的事实并提示报告异常 |
| JUnit 发布失败 | FAILURE |
| 日志归档为空 | 不覆盖 pytest 原始状态 |

产品优先级：

1. 测试结果正确。
2. JUnit 可用。
3. Allure 可用。
4. 日志可下载。

报告发布失败不得把真实测试失败误标记为成功。

## 18. 验收场景

### 18.1 单接口构建

输入：

```text
ENVIRONMENT=test
RUN_TYPE=single
FLOW=
```

验收：

- 收集全部单接口 Case。
- 生成 JUnit。
- 生成 Allure 原始结果。
- Allure 中每个 Case 是独立测试。
- 请求与响应附件已脱敏。

### 18.2 指定 Flow 构建

输入：

```text
ENVIRONMENT=test
RUN_TYPE=flow
FLOW=AnonymousSessionMediaSearch
```

验收：

- 只执行指定 Flow。
- Allure 中显示 Flow 业务名称。
- 每个 Flow 步骤按顺序展示。
- 提取、轮询和接口调用步骤可以定位。
- 失败步骤状态明确。

### 18.3 全部接口构建

输入：

```text
ENVIRONMENT=test
RUN_TYPE=all
FLOW=
```

验收：

- 收集全部单接口和全部 Flow。
- JUnit 与 Allure 用例数量一致。
- 任一用例失败时 Jenkins 构建失败。
- 日志和 Allure 报告均属于当前构建。

### 18.4 定时构建

验收：

- Jenkins 自动触发构建。
- 使用默认参数执行全部接口。
- 构建结束后可查看 JUnit、Allure 和日志。
- 没有与手动构建并发执行。

### 18.5 报告失败场景

人为使 Jenkins 节点找不到 Allure CLI：

- pytest 和 JUnit 结果仍然保留。
- Jenkins 明确显示 Allure 发布失败。
- Console Output 能定位为 CLI 或 PATH 问题。
- 不把报告失败误判为接口断言失败。

## 19. 非功能需求

### 19.1 简洁性

- 复用现有 `Jenkinsfile`。
- 不新增 Python Jenkins 工具类。
- 不新增报告生成 Shell 文件。
- 不引入 Jenkins Shared Library。
- 不引入 Docker。
- 不新增 `package.json`。

### 19.2 可维护性

- Pipeline 参数集中定义。
- JUnit、Allure 和日志目录命名固定。
- Allure 版本明确记录。
- Jenkinsfile 使用中文注释说明关键步骤。
- Jenkins 页面不保存大段重复 Shell 逻辑。

### 19.3 可诊断性

- 环境准备、测试执行和报告发布阶段可以区分。
- Allure CLI 不可用时输出明确错误。
- Flow 失败可以定位到具体步骤。
- 网络错误可以通过日志和脱敏附件定位。

## 20. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| Jenkins 未安装 Allure 插件 | 无法在构建页展示报告 | 先确认插件，安装需单独授权 |
| Jenkins 服务用户找不到 Allure CLI | 报告发布失败 | 在节点上验证 `allure --version` 和 PATH |
| Jenkins 插件与 Allure 3 配置错误 | 报告无法生成 | 使用 Allure 3 发布模式验证 |
| `allure-results` 未清理 | 混入旧构建结果 | 每次构建使用 `--clean-alluredir` |
| 并发构建同时清理结果 | 报告损坏 | 保持 `disableConcurrentBuilds()` |
| Allure 附件增大磁盘占用 | Jenkins 磁盘增长 | 限制归档为最近 7 次构建 |
| Allure 发布失败覆盖测试结论 | 状态判断不准确 | pytest 退出码优先，区分报告失败 |
| 报告包含敏感信息 | 凭据泄露 | 复用脱敏逻辑并增加报告扫描验收 |
| Jenkins Controller 执行构建 | 存在运行隔离风险 | J1.0 可先验证，后续迁移独立 Agent |

## 21. 依赖与前置条件

- Allure R1.0 项目回归测试通过。
- `requirements.txt` 包含 `allure-pytest`。
- 单接口和 Flow 默认收集筛选为空。
- Jenkins 节点具备 Python、pip 和 venv。
- Jenkins 节点可以访问 Git 和 Gateway。
- Jenkins Allure Report 插件状态已确认。
- Jenkins 服务用户可以执行 Allure 3 CLI。
- 用户确认后才创建独立 Jenkins 任务。
- 用户确认后才安装插件或修改 Jenkins 节点环境。

## 22. 验收标准

- [ ] 未修改任何已有 Jenkins 任务。
- [ ] 新建独立接口自动化 Pipeline。
- [ ] Git SCM 和 Script Path 配置正确。
- [ ] 手动 `single` 构建符合预期。
- [ ] 手动指定 Flow 构建符合预期。
- [ ] 手动 `all` 构建符合预期。
- [ ] 每日定时构建已加载。
- [ ] JUnit 发布成功。
- [ ] Allure 3 报告发布成功。
- [ ] Allure 中存在单接口业务层级。
- [ ] Allure 中存在 Flow 有序步骤。
- [ ] Allure 请求和响应附件已脱敏。
- [ ] 日志归档成功。
- [ ] `.env` 和 `.venv` 未归档。
- [ ] 构建和产物保留策略生效。
- [ ] 报告失败与测试失败可以区分。

## 23. 后续版本

J1.0 稳定后可考虑：

- Allure 历史趋势。
- 失败用例重试展示。
- 飞书构建结果通知。
- 按单接口 Case 参数化运行。
- 独立 Jenkins Agent。
- 多环境执行。
- 定时任务失败自动通知。

以上能力不进入本期，避免首次 Jenkins 接入过度复杂。

## 24. 参考资料

- [Allure Jenkins 集成](https://allurereport.org/docs/integrations-jenkins/)
- [Allure 3 安装](https://allurereport.org/docs/v3/install/)
- [Allure 工作原理](https://allurereport.org/docs/how-it-works/)
- `docs/接口自动化Allure报告接入-PRD.md`
- `docs/Jenkins集成-开发设计与开发计划.md`

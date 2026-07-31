# Jenkins 集成开发设计与开发计划

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档版本 | J1.0 |
| 编写日期 | 2026-07-31 |
| 需求依据 | `docs/接口自动化Jenkins集成-PRD.md` |
| 项目基线 | Gateway 接口自动化 V1.3 + Allure 报告 R1.0 |
| 技术栈 | Jenkins Pipeline + Python + pytest + JUnit + Allure 3 |
| 默认分支 | `dev` |
| 文档状态 | 待 Review |

## 2. 设计目标

在不改变现有接口自动化执行协议、不影响 Jenkins 已有任务的前提下，新增一个独立 Jenkins Pipeline，实现：

1. 手动参数化执行单接口、Flow 或全部接口测试。
2. 每天定时执行全部接口测试。
3. 使用 pytest 退出码决定 Jenkins 构建结果。
4. 使用 JUnit 展示 Jenkins 原生测试统计。
5. 使用 Allure 3 展示业务层级、Flow 步骤及脱敏附件。
6. 归档日期日志，保留完整请求和响应诊断信息。
7. 隔离任务工作空间、会话文件和报告目录。

## 3. 设计原则

### 3.1 最小接入

- 复用现有 `Jenkinsfile`。
- 复用 `runtest.py` 和两个真实接口 pytest 入口。
- 复用现有日志、脱敏和 Allure Reporter。
- 不新增 Jenkins Python 工具类。
- 不新增独立 Shell 脚本。
- 不引入 Docker、Shared Library 或新的构建框架。

### 3.2 结果职责分离

```text
pytest 退出码 ── 决定构建成功或失败
JUnit XML    ── Jenkins 原生用例统计
Allure       ── 业务层级、步骤和诊断附件
日期日志      ── 完整运行过程和深度排查
```

Allure 不替代 JUnit，报告发布失败也不能把真实接口失败误标记为成功。

### 3.3 任务隔离

- 只创建新的接口自动化任务。
- 不复制、修改、触发、删除或重命名已有任务。
- 不引用已有任务工作空间。
- 不设置已有任务为上游或下游。
- 所有清理操作只作用于新任务自己的工作空间。

### 3.4 安全优先

- Jenkins 登录信息不写入项目。
- Git 和业务凭据使用 Jenkins Credentials。
- `.env` 不提交、不归档、不主动输出。
- Allure 附件和文件日志继续复用现有脱敏逻辑。
- 安装插件、修改节点 PATH 或重启 Jenkins 必须单独确认。

## 4. 当前实现状态

### 4.1 项目侧

| 能力 | 当前状态 |
| --- | --- |
| 单接口入口 | 已完成 |
| Flow 入口 | 已完成 |
| `RUN_CASE_IDS` 默认全量收集 | 已为空 |
| `RUN_FLOW_IDS` 默认全量收集 | 已为空 |
| 日志分层与 7 天清理 | 已完成 |
| `allure-pytest` 依赖 | 已接入 |
| 单接口 Allure 元数据 | 已接入 |
| Flow Allure 元数据和步骤 | 已接入 |
| POST/PUT 脱敏附件 | 已接入 |
| `allure-results` Git 忽略 | 已配置 |
| 本地 Allure 3 使用说明 | 已补充 |

### 4.2 Jenkinsfile

当前 `Jenkinsfile` 已包含：

- `ENVIRONMENT`、`RUN_TYPE`、`FLOW` 参数。
- 每天北京时间凌晨 2 点所在小时定时执行。
- Python 虚拟环境和依赖安装。
- `single`、`flow`、`all` 三种执行分支。
- JUnit XML 生成和发布。
- 日期日志归档。
- 禁止同一任务并发构建。
- 构建记录和产物保留策略。

当前缺口：

- pytest 命令尚未生成 `allure-results`。
- 构建后尚未发布 Jenkins Allure 报告。
- 尚未归档 Allure 原始结果。
- 尚未验证 Jenkins Allure Report 插件。
- 尚未验证 Jenkins 服务用户能否执行 Allure 3 CLI。

### 4.3 Jenkins 环境

已确认：

- 当前账号具备新建、配置和执行 Pipeline 的权限。
- Pipeline、Git、Credentials、Credentials Binding 和 JUnit 插件可用。
- 当前 macOS Apple Silicon 构建节点在线。

待确认：

- Allure Report 插件是否已安装。
- Jenkins 服务用户的 PATH 是否包含 `allure`。
- 构建节点是否能够执行 `python3`、`venv` 和 `pip`。
- 构建节点是否能够访问 Git 仓库和测试 Gateway。

## 5. 总体架构

```text
Git 仓库 dev 分支
        ↓
独立 Jenkins Pipeline
        ↓
读取 Truthy_ApiAutoTest2/Jenkinsfile
        ↓
准备 .venv 并安装 requirements.txt
        ↓
清理当前构建旧报告
        ↓
按参数运行 pytest
        ↓
┌──────────────┬───────────────┬──────────────┐
│ JUnit XML    │ allure-results│ logs/日期目录 │
└──────────────┴───────────────┴──────────────┘
        ↓
Jenkins 发布 JUnit、Allure 并归档日志
```

数据只在当前 Pipeline 工作空间和当前构建产物之间流转，不读取其他任务的数据。

## 6. Jenkins 任务设计

### 6.1 基础配置

| 配置项 | 设计值 |
| --- | --- |
| 建议任务名称 | `truthy-api-autotest` |
| 任务类型 | Pipeline |
| Definition | Pipeline script from SCM |
| SCM | Git |
| 仓库地址 | `https://github.com/Lnyy-CZJ/Testproject.git` |
| 分支 | `*/dev` |
| Script Path | `Truthy_ApiAutoTest2/Jenkinsfile` |
| 工作空间 | Jenkins 为新任务独立分配 |

创建前必须检查任务名称是否存在。若存在同名任务，应停止并重新确认名称，不能覆盖。

### 6.2 Git 凭据

- 公开仓库不配置凭据。
- 私有仓库使用 Jenkins Credentials 中的 GitHub Token 或 SSH 私钥。
- 不把 Token 放入仓库 URL。
- 不复用或修改其他任务的凭据绑定配置。

## 7. Pipeline 参数设计

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `ENVIRONMENT` | Choice | `test` | 接口自动化运行环境 |
| `RUN_TYPE` | Choice | `all` | `all`、`single` 或 `flow` |
| `FLOW` | String | 空 | 指定 Flow 文件名 stem，留空执行全部 Flow |

### 7.1 参数执行矩阵

| RUN_TYPE | FLOW | 执行范围 |
| --- | --- | --- |
| `single` | 任意 | 全部单接口，忽略 FLOW |
| `flow` | 空 | 全部 Flow |
| `flow` | 指定值 | 指定 Flow |
| `all` | 空 | 全部单接口和全部 Flow |
| `all` | 指定值 | 全部单接口和指定 Flow |

### 7.2 参数校验

- `RUN_TYPE` 由 Choice 限制，Shell 中仍保留非法值保护。
- `FLOW` 由现有 Flow Loader 校验。
- 不存在的 Flow 在发送请求前失败。
- 当前只有 `test` 环境，新增环境 YAML 后再扩展 `ENVIRONMENT`。

## 8. Pipeline 选项设计

### 8.1 禁止并发

继续使用：

```groovy
disableConcurrentBuilds()
```

防止：

- 两个构建同时写 `.env`。
- 两个构建同时清理 `allure-results`。
- 两个构建同时写日期日志。
- 同一测试账号产生并发会话或业务数据冲突。

### 8.2 保留策略

继续使用：

```groovy
buildDiscarder(
    logRotator(
        numToKeepStr: '15',
        artifactNumToKeepStr: '7'
    )
)
```

| 对象 | 保留策略 |
| --- | --- |
| Jenkins 构建记录 | 最近 15 次 |
| Jenkins 归档产物 | 最近 7 次构建 |
| 工作空间日期日志 | 超过 7 天由现有日志系统清理 |

Allure 附件可能增加磁盘占用，因此不无限保留原始结果。

### 8.3 定时触发

继续使用：

```groovy
cron('TZ=Asia/Shanghai\nH 2 * * *')
```

- 使用北京时间。
- 每天凌晨 2 点所在小时触发。
- `H` 由 Jenkins 分配具体分钟。
- 定时构建使用默认参数：`test + all + 空 FLOW`。
- Pipeline 首次加载后，Jenkins 才会注册定时器。

## 9. Pipeline 阶段设计

### 9.1 阶段一：准备 Python 环境

职责：

1. 进入 `Truthy_ApiAutoTest2`。
2. 创建或复用 `.venv`。
3. 使用虚拟环境 Python 安装 `requirements.txt`。
4. 创建 `reports` 目录。
5. 删除旧 JUnit XML。
6. 清理当前工作空间的旧 `allure-results`。

设计命令：

```bash
set -eu
python3 -m venv .venv
.venv/bin/python -m pip install \
  --disable-pip-version-check \
  -r requirements.txt
mkdir -p reports
rm -f reports/junit*.xml
rm -rf allure-results
```

异常策略：

- `python3`、venv 或依赖安装失败时立即停止。
- 环境准备失败时不发送真实接口请求。
- 不删除 `.env`、`logs` 或其他任务目录。

### 9.2 阶段二：执行接口自动化

所有模式共用 pytest 报告参数：

```text
--alluredir=allure-results
--clean-alluredir
--allure-no-capture
```

#### 单接口

```bash
.venv/bin/python -m pytest \
  test_cases/test_single_api.py \
  --env="$ENVIRONMENT" \
  -s \
  --log-cli-level=INFO \
  --junitxml=reports/junit-single.xml \
  --alluredir=allure-results \
  --clean-alluredir \
  --allure-no-capture
```

#### 全部 Flow

```bash
.venv/bin/python -m pytest \
  test_cases/test_gateway_flow.py \
  --env="$ENVIRONMENT" \
  -s \
  --log-cli-level=INFO \
  --junitxml=reports/junit-flow.xml \
  --alluredir=allure-results \
  --clean-alluredir \
  --allure-no-capture
```

#### 指定 Flow

```bash
.venv/bin/python runtest.py \
  --env "$ENVIRONMENT" \
  --flow "$FLOW" \
  -- \
  -s \
  --log-cli-level=INFO \
  --junitxml=reports/junit-flow.xml \
  --alluredir=allure-results \
  --clean-alluredir \
  --allure-no-capture
```

#### 全部单接口和 Flow

```bash
.venv/bin/python -m pytest \
  test_cases/test_single_api.py \
  test_cases/test_gateway_flow.py \
  --env="$ENVIRONMENT" \
  -s \
  --log-cli-level=INFO \
  --junitxml=reports/junit-all.xml \
  --alluredir=allure-results \
  --clean-alluredir \
  --allure-no-capture
```

`RUN_TYPE=all` 保持一次 pytest 调用，使 pytest 在某条用例失败后仍能继续执行其他已收集用例，同时只生成一套一致的 JUnit 和 Allure 结果。

### 9.3 阶段三：构建后发布

无论测试成功或失败，都执行：

1. 发布 JUnit XML。
2. 发布 Allure 3 报告。
3. 归档日期日志。
4. 归档 Allure 原始结果。

建议逻辑：

```groovy
post {
    always {
        junit(
            allowEmptyResults: true,
            testResults: 'Truthy_ApiAutoTest2/reports/junit*.xml'
        )

        // 实际语法以当前 Jenkins 的 Pipeline Syntax 生成结果为准。
        allure(
            allureVersion: '3',
            includeProperties: false,
            results: [[path: 'Truthy_ApiAutoTest2/allure-results']]
        )

        archiveArtifacts(
            allowEmptyArchive: true,
            artifacts: 'Truthy_ApiAutoTest2/logs/**/*,Truthy_ApiAutoTest2/allure-results/**/*'
        )
    }
}
```

实现注意：

- Allure 插件安装后，先通过 Jenkins “Pipeline Syntax” 生成当前版本支持的精确语法。
- Allure 发布需要 Jenkins 服务用户 PATH 中存在 Allure 3 CLI。
- `allure-results` 为空时不得覆盖测试阶段的原始失败原因。
- pytest 通过但 Allure 发布失败时，构建标记为 `UNSTABLE`。
- pytest 失败时，构建仍保持 `FAILURE`。

## 10. Allure Jenkins 设计

### 10.1 Python 侧

Python 侧已经负责：

- 生成 Allure 原始结果。
- 单接口动态标题、suite、feature、story 和 tags。
- Flow 动态标题、feature 和 tags。
- Flow API、wait、poll 和 action 步骤。
- POST 和 PUT 请求响应附件。
- token 和签名 URL 脱敏。

Jenkinsfile 不重复实现报告元数据或附件逻辑，只传入 pytest 参数。

### 10.2 Jenkins 插件

接入前检查：

1. “Manage Jenkins → Plugins → Installed plugins” 中是否存在 Allure Report。
2. 插件是否支持 Pipeline 和 Allure 3。
3. 插件缺失时停止 Jenkinsfile Allure 发布改造。
4. 安装插件前获得用户确认。
5. 如需重启 Jenkins，确认没有其他任务正在构建。

插件属于 Jenkins 全局能力，安装或升级可能影响其他任务，因此不能作为自动化脚本的隐式动作。

### 10.3 Allure 3 CLI

Allure 3 Jenkins 发布依赖 Agent PATH 中的 `allure`：

```bash
allure --version
```

检查原则：

- 必须以 Jenkins 服务用户和构建环境验证。
- 本地终端能执行不代表 Jenkins 服务进程能执行。
- 当前本地 npm 用户目录只能作为参考。
- CLI 缺失或 PATH 不可见时，修改节点环境前获得确认。
- CLI 版本固定并记录，避免报告格式随环境漂移。

### 10.4 JUnit 与 Allure

| 维度 | JUnit | Allure |
| --- | --- | --- |
| Jenkins 原生统计 | 是 | 补充 |
| 构建健康度 | 是 | 否 |
| 业务层级 | 基础 | 完整 |
| Flow 步骤 | 不展示 | 展示 |
| 请求响应附件 | 不展示 | 展示 |
| 失败诊断 | 基础 | 详细 |

JUnit 和 Allure 来自同一次 pytest 运行，避免用例数量和状态不一致。

## 11. 日志与产物设计

### 11.1 目录

```text
Truthy_ApiAutoTest2/
├── reports/
│   └── junit-*.xml
├── allure-results/
├── logs/
│   └── YYYY-MM-DD/
│       └── *.log
├── .env
└── .venv/
```

### 11.2 发布与归档

| 目录 | 处理方式 |
| --- | --- |
| `reports/junit*.xml` | Jenkins JUnit 发布 |
| `allure-results/` | Jenkins Allure 发布，并归档最近 7 次 |
| `logs/**/*` | Jenkins 构建产物归档 |
| `.env` | 不发布、不归档 |
| `.venv` | 不发布、不归档 |
| `allure-report/` | 插件方案下不由项目重复生成 |

### 11.3 日志

继续使用现有日志系统：

- 控制台实时显示脱敏请求和响应。
- 文件日志按日期存储。
- 首次创建当天目录时清理超过 7 天的历史日期目录。
- Allure 不替代日志。

## 12. 会话与凭据设计

### 12.1 匿名会话

- 工作空间没有 `.env` 时，框架根据非敏感设备标识创建匿名会话。
- 会话创建或刷新成功后更新当前项目 `.env`。
- 后续构建可复用有效会话。
- 工作空间被清理后允许重新创建匿名会话。
- 禁止并发构建，避免同时更新 `.env`。

### 12.2 固定账号凭据

后续如需固定账号：

- token、refresh token、user ID 等使用 Jenkins Credentials。
- 通过 Credentials Binding 注入环境变量。
- 不写入 YAML、Jenkinsfile 或 Shell 明文参数。

### 12.3 报告安全

- 不归档 `.env`。
- 不把媒体文件内容附加到 Allure。
- 不保存完整预签名 URL。
- Allure 原始结果只允许 Jenkins 任务有权用户访问。
- 接入验收需要扫描已知测试 token 和签名参数，确保没有明文。

## 13. 构建状态设计

| 场景 | 构建状态 |
| --- | --- |
| pytest 全部通过，JUnit 和 Allure 发布成功 | SUCCESS |
| pytest 存在失败用例 | FAILURE |
| pytest 收集失败 | FAILURE |
| Python 环境准备失败 | FAILURE |
| Git 拉取失败 | FAILURE |
| Gateway 无法连接 | FAILURE |
| pytest 通过但 Allure 发布失败 | UNSTABLE |
| pytest 失败且 Allure 发布失败 | FAILURE |
| JUnit 发布失败 | FAILURE |
| 日志或原始结果归档为空 | 不覆盖 pytest 原始状态 |

优先级：

```text
pytest 结果 > JUnit 发布 > Allure 发布 > 日志归档
```

## 14. 异常处理设计

| 异常 | 处理 |
| --- | --- |
| Git 认证失败 | 停止，检查新任务 Git Credential |
| `python3` 不存在 | 准备阶段失败 |
| pip 安装失败 | 准备阶段失败 |
| YAML 配置错误 | pytest 收集失败，不发送请求 |
| Flow 不存在 | pytest 收集失败并列出可用 Flow |
| 接口断言失败 | pytest 失败，发布 JUnit、Allure 和日志 |
| Allure 插件不存在 | Jenkinsfile 改造前阻断 |
| Allure CLI 不可见 | 测试结果保留，报告发布标记异常 |
| `allure-results` 为空 | 输出明确提示，不覆盖测试错误 |
| 日志为空 | 跳过归档，不覆盖测试状态 |

## 15. 开发计划

### 阶段 0：确认 Jenkins 基线

状态：已完成。

工作项：

1. 只读检查 Jenkins 权限。
2. 确认可以新建和配置 Pipeline。
3. 确认 Git、Credentials、JUnit 等基础插件。
4. 确认构建节点在线。
5. 确认不修改已有任务。

结果：

- 权限满足接入要求。
- 基础插件满足 JUnit 版本接入。
- 未创建、修改或触发任何 Jenkins 任务。

### 阶段 1：完成项目 Allure 能力

状态：代码已实现，待最终回归确认。

工作项：

1. 增加 `allure-pytest`。
2. 实现 Allure Reporter。
3. 单接口接入动态元数据和执行 Step。
4. Flow 接入动态元数据和有序 Step。
5. POST/PUT 接入脱敏附件。
6. 忽略 `allure-results` 和 `allure-report`。
7. 补充本地 Allure 3 使用说明。
8. 增加报告层单元测试。

完成条件：

- Allure 报告层测试通过。
- 不传 `--alluredir` 时原测试行为不变。
- 生成的结果不含敏感明文。

### 阶段 2：确认 Jenkins Allure 前置条件

状态：待执行。

工作项：

1. 只读检查 Allure Report 插件是否已安装。
2. 确认插件版本支持 Allure 3。
3. 在 Jenkins 构建环境执行 `allure --version`。
4. 记录 Jenkins 服务用户可见的 Allure CLI 版本和路径。
5. 使用 Pipeline Syntax 生成 Allure 3 Pipeline 步骤。

分支处理：

- 插件和 CLI 均存在：进入阶段 3。
- 插件缺失：报告并等待安装授权。
- CLI 缺失：报告并等待节点环境修改授权。

完成条件：

- Jenkinsfile 可以使用确定的 Allure 3 发布语法。
- 不需要猜测插件或 CLI 状态。

### 阶段 3：更新 Jenkinsfile

状态：待执行。

测试先行：

1. 确认当前 Pipeline 参数和命令基线。
2. 确认当前三个运行模式只执行一次 pytest。
3. 准备静态检查项，防止漏加某个运行模式的 Allure 参数。

实现：

1. 准备阶段清理 `allure-results`。
2. `single` 增加三个 Allure pytest 参数。
3. 全部 Flow 增加三个 Allure pytest 参数。
4. 指定 Flow 增加三个 Allure pytest 参数。
5. `all` 两个分支增加三个 Allure pytest 参数。
6. `post.always` 增加 Allure 3 发布。
7. 归档 `allure-results/**/*`。
8. Allure 发布异常标记 `UNSTABLE`，不覆盖 pytest 失败。
9. 保留 JUnit 和日志现有逻辑。

涉及文件：

- `Jenkinsfile`
- 优先复用现有测试文件，不为静态字符串检查新增复杂工具。

完成条件：

- 三种模式都能生成 JUnit 和 Allure 原始结果。
- Jenkinsfile 不包含 Jenkins 系统管理或其他任务操作。

### 阶段 4：项目侧回归

状态：待执行。

验证：

```bash
python3 -m pytest test_cases/test_allure_report.py -q
python3 -m pytest \
  test_cases/test_framework.py \
  test_cases/test_v12.py \
  test_cases/test_v13.py \
  test_cases/test_allure_report.py \
  -q
python3 -m pytest test_cases/test_single_api.py --collect-only -q
python3 -m pytest test_cases/test_gateway_flow.py --collect-only -q
git diff --check
```

可选真实环境验证：

```bash
python3 runtest.py \
  --env test \
  -- \
  --alluredir=allure-results \
  --clean-alluredir \
  --allure-no-capture
```

真实接口验证会消耗测试环境资源，执行前单独确认。

完成条件：

- 框架和 Allure 回归通过。
- 单接口和 Flow 默认全量收集。
- Git 差异只包含确认范围内的文件。

### 阶段 5：提交并推送

状态：待用户明确授权。

工作项：

1. 检查当前工作区已有改动归属。
2. 只提交本次确认的 Jenkins 与 Allure 集成文件。
3. 提交到 `dev`。
4. 推送远程仓库。
5. 确认远程存在 `Truthy_ApiAutoTest2/Jenkinsfile`。

不在未授权情况下自动提交或推送。

### 阶段 6：创建独立 Jenkins 任务

状态：待用户明确授权。

工作项：

1. 检查 `truthy-api-autotest` 是否已存在。
2. 新建 Pipeline，不复制已有任务。
3. 配置 Git、`*/dev` 和 Script Path。
4. 私有仓库时绑定新任务需要的 Git Credential。
5. 保存新任务。

完成条件：

- 新任务可加载 Jenkinsfile。
- 已有任务配置、构建记录和工作空间无变化。

### 阶段 7：手动构建验收

状态：待执行。

按顺序验证：

#### 7.1 单接口

```text
ENVIRONMENT=test
RUN_TYPE=single
FLOW=
```

检查：

- 收集全部单接口。
- JUnit 发布成功。
- Allure 用例层级正确。
- 请求响应附件已脱敏。
- 日期日志可下载。

#### 7.2 指定 Flow

```text
ENVIRONMENT=test
RUN_TYPE=flow
FLOW=AnonymousSessionMediaSearch
```

检查：

- 只执行指定 Flow。
- Allure 显示 Flow 业务名称。
- API、等待和轮询步骤顺序正确。
- 失败可以定位到具体步骤。

#### 7.3 全部接口

```text
ENVIRONMENT=test
RUN_TYPE=all
FLOW=
```

检查：

- 同时收集全部单接口和全部 Flow。
- JUnit 与 Allure 用例状态一致。
- 日志和报告属于同一次构建。

#### 7.4 报告失败

在不发送额外真实请求的前提下验证 Allure 发布失败处理：

- pytest 成功结果仍保留。
- 构建标记为 `UNSTABLE`。
- Console Output 能定位插件或 CLI 问题。

### 阶段 8：定时构建与交接

状态：待执行。

工作项：

1. 确认 Jenkins 已加载 cron。
2. 确认页面显示下一次运行时间。
3. 验证定时构建使用默认参数。
4. 检查 JUnit、Allure 和日志。
5. 检查构建未并发执行。
6. 记录任务地址、参数和排查说明。

完成条件：

- 每天自动产生构建记录。
- 报告和日志能够按构建查看。
- 使用者可以独立手动运行和定位失败。

## 16. 测试计划

### 16.1 项目侧

| 测试 | 预期 |
| --- | --- |
| Allure Reporter 单元测试 | 元数据、步骤、附件和降级逻辑通过 |
| 框架回归 | 不带 Allure 参数时行为不变 |
| 单接口收集 | 收集全部 Case |
| Flow 收集 | 收集全部 Flow |
| Allure 原始结果 | 结果目录非空 |
| 敏感信息扫描 | token 和签名参数无明文 |
| Jenkinsfile 静态检查 | 三种模式均有 JUnit 和 Allure 参数 |

### 16.2 Jenkins 侧

| 场景 | 预期 |
| --- | --- |
| 首次 Pipeline 加载 | 参数和定时器生效 |
| `single` | 只执行单接口 |
| `flow` + 空 FLOW | 执行全部 Flow |
| `flow` + 指定 FLOW | 只执行指定 Flow |
| `all` | 执行单接口和 Flow |
| pytest 失败 | Jenkins FAILURE，报告仍发布 |
| Allure 发布失败 | Jenkins UNSTABLE，JUnit 保留 |
| 并发触发 | 后续构建等待 |
| 定时触发 | 使用默认参数执行 |

## 17. 验收清单

- [ ] Allure 项目侧回归通过。
- [ ] `RUN_CASE_IDS` 为空。
- [ ] `RUN_FLOW_IDS` 为空。
- [ ] Allure Report 插件状态已确认。
- [ ] Jenkins 服务用户可执行 Allure 3 CLI。
- [ ] Jenkinsfile 三种模式均生成 JUnit。
- [ ] Jenkinsfile 三种模式均生成 `allure-results`。
- [ ] JUnit 发布成功。
- [ ] Allure 3 报告发布成功。
- [ ] 日志和 Allure 原始结果归档成功。
- [ ] `.env` 和 `.venv` 未归档。
- [ ] 单接口手动构建通过。
- [ ] 指定 Flow 手动构建通过。
- [ ] 全部接口手动构建通过。
- [ ] 定时器已加载。
- [ ] 定时构建结果可查看。
- [ ] 未修改任何已有 Jenkins 任务。

## 18. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| Allure 插件缺失 | Pipeline 无法发布报告 | 先只读确认，安装需授权 |
| Jenkins PATH 无 Allure | 报告发布失败 | 以 Jenkins 服务用户验证 |
| 插件安装需要重启 | 可能影响其他任务 | 确认空闲窗口后操作 |
| Allure 参数漏加某分支 | 某模式没有报告 | 静态检查全部执行分支 |
| 结果目录未清理 | 混入旧用例 | 每次使用 clean 并清理工作目录 |
| 并发清理结果 | 报告损坏 | 禁止同任务并发 |
| 附件增大磁盘占用 | Jenkins 磁盘增长 | 只保留最近 7 次产物 |
| 报告含敏感数据 | 凭据泄露 | 复用脱敏并执行安全扫描 |
| Controller 执行构建 | 隔离性有限 | J1.0 先验证，后续迁移 Agent |

## 19. 回滚方案

### 19.1 项目侧

如果 Jenkinsfile Allure 发布逻辑异常：

1. 回退 Jenkinsfile 的 Allure 参数和发布步骤。
2. 保留 JUnit 和日志能力。
3. 重新执行项目侧回归。
4. 修复后再恢复 Allure 发布。

无需回滚接口自动化、Flow、日志或 Allure Python Reporter。

### 19.2 Jenkins 侧

如果新任务异常：

1. 禁用新建的接口自动化任务。
2. 保留构建日志用于排查。
3. 不修改已有任务进行“临时替代”。
4. 删除新任务或卸载插件前再次获得确认。

## 20. 交付物与状态

| 交付物 | 路径或位置 | 当前状态 |
| --- | --- | --- |
| Jenkins 集成 PRD | `docs/接口自动化Jenkins集成-PRD.md` | 已完成 |
| Jenkins 详细设计与计划 | `docs/Jenkins集成-开发设计与开发计划.md` | 已更新，待 Review |
| Allure Pytest 依赖 | `requirements.txt` | 已接入 |
| Allure Reporter | `utils/third_party/allure_reporter.py` | 已实现 |
| 单接口 Allure 接入 | `test_cases/test_single_api.py` | 已实现 |
| Flow Allure 接入 | `test_cases/test_gateway_flow.py` | 已实现 |
| Allure 报告层测试 | `test_cases/test_allure_report.py` | 已实现 |
| 基础 Jenkinsfile | `Jenkinsfile` | 已实现 |
| Jenkinsfile Allure 发布 | `Jenkinsfile` | 待开发 |
| Allure 插件和 CLI 检查 | Jenkins | 待执行 |
| 独立 Jenkins 任务 | Jenkins | 未创建 |
| 手动构建验收 | Jenkins | 未执行 |
| 定时构建验收 | Jenkins | 未执行 |

## 21. 参考资料

- `docs/接口自动化Jenkins集成-PRD.md`
- `docs/接口自动化Allure报告接入-PRD.md`
- `docs/接口自动化Allure报告接入-详细开发设计.md`
- [Allure Jenkins 集成](https://allurereport.org/docs/integrations-jenkins/)
- [Allure 3 安装](https://allurereport.org/docs/v3/install/)

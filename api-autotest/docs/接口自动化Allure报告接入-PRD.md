# Gateway 接口自动化 Allure 报告接入 PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 能力版本 | 报告能力 R1.0 |
| 项目基线 | Gateway 接口自动化 V1.3 |
| 日期 | 2026-07-31 |
| 技术栈 | Python + pytest + requests + PyYAML + Allure Pytest |
| 核心目标 | 为单接口 Cases 和多接口 Flows 生成结构化、可诊断且安全脱敏的 Allure 报告 |
| 文档状态 | 待 Review |

## 2. 背景

当前 V1.3 已具备以下能力：

- API 定义、单接口 Cases、Flows 和 Scenarios 分层管理。
- pytest 参数化执行单接口用例和多接口流程。
- Flow 步骤编排、等待、轮询、响应提取及 COS PUT 上传。
- Gateway 请求与响应日志、耗时记录和敏感信息脱敏。
- 自动创建及刷新匿名会话。

现有终端日志适合本地调试，但仍存在以下问题：

1. 测试结果主要依赖 pytest 文本输出，无法按业务模块、接口和流程直观查看。
2. 多接口 Flow 失败时，需要从日志中人工定位失败步骤。
3. 请求、响应、断言失败和耗时没有集中展示在同一测试结果页面。
4. 测试完成后缺少便于保存、分享和浏览的 HTML 报告。

因此，本次在不改变 V1.3 YAML 数据模型和执行协议的前提下，引入 Allure 报告能力。

## 3. 用户与使用场景

### 3.1 目标用户

- 接口自动化测试开发人员。
- 负责执行回归测试和分析失败结果的测试人员。
- 需要查看测试结果但不直接阅读 Python 代码的项目成员。

### 3.2 核心使用场景

1. 执行全部测试后，在浏览器查看通过、失败、跳过和耗时。
2. 执行某个单接口 case，查看对应请求、响应和断言错误。
3. 执行某个 Flow，按业务顺序查看每一个 API、等待、轮询和上传步骤。
4. 测试失败时，在报告中直接查看脱敏后的诊断附件。
5. 按 suite、feature、story 和 tags 区分单接口与多接口测试。

## 4. 产品目标

### 4.1 核心目标

1. pytest 执行结果可以写入 `allure-results`。
2. 单接口 YAML 中每一个 case 在 Allure 中显示为独立测试用例。
3. 每一个 Flow/Scenario 配对在 Allure 中显示为独立测试用例。
4. Flow 内部步骤按 YAML 顺序显示，并记录步骤状态和耗时。
5. Gateway 请求、响应及 PUT 上传摘要作为 JSON 附件展示。
6. 所有报告内容复用现有脱敏规则，不泄露 token 和预签名 URL。
7. 不改变现有 `runtest.py`、pytest、Cases、Flows 和 Scenarios 的默认执行行为。

### 4.2 成功标准

- 不传 `--alluredir` 时，现有测试仍可正常运行。
- 传入 `--alluredir` 后，pytest 成功生成 Allure 原始结果文件。
- Allure 中单接口标题使用 case 中文名称，而不是通用 Python 函数名。
- Allure 中 Flow 标题使用 Flow/Scenario 名称，并能看到有序步骤。
- 每次普通 Gateway 请求至少包含一份脱敏请求附件和一份脱敏响应附件。
- PUT 上传附件不包含文件二进制和完整预签名查询参数。
- access token、refresh token、auth token、Authorization 和签名 URL 不出现在报告明文中。
- Allure 接入后原有自动化测试无回归。

## 5. 范围

### 5.1 R1.0 包含

- 增加 `allure-pytest` Python 依赖。
- 支持通过 pytest `--alluredir` 生成 Allure 原始结果。
- 单接口 case 的动态标题、suite、feature、story 和 tags。
- Flow/Scenario 的动态标题、suite、feature 和 tags。
- Flow API、wait、poll 和 action 的 Allure Step。
- Gateway POST 请求和响应的脱敏 JSON 附件。
- COS PUT 请求摘要和响应状态附件。
- 异常请求的脱敏诊断附件。
- README 中的安装、执行、生成和查看报告说明。
- Allure 相关单元测试及全量回归验证。

### 5.2 R1.0 不包含

- Jenkins Allure 插件安装和 Pipeline 发布。
- GitHub Actions、GitLab CI 或其他 CI 平台集成。
- Allure 历史趋势、重试趋势和跨构建历史保存。
- 邮件、飞书、Slack 等报告通知。
- Allure TestOps 接入。
- 自定义 Allure 前端主题或插件。
- 将测试图片、上传文件二进制或 `.env` 内容附加到报告。
- 修改 API、Case、Flow 或 Scenario YAML 数据协议。
- 为 Allure 新增 Web 服务或数据库。

## 6. 报告信息架构

### 6.1 单接口用例

推荐层级：

```text
Parent Suite: Gateway API 自动化
Suite: 单接口测试
Feature: API ID
Story: Case ID
Title: Case 中文名称
Tags: Case YAML 中的 tags
```

示例：

```text
Gateway API 自动化
└── 单接口测试
    └── GetMe
        └── get_me_success
            └── 获取当前用户成功
```

### 6.2 多接口 Flow

推荐层级：

```text
Parent Suite: Gateway API 自动化
Suite: 多接口流程
Feature: Flow ID
Title: Flow 名称 / Scenario 名称
Tags: Flow YAML 中的 tags
```

步骤示例：

```text
姓名搜索成功场景
├── 1/4 create_task：CreateIntentTask
├── 2/4 poll_task：GetTask
│   ├── 第 1 次轮询
│   └── 第 2 次轮询：SUCCEEDED
├── 3/4 list_candidates：ListTaskCandidates
└── 4/4 candidate_detail：GetTaskCandidateDetail
```

## 7. 功能需求

### 7.1 依赖与运行

| 编号 | 需求 |
| --- | --- |
| AR-001 | `requirements.txt` 必须声明 `allure-pytest` |
| AR-002 | 使用 npm 用户级前缀安装固定版本 Allure 3 CLI，不写入项目 `package.json` |
| AR-003 | `runtest.py` 必须继续支持透传 `--alluredir`、`--clean-alluredir` 等 pytest 参数 |
| AR-004 | 不传 Allure 参数时不得影响原有测试执行 |

### 7.2 单接口报告

| 编号 | 需求 |
| --- | --- |
| AR-101 | 使用 `single_case["name"]` 作为 Allure 标题 |
| AR-102 | 使用 `api_id` 作为 feature |
| AR-103 | 使用 `case_id` 作为 story |
| AR-104 | 将 YAML tags 映射为 Allure tags |
| AR-105 | 执行接口调用时创建可显示耗时和失败状态的 Allure Step |

### 7.3 Flow 报告

| 编号 | 需求 |
| --- | --- |
| AR-201 | 使用 Flow/Scenario 的业务名称作为测试标题 |
| AR-202 | 每个 Flow step 必须生成独立 Allure Step |
| AR-203 | Step 名称必须至少包含顺序、step ID 和动作/API ID |
| AR-204 | wait 步骤显示等待秒数 |
| AR-205 | poll 步骤显示轮询次数、当前值和最终结果 |
| AR-206 | action 步骤显示具体动作名，例如 `prepared_media_upload` |

### 7.4 请求和响应附件

| 编号 | 需求 |
| --- | --- |
| AR-301 | Gateway POST 请求以 JSON 附件展示 URL、headers 和 payload |
| AR-302 | Gateway 响应以 JSON 附件展示 HTTP 状态、耗时和脱敏响应体 |
| AR-303 | 网络异常时附加脱敏请求和异常类型，不附加敏感异常内容 |
| AR-304 | PUT 请求附件展示脱敏 URL、headers 和 content length |
| AR-305 | PUT 响应附件展示 HTTP 状态和耗时 |
| AR-306 | JSON 附件使用正确媒体类型，支持 Allure 语法高亮 |
| AR-307 | 非 JSON 响应附件只记录状态、耗时、正文类型和长度，不保存正文 |

### 7.5 安全需求

| 编号 | 需求 |
| --- | --- |
| AR-401 | 附件只能使用 `mask_sensitive()` 处理后的数据 |
| AR-402 | access token、refresh token、auth token、Authorization 必须显示为 `***` |
| AR-403 | 预签名 URL 查询参数必须显示为 `***` |
| AR-404 | 不附加 `.env`、完整运行时上下文或媒体文件字节 |
| AR-405 | Allure 附件失败不得绕过脱敏规则改用原始数据 |

## 8. 命令与产物

### 8.1 生成全部测试结果

```bash
python3 runtest.py \
  --env test \
  -- \
  --alluredir=allure-results \
  --clean-alluredir \
  --allure-no-capture
```

### 8.2 生成指定 Flow 结果

```bash
python3 runtest.py \
  --env test \
  --flow AnonymousSessionMediaSearch \
  -- \
  --alluredir=allure-results \
  --clean-alluredir \
  --allure-no-capture
```

### 8.3 查看与生成静态报告

```bash
allure awesome allure-results \
  --output allure-report \
  --group-by parentSuite,suite,feature,story
allure open allure-report
```

### 8.4 产物规则

- `allure-results/`：pytest 生成的原始结果。
- `allure-report/`：Allure CLI 生成的静态 HTML。
- 两个目录均为运行产物，不提交到代码仓库。
- 多次执行需要合并结果时，后续执行不得使用 `--clean-alluredir`。

## 9. 非功能需求

### 9.1 兼容性

- 保持现有 Python、pytest、requests 和 PyYAML 架构。
- 不修改 V1.3 YAML Schema。
- 不改变 pytest 用例 ID 和筛选能力。

### 9.2 性能

- 附件序列化不得明显改变接口调用耗时。
- 不附加上传文件二进制。
- 轮询附件数量应受现有轮询超时和间隔约束，避免无限增长。

### 9.3 可维护性

- Allure 相关封装集中放在 `utils/third_party`。
- 业务执行层只调用报告封装，不直接散落重复的 JSON 序列化代码。
- 新增或修改 Python 代码包含清晰中文 docstring 和关键逻辑注释。

## 10. 验收标准

### 10.1 单接口验收

- 执行至少两条参数化 case。
- Allure 显示两个独立中文标题。
- feature、story 和 tags 映射正确。
- 每条 case 包含脱敏请求、响应附件。

### 10.2 Flow 验收

- 执行 `AnonymousSessionMediaSearch`。
- 报告显示完整 Flow 标题。
- create、poll、list 和 detail 步骤顺序正确。
- 失败时准确标记对应步骤。

### 10.3 安全验收

- 在 `allure-results` 和静态报告中搜索真实 token，结果必须为空。
- 在报告中搜索预签名 URL 原始查询签名，结果必须为空。
- 报告不包含 `.env` 内容和媒体字节。

### 10.4 回归验收

- 不带 `--alluredir` 的现有测试通过。
- 带 `--alluredir` 的测试通过并生成结果。
- YAML 收集、单接口筛选和 Flow 筛选行为保持不变。

## 11. 风险与约束

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| Allure 3 CLI 未安装或 npm 用户目录未加入 PATH | 无法生成 HTML | pytest 结果生成与 HTML 生成解耦；README 提供固定版本安装和检查命令 |
| 附件误用原始请求 | 泄露 token | 只允许传入现有脱敏副本；增加安全测试 |
| 轮询产生大量附件 | 报告体积增大 | Step 展示轮询摘要，附件数量受超时约束；后续按实际体积优化 |
| `--clean-alluredir` 误删前一批结果 | 多批结果无法合并 | README 明确仅首批执行使用 clean |
| Allure 代码侵入执行核心 | 后续维护困难 | 使用 `utils/third_party` 集中封装，核心仅调用最小接口 |

## 12. 官方参考

- [Allure Pytest 入门](https://allurereport.org/docs/pytest/)
- [Allure Pytest API 参考](https://allurereport.org/docs/pytest-reference/)
- [Allure Steps](https://allurereport.org/docs/steps/)
- [Allure Attachments](https://allurereport.org/docs/attachments/)
- [Allure 3 安装](https://allurereport.org/docs/v3/install/)
- [Allure 3 迁移兼容性](https://allurereport.org/docs/v3/migrate/)

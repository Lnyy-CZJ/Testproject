# Gateway 接口自动化 Allure 报告接入开发计划

## 1. 计划信息

| 项目 | 内容 |
| --- | --- |
| 能力版本 | 报告能力 R1.0 |
| 项目基线 | Gateway 接口自动化 V1.3 |
| 日期 | 2026-07-31 |
| 需求依据 | `docs/接口自动化Allure报告接入-PRD.md` |
| 设计依据 | `docs/接口自动化Allure报告接入-详细开发设计.md` |
| 计划状态 | 待 Review |

## 2. 任务目标

为现有单接口 Cases 和多接口 Flows 接入 Allure，提供业务化测试标题、有序 Flow 步骤、脱敏请求响应附件及本地 HTML 报告，同时保持 V1.3 数据模型和执行行为不变。

## 3. 成功标准

- `allure-pytest` 依赖安装成功。
- 单接口和 Flow 均能生成独立 Allure 测试结果。
- Flow 每个步骤及轮询过程可在报告中定位。
- Gateway POST 和 COS PUT 具备脱敏附件。
- Allure 原始结果可成功转换并打开为 HTML。
- 不带 Allure 参数的现有测试全部通过。
- 报告产物中不存在真实 token、签名 URL 和媒体二进制。

## 4. 交付物

- Allure Python 依赖声明。
- Allure 报告封装。
- 单接口动态报告元数据。
- Flow 动态报告元数据和步骤。
- Gateway POST、COS PUT 脱敏附件。
- Allure 报告层单元测试。
- `.gitignore` 产物规则。
- README 使用说明。

## 5. 实施约束

1. 只实现已确认的 R1.0 范围。
2. 不修改 V1.3 API、Case、Flow 和 Scenario Schema。
3. 不修改 Gateway 请求信封、会话刷新和断言协议。
4. 不接入 Jenkins 发布、历史趋势、通知或 TestOps。
5. Allure 只能使用已经脱敏的请求和响应对象。
6. 不附加媒体二进制、`.env` 或完整 RuntimeContext。
7. 所有新增和修改的 Python 代码使用清晰中文 docstring 和必要注释。
8. 每个阶段先补测试，再修改正式实现。

## 6. 影响文件

### 6.1 新增文件

| 文件 | 原因 |
| --- | --- |
| `utils/third_party/allure_reporter.py` | 集中隔离 Allure API，符合现有第三方预留目录职责 |
| `test_cases/test_allure_report.py` | 集中测试报告元数据、Step、附件和脱敏，不污染现有业务测试 |

### 6.2 修改文件

| 文件 | 修改内容 |
| --- | --- |
| `requirements.txt` | 添加 `allure-pytest` |
| `.gitignore` | 忽略 Allure 原始结果和 HTML 报告 |
| `test_cases/test_single_api.py` | 单接口动态元数据和执行 Step |
| `test_cases/test_gateway_flow.py` | Flow 动态元数据 |
| `utils/custom/flow_runner.py` | Flow 步骤和轮询子步骤 |
| `utils/custom/http_client.py` | 脱敏请求响应附件 |
| `README.md` | 安装、执行、报告生成和安全说明 |

## 7. 风险评估

| 风险 | 等级 | 缓解措施 |
| --- | --- | --- |
| 原始数据误附加导致凭证泄露 | 高 | 测试先行；附件只接受现有安全对象；扫描结果产物 |
| FlowRunner 加 Step 后改变异常行为 | 中 | Step 仅包装现有代码；回归轮询成功、超时和 action 失败 |
| 轮询附件过多导致报告体积增长 | 中 | 记录受控轮询；不附加媒体；实测后再决定压缩策略 |
| Allure 依赖影响无报告执行 | 中 | 验证不带 `--alluredir` 的完整回归 |
| Allure 3 CLI 或 npm PATH 缺失 | 低 | results 生成与 HTML 转换解耦；README 提供固定版本安装和检查命令 |

## 8. 分阶段开发计划

### 阶段 0：建立基线

目标：确认接入前测试、命令透传和脱敏行为。

工作项：

1. 运行框架单元测试和 V1.3 测试。
2. 运行 pytest 收集，记录单接口和 Flow 用例 ID。
3. 验证 `runtest.py` 能将未知参数原样传给 pytest。
4. 记录当前 `mask_sensitive()` 和签名 URL 脱敏测试结果。
5. 检查 `.gitignore` 当前内容。

只读或测试文件：

- `runtest.py`
- `test_cases/test_framework.py`
- `test_cases/test_v13.py`
- `utils/custom/http_client.py`
- `.gitignore`

验证命令：

```bash
python3 -m pytest test_cases/test_framework.py test_cases/test_v13.py -q
python3 -m pytest --collect-only -q
```

完成条件：

- 当前测试基线明确。
- 当前收集 ID 已记录。
- 已确认不存在需要先修复的无关失败。

### 阶段 1：添加依赖和报告封装

目标：建立最小 Allure 调用边界。

测试先行：

1. 单接口元数据映射测试。
2. Flow 元数据映射测试。
3. tags 映射测试。
4. JSON 附件序列化测试。
5. Step 标题透传测试。

实现：

1. 在 `requirements.txt` 增加 `allure-pytest`。
2. 新增 `utils/third_party/allure_reporter.py`。
3. 实现动态元数据、Step、JSON 和文本附件的最小封装。
4. 新增 `test_cases/test_allure_report.py`。
5. 所有函数补充中文功能、参数、返回值和异常说明。

涉及文件：

- `requirements.txt`
- `utils/third_party/allure_reporter.py`
- `test_cases/test_allure_report.py`

验证命令：

```bash
python3 -m pytest test_cases/test_allure_report.py -q
```

完成条件：

- 报告封装可独立测试。
- 业务执行代码尚未改变。

### 阶段 2：接入单接口报告

目标：每一个 YAML case 在 Allure 中具有业务化标题和层级。

测试先行：

1. `single_case.name` 映射为 title。
2. `api_id` 映射为 feature。
3. `case_id` 映射为 story。
4. tags 全量映射。
5. pytest 参数 ID 保持不变。

实现：

1. 在 `test_single_api.py` 调用单接口元数据封装。
2. 使用 Allure Step 包装 `gateway_api.execute()`。
3. 不修改 `_load_case_params()` 和 case 收集逻辑。

涉及文件：

- `test_cases/test_single_api.py`
- `test_cases/test_allure_report.py`

验证命令：

```bash
python3 -m pytest test_cases/test_allure_report.py -k single -q
python3 -m pytest test_cases/test_single_api.py --collect-only -q
```

完成条件：

- 单接口收集数量和 pytest ID 与基线一致。
- 报告元数据使用 YAML 业务字段。

### 阶段 3：接入 Flow 元数据与步骤

目标：Flow/Scenario 作为独立测试展示，内部步骤有序可定位。

测试先行：

1. Scenario 名称优先作为标题。
2. Flow ID 映射为 feature。
3. API、wait、action 标题格式正确。
4. Flow 步骤顺序不变。
5. Step 包装后原异常继续抛出。

实现：

1. 在 `test_gateway_flow.py` 设置 Flow 元数据。
2. 在 `FlowRunner.run()` 中包装每一个顶层步骤。
3. Step 名称包含顺序、step ID 和 API/action/wait 信息。
4. 保持现有分支和异常逻辑不变。

涉及文件：

- `test_cases/test_gateway_flow.py`
- `utils/custom/flow_runner.py`
- `test_cases/test_allure_report.py`

验证命令：

```bash
python3 -m pytest test_cases/test_allure_report.py -k flow -q
python3 -m pytest test_cases/test_v13.py -k flow -q
```

完成条件：

- Flow 每个顶层步骤均可在报告中显示。
- 原有 Flow 测试全部通过。

### 阶段 4：接入轮询子步骤

目标：在报告中展示轮询次数、状态和耗时，不改变轮询协议。

测试先行：

1. 第一次成功只产生一次尝试。
2. 多次后成功按顺序产生尝试。
3. 超时仍抛出原有 `FlowExecutionError`。
4. 最后实际值和调用次数保持原错误信息。
5. sleep、deadline 和 interval 行为不变。

实现：

1. 在 `_poll()` 每次尝试中创建子 Step。
2. 得到状态值后设置可读步骤标题或参数。
3. 不修改原有成功判断、等待和超时计算。

涉及文件：

- `utils/custom/flow_runner.py`
- `test_cases/test_allure_report.py`
- 现有 FlowRunner 测试文件

验证命令：

```bash
python3 -m pytest test_cases/test_allure_report.py -k poll -q
python3 -m pytest test_cases/test_v13.py -k poll -q
```

完成条件：

- 报告可定位每次轮询。
- 原有轮询测试无回归。

### 阶段 5：接入 Gateway POST 附件

目标：为每次 Gateway 请求提供脱敏请求和响应证据。

测试先行：

1. 请求附件内容等于 `safe_request`。
2. access/auth/refresh token 不出现在附件。
3. 响应附件包含状态码和耗时。
4. 响应预签名 URL 已脱敏。
5. 非 JSON 响应附件不保存正文，只保存类型和长度。
6. 网络异常附件不包含异常原文。
7. requests 异常继续原样抛出。

实现：

1. 请求前附加 `safe_request`。
2. 响应后附加状态、耗时和脱敏响应体。
3. 异常时附加请求、耗时和异常类型。
4. 不建立第二套脱敏函数。

涉及文件：

- `utils/custom/http_client.py`
- `test_cases/test_allure_report.py`
- `test_cases/test_framework.py`

验证命令：

```bash
python3 -m pytest test_cases/test_allure_report.py -k http -q
python3 -m pytest test_cases/test_framework.py -k "http_client or mask" -q
```

完成条件：

- 普通和异常请求均有安全诊断附件。
- 日志输出行为保持不变。

### 阶段 6：接入 COS PUT 附件

目标：展示上传请求摘要和状态，不泄露签名或文件内容。

测试先行：

1. URL 查询参数显示为 `***`。
2. `Content-Length` 和 `Content-Type` 正确保留。
3. 附件只包含 content length，不包含 `bytes` 内容。
4. PUT 状态码和耗时正确。
5. PUT 异常仍按原逻辑抛出。

实现：

1. 复用 PUT `safe_request`。
2. 附加脱敏上传摘要。
3. 附加响应 HTTP 状态和耗时。
4. 禁止读取或附加媒体文件路径和内容。

涉及文件：

- `utils/custom/http_client.py`
- `test_cases/test_allure_report.py`

验证命令：

```bash
python3 -m pytest test_cases/test_allure_report.py -k put -q
python3 -m pytest test_cases/test_framework.py -k put -q
```

完成条件：

- PUT 报告信息足以诊断状态和 header。
- 报告不含媒体二进制和原始签名。

### 阶段 7：产物管理和使用文档

目标：让本地使用者可以安装、执行、生成和打开报告。

实现：

1. `.gitignore` 增加：

```text
allure-results/
allure-report/
```

2. README 增加：
   - `allure-pytest` 安装。
   - Allure 3 npm 用户级前缀安装。
   - 全量和指定 Flow 结果命令。
   - `allure awesome` 和 `allure open`。
   - `--clean-alluredir` 合并注意事项。
   - `--allure-no-capture` 避免重复附件。
   - 非 JSON 响应正文不进入附件。
   - 报告安全说明。
3. 不修改 `Jenkinsfile`。

涉及文件：

- `.gitignore`
- `README.md`

验证：

```bash
export PATH="/Users/admin/.local/allure-npm/bin:$PATH"
allure --version
.venv/bin/python runtest.py --help
```

完成条件：

- 新使用者可以只根据 README 生成本地报告。
- Allure 运行产物不会被版本控制跟踪。

### 阶段 8：全量回归与安全验收

目标：确认报告可用且没有改变现有测试行为。

验证顺序：

1. 报告层测试：

```bash
python3 -m pytest test_cases/test_allure_report.py -q
```

2. 框架与 V1.3 回归：

```bash
python3 -m pytest test_cases/test_framework.py test_cases/test_v13.py -q
```

3. 全量测试：

```bash
python3 -m pytest -q
```

4. 生成 Allure 原始结果：

```bash
python3 runtest.py \
  --env test \
  -- \
  --alluredir=allure-results \
  --clean-alluredir \
  --allure-no-capture
```

5. 生成 HTML：

```bash
allure awesome allure-results \
  --output allure-report \
  --group-by parentSuite,suite,feature,story
allure open allure-report
```

6. 安全扫描：

- 搜索已知测试 token，必须没有匹配。
- 搜索 refresh token 前缀，必须没有明文。
- 搜索 COS 签名参数原值，必须没有明文。
- 确认报告目录没有媒体文件副本。

完成条件：

- 所有自动化测试通过或仅存在已确认的环境条件跳过。
- Allure HTML 可打开。
- 单接口、Flow、Step 和附件结构符合 PRD。
- 安全扫描通过。

## 9. 推荐实施顺序

```text
基线
  → 依赖与 Reporter
  → 单接口元数据
  → Flow 元数据和步骤
  → 轮询步骤
  → POST 附件
  → PUT 附件
  → README / gitignore
  → 全量与安全验收
```

该顺序确保每一步都可独立验证，失败时可以定位到最小改动范围。

## 10. 验收检查清单

### 功能

- [ ] 单接口标题、feature、story、tags 正确。
- [ ] Flow 标题、feature、tags 正确。
- [ ] API、wait、poll、action 步骤顺序正确。
- [ ] Gateway 请求和响应附件可预览。
- [ ] COS PUT 摘要可预览。
- [ ] Allure HTML 可生成并打开。

### 安全

- [ ] token 全部显示为 `***`。
- [ ] 签名 URL 查询参数显示为 `***`。
- [ ] `.env` 未进入报告。
- [ ] RuntimeContext 未整体附加。
- [ ] 媒体文件和字节未进入报告。

### 回归

- [ ] pytest 收集数量和 ID 未改变。
- [ ] `-k`、`-m`、`--env`、`--flow` 正常。
- [ ] 不带 Allure 参数执行正常。
- [ ] 会话创建和刷新正常。
- [ ] Flow 轮询和上传正常。
- [ ] 原有日志仍正常输出和脱敏。

### 文档

- [ ] README 包含安装和使用命令。
- [ ] `.gitignore` 包含两个报告产物目录。
- [ ] PRD、设计和开发计划与最终实现一致。

## 11. 回滚计划

若 Allure 接入导致无法接受的回归：

1. 按阶段逆序移除 HTTP 附件、Flow Step 和测试元数据调用。
2. 删除 reporter 和专用测试文件。
3. 从 requirements 移除 Allure 依赖。
4. 恢复 `.gitignore` 和 README 对应条目。
5. 重新运行原 V1.3 全量测试。

由于本计划不迁移 YAML、不修改业务数据、不改变请求协议，回滚不涉及数据恢复。

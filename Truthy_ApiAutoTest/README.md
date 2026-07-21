# Truthy API 自动化测试框架

框架提供 Gateway 单请求信封、配置加载、有限网络重试、Pydantic v2 响应模型、双层断言、测试数据缓存、递归脱敏、Allure 附件及统一的本地/CI 测试入口。

## 环境准备

要求 Python 3.11 及以上。建议在虚拟环境安装精确版本依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
```

敏感字段不写入 YAML，只通过环境变量注入：

```bash
export TRUTHY_AUTH_TOKEN='由凭据系统注入'
export TRUTHY_REFRESH_TOKEN='由凭据系统注入'
```

环境配置位于 `config/env.test.yaml` 与 `config/env.staging.yaml`。Gateway 地址等非秘密配置可放 YAML；以下敏感变量只能由本地安全环境或 CI 凭据系统注入，禁止写入仓库、日志和测试报告：

- `TRUTHY_AUTH_TOKEN`、`TRUTHY_REFRESH_TOKEN`：Gateway 身份凭据。
- `FEISHU_WEBHOOK`：飞书机器人完整 webhook（其中包含秘密 token）。
- 未来真实权益夹具所需凭据：协议确认前尚未定义，也不得自行猜测字段或地址。

## 运行

完整离线测试（真实联调用例默认跳过）：

```bash
python3 -m pytest
python3 runtest.py --suite contract --env test
python3 runtest.py --suite smoke --env test
python3 runtest.py --suite regression --env test --markers "p0 or p1"
```

生成 JUnit 与 Allure 结果（需安装可选测试依赖）：

```bash
python3 runtest.py --suite all --env test \
  --junitxml artifacts/junit.xml --alluredir allure-results
```

只有已获授权并明确需要真实只读联调时，才增加 `--run-live-safe`。该开关会访问环境配置中的 Gateway：

```bash
python3 runtest.py --suite contract --env test --run-live-safe
```

统一入口的所有 suite 永久排除 `payment_real` 和 `destructive`，附加 `--markers` 也不能绕过该保护。`--workers` 默认 1；仅安装 `pytest-xdist` 时才传递 `-n`。

## Marker 与运行安全级别

常用 marker 包括 `smoke`、`contract`、`p0`、`p1`、`compatibility`、`live_safe`、`live_write`、`payment_sandbox`、`payment_real` 与 `destructive`。`compatibility` 只允许通过 Jenkins 手工兼容扩展模式执行。安全级别命令如下：

```bash
# 离线安全：默认不联网，且永久排除危险 marker
python3 runtest.py --suite smoke --env test

# 安全只读联调：需明确授权和有效环境配置，仍排除危险 marker
python3 runtest.py --suite contract --env test --run-live-safe

# 危险测试：统一入口和 Jenkins 均不提供该能力
# 仅在专项人工审批、隔离环境和清理方案齐备后，才可直接使用 pytest：
python3 -m pytest -m "payment_real or destructive" --run-dangerous
```

`live_write` 必须同时标记 `destructive`。MR 与其他自动门禁不传真实联调开关；仅工作日只读冒烟固定传入 `--run-live-safe`。所有自动任务均不传 `--run-dangerous`。

## Jenkins、Allure 与飞书

`Jenkinsfile` 是静态模板：工作日定时触发、35 分钟超时、禁止并发、保留 30 天构建。MR 自动固定执行离线非写 `contract+p0`；工作日 cron 固定以 `--run-live-safe` 执行非写 `smoke+p0`，其中 Home 只读探针无需账号凭据，其他缺少外部条件的用例会明确 skip。release 模式先执行不可人工覆盖的 P0 阻断门禁，P1 失败后必须人工确认风险。支付沙箱和兼容扩展模式会校验 Jenkins 的手工用户触发原因，自动任务不能启用。Jenkins 节点需安装 Python 3.11+，并安装/配置 JUnit 与 Allure Jenkins 插件；实际 agent label 由 CI 管理员设置。Install 阶段使用带 hash 校验的锁文件，所有测试阶段只调用 `python3 runtest.py`，本地与 Jenkins 不维护两套入口。

在 Jenkins 凭据管理中保存飞书 webhook，并通过任务级凭据绑定将其注入环境变量 `FEISHU_WEBHOOK`；不要在 Jenkinsfile、参数默认值或仓库文件中写地址/token。`post always` 会运行 `scripts/notify_feishu.py`：未配置 webhook 时明确显示 disabled 并退出 0；通知失败不会覆盖测试构建结果。可在本地用 `FEISHU_DRY_RUN=1` 只生成并验证脱敏 payload，dry-run 不访问网络。

Allure 结果写入 `allure-results`。失败附件沿用框架现有的脱敏与 1 MB 上限机制，不重复附加原始请求/响应。

## 当前边界

- 真实权益夹具协议和凭据仍未提供，因此相关 TC024 场景明确跳过；框架不会根据猜测调用发放/撤销接口。
- 当前没有自动清理真实环境数据的能力。任何写入、真实支付或破坏性测试必须先具备隔离环境、人工授权和可验证的清理方案。
- 此仓库只提供 Jenkins/飞书模板与离线测试，尚未在实际 Jenkins 插件、凭据绑定或真实飞书机器人上联调。

## 故障排查

- `pip --require-hashes` 失败：确认使用 Python 3.11+、未手工修改 `requirements.lock`，并使用与锁文件兼容的平台；依赖变更应重新生成完整 hash 锁。
- `-n` 未生效：安装 `pytest-xdist`；未安装时框架自动串行运行。
- Allure 页面为空：确认 Jenkins Allure 插件已配置，且 `allure-results` 已产生结果文件。
- 飞书显示 disabled：确认 Jenkins 凭据绑定的变量名为 `FEISHU_WEBHOOK`；切勿打印变量值排查。
- `live_safe` 用例跳过：只有显式 `--run-live-safe` 才执行，并需检查目标环境与只读联调授权。
- 权益用例跳过：这是当前协议缺失下的预期安全行为，不应通过硬编码接口绕过。

## 关键约束

- 所有业务请求通过 `GatewayClient.invoke()` 发送到 `POST /gateway/invoke`。
- `comm` 不发送 `user_id`；创建类业务的 `client_request_id` 由调用方构造，并在网络重试中保持不变。
- 只重试连接异常和 HTTP 502/503/504，最多重试 2 次；读取超时、4xx 与业务错误不重试。
- HTTP 2xx 与业务成功必须分别使用 Gateway 顶层断言和业务子响应断言。
- 原始请求、响应、token、预签名 URL 和个人信息不得进入日志或报告附件。

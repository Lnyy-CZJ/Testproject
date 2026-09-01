# Dating AI Assistant 自动化评测工具

这是 V0.3.0 双流程轻量 MVP。它提供一个 Python 3.12 CLI，分别跑通：

- 完整 E2E 小规模验证：Identity → Preferences（仅 Reply）→ Media/COS → Quota
  （仅 Analysis）→ Task → Result → Delete。
- AI 快速批量评测：直接提交 `dating.transcript.v1`，执行内部 Reply/Analysis Evaluation
  的 Create → Poll → Result → Diagnostics → Delete。

两个流程共用 Case Runner、清理规则和安全 Artifact，但 Public 与 Internal Adapter 的服务名、
方法映射和 Wire Schema 完全隔离。

MVP 不包含 AI Judge、内容质量评分、正式报告、自动发布、门禁、CI 或数据库。

## 安装

```bash
cd /Users/admin/Testproject/dating_tool
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
```

`.env` 已被 Git 忽略。API Key、Public Token、Device ID、签名 URL 和聊天/结果正文不会写入
控制台或安全摘要 Artifact。内部 API Key 只能通过当前进程环境或本地 `.env` 注入；请不要
把带值的设置命令保存在脚本、Shell History、测试报告或文档中。下文的本地 Wire Log 是
用户为排障显式启用的例外，会原样保存这些数据。

## 命令

CLI 只提供四个命令：

```bash
dating-eval doctor --mode <e2e|eval>
dating-eval validate --mode <e2e|eval> --dataset <path> [--case <case_id>]
dating-eval run --mode <e2e|eval> --dataset <path> [--case <case_id>]
dating-eval cleanup --run <run_id>
```

退出码固定为：

| 退出码 | 含义 |
| --- | --- |
| `0` | 协议执行成功，并且所有已知 Task 已清理 |
| `1` | 单案例业务或契约失败 |
| `2` | 配置或数据集错误，未开始远端执行 |
| `3` | 鉴权、权限、安全或环境 readiness 错误 |
| `4` | 网络中断等导致执行未完成，或仍有待清理 Task |

`validate` 只做本地解析、字节/边界和图片检查，不构建 Adapter，不访问 staging。`run` 会先
校验完整数据集，再应用 `--case` 精确筛选，不能通过筛选绕过坏行。

## 原始链路日志

`doctor`、`run` 以及确实存在待删除 Internal Task 的 `cleanup`，每次调用只创建一个日志，
该次命令中的 Health、Gateway 和 COS 请求共享同一文件：

```text
logs/2026-08-28/20260828_025800_346901_test_20019.log
```

文件使用 JSON Lines 格式，记录业务请求参数、Requests 最终生成的 PreparedRequest、请求/
响应顺序、关联 ID、实际编码后的 URL、Session/Cookie 等运行时 Header、序列化 Body、HTTP
状态码、服务端响应 Header/正文、耗时和原始异常消息。COS 请求与响应的二进制正文使用
Base64 保存。日志**完全不脱敏、不截断**，包括 API Key、Authorization、Public Token、
Device ID、签名 URL、聊天截图、聊天正文和模型结果；它只能保留在个人本机，禁止提交 Git、
上传测试平台、放进报告或发送给他人。`logs/` 已被 Git 忽略，日期目录权限为 `0700`，日志
文件权限为 `0600`。如需把日志移到其他本地磁盘，可设置 `AIDATING_LOG_ROOT`。

`doctor` 和 `run` 会在配置与数据校验前创建日志，因此前置失败也会留下 `cli_error`；
`cleanup` 则仅在确认存在待删除 Internal Task 后、读取网络配置前创建。若日志根目录无法
创建，或运行期间磁盘写满、日志被删除、同名替换或权限发生变化，logger 会永久进入
fail-open 降级状态并在控制台提示：不会用默认权限重建文件，也不会覆盖已经成功返回的
Create 结果或阻断 `finally` 删除远端 Task。

`validate` 没有网络行为，因此不会生成链路日志。

## 快速批量评测

本地校验不需要 API Key：

```bash
dating-eval validate --mode eval --dataset datasets/eval-smoke.jsonl
```

真实联调前，在当前环境中安全设置以下变量：

- `AIDATING_EVAL_BASE_URL`：必须是后端确认的精确 staging `/admin/invoke` 地址；
- `AIDATING_EVAL_API_KEY`：测试服务账号 Key；
- `AIDATING_EVAL_ALLOW_INSECURE_HTTP=true`：仅临时 HTTP CLB 需要；
- `AIDATING_EVAL_CONCURRENCY`：默认 3，范围 1～5。

然后执行：

```bash
dating-eval doctor --mode eval
dating-eval run --mode eval --dataset datasets/eval-smoke.jsonl --case eval-reply-happy-001
dating-eval run --mode eval --dataset datasets/eval-smoke.jsonl --case eval-analysis-happy-001
```

批量模式默认并发 3、最大 5；Create 开始时间至少相隔 2 秒；所有 Admin Gateway 请求共享
120 次/分钟滑动窗口和服务端 `retry_after_seconds` cooldown。单 Task 每 3 秒轮询一次，最多
等待 4 分钟。每次真实重复运行都会生成新的幂等键；同一次网络结果未知重试复用原键。

## 完整截图 E2E

先把确认已脱敏、无 EXIF 的本地图片放在 `datasets/media/`。该目录中的媒体默认不进入 Git。
仓库当前本地工作区包含一张 Pillow 合成的
`datasets/media/staging-analysis-smoke.png`，只用于 Analysis 单图 smoke。

```bash
dating-eval validate --mode e2e --dataset datasets/e2e-smoke/analysis-single.json
```

真实运行还需要在环境中设置固定公开 Gateway/Health URL、唯一测试 Device ID 和
`AIDATING_E2E_FIXTURE_ROOT=datasets`：

```bash
dating-eval doctor --mode e2e
dating-eval run --mode e2e --dataset datasets/e2e-smoke/analysis-single.json
```

执行前人工确认 Quota 有余额或 `unlimited=true`。Analysis 始终按
Identity → Media → Quota → Task → Result → Delete 执行，不会因 Reply Preferences 未开放
而阻断。

Public 鉴权请求遇到一次 `UNAUTHENTICATED` 时，会在内存中刷新 Session、校验 `GetMe`，并以
相同 request ID 重试原请求；同一个 Run 最多自动刷新一次，第二次鉴权失败会停止后续创建，
但仍清理所有已观察到的 Task。

Public Reply 当前采用分层验收：代码、协议和 Fake Integration 已覆盖
Identity/Preferences/Media/Task/Result/Delete；真实 staging 先只执行 Preferences 与
Task/Result sentinel readiness，不上传媒体、不创建 Task。后端冻结并开放 Reply 方法后，
再准备 `datasets/media/reply-*.png` 并开启完整 Reply smoke。

若要校验 `datasets/e2e-smoke/` 整个目录，需要先按各 JSON 中的文件名补齐 1 图和多图的
本地脱敏 Fixture。

## Artifact 与恢复清理

每次 Run 写入私有权限目录：

```text
artifacts/<run_id>/
├── manifest.json
├── run-state.jsonl
└── cases/<case_id>/
    ├── metadata.json
    ├── task.json
    ├── result.json
    ├── diagnostics.json
    ├── cleanup.json
    └── error.json
```

每类 Case Artifact 使用独立字段白名单；正文、候选回复、聊天消息、Prompt、模型原始输出、
身份字段、认证 Header、签名 URL 和任何未经审查的新字段都不会落盘。若 Create 已返回
`task_id` 后才发现状态或 Schema 不合法，Runner 也会记录恢复锚点并在 `finally` 中逐个
删除。内部 Eval 可从事件日志恢复尚未清理的 Task：

```bash
dating-eval cleanup --run <run_id>
```

Public Token 不会写入可恢复状态或安全摘要 Artifact，因此 Public 跨进程 cleanup 仍返回
退出码 4，只依靠当前进程 finally 删除和服务端 TTL。需要注意，原始 Wire Log 会记录网络
请求中的 Public Token，但 cleanup 不会读取或复用日志中的凭据。

## 测试与显式 staging opt-in

默认测试绝不访问 staging：

```bash
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
dating-eval --help
```

只有环境变量、测试凭据和本地脱敏媒体均已准备好时，才显式开启：

```bash
AIDATING_RUN_STAGING_TESTS=1 \
.venv/bin/python -m unittest \
  tests.staging.test_public_analysis_smoke \
  tests.staging.test_internal_reply_smoke \
  tests.staging.test_internal_analysis_smoke -v
```

Public Reply 全链路还需要独立设置 `AIDATING_RUN_PUBLIC_REPLY_STAGING=1`。未开启时默认跳过，
Fake PASS 不能替代真实 staging PASS。

现有 Node 截图 Fixture 生成器属于独立 WIP，原文件及其预存 TDD 红灯保持不变；本 Python
MVP 的验收命令不包含 `npm test`。

## 本地 Web 工作台

Web 工作台与 CLI 共用同一套 `RunApplicationService`、Adapter、Runner、Artifact 和清理逻辑，
提供两个最小闭环：完整 E2E 小规模验证，以及上传 `dating.transcript.v1` JSONL 的快速批量评测。
页面只绑定本机回环地址，不允许修改 Gateway、Service、Method、API Key 或 Device ID，也不提供
AI 自动裁判、内容质量评分、正式报告、发布、门禁或 CI。

```bash
.venv/bin/pip install -e .
.venv/bin/dating-eval-web
```

默认监听 `127.0.0.1:5005`，可使用 `AIDATING_WEB_PORT` 覆盖端口。启动后可检查：

```bash
curl -fsS http://127.0.0.1:5005/health
```

创建页先把上传内容写入私有 Draft，再调用本地 `/api/runs/validate`；校验通过后由后台 RunManager
异步执行，详情页每 3 秒读取 Run、Case、Cleanup 和 Wire Log 尾部。Run 结束时 Draft 和临时图片/
JSONL 副本会删除，完整日志仍按 `logs/YYYY-MM-DD/YYYYMMDD_HHMMSS_microseconds_test_PID.log`
保留在本机供排障。

# API 测试智能体 V2.0：S2 真实执行安全评审与本机试点记录

> 评审结论：**有条件批准本机无生产数据测试环境试点**  
> 批准日期：2026-08-13  
> 批准范围：测试开发平台本机环境、已登记目标 `local-platform-dev`、HTTP API、允许 GET/POST/PUT/PATCH/DELETE  
> 确认角色：平台管理员、测试开发、测试执行人员（均须具备 `api-test-agent.execute`）  
> 生产环境：**未批准，固定禁止**；默认部署仍为 `API_EXECUTION_ENABLED=false`

## 1. 为什么人工确认后仍需要运行时安全

人工确认解决“测试人员是否希望执行这些用例”的业务决策；运行时安全解决“程序实际只能按确认内容访问登记目标”的技术约束。两者缺一不可：文档、LLM 输出、变量替换、重定向、DNS、目标配置或程序缺陷都可能使实际请求偏离人工看到的摘要。

因此，本版本保留两道门禁：

1. 执行前展示目标、可执行用例、写请求、高风险和脚本数量，并生成绑定当前用例版本的确认 SHA；确认 SHA 变化必须重新确认。
2. 运行时仅允许登记的 scheme、host、port 和 path；每个 Run 使用独立受限容器，经出口代理访问目标。

## 2. 威胁模型与保护对象

保护对象包括目标环境、请求与响应、平台 Client Token、模型凭证、KEK、数据库、任务产物和宿主机。主要威胁包括：恶意文档或脚本、SSRF、DNS Rebinding、重定向绕过、Host Header 欺骗、跨 Run 数据访问、凭证泄漏、资源耗尽、孤儿容器和日志泄密。

已实施的核心缓解：契约与目标分离；执行定义只保存相对 path 和 `target_id`；Controller 窄协议拒绝命令、宿主路径、任意环境变量及网络模式；出口代理校验目标和 DNS；Executor 无平台/模型/数据库凭证；结果在 Executor、Web 存储、展示和下载前分层脱敏。

## 3. 容器运行时和权限边界

- 一个 `ExecutionRun` 创建一个独立短生命周期 Executor 容器，完成、失败或超时后强制删除。
- API Agent Web 不挂载 Docker Socket，也不具备创建宿主进程或容器的能力。
- 独立 Controller 是唯一挂载 Docker Socket 的组件。Controller 只接受 Run ID、逻辑输入/输出 ID、输入 SHA、固定策略 ID和超时。
- 浏览器不能指定镜像、命令、宿主路径、环境变量、网络模式、capability 或挂载。
- Executor 使用非 root UID 10003、只读根文件系统、`cap_drop=ALL`、`no-new-privileges`、0.5 CPU、256MB 内存、64 PID、32MB 临时目录和执行超时。
- Executor 只读挂载当前 Run 的 `input.json`；输出通过 stdout 由 Controller 原子写入当前 Run 独占目录。

已知高权限边界：Docker Socket 等同宿主高权限，因此 Controller 必须保持独立、内部不可由浏览器访问、部署配置不可编辑，并作为后续渗透测试重点。生产启用前建议迁移到 rootless/隔离运行时或受控容器编排 API。

## 4. 固定镜像、SBOM 和漏洞扫描

- Controller 启动时将部署侧镜像引用解析为不可变 Image ID，创建容器时仅使用该 `sha256` ID。
- 本机试点最终 Executor 镜像 ID：`sha256:02bd3d3a146d37579d387084fe732c3905b14fcfb8bfca3a28c987cb304e6a57`（源码变更重建后须重新记录）。
- 镜像仅包含 Python 标准库和固定 Runner，不包含模型 SDK、数据库驱动、平台 SDK 或目标凭证。
- 已使用 Docker Scout 生成 SPDX SBOM，共索引 124 个包。
- 高危漏洞扫描当前被 Docker Scout 登录要求阻断，**不影响本机试点，但属于生产启用阻断项**。生产前必须完成 CVE 扫描、镜像签名和扫描结果归档，高危漏洞不得放行。

## 5. 目标登记、Egress、DNS、重定向与 SSRF

本机试点只登记以下目标：

| 字段 | 值 |
| --- | --- |
| target_id | `local-platform-dev` |
| 用户展示地址 | `http://127.0.0.1:8080` |
| 容器内部地址 | `http://platform-gateway:80` |
| path 前缀 | `/api/v1/` |
| 方法 | GET、POST、PUT、PATCH、DELETE（由可执行用例决定） |
| 数据属性 | 本机、无生产数据 |

Executor 只连接内部 `api-executor` 网络，通过 Egress Proxy 访问平台默认网络。代理对每次请求重新校验 scheme、host、port、path、Host Header 和 DNS；DNS 前后结果不一致时拒绝。未登记 Host、loopback、link-local、metadata、混淆 IP 和未授权路径均拒绝。重定向由客户端发起的新代理请求再次校验，不能绕过目标登记。

真实负向验证：请求 `169.254.169.254/latest/meta-data` 被拒绝，错误为 `EGRESS_TARGET_NOT_REGISTERED`，未到达 metadata 服务。

## 6. Credential 策略

- 本轮试点仅执行无需登录的健康接口，没有配置目标 Credential。
- Executor 不获得模型凭证、平台 Client Token、KEK、数据库访问或 Controller Token。
- API Agent Web 与 Controller 使用只读文件中的独立随机 Bearer Token进行内部鉴权，并使用恒定时间比较；Token 不进入请求日志或 Run 产物。
- 当前内部 Token 是静态本机 Secret，可通过替换 Secret 文件并重启组件轮换。生产前必须补充自动轮换、双 Token 过渡或工作负载身份方案。
- 后续如测试需鉴权的写接口，必须另行评审最小权限测试账号和注入方式；不得把 Cookie、CSRF Token 或密码写入用例、Run 输入、日志或报告。

## 7. 人工门禁、权限与写操作

- 只有 `api-test-agent.execute` 权限可获取最终执行动作；任务所有权、CSRF 和平台授权仍同时生效。
- 平台管理员、测试开发和测试执行角色均获得最终确认权限。
- 执行预览保存目标摘要、用例 SHA、写请求数、高风险数、脚本数和确认 SHA。
- 写方法已获本机试点授权，但每次 Run 仍需针对当前摘要确认；本次实际验证只调用只读健康接口，没有修改平台数据。
- 高风险用例仍需逐条 Review；含 setup/teardown 脚本的真实 Executor 当前明确拒绝，不执行任意 Python。

## 8. 取消、超时、回收、结果和审计

- Controller 支持按 Run ID取消；终态 Run 不允许覆盖，重试生成新 Run。
- 容器超时返回 `EXECUTION_TIMEOUT` 并在 `finally` 中强制回收；孤儿对账只处理带平台管理标签的 Executor。
- 输入 SHA 不一致返回 `EXECUTION_INPUT_SHA_MISMATCH`；策略 ID 不一致返回 `EXECUTION_POLICY_DENIED`。
- 每次执行保存 Run、CaseResult、耗时、阈值来源、分类和脱敏报告；报告失败不覆盖上游产物。
- 审计不保存文档正文、完整请求响应或 Secret。

## 9. 已完成验证

- Controller 无/错 Token 拒绝，额外 `command`/`environment` 字段拒绝。
- 固定 Image ID、非 root Executor、只读根、能力清空、资源和 PID 限制。
- SSRF、IPv4/IPv6、metadata、Host Header、未登记 path、DNS 和重定向策略负向测试。
- Executor 成功、失败、超时、取消和孤儿回收语义；容器执行后无残留。
- 请求、响应、Header、Cookie、Query、JSON、日志、报告和草稿递归脱敏。
- API 路由权限、CSRF、任务所有权、确认 SHA 失效和创建 Run 前门禁。
- 本机真实链路：API Agent → Controller → 单 Run Executor → Egress Proxy → `GET /api/v1/health/live`，返回 HTTP 200，报告 `passed`，耗时 16ms。
- 真实负向链路：未登记 metadata 目标返回 403，代理拒绝原因可追溯。
- 智能体最终全量测试 109 项、S2 专项测试 20 项、平台后端 17 项均通过（最终全量结果以交付说明为准）。

## 10. 本机启停与应急回滚

- 默认启动不包含 S2 Controller/Proxy，且 `API_EXECUTION_ENABLED=false`。
- 本机试点需显式使用 Compose Profile `s2-execution` 并设置 `API_EXECUTION_ENABLED=true`。
- 紧急停止：将开关恢复为 false，重建 API Agent，并停止 `api-execution-controller`、`api-egress-proxy`；必要时按标签回收 `api-test-agent.managed=true` 的孤儿容器。
- 回滚不删除任务、Run、报告或 Bug 草稿，已有数据改为只读。

## 11. 评审结论和剩余门禁

结论：批准当前用户明确限定的本机、无生产数据、单登记目标试点；允许测试人员在最终确认后执行读写用例。此次批准不扩展到生产环境、其他主机、其他端口或其他 path。

生产或共享测试环境启用前仍必须完成：

1. Docker Socket 风险替代或专项渗透测试；
2. CVE 扫描、镜像签名和扫描报告归档；
3. 自动 Secret 轮换或工作负载身份；
4. 需要鉴权时的最小 Credential 注入设计；
5. HTTPS CONNECT/证书校验方案（当前试点仅 HTTP）；
6. 取消竞态、进程重启和孤儿容器人工演练；
7. 基础设施、安全与数据责任人对目标登记的联合审批。

不得实现或启用外部 Bug 提交、稳定资产发布、生产目标、Postman、gRPC、WebSocket、GraphQL、压测或 P95/P99。

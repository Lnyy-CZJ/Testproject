# 两个 AI 测试智能体独立发布与归档运行手册

## 1. 当前交付状态

当前本机 Release 为 `0.1.0-local.20260817.f1a6260`。功能项目和 API 项目已分别使用新源码目录、新 runtime 和独立镜像运行；旧 `AItestcase_Agents`、旧 runtime 与历史 `output/` 仍保留，未删除、覆盖或改为只读。

首次发布范围固定为可信生成和 Review：

```text
API_EXECUTION_ENABLED=false
DATABASE_PERSIST_ENABLED=false
ALLOWED_TARGETS=[]
API_EXECUTION_TARGETS=[]
```

## 2. 构建与发布

平台主 Compose 只消费镜像，本机构建必须显式叠加 override：

```bash
cd /Users/admin/Testproject/test-platform
docker compose -f docker-compose.yml -f docker-compose.local-build.yml \
  --profile s2-execution --profile s2-build build \
  functional-test-agent api-test-agent api-execution-controller api-egress-proxy api-test-executor-image
```

普通可信生成发布只更新两个 Agent 服务：

```bash
docker compose up -d --no-deps functional-test-agent
docker compose up -d --no-deps api-test-agent
docker compose ps functional-test-agent api-test-agent
```

不得使用 `latest`。API 四镜像必须使用同一 Release；Controller 的 `EXECUTOR_IMAGE` 必须直接使用 `API_EXECUTOR_IMAGE`，不能从平台 `APP_REVISION` 拼接。

## 3. runtime 迁移和校验

功能和 API 必须分两次切换。每次先停止旧服务，再执行 dry-run、复制和 verify：

```bash
python3 /Users/admin/Testproject/functional-test-agent/scripts/migrate_legacy_runtime.py \
  --source /Users/admin/Testproject/AItestcase_Agents/runtime/dev/functional \
  --destination /Users/admin/Testproject/functional-test-agent/runtime/dev/functional \
  --environment dev --dry-run --manifest /tmp/functional-runtime-dry-run.json

python3 /Users/admin/Testproject/functional-test-agent/scripts/migrate_legacy_runtime.py \
  --source /Users/admin/Testproject/AItestcase_Agents/runtime/dev/functional \
  --destination /Users/admin/Testproject/functional-test-agent/runtime/dev/functional \
  --environment dev --manifest /tmp/functional-runtime-migration.json

python3 /Users/admin/Testproject/functional-test-agent/scripts/migrate_legacy_runtime.py \
  --source /Users/admin/Testproject/AItestcase_Agents/runtime/dev/functional \
  --destination /Users/admin/Testproject/functional-test-agent/runtime/dev/functional \
  --environment dev --verify-only
```

API 使用相同参数结构，但脚本、源和目标目录改为 `api-test-agent` 与 `runtime/dev/api`。工具拒绝宽泛路径、符号链接、越界和同名异内容；复制过程不删除源数据。`running` 任务由新服务启动恢复为 `failed/WORKER_INTERRUPTED`，其他 Review 状态原样保留。

## 4. 独立回滚

功能回滚只替换 `FUNCTIONAL_AGENT_IMAGE`：

```bash
FUNCTIONAL_AGENT_IMAGE=<上一功能镜像> docker compose up -d --no-deps functional-test-agent
```

API 回滚前再次确认执行关闭，并把四个变量整体切回同一 Release：

```bash
API_EXECUTION_ENABLED=false \
API_AGENT_IMAGE=<上一API镜像> \
API_EXECUTION_CONTROLLER_IMAGE=<上一Controller镜像> \
API_EGRESS_PROXY_IMAGE=<上一Egress镜像> \
API_EXECUTOR_IMAGE=<上一Executor镜像> \
docker compose --profile s2-execution up -d --no-deps api-test-agent api-execution-controller api-egress-proxy
```

常规回滚不删除新旧 runtime，不合并 Review、Run 或报告字段。若旧代码不能读取新数据，旧服务只能只读访问旧 runtime。

## 5. 旧仓冻结与归档门禁

本次只完成归档准备，不立即冻结。必须同时满足以下条件后才允许归档：

1. 功能项目完成两个稳定 Release；
2. API 项目完成两个稳定 Release；
3. 两边分别完成生产式回滚演练；
4. 旧历史入口已连续保留至少 180 天，且管理员再次批准下线；
5. 已确认归档不包含 `.env`、Secret、runtime、缓存或临时凭据；
6. 历史 `output/` 的文件数和总字节与基线一致。

批准后目标目录固定为：

```text
/Users/admin/Testproject/archive/AItestcase_Agents/ai-agents-split-baseline-20260817/
```

归档应复制而非移动，先生成 SHA 清单并验证，再把目录权限设为 `0555`、普通文件设为 `0444`。源目录和历史入口不得自动删除；删除必须作为新的管理员审批事项执行。

## 6. 发布后检查

```bash
cd /Users/admin/Testproject/test-platform
docker compose config --quiet
docker compose exec -T platform-gateway nginx -t
docker compose ps functional-test-agent api-test-agent
```

应确认两个服务均为 `healthy`，挂载分别指向两个新项目，并再次检查 API 四个安全环境变量。发布清单见 `docs/split-release-manifest.json`，交付文件 SHA 见 `docs/split-delivery-files.json`，runtime 逐文件 SHA 见两个新项目根目录的 `runtime-migration-manifest.json`。

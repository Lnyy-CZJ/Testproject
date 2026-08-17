# 两个 AI 测试智能体独立发布与归档运行手册

## 1. 当前交付状态

当前本机 Release 为 `0.1.1-local.20260817.c99fe11`，服务器 Release 为 `0.1.1-server.20260817.c99fe11`。功能项目和 API 项目分别使用独立源码目录、runtime 和镜像运行；旧单体目录已在完成独立升级、回滚验证后从本机和服务器项目目录移除，删除前基线由 Git tag `ai-agents-split-baseline-20260817` 保留。

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

功能和 API runtime 迁移已经完成，不得在日常发布中重复执行。当前服务分别只使用 `functional-test-agent/runtime/<environment>/functional` 和 `api-test-agent/runtime/<environment>/api`；历史迁移结果由两个项目根目录的 `runtime-migration-dry-run.json` 与 `runtime-migration-manifest.json` 留档。

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

## 5. 旧仓归档与恢复

删除前的 Git 跟踪源码保存在 tag `ai-agents-split-baseline-20260817`。未跟踪的旧 runtime、output 和环境文件不会进入 Git tag，删除前已分别保存为权限 `0600` 的本机与服务器备份；备份可能包含历史凭证，不得上传仓库或对外共享。

需要查看旧源码时，解压到项目目录之外：

```bash
mkdir -p /tmp/ai-agents-split-baseline
git archive ai-agents-split-baseline-20260817 AItestcase_Agents \
  | tar -x -C /tmp/ai-agents-split-baseline
```

不得重新把旧目录接回 Compose；线上回滚继续使用两个独立智能体的不可变镜像和独立 runtime。

## 6. 发布后检查

```bash
cd /Users/admin/Testproject/test-platform
docker compose config --quiet
docker compose exec -T platform-gateway nginx -t
docker compose ps functional-test-agent api-test-agent
```

应确认两个服务均为 `healthy`，挂载分别指向两个新项目，并再次检查 API 四个安全环境变量。发布清单见 `docs/split-release-manifest.json`，交付文件 SHA 见 `docs/split-delivery-files.json`，runtime 逐文件 SHA 见两个新项目根目录的 `runtime-migration-manifest.json`。

# 测试开发平台

该项目是测试工具的统一入口，当前使用 React + TypeScript + Vite、FastAPI、PostgreSQL、Alembic、Nginx 和 Docker Compose。接入工具：

- `TrackEvents_tess`：埋点日志分析；
- `log_filter_tool`：接口日志筛选与统计；
- `Truthy_Search`：检索执行、字段对比与评测报告；
- `Truthy_ApiAutoTest2`：Gateway 接口自动化（任务触发、结果统计、Allure 报告）。

平台负责工具导航、状态探测和反向代理；各工具继续保持独立源码、独立容器和独立测试。本轮不包含登录、RBAC、任务中心、Worker、Redis 或 Celery。

## 目录要求

五个项目保持同级，平台不复制工具业务源码：

```text
Testproject/
├── test-platform/
├── TrackEvents_tess/
├── log_filter_tool/
├── Truthy_Search/
└── Truthy_ApiAutoTest2/
```

`web/` 是升级前静态首页，仅作为回滚资源保留；生产首页来自 `frontend/` 的 Vite 构建产物。

## 启动与迁移

```bash
cd /Users/admin/Testproject/test-platform
cp .env.example .env
# 首次启动前，请修改 .env 中的 POSTGRES_PASSWORD。
docker compose up --build -d
```

默认访问 `http://localhost:8080`。启动流程会等待 PostgreSQL 健康，运行 `alembic upgrade head`，迁移成功后再启动 FastAPI。只有 Nginx 的 `${PLATFORM_PORT:-8080}` 映射到宿主机。

常用命令：

```bash
# 查看服务与一次性迁移容器状态
docker compose ps -a

# 重复执行迁移（应保持幂等）
docker compose run --rm platform-migrate

# 查看平台日志
docker compose logs --tail=100 platform-gateway platform-api platform-db platform-migrate

# 停止服务，保留 PostgreSQL 命名卷
docker compose down

# 明确删除数据库数据（不可恢复，仅在确认重建空库时使用）
docker compose down
docker volume rm platform-db-data
```

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `PLATFORM_PORT` | `8080` | 唯一宿主机映射端口 |
| `POSTGRES_DB` | `test_platform` | 平台数据库名 |
| `POSTGRES_USER` | `platform` | 平台数据库用户 |
| `POSTGRES_PASSWORD` | 本地开发默认值 | 应在 `.env` 中覆盖，禁止提交真实密码 |
| `APP_ENV` | `development` | FastAPI 运行环境 |
| `LOG_LEVEL` | `INFO` | 后端日志级别 |
| `TOOL_HEALTH_TIMEOUT_SECONDS` | `3` | 工具内部健康探测超时秒数 |

`DATABASE_URL` 由 Compose 使用以上数据库变量组装，不进入前端构建。

## 路由

| 路径 | 功能 |
|---|---|
| `/` 及未知 React 页面路由 | React 平台首页 |
| `/api/v1/health/live` | FastAPI 进程存活 |
| `/api/v1/health/ready` | FastAPI 与 PostgreSQL 就绪 |
| `/api/v1/tools` | 数据库驱动的工具目录 |
| `/api/v1/tools/{tool_id}/health` | 平台代理的工具健康状态 |
| `/trackevents/` | 埋点测试工具 |
| `/log-filter/` | 日志分析工具 |
| `/truthy-search/` | 检索评测工具 |
| `/api-autotest/` | 接口自动化工具 |

平台 API 或数据库异常时，React 会显示提示并使用内置的四个基础工具入口；工具链接不会被禁用。

`Truthy_Search` 的平台模式和独立模式会复用同一 SQLite，禁止同时运行。平台启动前应先确认没有 `RUNNING` Run，再停止 `Truthy_Search/compose.yml` 管理的独立 `searchtool` 容器。

`Truthy_ApiAutoTest2` 平台模式的凭证放在 `Truthy_ApiAutoTest2/.env.platform`（挂载为容器内 `.env`，与独立模式的 `.env` 隔离）；任务单槽位串行执行，任务记录、日志与报告均为文件产物，不落平台数据库。

## 测试

```bash
# 前端
cd /Users/admin/Testproject/test-platform/frontend
npm test
npm run build
npm audit --audit-level=high

# 后端
cd /Users/admin/Testproject/test-platform/backend
.venv/bin/pytest

# 平台运行态冒烟
cd /Users/admin/Testproject/test-platform
python3 -m unittest discover -s tests -v

# Nginx
docker compose exec -T platform-gateway nginx -t
```

三个工具继续使用各自项目中的独立测试命令。

## 回滚

React 上线异常时，可临时把 `platform-gateway` 恢复为 `nginx:1.27-alpine`，并重新挂载：

```yaml
volumes:
  - ./web:/usr/share/nginx/html:ro
  - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
  - ./nginx/tool-unavailable.html:/etc/nginx/errors/tool-unavailable.html:ro
```

数据库结构仅通过 Alembic 变更。只回退 Truthy_Search 目录记录时，先停止平台管理的 `truthy-search`，再执行 `docker compose run --rm platform-migrate alembic downgrade -1`。API 或数据库暂时故障不要求回滚其他工具路由。

## 排障

```bash
docker compose config
docker compose ps -a
docker compose logs --tail=200 platform-migrate platform-api platform-db
docker compose logs --tail=200 truthy-search
curl -i http://127.0.0.1:8080/api/v1/health/live
curl -i http://127.0.0.1:8080/api/v1/health/ready
curl -i http://127.0.0.1:8080/api/v1/tools
curl -i http://127.0.0.1:8080/truthy-search/health
curl -i http://127.0.0.1:8080/api-autotest/health
```

`live` 正常但 `ready` 返回 503 时，优先检查 PostgreSQL 和迁移日志。工具不可用时，平台 API 仍以 200 返回 `unhealthy`，其他工具与平台首页应继续可用。

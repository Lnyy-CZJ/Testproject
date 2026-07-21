# BugAgent Python Backend

BugAgent Python 重构版后端服务，基于 FastAPI、SQLAlchemy async、Redis 和 Celery 实现。

当前实现阶段:

- 第零阶段: 契约冻结 + 基础设施
- 第一阶段: 账号、项目、迭代、仓库基础 API
- 第二阶段: 缺陷、状态机、附件、评论、权限
- 第三阶段: Agent 分析、SSE、Token、记忆
- 第四阶段: 修复任务、人工修复、PR 生命周期
- 第五阶段: 信号接入、检索、质量洞察
- 第六阶段: 双跑验证、生产预检、灰度回滚门禁

常用命令:

```bash
python3 -m pytest -q
make dev
make schema-diff DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/bug_agent
make preflight
make dual-run-compare GO_RESPONSE=go.json PY_RESPONSE=python.json
```

## Docker 一键启动

本地 Docker Desktop 启动后，在本目录执行：

```bash
docker compose up -d --build
docker compose ps
```

Compose 会启动前端、FastAPI、PostgreSQL 和 Redis。FastAPI 容器会先自动执行
`alembic upgrade head`，不需要再手动迁移或启动 Python、Node 服务。

- 应用首页: `http://localhost:8080`
- 后端 Swagger: `http://localhost:8765/docs`
- 后端健康检查: `http://localhost:8765/healthz`

停止全部服务：

```bash
docker compose down
```

保留数据卷；只有需要删除本地数据库数据时才执行 `docker compose down -v`。

上线门禁:

- `scripts/preflight_check.py`: 检查生产模式、JWT 密钥、数据库密码和加密密钥。
- `scripts/dual_run_compare.py`: 比较 Go/Python 双跑 JSON 响应，默认忽略时间戳等易变字段。
- `/api/v1/ops/preflight`: 平台管理员可执行的预检接口。
- `/api/v1/ops/dual-run/compare`: 平台管理员可调用的双跑响应比较接口。
- `/api/v1/ops/rollback-plan`: 灰度回滚操作说明。

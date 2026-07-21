.PHONY: dev install test lint migrate schema-diff preflight dual-run-compare

# 安装依赖（含开发依赖）
install:
	pip install -e ".[dev]"

# 启动开发服务器（热重载）
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8765

# 运行测试
test:
	pytest -v --cov=app --cov-report=term

# 代码检查
lint:
	ruff check app/ tests/
	ruff format --check app/ tests/

# 代码格式化
format:
	ruff check --fix app/ tests/
	ruff format app/ tests/

# 数据库迁移
migrate:
	alembic upgrade head

# Schema 兼容性检查
# 用法: make schema-diff DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/bug_agent
schema-diff:
	python3 scripts/schema_diff.py --database-url "$(DATABASE_URL)"

# 生产上线预检
preflight:
	python3 scripts/preflight_check.py --json

# Go/Python 双跑响应比较
# 用法: make dual-run-compare GO_RESPONSE=go.json PY_RESPONSE=python.json
dual-run-compare:
	python3 scripts/dual_run_compare.py --go "$(GO_RESPONSE)" --python "$(PY_RESPONSE)"

# 生成新迁移
migration:
	alembic revision --autogenerate -m "$(msg)"

# Docker 启动
docker-up:
	docker compose up -d

# Docker 停止
docker-down:
	docker compose down

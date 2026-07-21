# BugAgent Web

React + Vite 前端，已接入同仓库的 Python FastAPI 后端。

## 本地启动

先在 `../bug_agent_py` 启动 PostgreSQL、Redis 和 Python API：

```bash
cd /Users/admin/Testproject/bug_agent/bug_agent_py
docker compose up -d postgres redis
python3 -m pip install -e ".[dev]"
alembic upgrade head
make dev
```

再启动前端：

```bash
cd /Users/admin/Testproject/bug_agent/web
npm ci
npm run dev
```

浏览器访问 `http://localhost:5678`。开发服务器会将 `/api` 和 SSE 请求代理到默认的 Python 地址 `http://localhost:8765`。

## 配置

可在 `web/.env.local` 中设置以下变量；该文件只保存本机配置，不应提交密钥。

```dotenv
# 开发代理转发目标，默认 http://localhost:8765
VITE_BACKEND_TARGET=http://localhost:8765

# 前端运行时请求基础路径。使用开发代理时保持默认即可。
VITE_API_BASE_URL=/api/v1
```

部署到独立前端域名时，将 `VITE_API_BASE_URL` 设为可从浏览器访问的 Python API 网关地址，例如 `https://api.example.com/api/v1`；同时在 Python 服务的 CORS 白名单中加入前端域名。SSE 会自动沿用该地址。

## 构建

```bash
npm run build
```

构建产物位于 `dist/`，可由 Nginx 或其他静态服务器托管。反向代理需要将 `/api/` 原样转发到 Python 服务，并关闭 SSE 的响应缓冲。

Python 当前已覆盖账号、项目、迭代、仓库、缺陷、Agent、修复任务、信号和质量洞察主链路。旧 Go 前端中的凭据、协作、通知、RBAC、审计、MCP/Skills、发布与回归页面仍依赖 Python 尚未提供的服务端接口，访问这些页面会收到明确的接口不存在响应，不能视为已迁移完成。

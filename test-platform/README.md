# 测试开发平台 MVP

该项目是测试工具的统一入口。当前接入：

- `TrackEvents_tess`：埋点日志分析；
- `log_filter_tool`：接口日志筛选与统计。

平台只负责首页、服务状态和反向代理。两个工具保持独立源码、独立容器和独立测试。

## 目录要求

本地开发使用同级目录作为 Docker 构建上下文：

```text
Testproject/
├── test-platform/
├── TrackEvents_tess/
└── log_filter_tool/
```

## 启动

需要 Docker 和 Docker Compose。

```bash
cd /Users/admin/Testproject/test-platform
cp .env.example .env
docker compose up --build -d
```

默认访问地址：`http://localhost:8080`。

如需修改平台端口，编辑 `.env` 中的 `PLATFORM_PORT`。

## 常用操作

```bash
# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f

# 重新构建并启动
docker compose up --build -d

# 停止平台
docker compose down
```

`docker compose down` 不会删除两个工具的源码。MVP 默认不持久保存平台收到的日志；日志分析工具的主动导出文件保存在容器临时目录，容器重建后会清除。

## 验证

平台启动后运行：

```bash
python3 -m unittest discover -s tests -v
```

两个工具的独立测试：

```bash
cd /Users/admin/Testproject/TrackEvents_tess
python3 -m unittest discover -p 'test_*.py' -v

cd /Users/admin/Testproject/log_filter_tool
.venv/bin/python -m unittest discover -s tests -v
```

## 对外路由

| 路径 | 功能 |
|---|---|
| `/` | 平台首页 |
| `/trackevents/` | 埋点测试工具 |
| `/trackevents/health` | 埋点工具健康检查 |
| `/log-filter/` | 日志分析工具 |
| `/log-filter/health` | 日志工具健康检查 |

只有平台网关端口映射到宿主机；两个工具端口仅在 Docker 内部网络使用。

## 独立运行兼容

两个工具的基础路径默认均为空，因此原独立启动方式保持不变。平台 Compose 通过环境变量启用子路径：

- `TRACKEVENTS_BASE_PATH=/trackevents`；
- `LOG_FILTER_BASE_PATH=/log-filter`。

## 接入新工具

新工具至少需要：

1. 独立 Dockerfile 和内部端口；
2. 可配置的 URL 基础路径；
3. 不依赖业务数据的轻量健康检查；
4. 页面资源、表单和 API 地址遵循基础路径；
5. 自动化测试和独立启动说明。

接入时只需在平台 Compose 中增加服务、在 Nginx 中增加代理路径，并在首页增加工具卡片和健康检查配置。不要把工具业务源码复制到平台项目。

## 当前限制

- 尚未实现登录、权限和审计；
- 尚未实现统一任务记录和结果汇总；
- 建议仅部署在受控内网；
- 本地构建依赖三个项目保持同级；
- 工具主动导出的日志在容器重建后不会保留。

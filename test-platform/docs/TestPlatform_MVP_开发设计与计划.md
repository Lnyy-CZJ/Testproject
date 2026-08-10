# 测试开发平台 MVP 开发设计与计划

> 文档版本：V1.0  
> 创建日期：2026-07-21  
> 需求依据：[TestPlatform_MVP_PRD.md](./TestPlatform_MVP_PRD.md)  
> 首批接入工具：`TrackEvents_tess`、`log_filter_tool`

---

## 1. 文档目的

本文档将测试开发平台 MVP 的产品需求转换为可实施的技术方案，明确：

- 平台与现有工具的职责边界；
- 工程目录及文件设计；
- Docker Compose 和 Nginx 的服务编排方式；
- 两个工具的子路径适配方案；
- 健康检查、异常处理和安全约束；
- 分阶段开发顺序、测试方案、验收标准和回滚方式。

本阶段坚持最小化改动。平台只提供统一入口、工具导航、状态展示和反向代理，不修改两个工具的核心分析逻辑，也不引入数据库、登录系统或任务中心。

---

## 2. 需求理解与成功标准

### 2.1 核心需求

在 `/Users/admin/Testproject` 下创建与其他工具同级的 `test-platform` 项目，将两个独立 Web 工具聚合到统一入口：

- `/trackevents/`：访问 `TrackEvents_tess`；
- `/log-filter/`：访问 `log_filter_tool`；
- `/`：访问平台首页。

每个工具继续拥有独立源码、依赖、容器和测试。平台通过 Docker 网络访问工具服务，对用户只暴露一个入口端口。

### 2.2 可验证的成功标准

- 一条 Docker Compose 命令可启动平台和两个工具；
- 用户通过一个地址访问平台首页；
- 首页展示两个工具卡片及实时运行状态；
- 两个工具可以在规定子路径下完成现有功能；
- 页面刷新、表单提交、示例日志和 API 调用不会跳出平台路径；
- 停止任一工具不会影响平台首页和另一个工具；
- 两个工具保留默认根路径模式，可以继续独立运行；
- 现有自动化测试全部通过，新增子路径测试通过；
- 工具服务端口不直接映射到宿主机。

### 2.3 交付物

- `test-platform` 平台工程；
- 平台首页及工具状态展示；
- Nginx 统一入口配置；
- Docker Compose 服务编排；
- `TrackEvents_tess` 子路径适配；
- `log_filter_tool` 子路径适配；
- 自动化测试和手工验收记录；
- 平台启动和工具接入说明。

---

## 3. 现状分析

### 3.1 `TrackEvents_tess`

当前实现：

- 使用 Python 标准库 `ThreadingHTTPServer`；
- Web 页面 HTML、CSS、JavaScript 内嵌在 `trackevents_web.py`；
- `GET /` 和 `GET /index.html` 返回页面；
- `GET /favicon.svg` 返回图标；
- `POST /api/analyze` 执行埋点分析；
- 默认监听 `127.0.0.1:8000`；
- 已有 Dockerfile、Docker Compose、健康检查和 Web 测试。

接入风险：

- 页面中的 `/favicon.svg`、`/api/analyze` 是根路径地址；
- HTTP Handler 当前只识别根路径路由；
- 直接代理到 `/trackevents/` 会导致资源或 API 请求被发送到错误位置。

### 3.2 `log_filter_tool`

当前实现：

- 使用 Flask；
- `GET/POST /` 渲染日志筛选页面；
- `GET /sample` 返回示例日志；
- 核心日志解析逻辑与 Flask 路由位于同一个 `app.py`；
- 默认监听 `127.0.0.1:5001`；
- 已有 Dockerfile、Docker Compose 和核心测试。

接入风险：

- Flask 应用当前使用根路由；
- HTML 表单、示例日志地址需要检查是否使用硬编码根路径；
- 需要保证代理前缀不会影响独立运行和现有测试。

### 3.3 设计结论

两个工具均已具备独立 Web 能力，不需要重新开发页面。MVP 只需要：

1. 新增平台静态首页；
2. 新增 Nginx 统一入口；
3. 新增平台级 Docker Compose；
4. 为两个工具增加可配置的基础路径；
5. 增加路由测试和隔离性验证。

---

## 4. 总体技术设计

### 4.1 逻辑架构

```text
                    ┌──────────────────────────┐
                    │         浏览器           │
                    └────────────┬─────────────┘
                                 │ HTTP
                                 ▼
                    ┌──────────────────────────┐
                    │ platform-gateway / Nginx │
                    │ 对外仅暴露平台端口       │
                    └───────┬────────┬─────────┘
                            │        │
                 /trackevents/      /log-filter/
                            │        │
             ┌──────────────▼─┐   ┌──▼────────────────┐
             │ trackevents-web │   │ log-filter-tool   │
             │ 内部端口 8000   │   │ 内部端口 5001     │
             └─────────────────┘   └───────────────────┘

平台根路径 / 由 Nginx 直接返回 platform-web 静态资源。
```

### 4.2 物理部署

MVP 使用一个 Docker Compose 项目和一个内部 bridge 网络：

| 服务 | 职责 | 容器内部端口 | 宿主机映射 |
|---|---|---:|---|
| `platform-gateway` | 首页、反向代理、统一错误处理 | 80 | `${PLATFORM_PORT:-8080}:80` |
| `trackevents-web` | 埋点分析 | 8000 | 不映射 |
| `log-filter-tool` | 日志筛选和统计 | 5001 | 不映射 |

用户默认访问 `http://localhost:8080`。工具只能通过 Docker 内部网络被 Nginx 访问。

### 4.3 职责边界

#### 平台负责

- 工具导航；
- 服务状态展示；
- 路径转发；
- 统一错误页；
- 对外端口；
- 平台启动和服务编排。

#### 工具负责

- 自身页面和业务逻辑；
- 输入校验；
- 业务错误提示；
- 自身健康检查；
- 独立测试；
- 独立运行能力。

#### MVP 明确不负责

- 平台代替工具执行分析；
- 平台保存用户日志；
- 工具之间共享代码；
- 平台统一业务返回结构；
- 平台数据库和用户体系。

---

## 5. 工程与文件设计

### 5.1 父目录结构

```text
/Users/admin/Testproject/
├── test-platform/
├── TrackEvents_tess/
├── log_filter_tool/
├── Truthy_Search/
├── Truthy_ApiAutoTest/
└── ...
```

`test-platform` 与工具项目同级。平台不复制工具代码，开发环境通过同级目录构建工具镜像。

### 5.2 平台项目结构

```text
test-platform/
├── web/
│   ├── index.html            # 平台首页结构
│   ├── styles.css            # 平台样式
│   └── app.js                # 状态探测和页面交互
├── nginx/
│   ├── nginx.conf            # 反向代理、静态资源和错误处理
│   └── tool-unavailable.html # 工具不可用错误页
├── tests/
│   └── smoke_test.py         # 平台入口和工具路由冒烟测试
├── .env.example              # 平台端口等配置模板
├── .gitignore                # 忽略本地配置和临时数据
├── docker-compose.yml        # 三个服务的统一编排
└── README.md                 # 启动、停止、验证和接入说明
```

以上均为实现 MVP 所需文件。若实施前希望进一步压缩文件数量，可将错误页合并到 Nginx 配置、将 CSS 和 JavaScript 内嵌到 `index.html`，但独立文件更便于维护和缓存。不得在本阶段新增平台后端项目。

### 5.3 现有项目修改清单

| 项目 | 文件 | 修改目的 |
|---|---|---|
| `TrackEvents_tess` | `trackevents_web.py` | 支持 `TRACKEVENTS_BASE_PATH`，统一构造页面和 API 路径 |
| `TrackEvents_tess` | `test_trackevents_web.py` | 增加根路径、子路径和健康检查测试 |
| `TrackEvents_tess` | `docker-compose.yml` | 可选：补充基础路径环境变量示例 |
| `log_filter_tool` | `app.py` | 支持 `APPLICATION_ROOT` 或 Blueprint URL 前缀，增加健康检查 |
| `log_filter_tool` | `templates/index.html` | 使用 `url_for` 生成表单和示例日志地址 |
| `log_filter_tool` | `tests/test_log_filter.py` | 增加根路径、子路径和健康检查测试 |
| `log_filter_tool` | `docker-compose.yml` | 可选：补充基础路径环境变量示例 |

不修改两个工具的核心解析、统计和分析函数。

---

## 6. URL 与反向代理设计

### 6.1 对外路由

| 方法 | 对外路径 | 目标 | 预期结果 |
|---|---|---|---|
| GET | `/` | 平台静态首页 | 200 HTML |
| GET | `/styles.css` | 平台静态资源 | 200 CSS |
| GET | `/app.js` | 平台静态资源 | 200 JavaScript |
| GET | `/health/tools` | Nginx 聚合层或前端独立探测 | JSON 或状态结果 |
| GET | `/trackevents/` | `trackevents-web` | 200 HTML |
| GET | `/trackevents/favicon.svg` | `trackevents-web` | 200 SVG |
| GET | `/trackevents/health` | `trackevents-web` | 200 JSON |
| POST | `/trackevents/api/analyze` | `trackevents-web` | 分析结果 JSON |
| GET | `/log-filter/` | `log-filter-tool` | 200 HTML |
| POST | `/log-filter/` | `log-filter-tool` | 筛选结果 HTML |
| GET | `/log-filter/sample` | `log-filter-tool` | 示例日志文本 |
| GET | `/log-filter/health` | `log-filter-tool` | 200 JSON |

### 6.2 末尾斜杠规则

- `/trackevents` 永久或临时重定向到 `/trackevents/`；
- `/log-filter` 重定向到 `/log-filter/`；
- 页面和接口统一使用带前缀的绝对路径；
- Nginx 配置必须明确 `location /trackevents/` 和 `location /log-filter/`，避免前缀误匹配。

### 6.3 代理头

Nginx 转发时至少设置：

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Prefix /trackevents;
```

`log-filter` 路由使用对应的 `/log-filter` 前缀。MVP 工具以配置的基础路径为主，`X-Forwarded-Prefix` 用于保留标准代理语义和后续扩展。

### 6.4 路径转发策略

推荐让上游服务直接识别完整子路径：

```text
/trackevents/api/analyze
        │
        └── 原样转发到 trackevents-web:8000/trackevents/api/analyze
```

原因：

- 浏览器地址、Nginx 地址和应用路由保持一致；
- 工具生成的页面 URL 容易验证；
- 避免 Nginx 去前缀后，工具重定向回根路径；
- 后续接入鉴权时可以按工具前缀配置规则。

独立运行模式下基础路径默认为空字符串，原有 `/` 和 `/api/analyze` 路由保持不变。

---

## 7. `TrackEvents_tess` 适配设计

### 7.1 配置设计

新增环境变量：

| 变量 | 默认值 | 平台模式值 | 说明 |
|---|---|---|---|
| `TRACKEVENTS_HOST` | `127.0.0.1` | `0.0.0.0` | 监听地址 |
| `TRACKEVENTS_PORT` | `8000` | `8000` | 服务端口 |
| `TRACKEVENTS_BASE_PATH` | 空字符串 | `/trackevents` | URL 基础路径 |

基础路径规范化规则：

- 空值表示根路径模式；
- 非空值必须以 `/` 开头；
- 末尾 `/` 在内部统一去除；
- 禁止包含查询参数、协议、域名、`..` 或重复斜杠；
- 非法配置应在启动时抛出明确异常，不静默修正危险值。

### 7.2 路由设计

通过一个路径拼接函数生成路由：

```text
route("/")             → /trackevents/
route("/favicon.svg")  → /trackevents/favicon.svg
route("/health")       → /trackevents/health
route("/api/analyze")  → /trackevents/api/analyze
```

根路径模式下：

```text
route("/")             → /
route("/api/analyze")  → /api/analyze
```

### 7.3 页面地址设计

内嵌 HTML 中以下地址必须由基础路径生成：

- favicon 地址；
- JavaScript `fetch` 分析接口地址；
- 返回平台链接。

为避免在大型 HTML 字符串中执行不安全的多次替换，推荐使用少量明确占位符，例如：

```text
__BASE_PATH__
__ANALYZE_URL__
__FAVICON_URL__
```

服务返回 HTML 前统一替换。替换值来自已验证的基础路径，不接受用户请求参数。

### 7.4 健康检查

新增 `GET {BASE_PATH}/health`：

```json
{
  "status": "ok",
  "service": "trackevents"
}
```

健康检查只验证 Web 进程能够响应，不读取默认日志、不执行完整分析，也不依赖外部服务。

### 7.5 兼容性要求

- 未设置 `TRACKEVENTS_BASE_PATH` 时，所有现有地址不变；
- 原 Dockerfile 的容器健康检查可以继续访问根路径，或改为独立的 `/health`；
- 平台 Compose 覆盖基础路径，不要求修改开发者本地配置；
- 不改变 `analyze_log_text`、`resolve_log_text` 的业务行为和返回结构。

### 7.6 测试用例

- 空基础路径返回原首页；
- `/api/analyze` 在根路径模式正常；
- `/trackevents/` 返回页面；
- 页面中的 favicon 和 API 地址包含 `/trackevents`；
- `/trackevents/api/analyze` 正常返回；
- `/api/analyze` 在平台模式下返回 404；
- `/trackevents/health` 返回固定健康状态；
- 非法基础路径启动失败；
- 原有核心分析测试全部通过。

---

## 8. `log_filter_tool` 适配设计

### 8.1 配置设计

新增环境变量：

| 变量 | 默认值 | 平台模式值 | 说明 |
|---|---|---|---|
| `LOG_FILTER_HOST` | `127.0.0.1` | `0.0.0.0` | 监听地址 |
| `LOG_FILTER_PORT` | `5001` | `5001` | 服务端口 |
| `LOG_FILTER_BASE_PATH` | 空字符串 | `/log-filter` | URL 基础路径 |

基础路径使用与 `TrackEvents_tess` 一致的格式规则，降低后续工具接入的认知成本。

### 8.2 Flask 路由方案

推荐使用 Blueprint 注册前缀：

```text
create_app()
  └── 创建 Blueprint
        ├── GET/POST /
        ├── GET /sample
        └── GET /health
  └── app.register_blueprint(blueprint, url_prefix=BASE_PATH)
```

选择 Blueprint 的原因：

- Flask 原生支持；
- 路由前缀行为明确；
- `url_for` 可自动生成带前缀地址；
- 默认空前缀可保持原有路由；
- 不依赖代理中间件猜测 `SCRIPT_NAME`。

不新建额外 Python 模块，直接在现有 `app.py` 内做局部调整，保持当前小型项目结构。

### 8.3 模板修改

模板中所有内部地址使用 `url_for`：

- 表单提交地址使用首页路由；
- 示例日志请求使用 sample 路由；
- 健康检查不需要在业务页面调用；
- 返回平台地址可由环境变量或固定相对跳转提供。

不得在 JavaScript 或 HTML 中硬编码 `/sample`、`/` 等根路径。

### 8.4 健康检查

新增 `GET {BASE_PATH}/health`：

```json
{
  "status": "ok",
  "service": "log-filter"
}
```

健康检查不读取示例日志，不执行日志解析。

### 8.5 启动参数

本地直接执行 `app.py` 时，读取：

- `LOG_FILTER_HOST`；
- `LOG_FILTER_PORT`；
- `LOG_FILTER_BASE_PATH`。

调试模式不应在容器或共享测试环境默认开启。Docker 启动方式保持当前架构，不在本期引入 Gunicorn；若后续面向多人长期使用，再单独评估生产 WSGI 服务。

### 8.6 兼容性要求

- 未配置基础路径时，`GET/POST /` 和 `GET /sample` 保持不变；
- 现有解析函数和统计函数不修改；
- 现有模板展示结果不改变；
- 平台模式下所有表单和请求保持 `/log-filter` 前缀；
- 文件大小限制保持现有配置。

### 8.7 测试用例

- 根路径模式首页 GET 正常；
- 根路径模式表单 POST 正常；
- 根路径模式 `/sample` 正常；
- 平台模式 `/log-filter/` GET 正常；
- 平台模式 `/log-filter/` POST 正常；
- HTML 中的表单和示例地址包含 `/log-filter`；
- `/log-filter/sample` 正常；
- `/log-filter/health` 返回固定健康状态；
- 平台模式下根路径业务路由返回 404；
- 现有日志解析测试全部通过。

---

## 9. 平台首页设计

### 9.1 页面结构

```text
┌──────────────────────────────────────────────┐
│ 测试开发平台                  平台版本 V0.1 │
├──────────────────────────────────────────────┤
│ 统一管理测试工具、自动化能力和测试资产       │
│                                              │
│ ┌────────────────┐  ┌─────────────────────┐ │
│ │ 埋点测试       │  │ 日志分析            │ │
│ │ ● 正常         │  │ ● 正常              │ │
│ │ 检查事件与参数 │  │ 筛选接口并统计状态  │ │
│ │ [进入工具]     │  │ [进入工具]          │ │
│ └────────────────┘  └─────────────────────┘ │
│                                              │
│ 即将接入：测试 Agent、接口自动化、用例管理   │
└──────────────────────────────────────────────┘
```

### 9.2 工具配置

MVP 工具数量只有两个，直接在 `app.js` 中维护静态配置：

```javascript
[
  {
    id: "trackevents",
    name: "埋点测试",
    path: "/trackevents/",
    healthPath: "/trackevents/health"
  },
  {
    id: "log-filter",
    name: "日志分析",
    path: "/log-filter/",
    healthPath: "/log-filter/health"
  }
]
```

此处不新增工具注册后端或动态配置文件。工具数量明显增加、出现权限差异后，再迁移为平台 API 返回配置。

### 9.3 状态探测

页面加载时对两个健康地址分别发送 GET 请求：

- 初始状态：`检测中`；
- HTTP 200 且响应格式有效：`正常`；
- 超时、网络错误或非 200：`异常`；
- 单个请求超时建议 3 秒；
- 状态探测失败不阻止用户点击工具入口。

MVP 不需要 `/health/tools` 聚合后端。前端直接调用同域健康接口更简单，并能准确反映 Nginx 到上游服务的完整链路。

### 9.4 可访问性与响应式

- 工具入口使用语义化链接或按钮；
- 状态不能只依赖颜色，同时显示文字；
- 键盘可聚焦并进入工具；
- 手机和窄屏下工具卡片改为单列；
- 不使用大型前端框架和外部 CDN。

---

## 10. Nginx 设计

### 10.1 静态资源

- `/` 返回 `web/index.html`；
- `/styles.css` 和 `/app.js` 返回对应资源；
- 未命中的平台静态资源返回 404，不回退到首页；
- 为 HTML 禁止长期缓存，为版本稳定的 CSS/JS 设置短期缓存即可。

### 10.2 工具代理

核心行为：

- `/trackevents/` 转发到 `trackevents-web:8000`；
- `/log-filter/` 转发到 `log-filter-tool:5001`；
- 连接超时使用较短值；
- 读取超时需要允许用户提交较大日志并完成分析，建议初始设置 60 秒；
- 保留请求体，支持 POST；
- 关闭 Nginx 版本信息；
- 设置合理的 `client_max_body_size`，与工具现有 25 MB 限制保持一致。

### 10.3 错误处理

上游连接失败或超时时返回统一错误页：

- HTTP 状态保持 502 或 504；
- 页面显示“工具暂时不可用”；
- 提供返回平台首页和重试链接；
- 不显示上游容器名、IP 或内部端口；
- API 请求发生上游错误时应尽量保留 JSON 或 HTTP 错误语义，避免用 HTML 覆盖所有 API 错误。

实现时可根据请求路径区分页面与 API：页面使用友好错误页，API 保持标准 502/504 响应。

### 10.4 安全响应头

MVP 建议增加：

```text
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
Referrer-Policy: same-origin
```

内容安全策略需要结合两个现有内嵌页面验证后再启用，避免未经验证就阻断内联脚本或样式。

---

## 11. Docker Compose 设计

### 11.1 构建上下文

平台 Compose 位于 `test-platform`，本地开发时引用同级目录：

```text
trackevents-web.build.context = ../TrackEvents_tess
log-filter-tool.build.context = ../log_filter_tool
```

平台网关使用官方 Nginx 轻量镜像，挂载或复制平台静态文件和配置。

### 11.2 环境变量

`trackevents-web`：

```dotenv
TRACKEVENTS_HOST=0.0.0.0
TRACKEVENTS_PORT=8000
TRACKEVENTS_BASE_PATH=/trackevents
```

`log-filter-tool`：

```dotenv
LOG_FILTER_HOST=0.0.0.0
LOG_FILTER_PORT=5001
LOG_FILTER_BASE_PATH=/log-filter
```

平台：

```dotenv
PLATFORM_PORT=8080
```

### 11.3 服务依赖

- 网关可以声明依赖两个工具服务启动；
- `depends_on` 不能替代运行时健康检查；
- 工具服务启动慢时，网关应先正常提供平台首页，工具卡片显示检测中或异常；
- 工具恢复后，无需重启网关即可重新访问。

### 11.4 健康检查

容器健康检查分别访问：

- `http://127.0.0.1:8000/trackevents/health`；
- `http://127.0.0.1:5001/log-filter/health`。

网关健康检查访问自身根路径或单独的静态健康文件。健康检查命令应使用镜像内已有工具，避免仅为健康检查安装额外依赖。

### 11.5 数据与日志

- MVP 不挂载用户上传日志目录；
- `TrackEvents_tess/default.log` 如仍需使用，只读挂载；
- 容器标准输出由 Docker 管理；
- 不在平台仓库保存工具输出；
- 不设置固定 `container_name`，避免多个开发者或多个 Compose 项目发生命名冲突。

---

## 12. 安全与文件管理设计

### 12.1 请求限制

- Nginx `client_max_body_size` 与工具上限统一为 25 MB；
- 工具继续执行自己的输入校验；
- 请求超时后不在平台保存请求正文；
- 不允许通过 URL 参数传递 Token 或敏感配置。

### 12.2 文件处理

两个现有工具的主要输入是日志文本。MVP 默认按请求处理，不建立公共文件中心：

- 浏览器提交的日志仅在请求处理期间存在；
- 平台网关不落盘请求体，Nginx 必要的临时缓冲由运行环境管理；
- 不新增共享 volume；
- 默认日志文件仅作为工具示例或开发数据；
- `.env`、日志、分析输出和临时文件禁止提交 Git。

### 12.3 网络暴露

- 宿主机只暴露平台端口；
- 工具端口使用 Compose `expose` 或仅依靠容器网络；
- 生产或共享测试环境部署在受控内网；
- 在统一登录上线前，不建议直接暴露到公网。

### 12.4 敏感信息

- 平台首页不包含任何凭证；
- Nginx 错误页不暴露内部服务信息；
- 工具日志不得打印完整用户输入；
- 若后续保存任务结果，必须先设计访问控制和保留周期。

---

## 13. 测试设计

### 13.1 测试分层

| 层级 | 目标 | 执行方式 |
|---|---|---|
| 工具单元测试 | 核心分析逻辑无回归 | 运行现有测试 |
| 工具路由测试 | 根路径和基础路径均可用 | Flask test client / HTTP Server 测试 |
| 平台静态检查 | 首页资源和链接正确 | 文件检查或轻量 HTTP 测试 |
| 代理集成测试 | Nginx 可转发 GET/POST | 启动 Compose 后执行 HTTP 请求 |
| 隔离性测试 | 单工具失败不影响整体 | 分别停止工具容器 |
| 手工业务回归 | 页面交互和真实日志处理正常 | 浏览器验证 |

### 13.2 修复与改造测试顺序

对子路径兼容改造采用以下顺序：

1. 先增加能够证明根路径现状的测试；
2. 增加平台子路径预期测试，确认改造前失败；
3. 实施最小路由修改；
4. 运行新增测试确认子路径生效；
5. 运行全部现有测试确认无回归；
6. 启动平台执行端到端验证。

### 13.3 自动化冒烟测试

平台冒烟测试至少覆盖：

```text
GET  /                              → 200
GET  /trackevents/                  → 200
GET  /trackevents/health            → 200 + status=ok
POST /trackevents/api/analyze       → 200 或可预期业务响应
GET  /log-filter/                   → 200
GET  /log-filter/health             → 200 + status=ok
GET  /log-filter/sample             → 200
POST /log-filter/                   → 200
GET  /unknown                       → 404
```

### 13.4 隔离性测试

1. 启动全部服务并确认两个工具状态正常；
2. 停止 `trackevents-web`；
3. 确认平台首页和 `/log-filter/` 正常；
4. 确认埋点工具显示异常或返回友好错误；
5. 恢复 `trackevents-web`；
6. 对 `log-filter-tool` 执行相同验证。

### 13.5 回归测试命令原则

实际命令以项目现有 README 和依赖环境为准。开发过程中应记录：

- 执行命令；
- Python 版本；
- 测试总数；
- 通过和失败数量；
- Docker Compose 版本；
- 手工测试使用的浏览器版本。

---

## 14. 开发实施计划

### 14.1 阶段 0：基线确认

目标：在修改前确认两个工具当前状态可复现、可测试。

任务：

1. 检查工作区 Git 状态，避免覆盖用户已有修改；
2. 按两个项目现有方式运行自动化测试；
3. 独立启动两个工具并记录首页、API 和示例日志行为；
4. 记录当前端口、依赖和 Docker 构建结果；
5. 确认平台默认端口使用 `8080`。

完成标准：

- 两个工具的测试基线明确；
- 现有失败被记录并与本次改造区分；
- 现有页面和 API 可独立访问。

### 14.2 阶段 1：`TrackEvents_tess` 子路径适配

目标：同时支持根路径模式和 `/trackevents` 平台模式。

任务：

1. 为现有根路径行为补充测试；
2. 增加平台子路径失败测试；
3. 增加基础路径读取和校验；
4. 调整 Handler 路由匹配；
5. 调整 HTML 中 favicon 和分析接口地址；
6. 增加健康检查；
7. 运行核心及 Web 全量测试；
8. 独立启动验证根路径兼容。

完成标准：

- 根路径和子路径测试均通过；
- 核心分析代码没有修改；
- 原 Docker 独立启动能力保留。

### 14.3 阶段 2：`log_filter_tool` 子路径适配

目标：同时支持根路径模式和 `/log-filter` 平台模式。

任务：

1. 为现有 Flask 路由补充基线测试；
2. 增加平台子路径失败测试；
3. 在现有 `app.py` 内使用 Blueprint 注册可配置前缀；
4. 模板内部地址改为 `url_for`；
5. 增加健康检查；
6. 调整启动环境变量；
7. 运行全量测试；
8. 独立启动验证根路径兼容。

完成标准：

- 根路径和子路径测试均通过；
- 日志过滤和统计函数没有修改；
- 页面 GET、POST 和 sample 功能正常。

### 14.4 阶段 3：平台骨架

目标：实现平台首页、Nginx 统一入口和 Compose 编排。

任务：

1. 创建同级 `test-platform` 工程；
2. 实现静态首页、工具卡片和响应式样式；
3. 实现前端健康状态探测；
4. 配置 Nginx 静态资源和两个代理路径；
5. 配置统一错误页、请求大小和代理超时；
6. 编写平台级 Docker Compose；
7. 只暴露平台端口；
8. 添加 `.env.example`、`.gitignore` 和 README。

完成标准：

- Compose 可以成功构建和启动；
- 首页显示两个工具及正确状态；
- 两个工具入口和业务操作正常。

### 14.5 阶段 4：集成验证

目标：确认整体功能、隔离性和安全约束符合 PRD。

任务：

1. 执行平台冒烟测试；
2. 浏览器验证工具页面和业务流程；
3. 验证页面刷新和末尾斜杠跳转；
4. 分别停止工具服务，验证故障隔离；
5. 检查宿主机端口暴露；
6. 检查错误页是否泄露内部信息；
7. 检查 25 MB 请求限制；
8. 运行两个工具全部回归测试。

完成标准：

- PRD 验收项全部通过；
- 无未说明的回归；
- 测试记录完整。

### 14.6 阶段 5：文档与交付

目标：确保其他开发者可以启动、验证和接入新工具。

任务：

1. 完善平台 README；
2. 记录启动、停止、重建和查看日志命令；
3. 记录两个工具独立运行方式；
4. 编写新工具接入检查清单；
5. 记录已知限制和第二阶段建议。

完成标准：

- 新环境按 README 可以完成启动；
- 不依赖口头说明即可完成基础排障。

---

## 15. 任务拆分与依赖关系

| 编号 | 任务 | 依赖 | 预计复杂度 | 主要产出 |
|---|---|---|---|---|
| T0 | 基线检查 | 无 | 小 | 基线测试记录 |
| T1 | TrackEvents 路由测试 | T0 | 小 | 失败测试和兼容测试 |
| T2 | TrackEvents 子路径适配 | T1 | 中 | 路由、HTML、健康检查 |
| T3 | Log Filter 路由测试 | T0 | 小 | 失败测试和兼容测试 |
| T4 | Log Filter 子路径适配 | T3 | 中 | Blueprint、模板、健康检查 |
| T5 | 平台首页 | 无 | 小 | HTML/CSS/JS |
| T6 | Nginx 配置 | T2、T4 | 中 | 统一路由和错误处理 |
| T7 | Compose 编排 | T2、T4、T6 | 中 | 一键启停配置 |
| T8 | 平台冒烟测试 | T7 | 小 | HTTP 集成测试 |
| T9 | 隔离与安全验证 | T7 | 小 | 验收记录 |
| T10 | README 和接入说明 | T8、T9 | 小 | 交付文档 |

建议执行主线：

```text
T0 → T1 → T2 ┐
              ├→ T6 → T7 → T8 → T9 → T10
T0 → T3 → T4 ┘
        T5 ───┘
```

在单人开发场景中按表格顺序完成即可，不需要为 MVP 增加额外的项目管理系统。

---

## 16. 风险评估与缓解措施

### 16.1 路由兼容风险

风险：子路径改造导致工具独立模式失效。

缓解：

- 基础路径默认空字符串；
- 修改前先补根路径测试；
- 根路径与子路径测试同时保留；
- 不删除原有路由行为。

### 16.2 Flask 前缀风险

风险：仅设置 `APPLICATION_ROOT` 并不会自动为所有路由增加前缀。

缓解：使用 Blueprint 明确注册 `url_prefix`，模板统一通过 `url_for` 生成内部地址。

### 16.3 内嵌 HTML 地址风险

风险：`TrackEvents_tess` 的内嵌 HTML 存在遗漏的根路径地址。

缓解：

- 使用 `rg` 检索 `href="/`、`src="/`、`fetch('/` 等模式；
- 地址集中通过占位符注入；
- 增加返回 HTML 内容断言和浏览器验证。

### 16.4 容器构建上下文风险

风险：平台 Compose 依赖同级目录结构，移动项目后构建失败。

缓解：

- README 明确本地目录要求；
- MVP 接受同级目录约束；
- 后续测试环境改为使用版本化镜像。

### 16.5 健康状态误判

风险：前端网络错误或浏览器缓存造成状态不准确。

缓解：

- 健康接口禁用缓存；
- 设置短超时；
- 显示“状态仅代表服务可访问”；
- 状态异常时仍允许用户尝试进入。

### 16.6 大日志请求风险

风险：大请求占用内存或触发代理错误。

缓解：

- 网关与工具统一 25 MB 限制；
- 设置代理超时；
- 错误信息明确提示大小限制；
- MVP 不持久化日志。

---

## 17. 回滚方案

### 17.1 工具代码回滚

工具适配必须保持默认根路径行为。若平台模式出现问题：

1. 停止平台 Compose；
2. 按各工具原 Docker Compose 或 Python 命令独立启动；
3. 不设置基础路径环境变量；
4. 使用原端口访问工具。

由于核心业务函数不修改，回滚只涉及路由和部署层。

### 17.2 平台配置回滚

- Nginx 与 Compose 均在新建的 `test-platform` 项目内；
- 删除或停止平台容器不会修改工具数据；
- 工具项目不依赖平台项目才能启动；
- 回滚平台配置时保留测试记录，避免重复引入同类路由问题。

### 17.3 数据恢复

MVP 不建立平台数据库，也不持久保存用户日志，因此没有数据库迁移和数据回滚步骤。默认日志文件只读挂载，不应被平台修改。

---

## 18. 新工具接入约定草案

完成 MVP 后，新工具接入时填写以下信息：

```yaml
id: example-tool
name: 示例工具
description: 工具用途说明
base_path: /example-tool
internal_port: 8000
health_path: /example-tool/health
docker_build_context: ../example-tool
```

接入检查项：

- [ ] 项目与平台同级或提供独立镜像；
- [ ] 可独立启动；
- [ ] 支持可配置基础路径；
- [ ] 页面资源和 API 不硬编码根路径；
- [ ] 提供轻量健康检查；
- [ ] 提供 Dockerfile；
- [ ] 明确端口、请求大小和超时；
- [ ] 明确是否保存文件及其清理策略；
- [ ] 不要求复制业务源码到平台；
- [ ] 有基本自动化测试。

该 YAML 仅用于说明未来配置字段，MVP 不需要实现动态读取或创建该文件。

---

## 19. 后续演进边界

MVP 完成后，建议按以下顺序演进：

1. 增加 `platform-api`，实现用户登录和统一会话；
2. 建立用户、角色、工具权限和审计日志；
3. 定义统一任务协议：提交、运行中、成功、失败、取消；
4. 建立任务记录和结果索引；
5. 接入耗时型工具和测试 Agent；
6. 建设报告中心和通知能力；
7. 接入测试用例管理和接口自动化。

在进入第二阶段之前，不应在 MVP 静态首页中模拟登录、任务或权限数据，以免形成后续难以兼容的临时协议。

---

## 20. 开发完成自检清单

### 架构与范围

- [ ] 平台与工具项目保持同级；
- [ ] 平台未复制工具业务代码；
- [ ] 未引入数据库或不必要的后端框架；
- [ ] 只修改了路由、模板、健康检查和部署相关代码；
- [ ] 两个工具仍可独立运行。

### 代码质量

- [ ] 新增配置和关键路径逻辑有清晰注释；
- [ ] 函数参数、返回值和异常行为有说明；
- [ ] 未添加重复或与当前任务无关的辅助代码；
- [ ] 代码风格与各自项目保持一致；
- [ ] 环境变量有默认值和文档。

### 功能与测试

- [ ] 平台首页和两个工具入口正常；
- [ ] 根路径与子路径测试通过；
- [ ] 现有测试全部通过；
- [ ] GET、POST、favicon、sample 和 analyze 均已验证；
- [ ] 单工具异常不会影响其他服务；
- [ ] 平台只暴露一个宿主机端口。

### 安全与文件

- [ ] 请求大小限制有效；
- [ ] 错误页不暴露内部信息；
- [ ] 日志和环境变量未提交 Git；
- [ ] 没有新增不必要的持久化目录；
- [ ] 共享环境未开启 Flask debug 模式。

---

## 21. 最终验收结论模板

```text
任务目标：将 TrackEvents_tess 与 log_filter_tool 聚合到测试开发平台 MVP。

验收结果：
  [ ] 平台统一入口可访问
  [ ] 两个工具均可从平台进入并完成核心操作
  [ ] 工具健康状态显示正确
  [ ] 任一工具停止不影响其他服务
  [ ] 两个工具独立运行能力保留
  [ ] 自动化测试全部通过
  [ ] 安全与文件管理检查通过

测试环境：
  - 操作系统：
  - Docker 版本：
  - Docker Compose 版本：
  - Python 版本：
  - 浏览器版本：

已知限制：
  - MVP 未实现登录和权限；
  - MVP 未保存统一任务记录；
  - MVP 在受控内网中使用；
  - 本地构建依赖规定的同级目录结构。

结论：通过 / 有条件通过 / 不通过
```


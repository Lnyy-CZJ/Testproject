# 05 · 模块详解：web_app.py（Flask Web 应用）

文件：[web_app.py](../../web_app.py)（约 3386 行）
模板：[templates/](../../templates)（24 个） · 静态资源：[static/](../../static)（app.css / app.js）

## 1. 职责与架构风格

searchTool v1.3 的**本地单用户 Web 入口**：导入数据集/历史结果、调用检索接口采集 Run、字段处理、人工复核、生成静态 HTML/Excel 报告。

- **单体工厂模式**：全部 39 条路由注册在 `create_app()`（行 321–3348）内部，闭包引用 `store / service / coordinator`，无 Blueprint；
- 数据层委托 `AnalysisStore` + `AnalysisService`；真实检索调用委托 `search_tool.SearchClient / Config`；
- 支持平台模式挂载：`SEARCH_WEB_BASE_PATH` 前缀 + WSGI 中间件（独立模式 `/`，测试平台模式 `/truthy-search`）。

## 2. 类

| 类 | 行号 | 职责 |
|---|---|---|
| `BasePathMiddleware` | 111–136 | 纯 WSGI 中间件：平台模式下剥离 base_path 前缀写 `SCRIPT_NAME`；不匹配路径返回不含内部信息的 404 |
| `RunCoordinator` | 224–318 | 后台执行器（见第 5 节） |

模块级纯函数：`normalize_base_path`（80，拒绝 `..`、`://`、`?`、`#`、`\`、重复斜杠）、`_project_path`（139）、`_positive_int`（146）、`_threshold_form_payload`（156，表单键 `threshold__<stage>__<field>` 还原为服务层结构）、`_boolean_value`（171）、`_format_datetime`（186，统一展示时区 `YYYY-MM-DD HH:mm:ss`）。

文件级常量（57–77）：`TERMINAL_RUN_STATUSES`（COMPLETED/PARTIAL_FAILED/FAILED/INTERRUPTED）、`QUERY_STAGES`（FULL_NAME、FULL_NAME_SOCIAL）、`ALLOWED_UPLOAD_SUFFIXES`（.jsonl/.json/.xlsx）、`REPORT_TYPES`（SINGLE/COMPARE）、`REPORT_STATUSES`（READY/STALE/FAILED）。

## 3. create_app 初始化流程（321–433）

1. **配置加载**（335–413）：`SEARCH_ENV_FILE` 覆盖 > 进程环境 > 默认 `.env`；`dotenv_values` 读取不注入 `os.environ`；`setting()` 闭包按"显式覆盖 > 进程环境 > env 文件 > 默认值"四级优先级；
2. **关键 app.config**：

| 配置键 | 默认值 |
|---|---|
| `SECRET_KEY` | `"local-searchtool-v1.3"`（`SEARCH_WEB_SECRET_KEY` 覆盖） |
| `SEARCH_DATA_DIR / SEARCH_DB_FILE` | `data` / `data/searchtool_v1_3.db` |
| `SEARCH_IMPORT_DIR / SEARCH_RAW_DIR` | `data/imports` / `data/raw` |
| `SEARCH_REPORT_DIR` | `output/reports` |
| `SEARCH_REPORT_EXCEL_ENABLED` | `True` |
| `SEARCH_DISPLAY_TIMEZONE` | `Asia/Shanghai`（IANA 校验，非法回退） |
| `SEARCH_WEB_HOST / SEARCH_WEB_PORT` | `127.0.0.1` / `5002` |
| `SEARCH_WEB_BASE_PATH / PLATFORM_HOME_URL` | `""` / `""` |
| `MAX_CONTENT_LENGTH` | 50MB（`SEARCH_WEB_MAX_UPLOAD_BYTES`） |

3. **base path 中间件**（409–413）：非空时包裹 `app.wsgi_app`；
4. **装配**（415–433）：`AnalysisStore.initialize()` → `AnalysisService(...)` → `ensure_default_field_schema()` + `ensure_default_field_schema_v3()`（保留历史 v2 快照再建 v3）→ `recover_interrupted_runs()` → `RunCoordinator(service, env_file)`；全部挂到 `app.extensions`；
5. **模板过滤器**：`status_class`（607，状态→视觉等级）、`format_datetime`（646）、`is_http_url`（652，仅 http/https 可点击）、`is_image_url`（661，图片扩展名白名单）。

## 4. 路由清单（39 条 + 3 个错误处理器）

### 4.1 健康检查与首页

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | JSON 探活（`SELECT 1`）；SQLite 异常返回 503，不暴露细节 |
| GET | `/` | `index.html`：Evaluation 汇总 + 最近 10 份报告 |

### 4.2 Evaluation（评测）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/evaluations/new` | 创建评测并绑定 ACTIVE 阈值方案 |
| GET | `/evaluations/<evaluation_id>` | 详情：Run 列表、可选 Dataset、关联报告、阈值快照 |
| POST | `/evaluations/<id>/threshold-profile` | 更换方案快照（仅影响新报告） |
| POST | `/evaluations/<id>/thresholds` | 直接编辑参考线阈值；非法提交不覆盖旧值 |

### 4.3 Run 采集与状态

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/evaluations/<id>/runs` | 创建 PENDING Run 并立即 `coordinator.submit`；`ActiveRunError` → 409 |
| GET | `/runs/<run_id>` | Run 详情：Query 分页（50/页）+ 过滤 + 排序白名单；最近 20 条 failures、字段配置、历史 Process、Baseline、人物关联摘要、字段对齐问题 |
| POST | `/runs/<run_id>/evaluation-phase` | 人工补录评估阶段 |
| GET/POST | `/runs/<run_id>/person-links` | 人物关联页：精确姓名建议 + 本地过滤；批量或逐行提交；乐观锁冲突 409；可选 sync_dataset |
| GET | `/api/runs/<run_id>/status` | JSON 轮询：总/成功/失败 Query 数、当前 Query 与 stage |
| GET | `/downloads/<file_type>/<run_id>` | 下载 report-html / report-excel / results / failures；`relative_to` 防路径穿越 |

### 4.4 Query / Candidate 下钻

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/runs/<run_id>/queries/<query_id>` | Query 输入、Task 字段逐项数据状态（MISSING/ERROR/VALID）、候选人分页、Raw 索引、`public_fields`（Admin 公共信息在此展示）、`retry_allowed` 判定 |
| POST | `/runs/<run_id>/queries/<query_id>/retry` | 原 Run 内排队重跑失败/未执行 Query |
| GET | `/candidates/<candidate_pk>` | 候选人五模块（Summary/Insights/Photos/Profile/Social）、Raw 索引、按 process_id 读处理结果、复核上下文 |

### 4.5 Raw 与导入

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/raw/<raw_id>` | 按 Raw ID 返回单条脱敏业务 JSON（按需加载） |
| GET/POST | `/imports` | 三种 `import_type`：`dataset`（JSONL/Excel）、`results_jsonl`（可附 failures/metadata）、`results_excel`；上传落 `data_dir/.uploads` 临时目录即用即删；扩展名白名单 + `secure_filename` |

### 4.6 Baseline（基准）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/baselines` | POST 导入版本化基准；GET 按版本分页展示人物（按活跃字段配置的 CANDIDATE 定义组织分组） |
| POST | `/baselines/<version>/people/<person_id>/available-fields` | 保存人物级"可评估字段"（来源 MANUAL） |

### 4.7 FieldSchema（字段配置）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/field-schemas` | 不可变版本列表 + 激活状态 + Process 引用计数 |
| GET/POST | `/field-schemas/new` | 基于 base 版本预填或提交完整 JSON 发布新版本 |
| GET/POST | `/field-schemas/<version>/comparison-matrix` | 字段 × 基准人物矩阵（过滤/钻取）+ 待配置字段建议；POST 从当前不可变 Schema 复制勾选发布新版本 |
| GET | `/api/field-schemas/<version>` | JSON 配置快照 |
| GET | `/api/field-schemas/<version>/comparison-matrix` | 矩阵 API（baseline_version 必填） |

### 4.8 Process（处理）与复核

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/runs/<run_id>/process` | 同步执行 `PROCESS_EXISTING` / `REPROCESS_EXISTING`（须确认；字段对齐 ERROR 级问题需显式 acknowledge） |
| GET | `/processes/<process_id>` | 不可变处理结果：指标、同 Evaluation 兼容 Process 对比、分页 processed candidates + 复核状态、分类进度、字段矩阵 |
| GET/POST | `/processes/<id>/queries/<query_id>/classification` | Query 级身份归类（HIT/NOT_HIT 等）、批量 NOT_HIT、primary hit、乐观锁 |
| POST | `/processes/<id>/candidates/<pk>/review` | 候选人终判 + 字段完整度/准确度得分；旧页面覆盖被拒（409）；保存后关联 READY 报告标记过期 |
| GET | `/api/processes/<process_id>/status` / `/metrics` | JSON 终态摘要与可追溯指标 |

### 4.9 Threshold Profile（参考线方案）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/threshold-profiles` | 全部版本（含归档）+ Evaluation 引用计数 |
| GET/POST | `/threshold-profiles/new` / `/threshold-profiles` | 创建不可变方案版本（支持 `based_on_profile_id` 派生） |
| GET | `/threshold-profiles/<profile_id>` | 不可变内容、来源版本、引用方 |
| GET | `/threshold-profiles/<profile_id>/copy` | 基于历史版本预填新版本表单（建议 `MAX(version)+1`） |
| POST | `/threshold-profiles/<profile_id>/archive` | 归档（历史引用仍可查看） |

### 4.10 Report（报告）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/reports` | 报告中心：按 Evaluation/系统版本/类型/状态过滤，50/页，附产物可用性标记 |
| POST | `/reports` | 创建报告：`create_report`（SINGLE/COMPARE）→ 渲染静态 HTML → 若启用 Excel 尝试导出（子进程失败降级 warning 不阻断）；任一步失败 `mark_report_failed` |
| GET | `/reports/<report_id>` | 只读 metrics_json 快照展示，不重算历史数字 |

> Admin 公共信息没有独立路由组：采集在 search_tool.py，展示落在 Query 详情页的 `public_fields`。

### 4.11 错误处理器

413（上传超限，提示调整 `SEARCH_WEB_MAX_UPLOAD_BYTES`）、404、500 —— 均渲染不含内部路径/堆栈的 `error.html`。

## 5. 后台 Run 执行机制（RunCoordinator，224–318）

- **线程模型**：`ThreadPoolExecutor(max_workers=1)`——全局串行单线程，天然限制并发为 1；Run 与 Query 重试共用同一队列，规避 SQLite 跨线程问题；
- **状态保护**：`_lock` + `_futures` 字典；`submit(run_id)` / `submit_query_retry(run_id, query_id)` 拒绝重复提交（抛 `ActiveRunError`，路由层转 409）；
- **异常收敛**：`_execute` 捕获一切异常 → `mark_run_failed`（只记类型与消息）；Query 重试异常只标记该 Query；
- **凭证延迟加载**：`_default_client` 在后台真正开始执行时才 `Config.from_env` 读接口 Token——未配置凭证也能先启动 Web 浏览/导入历史数据，更新 Token 无需重启；
- **INTERRUPTED 恢复**：启动时 `recover_interrupted_runs()` 把遗留 RUNNING 执行 Run 置 INTERRUPTED，其 RUNNING Query 置 FAILED；已落库数据保留，可页面触发 `/retry`；
- **关闭**：`main` 退出时 `shutdown(wait=True)` 等待当前 Query 安全收尾。

## 6. 安全机制汇总

| 机制 | 说明 |
|---|---|
| 只监听本机 | 默认 `127.0.0.1`；`debug=False, use_reloader=False` |
| 上传限制 | 50MB 上限；后缀白名单 `.jsonl/.json/.xlsx`；`secure_filename`；临时目录即用即删 |
| 路径穿越 | `normalize_base_path` 拒绝危险字符；下载路由 `relative_to(data_dir)` 校验 |
| 信息泄露控制 | 健康检查/后台异常/404/500/413 均不暴露堆栈、内部路径与配置 |
| XSS/URL 安全 | 仅 http/https 渲染为链接；图片扩展名白名单 |
| SQL 注入控制 | 全参数化查询；排序列白名单字典；LIKE 关键字转义 `\ % _` |
| 乐观锁 | 人物关联、身份归类、候选人复核均带版本校验，冲突 409 |

## 7. main 入口（3351–3386）

`--env-file`（默认 `.env`）、`--host`、`--port`；`create_app(overrides)` → `app.run(threaded=True)`（页面请求多线程，重活被单线程执行器串行化）→ finally `coordinator.shutdown(wait=True)`。

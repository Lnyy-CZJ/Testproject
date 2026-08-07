# Truthy_Search（searchTool）Code Wiki

本 Wiki 基于对仓库源码的完整分析生成，覆盖项目整体架构、主要模块职责、关键类与函数、依赖关系和运行方式。

## 项目一句话简介

**searchTool** 是一个面向 "People Insight" 人物检索服务的**本地评测工具集**：它批量调用检索接口（CreateIntentTask → GetTask → ListTaskCandidates → GetTaskCandidateDetail）采集候选人数据，并通过本地单用户 Web 平台完成数据导入、版本化字段处理、基准对比、身份判定、人工复核、指标计算（metrics-v4）与评测报告（report-model-v5）生成。

## 文档目录

| 文档 | 内容 |
|---|---|
| [01_项目总览与架构](./01_项目总览与架构.md) | 系统定位、整体架构图、核心业务流程、目录结构、关键设计原则 |
| [02_模块详解_search_tool](./02_模块详解_search_tool.md) | CLI 采集工具：检索接口调用链、Admin 公共信息采集、脱敏、输出格式、退出码 |
| [03_模块详解_analysis_store与数据库](./03_模块详解_analysis_store与数据库.md) | SQLite 存储层、18 张表结构、Schema v4 迁移链、表关系 |
| [04_模块详解_analysis_service](./04_模块详解_analysis_service.md) | 核心业务编排层：导入、采集执行、字段配置与处理、身份判定、指标计算、报告生成 |
| [05_模块详解_web_app](./05_模块详解_web_app.md) | Flask Web 应用：路由清单、后台执行器、安全机制 |
| [06_模块详解_result_to_excel](./06_模块详解_result_to_excel.md) | Excel 导出：Python 启动器 + Node 构建器、Sheet 结构 |
| [07_依赖关系与运行方式](./07_依赖关系与运行方式.md) | 第三方依赖、模块间依赖、安装/配置/运行/测试/Docker/备份全流程 |

## 源码文件速览

| 文件 | 行数 | 角色 |
|---|---|---|
| [search_tool.py](../../search_tool.py) | ~2552 | 命令行批量检索采集工具（也被 Web 后台作为库调用） |
| [analysis_service.py](../../analysis_service.py) | ~15216 | v1.3 本地检索分析核心服务（导入/处理/指标/报告） |
| [analysis_store.py](../../analysis_store.py) | ~877 | SQLite Schema v4、迁移、连接与事务管理 |
| [web_app.py](../../web_app.py) | ~3386 | Flask 本地单用户 Web（39 条路由） |
| [result_to_excel.py](../../result_to_excel.py) | ~167 | Excel 导出 Python 启动器 |
| [result_to_excel_builder.mjs](../../result_to_excel_builder.mjs) | ~2770 | Node.js Excel 工作簿构建器 |
| [static/](../../static) | — | Web 前端样式与脚本（app.css / app.js） |
| [templates/](../../templates) | — | 24 个 Jinja2 页面模板 |
| [tests/](../../tests) | — | unittest 测试套件与脱敏夹具 |

## 版本与契约速查

| 契约 | 当前值 | 说明 |
|---|---|---|
| 结果 Schema | `1.3.1`（`RESULT_SCHEMA_VERSION`） | results/failures JSONL 记录契约 |
| 数据库 Schema | `4`（`DB_SCHEMA_VERSION`） | SQLite 库结构版本，启动时校验/迁移 |
| 字段配置 | `field-schema-default-v2` / `field-schema-default-v3` | 系统默认 FieldSchema |
| 处理规则 | `field-processing-v1` … `v5` | 随 Process 冻结，v3 Schema 用 v5 |
| 指标规则 | `metrics-v1` … `metrics-v4` | 按 Process 的 rule_version 严格分派 |
| 报告模型 | `report-model-v2` … `v5`、`report-model-v6-compare` | 报告快照契约 |

## 配套文档（仓库内）

- [README.md](../../README.md)：面向使用者的完整操作手册
- [docs/数据库说明.md](../数据库说明.md)：数据库表字段说明（注意：该文档停留在 Schema v3，v4 差异见 [03 章](./03_模块详解_analysis_store与数据库.md#与-docs数据库说明md-的差异)）
- `docs/searchTool_v1.3_MVP_*.md`：各阶段 PRD、开发设计与验收记录

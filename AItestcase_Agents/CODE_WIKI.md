# 多智能体测试自动化系统 — Code Wiki

> **项目版本**: v1.0  
> **生成日期**: 最新
> **项目路径**: `d:\PythonProject\AItestcase_Agents`

---

## 目录

1. [项目概述](#1-项目概述)
2. [整体架构](#2-整体架构)
3. [项目目录结构](#3-项目目录结构)
4. [核心模块详解](#4-核心模块详解)
   - 4.1 [API 接口自动化测试智能体 (api_test)](#41-api-接口自动化测试智能体-api_test)
   - 4.2 [功能测试用例生成智能体 (functional_test)](#42-功能测试用例生成智能体-functional_test)
   - 4.3 [公共基础层 (common)](#43-公共基础层-common)
   - 4.4 [RAG 知识库 (LightRAG)](#44-rag-知识库-lightrag)
5. [关键类与函数说明](#5-关键类与函数说明)
6. [数据流与依赖关系](#6-数据流与依赖关系)
7. [数据库设计](#7-数据库设计)
8. [环境配置与运行方式](#8-环境配置与运行方式)
9. [技术栈](#9-技术栈)

---

## 1. 项目概述

本项目是一个基于 **大语言模型 (LLM)** 的 **多智能体测试自动化系统**，包含两个核心智能体：

| 智能体 | 职责 | 核心功能 |
|--------|------|---------|
| **API 接口自动化测试智能体** | 基于 API 文档生成并执行接口测试 | 解析 API 文档 → 生成基础用例 → 生成可执行用例 → 预执行验证 → 数据库保存 |
| **功能测试用例生成智能体** | 基于需求文档生成功能测试用例 | 语义检索需求 → 生成测试点 → 验证覆盖率 → 生成测试用例 → JSON/Excel 导出 |

### 1.1 设计理念

- **分层架构**: 将测试用例分为"基础用例"(抽象测试点)和"可执行用例"(含具体参数、脚本、断言逻辑)两层。
- **工作流驱动**: 使用 **LangGraph** 实现可编排、可观测的工作流，支持条件分支、循环和并发生成。
- **AI 增强**: 利用大语言模型实现文档解析、用例生成、覆盖率分析等智能化功能。
- **持久化存储**: 用例存储到 MySQL 数据库，支持版本管理和复用。
- **数据驱动**: 支持从 YAML/JSON 数据文件加载测试参数，实现数据与逻辑分离。
- **RAG 知识库**: 集成 LightRAG 与 Neo4j 图数据库，支持多模态文档的语义检索。

### 1.2 应用场景

- **接口测试自动化**: 从 API 文档自动生成测试用例并执行
- **功能测试设计**: 从需求文档自动生成功能测试用例
- **回归测试**: 自动化执行已生成的测试用例
- **CI/CD 集成**: 作为 CI 流水线的测试环节

---

## 2. 整体架构

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                         多智能体测试自动化系统                                   │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────────┐      ┌───────────────────────────────────────┐  │
│  │   功能测试用例生成智能体   │      │      API接口自动化测试智能体            │  │
│  │   (functional_test)     │      │      (api_test)                      │  │
│  └───────────┬─────────────┘      └──────────────┬────────────────────────┘  │
│              │                                    │                           │
│              ▼                                    ▼                           │
│  ┌─────────────────────────┐      ┌───────────────────────────────────────┐  │
│  │  case_generator_agent   │      │      api_testcase_agent.py            │  │
│  │  (LangChain Agent)      │      │      (入口编排类)                      │  │
│  └───────────┬─────────────┘      └──────────────┬────────────────────────┘  │
│              │                                    │                           │
│              ▼                                    ▼                           │
│  ┌─────────────────────────┐      ┌───────────────────────────────────────┐  │
│  │ GeneratorTestCaseWorflow│      │   工作流引擎 (LangGraph)               │  │
│  │  (主工作流)              │      │                                       │  │
│  │  ├─ 需求结构化摘要       │      │  ApiCaseGeneratoMainWorkFlow          │  │
│  │  ├─ 获取测试点(子工作流) │      │  ├─ ApiBaseCaseGeneratorWorkFlow      │  │
│  │  ├─ 首次生成测试用例     │      │  └─ ApiRunCaseGeneratorWorkFlow       │  │
│  │  ├─ 验证覆盖率           │      │       (支持并发生成)                   │  │
│  │  └─ 补充缺失用例         │      └──────────────┬────────────────────────┘  │
│  └───────────┬─────────────┘                     │                           │
│              │                                    ▼                           │
│              ▼                     ┌───────────────────────────────────────┐  │
│  ┌─────────────────────────┐       │      工具执行层                        │  │
│  │   文档服务层             │       │  TestExecutor → BaseTestCase         │  │
│  │   DocumentServiceFactory│       │  DataAwareBaseTestCase               │  │
│  │   ├─ ObsidianAdapter    │       │  DBClient / TestDataHub              │  │
│  │   └─ LightRAGAdapter    │       └──────────────┬────────────────────────┘  │
│  └───────────┬─────────────┘                      │                           │
│              │                                     ▼                           │
│              ▼                      ┌───────────────────────────────────────┐  │
│  ┌─────────────────────────┐       │           数据库层                      │  │
│  │    LightRAG 知识库      │       │  MySQL (api_base_case, api_test_case)  │  │
│  │    + Neo4j 图数据库     │       │  + 测试数据文件 (YAML/JSON)            │  │
│  └─────────────────────────┘       └───────────────────────────────────────┘  │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 项目目录结构

```
AItestcase_Agents/
├── agents/                          # 智能体核心代码
│   ├── api_test/                    # API 接口自动化测试智能体
│   │   ├── api_testcase_agent.py    # 入口：API测试完整执行编排
│   │   ├── parsers/                 # API 文档解析器
│   │   │   └── ai_parser_api_document.py  # AI 驱动的文档解析（核心）
│   │   ├── generators/              # 用例/数据生成器
│   │   │   └── data_aware_case_generator.py  # 数据感知型用例生成器
│   │   ├── prompts/                 # LLM 提示词
│   │   │   ├── api_document_parser.py       # 文档解析提示词
│   │   │   ├── base_case_generator.py       # 基础用例生成提示词
│   │   │   ├── api_case_generator.py        # 可执行用例生成提示词
│   │   │   ├── base_case_check_coverage.py  # 覆盖率检查提示词
│   │   │   ├── supplement_case.py           # 用例补充提示词
│   │   │   └── unified_api_case_generator.py # 统一用例生成提示词
│   │   └── workflows/              # LangGraph 工作流
│   │       ├── api_case_generator_main_workflow.py  # 主流程（编排）
│   │       ├── api_basecase_workflow.py             # 基础用例生成子流程
│   │       └── api_run_case_wrokflow.py             # 可执行用例生成子流程
│   ├── functional_test/            # 功能测试用例生成智能体
│   │   ├── case_generator_agent.py # 入口：LangChain Agent
│   │   ├── prompts/                # LLM 提示词
│   │   │   ├── case_generator_agent.py           # Agent 系统提示词
│   │   │   ├── generator_test_point.py           # 测试点生成
│   │   │   ├── generator_testcase.py             # 测试用例生成
│   │   │   ├── requirement_summary_prompt.py     # 需求摘要
│   │   │   ├── supplement_missing_test_cases.py  # 补充缺失用例
│   │   │   ├── supplement_missing_test_points.py # 补充缺失测试点
│   │   │   ├── verify_test_points_coverage.py    # 验证测试点覆盖率
│   │   │   └── verify_testcase_coverage.py       # 验证用例覆盖率
│   │   └── workflows/
│   │       └── case_generator_workflow.py        # 主工作流（含子工作流）
│   ├── common/                    # 公共基础层
│   │   ├── config/                # 配置
│   │   │   ├── settings.py        # LLM 模型配置、路径配置
│   │   │   └── LightRAGTools.py   # LightRAG 工具函数
│   │   ├── document/              # 文档服务适配器
│   │   │   ├── base.py            # 抽象基类 BaseDocumentAdapter
│   │   │   ├── factory.py         # 工厂类 DocumentServiceFactory
│   │   │   ├── lightrag_adapter.py # LightRAG 适配器
│   │   │   ├── obsidian_adapter.py # Obsidian 本地文件适配器
│   │   │   ├── obsidian_url_parser.py # Obsidian URL 解析
│   │   │   └── config.py          # 文档服务配置
│   │   ├── tools/                 # 全局工具
│   │   │   ├── tools.py           # Agent 工具（search_requirement, generator_case）
│   │   │   └── global_tools.py    # 测试数据生成函数
│   │   └── utils/                 # 工具函数
│   │       ├── basecase.py        # 核心：单条接口用例执行器
│   │       ├── data_aware_basecase.py  # 数据感知型用例执行器
│   │       ├── api_testcase_execute.py # 测试执行器（套件/工作流级别）
│   │       ├── database_client.py # 数据库客户端
│   │       ├── test_data_hub.py   # 测试数据中枢管理器
│   │       └── test_result.py     # 测试结果记录器
├── LightRAG/                      # RAG 知识库服务
│   ├── app.py                     # FastAPI 服务入口
│   ├── document_service.py        # 核心：LightRAG 文档服务
│   ├── rag_manager.py             # CLI 管理工具
│   ├── neo4j_storage.py           # Neo4j 图数据库存储层
│   ├── embedding_func.py          # 向量嵌入函数
│   ├── llm_model_func.py          # LLM 模型调用函数
│   ├── rerank.py                  # 重排序函数
│   ├── env_config.py              # 环境变量与路径配置
│   ├── documents/                 # 文档存放目录
│   ├── rag_storage/               # RAG 持久化存储
│   └── parser_output/             # 文档解析输出
├── datas/                         # 数据文件
│   ├── ApiDocument/               # API 文档
│   └── TestData/                  # 测试数据文件 (YAML)
├── output/                        # 输出目录
│   ├── test_reports/              # 测试报告 (JSON)
│   └── {项目名称}/{模块}/         # 功能测试用例 (JSON+XLSX)
├── tests/                         # 单元测试
│   └── test_basecase_defense.py
├── docs/                          # 文档
│   ├── README.md
│   ├── AGENTS.md
│   └── 统一接口测试用例提示词设计文档.md
└── .env                           # 环境变量文件
```

---

## 4. 核心模块详解

### 4.1 API 接口自动化测试智能体 (api_test)

#### 4.1.1 入口类：`APITestCaseExecutor`

**文件位置**: [agents/api_test/api_testcase_agent.py](file:///d:/PythonProject/AItestcase_Agents/agents/api_test/api_testcase_agent.py)

**职责**: 编排 API 测试的完整流程。

**执行流程**:
1. `read_api_document()` — 读取 API 文档内容
2. `parse_api_document()` — 调用 `AIAPIDocumentParser` 使用 LLM 解析文档
3. `generate_test_cases()` — 调用 `ApiCaseGeneratoMainWorkFlow` 生成基础用例和可执行用例
4. `execute_test_cases()` — 调用 `TestExecutor` 执行所有用例
5. `generate_report()` — 生成 JSON 格式测试报告并保存

#### 4.1.2 API 文档解析器：`AIAPIDocumentParser`

**文件位置**: [agents/api_test/parsers/ai_parser_api_document.py](file:///d:/PythonProject/AItestcase_Agents/agents/api_test/parsers/ai_parser_api_document.py)

**职责**: 使用 LLM 将非结构化的 API 文档（Markdown）解析为结构化数据。

**核心方法**:
- `parser(api_document)` → 调用 LLM 解析文档，返回结构化 API 信息
- `normalize_parameter_roles(api_info)` — 标准化参数分类（必填/选填/固定/条件）
- `_normalize_parameter(parameter)` — 单参数分类逻辑
- `_strip_base_url_from_path(raw_path)` — 规范化 URL 路径

**输出数据结构** (`InterfaceDocumentParserModel`):
```python
{
    "base_url": "http://host/index.php?s=",
    "path": "/api/user/login",
    "method": "POST",
    "summary": "用户登录",
    "parameters": {
        "header": [...],   # 请求头参数
        "path": [...],     # 路径参数
        "query": [...]     # 查询参数
    },
    "requestBody": {
        "content_type": "application/json",
        "body": [...]      # 请求体参数
    },
    "responses": {...}     # 响应定义
}
```

#### 4.1.3 基础用例生成工作流：`ApiBaseCaseGeneratorWorkFlow`

**文件位置**: [agents/api_test/workflows/api_basecase_workflow.py](file:///d:/PythonProject/AItestcase_Agents/agents/api_test/workflows/api_basecase_workflow.py)

**职责**: 基于 API 文档生成基础用例（抽象测试点）并保存到数据库。

**执行流程 (LangGraph)**:
```
START → 生成基础测试用例 → 检查用例覆盖率 → (条件分支)
    ├─ 覆盖率通过 → 输出基础测试用例 → END
    └─ 覆盖率不通过 → 补充生成测试用例 → 检查用例覆盖率 (循环)
```

**核心节点**:
| 节点 | 方法 | 功能 |
|------|------|------|
| 生成基础测试用例 | `generator_base_case()` | 调用 LLM 根据 API 文档生成基础用例列表 |
| 检查用例覆盖率 | `check_coverage()` | 调用 LLM 分析用例是否覆盖所有测试点 |
| 补充生成测试用例 | `supplement_case()` | 根据覆盖率报告补充缺失用例 |
| 输出基础测试用例 | `output_base_case()` | 将用例保存到 MySQL `api_base_case` 表 |

**数据模型**:
```python
class BaseCaseParser(BaseModel):
    name: str          # 用例名称
    steps: list        # 测试步骤
    dependencies: list # 前置依赖接口
    data_ref: str      # 可选：测试数据引用路径
```

#### 4.1.4 可执行用例生成工作流：`ApiRunCaseGeneratorWorkFlow`

**文件位置**: [agents/api_test/workflows/api_run_case_wrokflow.py](file:///d:/PythonProject/AItestcase_Agents/agents/api_test/workflows/api_run_case_wrokflow.py)

**职责**: 基于基础用例生成可执行的接口测试用例，进行语法校验并保存。

**执行流程 (LangGraph)**:
```
START → 加载工具函数和文件列表 → 生成接口用例 → 加载测试数据 → 静态语法校验 → (条件分支)
    ├─ (ready) → 保存用例 → END
    └─ (disabled && 重试次数≤3) → 生成接口用例 (重新生成)
```

**核心节点**:
| 节点 | 方法 | 功能 |
|------|------|------|
| 加载工具函数 | `get_functions_and_files()` | 加载 `global_tools` 中的函数列表和数据文件列表 |
| 加载测试数据 | `load_test_data()` | 根据 `data_ref` 从 YAML 数据文件加载测试参数 |
| 生成接口用例 | `generator_api_case()` | 调用 LLM 生成含具体请求参数的可执行用例 |
| 静态语法校验 | `static_syntax_check()` | 编译校验 setup/teardown 脚本的 Python 语法 |
| 保存用例 | `sava_api_case()` | 保存到 MySQL `api_test_case` 表 |

**数据模型**:
```python
class APICaseRuntimeParser(BaseModel):
    name: str         # 用例名称
    description: str  # 用例描述
    interface: str    # 接口名称或路径
    preconditions: list  # 前置依赖接口信息
    request: dict     # 请求数据（method, url, headers, body, scripts）
    data_ref: str     # 测试数据引用路径
```

**支持并发生成**: 主流程 [`ApiCaseGeneratoMainWorkFlow`](file:///d:/PythonProject/AItestcase_Agents/agents/api_test/workflows/api_case_generator_main_workflow.py) 使用 LangGraph 的 `Send` API 实现可执行用例的并发生成。

---

### 4.2 功能测试用例生成智能体 (functional_test)

#### 4.2.1 入口：`case_generator_agent.py`

**文件位置**: [agents/functional_test/case_generator_agent.py](file:///d:/PythonProject/AItestcase_Agents/agents/functional_test/case_generator_agent.py)

**职责**: 作为 LangChain Agent，接收用户自然语言输入，决定调用工具。

**绑定工具**:
- `search_requirement` — 从文档知识库检索需求
- `generator_case` — 基于需求文档生成测试用例

**智能体系统提示词**: [agents/functional_test/prompts/case_generator_agent.py](file:///d:/PythonProject/AItestcase_Agents/agents/functional_test/prompts/case_generator_agent.py)

#### 4.2.2 工具函数

**文件位置**: [agents/common/tools/tools.py](file:///d:/PythonProject/AItestcase_Agents/agents/common/tools/tools.py)

| 工具 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `search_requirement(query)` | 从文档知识库检索需求文档 | 查询关键字 | 匹配文档的完整内容 |
| `generator_case(document, config)` | 调用工作流生成测试用例 | 需求文档全文 | 用例生成结果摘要 |

**search_requirement 检索策略**: 支持 ObsidianAdapter（本地文件）和 LightRAGAdapter（向量检索），通过环境变量 `DOCUMENT_ADAPTER` 切换。

#### 4.2.3 测试用例生成工作流：`GeneratorTestCaseWorkflow`

**文件位置**: [agents/functional_test/workflows/case_generator_workflow.py](file:///d:/PythonProject/AItestcase_Agents/agents/functional_test/workflows/case_generator_workflow.py)

**职责**: 生成功能测试用例的主工作流，包含两个子工作流。

**主工作流执行流程**:
```
START → 需求结构化摘要 → 获取测试点(子工作流) → 首次生成测试用例 → 验证测试用例覆盖率 → (条件分支)
    ├─ 已覆盖 → 保存测试用例 → END
    └─ 未覆盖且轮次<2 → 补充缺失测试用例 → 验证测试用例覆盖率 (循环)
```

**子工作流：`GeneratorPointWorkflow`（测试点生成）**:
```
START → 首次生成测试点 → 验证测试点覆盖率 → (条件分支)
    ├─ 已覆盖 → 输出所有测试点 → END
    └─ 未覆盖且轮次<4 → 补充缺失测试点 → 验证测试点覆盖率 (循环)
```

**核心特性**:
- **需求结构化摘要**: 使用 LLM 将需求文档压缩为结构化摘要，包含模块名、功能列表、字段、业务规则、主/异常流程等
- **宽松 JSON 解析**: `RelaxedJsonOutputParser` 支持标准 JSON、partial JSON、json_repair 三层降级解析
- **本地覆盖矩阵**: 支持环境变量 `USE_COVERAGE_MATRIX` 开启本地关键词预匹配，减少 LLM 调用
- **分批生成**: 通过 `CASE_GENERATION_BATCH_SIZE` 控制单批次测试点数量，避免过长响应
- **输出去重**: 使用 `merge_unique_cases()` 按用例名去重
- **双格式输出**: 支持 JSON + Excel (xlsx) 双格式导出

**数据模型**:
```python
class TestCaseModel(BaseModel):
    case_id: str          # 用例ID
    case_name: str        # 用例名称
    priority: str         # 优先级
    preconditions: str    # 前置条件
    test_steps: str       # 测试步骤
    test_data: str        # 测试数据
    expected_result: str  # 预期结果
    actual_result: str    # 实际结果（可选）
```

---

### 4.3 公共基础层 (common)

#### 4.3.1 核心用例执行器：`BaseTestCase`

**文件位置**: [agents/common/utils/basecase.py](file:///d:/PythonProject/AItestcase_Agents/agents/common/utils/basecase.py)

**职责**: 单条接口测试用例的核心执行逻辑。

**执行流程 (`run()`)**:
```
1. execute_preconditions() — 执行前置依赖接口
   ├─ 遍历每个前置接口
   │   ├─ execute_setup_script() — 执行前置脚本
   │   ├─ replace_variables() — 替换变量引用 (${{var}}, {{var}}, ${var}, {var})
   │   ├─ request_api() — 发送 HTTP 请求
   │   ├─ execute_teardown_script() — 执行后置脚本
   │   └─ extract_data() — 使用 jmespath 提取响应数据到环境变量
   └─ ...
2. execute_setup_script() — 执行主请求的前置脚本
3. replace_variables() — 替换主请求的变量
4. request_api() — 发送主请求
5. execute_teardown_script() — 执行后置脚本
```

**变量替换**: 支持四种占位符格式：`${{var}}`、`{{var}}`、`${var}`、`{var}`。从 `test_env_global` 字典中查找替换值。

**脚本执行安全**: 使用 `func_timeout` 设置 5 秒超时，防止死循环脚本阻塞。

**请求分发**: 根据 `Content-Type` 自动选择请求编码方式：
- `application/json` → `json=body`
- `application/xml` → `data=body`
- `multipart/form-data` → `MultipartEncoder`
- 其他 → `data=body`

#### 4.3.2 数据感知执行器：`DataAwareBaseTestCase`

**文件位置**: [agents/common/utils/data_aware_basecase.py](file:///d:/PythonProject/AItestcase_Agents/agents/common/utils/data_aware_basecase.py)

**职责**: 继承 `BaseTestCase`，支持从用例的 `_test_data` 字段注入测试数据到执行上下文。

**增强点**:
- `replace_variables()` 前先将 `_test_data` 中的数据注册到 `test_env_global`
- 不修改父类任何原有逻辑

#### 4.3.3 测试执行器：`TestExecutor`

**文件位置**: [agents/common/utils/api_testcase_execute.py](file:///d:/PythonProject/AItestcase_Agents/agents/common/utils/api_testcase_execute.py)

**职责**: 管理测试用例的执行生命周期，支持单条、套件、任务三级执行。

**核心方法**:
| 方法 | 功能 |
|------|------|
| `execute_test_case(case_data)` | 执行单条用例，记录结果并回写数据库 |
| `execute_test_suite(suite_data)` | 执行用例套件，统计汇总 |
| `execute_workflow_cases(workflow_state)` | 执行工作流生成的用例 |
| `execute_test_task(task_data)` | 执行测试任务（多套件） |

**结果回写**: 执行后自动将 `real_response`（含 `status_code`、`response_body`、`error_message`）回写到 MySQL `api_test_case` 表的 `real_response` 字段。

#### 4.3.4 数据库客户端：`DBClient`

**文件位置**: [agents/common/utils/database_client.py](file:///d:/PythonProject/AItestcase_Agents/agents/common/utils/database_client.py)

**职责**: 支持多种数据库类型的连接管理。

**支持的数据库类型**: MySQL、MongoDB、Redis、SQLite、Oracle、PostgreSQL（目前仅 MySQL 完全实现）。

**连接池**: 使用 `db_pool` 字典维护多个数据库连接，支持通过名称访问。

#### 4.3.5 测试数据中枢：`TestDataHub`

**文件位置**: [agents/common/utils/test_data_hub.py](file:///d:/PythonProject/AItestcase_Agents/agents/common/utils/test_data_hub.py)

**职责**: 从 YAML/JSON 文件加载测试数据，按命名空间隔离，提供数据引用解析能力。

**数据文件格式**:
```yaml
api_name: LoginApi
api_path: /api/user/login
test_data:
  baseline:              # 基准数据
    accounts: "czj11"
    pwd: "czj111"
  boundary:              # 边界值数据
    pwd_min_minus:
      _inherits: "baseline"      # 继承基准数据
      _overrides:
        pwd: "12345"             # 只覆盖密码字段
```

**核心方法**:
- `load_data_file(file_path, namespace)` — 加载数据文件到命名空间
- `resolve_case_data_with_lineage(data_ref)` — 解析数据引用，返回合并数据和 lineage 溯源信息
- `get_data(ref, namespace)` — 支持短格式和长格式数据引用

#### 4.3.6 测试结果记录：`TestResult`

**文件位置**: [agents/common/utils/test_result.py](file:///d:/PythonProject/AItestcase_Agents/agents/common/utils/test_result.py)

**职责**: 记录每条用例的执行状态、日志、请求信息和响应数据。

**核心字段**:
```python
TestResult:
    case_id, case_name       # 用例标识
    status                   # passed / failed / error / skipped
    error_message, traceback # 错误信息
    start_time, end_time, duration  # 执行时间
    logs[]                   # 日志列表（含 level 和 message）
    api_requests_info[]      # API 请求/响应信息列表
```

#### 4.3.7 全局工具函数：`global_tools`

**文件位置**: [agents/common/tools/global_tools.py](file:///d:/PythonProject/AItestcase_Agents/agents/common/tools/global_tools.py)

**职责**: 提供测试中常用的数据生成函数，供用例脚本调用。

| 函数 | 功能 |
|------|------|
| `random_mobile()` | 随机生成手机号 |
| `random_account()` | 随机生成 6-18 位账号 |
| `random_password()` | 随机生成 8-16 位密码 |
| `random_email()` | 随机生成邮箱 |
| `random_name()` | 随机生成中文姓名 |
| `random_ssn()` | 随机生成身份证号 |
| `random_addr()` | 随机生成地址 |
| `random_ipv4()` | 随机生成 IPv4 地址 |
| `get_timestamp()` | 获取当前时间戳 |
| `base64_encode()` | Base64 编码 |
| `md5_encrypt()` | MD5 加密 |
| `rsa_encrypt()` | RSA 加密 |

#### 4.3.8 文档服务适配器体系

**抽象基类**: [base.py](file:///d:/PythonProject/AItestcase_Agents/agents/common/document/base.py)

**工厂类**: [factory.py](file:///d:/PythonProject/AItestcase_Agents/agents/common/document/factory.py) — 通过环境变量 `DOCUMENT_ADAPTER` 切换适配器类型。

**适配器类型**:

| 适配器 | 功能 | 适用场景 |
|--------|------|---------|
| **ObsidianAdapter** | 直接读取本地文件系统 | 纯本地文档，零外部依赖 |
| **LightRAGAdapter** | 封装 LightRAG 服务 | 多模态文档、向量检索 |

**统一接口**:
- `initialize()` — 初始化
- `insert_document(file_path)` — 插入文档
- `query_documents(query, top_k, mode)` — 语义检索
- `get_document(doc_id)` — 获取文档详情
- `delete_document(doc_id)` — 删除文档
- `list_documents(limit, offset)` — 列出文档

**ObsidianAdapter** 额外支持:
- Obsidian URL 解析 (`get_document_by_url`)
- Vault 自动发现 (`find_vault_by_discovery`)
- 文档片段化检索 (`_build_document_snippet`)
- 关键词降级检索

#### 4.3.9 数据感知用例生成器：`DataAwareCaseGenerator`

**文件位置**: [agents/api_test/generators/data_aware_case_generator.py](file:///d:/PythonProject/AItestcase_Agents/agents/api_test/generators/data_aware_case_generator.py)

**职责**: 从 API 文档解析验证规则，自动生成边界值、异常值和安全测试数据，导出为 TestDataHub 兼容的数据文件。

**数据分类**:
| 分类 | 生成逻辑 |
|------|---------|
| `normal` | 正向数据 — 有效范围内的中间值 |
| `boundary` | 边界值 — min-1, min, max, max+1 |
| `abnormal` | 异常值 — 空字符串、null、特殊字符、Emoji、类型错误 |
| `security` | 安全测试 — SQL注入、XSS、命令注入 |

---

### 4.4 RAG 知识库 (LightRAG)

#### 4.4.1 文档服务：`LightRAGDocumentService`

**文件位置**: [LightRAG/document_service.py](file:///d:/PythonProject/AItestcase_Agents/LightRAG/document_service.py)

**职责**: 提供多模态文档的插入、解析、索引、检索和删除功能。

**初始化流程**:
1. 创建工作目录和解析输出目录
2. 初始化 `LightRAG` 引擎（配置 embedding 和 LLM 函数）
3. 初始化 `RAGAnything`（用于多模态文档解析）
4. 初始化 `Neo4jStorage`（图数据库连接）

**文档解析策略**（按文件类型路由）:
| 文件类型 | 解析策略 | 处理方式 |
|----------|---------|---------|
| `.md`, `.txt`, `.json`, `.log`, `.csv` | `text` | 直接读取，绕过 MinerU |
| `.html`, `.htm` | `html` | BeautifulSoup 提取文本 |
| `.docx`, `.pptx`, `.xlsx` | `office` | 轻量解析 |
| `.png`, `.jpg`, `.jpeg`, `.bmp` | `image` | 多模态模型处理 |
| `.pdf` | `pdf` | MinerU 深度解析 |

**检索流程** (`query_documents`):
1. 从 Neo4j 图数据库搜索匹配的文档块和关键词
2. 将图匹配结果增强到查询中
3. 调用 `LightRAG.aquery()` 进行语义检索

#### 4.4.2 Neo4j 图存储：`Neo4jStorage`

**文件位置**: [LightRAG/neo4j_storage.py](file:///d:/PythonProject/AItestcase_Agents/LightRAG/neo4j_storage.py)

**职责**: 使用 Neo4j 图数据库存储文档、内容块、实体及其关系。

**图模型**:
```
(Document) --[:HAS_BLOCK]--> (ContentBlock)
(Document) --[:HAS_KEYWORD]--> (Entity)
(ContentBlock) --[:MENTIONS]--> (Entity)
```

**核心方法**:
- `upsert_document()` — 插入或更新文档节点
- `replace_document_blocks()` — 替换文档内容块和关键词关系
- `search_documents(keyword)` — 按关键词搜索文档、内容块和实体
- `get_document(doc_id)` — 获取完整文档信息（含块和关键词）
- `delete_document(doc_id)` — 删除文档及其关联

#### 4.4.3 FastAPI 服务：`app.py`

**文件位置**: [LightRAG/app.py](file:///d:/PythonProject/AItestcase_Agents/LightRAG/app.py)

**REST API 端点**:

| 端点 | 方法 | 功能 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/documents` | POST | 插入文档 |
| `/documents` | GET | 列出文档 |
| `/documents/query` | POST | 语义检索文档 |
| `/documents/search` | GET | 关键词搜索文档 |
| `/documents/{doc_id}` | GET | 获取文档详情 |
| `/documents/{doc_id}` | DELETE | 删除文档 |
| `/documents/delete` | POST | 按路径或ID删除文档 |

#### 4.4.4 CLI 管理工具：`rag_manager.py`

**文件位置**: [LightRAG/rag_manager.py](file:///d:/PythonProject/AItestcase_Agents/LightRAG/rag_manager.py)

**使用示例**:
```bash
# 列出文档
python rag_manager.py list
# 查询文档
python rag_manager.py query "文档主要讲了什么"
# 搜索文档
python rag_manager.py search "关键词"
# 插入文档
python rag_manager.py insert "documents/文档.pdf"
# 删除文档
python rag_manager.py delete --doc-id <doc_id>
```

---

## 5. 关键类与函数说明

### 5.1 API 测试模块关键类

| 类名 | 文件 | 职责 | 关键方法 |
|------|------|------|---------|
| `APITestCaseExecutor` | `api_testcase_agent.py` | 完整流程编排 | `run()`, `parse_api_document()`, `generate_test_cases()`, `execute_test_cases()`, `generate_report()` |
| `AIAPIDocumentParser` | `parsers/ai_parser_api_document.py` | AI 解析文档 | `parser()`, `normalize_parameter_roles()` |
| `ApiBaseCaseGeneratorWorkFlow` | `workflows/api_basecase_workflow.py` | 基础用例生成 | `generator_base_case()`, `check_coverage()`, `supplement_case()` |
| `ApiRunCaseGeneratorWorkFlow` | `workflows/api_run_case_wrokflow.py` | 可执行用例生成 | `generator_api_case()`, `static_syntax_check()`, `load_test_data()`, `sava_api_case()` |
| `ApiCaseGeneratoMainWorkFlow` | `workflows/api_case_generator_main_workflow.py` | 主流程编排 | `generator_base_case()`, `api_case_generation_task_split()`, `generate_run_api_case()` |
| `DataAwareCaseGenerator` | `generators/data_aware_case_generator.py` | 数据生成 | `parse_validation_rules()`, `generate_test_data()`, `export_data_file()` |

### 5.2 功能测试模块关键类

| 类名 | 文件 | 职责 | 关键方法 |
|------|------|------|---------|
| `GeneratorPointWorkflow` | `workflows/case_generator_workflow.py` | 测试点生成子工作流 | `generate_initial_test_points()`, `verify_test_points_coverage()`, `supplement_missing_test_points()` |
| `GeneratorTestCaseWorkflow` | `workflows/case_generator_workflow.py` | 测试用例生成主工作流 | `summarize_requirement()`, `get_test_points()`, `generate_initial_test_cases()`, `verify_testcase_coverage()`, `save_test_cases()` |
| `RelaxedJsonOutputParser` | `workflows/case_generator_workflow.py` | 宽松 JSON 解析 | `parse_result()` — 三级降级解析 |

### 5.3 公共基础层关键类

| 类名 | 文件 | 职责 | 关键方法 |
|------|------|------|---------|
| `BaseTestCase` | `utils/basecase.py` | 单条用例执行核心 | `run()`, `replace_variables()`, `request_api()`, `execute_preconditions()`, `execute_setup_script()`, `execute_teardown_script()`, `extract_data()` |
| `DataAwareBaseTestCase` | `utils/data_aware_basecase.py` | 数据感知执行 | 继承 `BaseTestCase`，增强 `replace_variables()` |
| `TestExecutor` | `utils/api_testcase_execute.py` | 测试执行器 | `execute_test_case()`, `execute_test_suite()`, `execute_workflow_cases()` |
| `DBClient` | `utils/database_client.py` | 数据库客户端 | 支持多数据库类型的连接池 |
| `TestResult` | `utils/test_result.py` | 测试结果记录 | `add_error_log()`, `add_info_log()`, `add_warning_log()` |
| `TestDataHub` | `utils/test_data_hub.py` | 数据中枢管理 | `load_data_file()`, `resolve_case_data_with_lineage()`, `get_data()`, `save_data_file()` |
| `BaseDocumentAdapter` | `document/base.py` | 文档服务基类 | 抽象方法: `initialize()`, `insert_document()`, `query_documents()`, `get_document()`, `delete_document()`, `list_documents()` |
| `DocumentServiceFactory` | `document/factory.py` | 文档服务工厂 | `create()`, `from_config()`, `clear_cache()` |
| `ObsidianAdapter` | `document/obsidian_adapter.py` | 本地文件适配器 | `_keyword_search()`, `_semantic_search()`, `_build_document_snippet()`, `find_vault_by_discovery()` |
| `LightRAGAdapter` | `document/lightrag_adapter.py` | LightRAG 适配器 | 封装 `LightRAGDocumentService` 调用 |

### 5.4 LightRAG 模块关键类

| 类名 | 文件 | 职责 | 关键方法 |
|------|------|------|---------|
| `LightRAGDocumentService` | `document_service.py` | 文档服务核心 | `initialize()`, `insert_document()`, `query_documents()`, `delete_document()`, `_select_parse_strategy()`, `_collect_graph_matches()` |
| `Neo4jStorage` | `neo4j_storage.py` | 图数据库存储 | `upsert_document()`, `replace_document_blocks()`, `search_documents()`, `get_document()` |

### 5.5 关键函数

| 函数 | 文件 | 功能 |
|------|------|------|
| `search_requirement(query)` | `tools/tools.py` | 文档需求检索服务工具 |
| `generator_case(document, config)` | `tools/tools.py` | 基于需求生成用例服务工具 |
| `random_mobile()` | `tools/global_tools.py` | 随机手机号生成 |
| `md5_encrypt(data)` | `tools/global_tools.py` | MD5 加密 |
| `get_system_db_connection()` | `workflows/api_basecase_workflow.py` | 线程级单例数据库连接 |
| `ensure_list(data)` | `workflows/case_generator_workflow.py` | 确保 LLM 返回值始终为列表 |
| `build_test_cases_brief()` | `workflows/case_generator_workflow.py` | 压缩用例为最小字段集合 |
| `build_coverage_matrix()` | `workflows/case_generator_workflow.py` | 本地覆盖矩阵预过滤 |

---

## 6. 数据流与依赖关系

### 6.1 API 测试数据流

```
API文档(Markdown)
    │
    ▼
AIAPIDocumentParser.parser() → api_info (结构化字典)
    │
    ▼
ApiCaseGeneratoMainWorkFlow
    │
    ├── ApiBaseCaseGeneratorWorkFlow
    │       └── LLM 生成基础用例 → MySQL(api_base_case)
    │
    └── ApiRunCaseGeneratorWorkFlow (并行)
            │
            ├── 加载工具函数列表 (global_tools)
            ├── 加载测试数据文件 (TestDataHub)
            ├── LLM 生成可执行用例
            ├── 静态语法校验 (compile)
            └── 保存到 MySQL(api_test_case)
                │
                ▼
TestExecutor.execute_test_case()
    │
    ├── BaseTestCase.run()
    │   ├── execute_preconditions() → HTTP请求前置接口
    │   ├── execute_setup_script() → exec(setup_script)
    │   ├── replace_variables() → 变量占位符替换
    │   ├── request_api() → HTTP请求
    │   ├── execute_teardown_script() → exec(teardown_script)
    │   └── extract_data() → jmespath提取
    │
    └── 结果回写 MySQL(api_test_case.real_response)
        │
        ▼
    生成 JSON 测试报告 → output/test_reports/
```

### 6.2 功能测试数据流

```
用户输入 (如："查看排位赛需求文档，生成测试用例")
    │
    ▼
CaseGenerator Agent
    │
    ├── search_requirement("排位赛")
    │   └── 文档服务适配器 → 获取需求文档全文
    │
    └── generator_case(需求文档全文)
        │
        ▼
    GeneratorTestCaseWorkflow
        │
        ├── 需求结构化摘要 → requirement_summary (字典)
        │
        ├── GeneratorPointWorkflow (子工作流)
        │   ├── 首次生成测试点
        │   ├── 验证测试点覆盖率
        │   └── 补充缺失测试点 (最多4轮)
        │
        ├── 首次生成测试用例 (分批，LLM)
        ├── 验证测试用例覆盖率 (本地矩阵+LLM)
        ├── 补充缺失测试用例 (循环，最多2轮)
        │
        └── 保存测试用例
            ├── JSON 文件 → output/{项目}/{模块}/testcases_*.json
            └── Excel 文件 → output/{项目}/{模块}/testcases_*.xlsx
```

### 6.3 模块依赖关系

| 模块 | 依赖模块 | 依赖说明 |
|------|---------|---------|
| `api_testcase_agent.py` | `parsers.ai_parser_api_document`, `workflows.api_case_generator_main_workflow`, `utils.api_testcase_execute` | 流程编排 |
| `case_generator_agent.py` | `tools.tools`, `prompts.case_generator_agent`, `config.settings` | Agent 创建 |
| `api_case_generator_main_workflow.py` | `workflows.api_basecase_workflow`, `workflows.api_run_case_wrokflow` | 主流程编排 |
| `api_basecase_workflow.py` | `prompts.base_case_generator`, `prompts.base_case_check_coverage`, `prompts.supplement_case`, `config.settings` | LLM 调用 |
| `api_run_case_wrokflow.py` | `prompts.api_case_generator`, `tools.global_tools`, `utils.test_data_hub` | 可执行用例生成 |
| `api_testcase_execute.py` | `utils.basecase`, `utils.test_result`, `utils.database_client` | 用例执行 |
| `basecase.py` | `tools.global_tools`, `utils.database_client`, `utils.test_result` | 单条用例执行 |
| `data_aware_basecase.py` | `utils.basecase`, `utils.test_result` | 数据感知执行 |
| `case_generator_workflow.py` | `prompts.*` (8个), `config.settings` | 工作流执行 |
| `tools.py` | `document.factory`, `workflows.case_generator_workflow` | Agent 工具 |
| `document.factory.py` | `document.obsidian_adapter`, `document.lightrag_adapter` | 适配器工厂 |
| `LightRAG/*` | `neo4j`, `lightrag`, `raganything` | RAG 服务 |

---

## 7. 数据库设计

### 7.1 MySQL 表结构

#### `api_base_case` — 基础用例表

```sql
CREATE TABLE api_base_case (
  id           INT PRIMARY KEY AUTO_INCREMENT,  -- 主键
  interface_id VARCHAR(50),                     -- 接口ID
  name         VARCHAR(200),                    -- 用例名称
  steps        TEXT,                            -- 测试步骤 (JSON)
  expected     TEXT,                            -- 预期结果 (已废弃，存空数组)
  status       VARCHAR(20) DEFAULT 'ready',     -- 状态: ready/disabled
  created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `api_test_case` — 可执行用例表

```sql
CREATE TABLE api_test_case (
  id              INT PRIMARY KEY AUTO_INCREMENT,  -- 主键
  base_case_id    INT,                             -- 关联基础用例ID
  name            VARCHAR(200),                    -- 用例名称
  description     TEXT,                            -- 用例描述
  interface_name  VARCHAR(200),                    -- 接口名称
  preconditions   JSON,                            -- 前置依赖 (JSON数组)
  request         JSON,                            -- 请求数据 (JSON)
  assertions      JSON,                            -- 断言 (已废弃，存空对象)
  real_response   JSON,                            -- 实际响应 (执行后回写)
  status          VARCHAR(20) DEFAULT 'disabled',  -- 状态: ready/disabled
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (base_case_id) REFERENCES api_base_case(id)
);
```

### 7.2 线程安全的数据库连接

工作流组件使用 `threading.local()` 实现线程级单例数据库连接，避免多线程并发执行时的连接冲突。

---

## 8. 环境配置与运行方式

### 8.1 环境变量 (.env)

```ini
# ===== 数据库配置 =====
db_name=localhost
db_port=3306
db_user=root
db_password=123456
db_database=test

# ===== LLM 模型配置 =====
MODEL_V3=deepseek-ai/DeepSeek-V3.2
GJLD_base_url=https://api.siliconflow.cn/v1
GJLD_api_key=your_api_key_here

# ===== 功能测试工作流配置 =====
USE_REQUIREMENT_SUMMARY=False       # 启用需求结构化摘要 (默认关闭)
USE_COVERAGE_MATRIX=true            # 启用本地覆盖矩阵预过滤 (默认开启)
CASE_GENERATION_BATCH_SIZE=5        # 单批次测试点数量
USE_BRIEF_CONTEXT=true              # 覆盖率校验使用轻量上下文 (默认开启)
DOCUMENT_QUERY_TOP_K=3              # 需求检索返回文档数

# ===== Obsidian 配置 =====
DOCUMENT_ADAPTER=obsidian           # 文档适配器类型 (obsidian / lightrag)
OBSIDIAN_VAULT_PATH=                # Obsidian Vault 路径
OBSIDIAN_VAULT_DISCOVERY=false      # Vault 自动发现

# ===== Neo4j 配置 =====
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=test1234

# ===== LightRAG 配置 =====
LIGHTRAG_WORKSPACE=default
EMBEDDING_DIM=2560
EMBEDDING_MAX_TOKEN_SIZE=512
```

### 8.2 运行方式

#### 运行 API 接口自动化测试智能体

```bash
cd d:\PythonProject\AItestcase_Agents
python agents/api_testcase_agent.py
```

默认读取 `datas/ApiDocument/LoginApi_Doc.md` 作为 API 文档，输出测试报告到 `output/test_reports/`。

#### 运行功能测试用例生成智能体

```bash
cd d:\PythonProject\AItestcase_Agents
python agents/case_generator_agent.py
```

默认查询"排位赛需求文档"并生成测试用例，输出到 `output/项目C：赛事系统/排位赛功能/`。

#### 启动 LightRAG 服务

```bash
cd d:\PythonProject\AItestcase_Agents\LightRAG
# 启动 API 服务
uvicorn app:app --reload

# 或使用 CLI 管理
python rag_manager.py list
python rag_manager.py query "查询内容"
python rag_manager.py search "关键词"
python rag_manager.py insert "documents/文档.pdf"
```

### 8.3 输出说明

| 输出类型 | 路径 | 格式 | 说明 |
|---------|------|------|------|
| 测试报告 | `output/test_reports/test_report_*.json` | JSON | 用例执行结果汇总和详情 |
| 功能测试用例 | `output/{项目名称}/{模块}/testcases_*.json` | JSON | 功能测试用例列表 |
| 功能测试用例 | `output/{项目名称}/{模块}/testcases_*.xlsx` | Excel | 同上，Excel 格式 |
| 测试点 | `output/test_points/test_points_*.json` | JSON | 中间产物：测试点列表 |

---

## 9. 技术栈

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| **编程语言** | Python | 3.11+ | 主要开发语言 |
| **LLM 框架** | LangChain | 0.2+ | LLM 集成、Agent 框架、工具调用 |
| **工作流引擎** | LangGraph | 0.1+ | 工作流编排（条件分支、循环、并行） |
| **向量引擎** | LightRAG | - | RAG 检索与问答 |
| **多模态解析** | RAGAnything | - | PDF/Office/图片的智能解析 |
| **图数据库** | Neo4j | - | 文档知识图谱存储 |
| **关系数据库** | MySQL | 8.0+ | 用例存储 |
| **Web 框架** | FastAPI | - | LightRAG REST API 服务 |
| **HTTP 客户端** | requests | 2.31+ | 接口请求 |
| **JSON 查询** | jmespath | 1.0+ | JSON 数据提取 |
| **数据解析** | PyYAML | - | 测试数据文件解析 |
| **Excel 处理** | pandas + openpyxl | - | 用例导出 Excel |
| **环境管理** | python-dotenv | 1.0+ | 环境变量配置 |
| **脚本安全** | func_timeout | - | 脚本执行超时保护 |

---

> **文档版本**: v1.0  
> **生成日期**: 最新
> **项目状态**: 开发中
# 多智能体测试自动化系统项目说明文档
## 0. 附录：项目目录结构
AItestcase_Agents/
├── agents/                    # 智能体入口
│   ├── api_testcase_agent.py  # API接口自动化测试智能体
│   └── case_generator_agent.py # 功能测试用例生成智能体
├── workflow/                  # 工作流定义
│   ├── api_case_generator_main_workflow.py
│   ├── api_basecase_workflow.py
│   ├── api_run_case_wrokflow.py
│   └── case_generator_workflow.py
├── utils/                     # 工具函数
│   ├── api_testcase_execute.py
│   ├── basecase.py
│   ├── database_client.py
│   ├── test_result.py
│   └── api_document_parser/   # API文档解析器
├── config/                    # 配置
│   ├── settings.py            # 全局配置
│   └── prompts/               # 提示词文件
├── LightRAG/                  # RAG知识库
├── mac_tools/                 # 全局工具
│   ├── global_tools.py        # 测试数据生成工具
│   └── tools.py               # Agent工具定义
├── datas/                     # 数据文件
│   └── ApiDocument/           # API文档目录
├── output/                    # 输出目录
│   ├── test_reports/          # 测试报告
│   └── {项目名称}/            # 功能测试用例
├── .env                       # 环境变量
└── README_old.md              # 旧版说明文档
---

## 1. 项目概述

### 1.1 项目简介

本项目是一个基于大语言模型的**多智能体测试自动化系统**，包含两个核心智能体：

| 智能体名称 | 职责 | 核心功能 |
|-----------|------|---------|
| **功能测试用例生成智能体** | 基于需求文档生成功能测试用例 | 从产品文档/需求文档中提取测试点，生成完整的功能测试用例 |
| **API接口自动化测试智能体** | 基于API文档生成并执行接口测试 | 解析API文档 → 生成基础用例 → 生成可执行用例 → 预执行验证 → 数据库保存 |

### 1.2 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         多智能体测试自动化系统                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────┐        ┌───────────────────────────────────┐  │
│  │  功能测试用例生成     │        │        API接口自动化测试智能体       │  │
│  │        智能体        │        │                                   │  │
│  └──────────┬──────────┘        └───────────────┬───────────────────┘  │
│             │                                   │                       │
│             ▼                                   ▼                       │
│  ┌─────────────────────┐        ┌───────────────────────────────────┐  │
│  │  case_generator_   │        │        api_testcase_agent.py      │  │
│  │     agent.py       │        │                                   │  │
│  └──────────┬──────────┘        └───────────────┬───────────────────┘  │
│             │                                   │                       │
│             ▼                                   ▼                       │
│  ┌─────────────────────┐        ┌───────────────────────────────────┐  │
│  │ case_generator_    │        │        工作流引擎 (LangGraph)      │  │
│  │   workflow.py      │        │                                   │  │
│  └──────────┬──────────┘        │  ApiCaseGeneratoMainWorkFlow      │  │
│             │                   │  ApiBaseCaseGeneratorWorkFlow      │  │
│             ▼                   │  ApiRunCaseGeneratorWorkFlow       │  │
│  ┌─────────────────────┐        └───────────────┬───────────────────┘  │
│  │    LightRAG         │                        │                       │
│  │  (知识库检索)       │                        ▼                       │
│  └─────────────────────┘        ┌───────────────────────────────────┐  │
│                                 │          工具层                      │  │
│                                 │  api_testcase_execute.py           │  │
│                                 │  basecase.py                       │  │
│                                 │  database_client.py                │  │
│                                 └───────────────┬───────────────────┘  │
│                                                 │                       │
│                                                 ▼                       │
│                                 ┌───────────────────────────────────┐  │
│                                 │            数据库层                 │  │
│                                 │   MySQL (api_base_case,           │  │
│                                 │          api_test_case)           │  │
│                                 └───────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 设计理念

1. **分层架构**：将测试用例分为"基础用例"和"可执行用例"两层
   - **基础用例**：抽象的测试点描述，与具体执行环境无关
   - **可执行用例**：包含具体参数、前置脚本、断言逻辑的可直接执行的用例

2. **工作流驱动**：使用 LangGraph 实现可编排、可观测的工作流

3. **AI增强**：利用大语言模型实现文档解析、用例生成、覆盖率分析等智能化功能

4. **持久化存储**：将生成的用例存储到数据库，支持版本管理和复用

### 1.4 应用场景

| 场景 | 描述 |
|------|------|
| **接口测试自动化** | 从API文档自动生成测试用例并执行 |
| **功能测试设计** | 从需求文档自动生成功能测试用例 |
| **回归测试** | 自动化执行已生成的测试用例 |
| **CI/CD集成** | 作为CI流水线的测试环节 |

---

## 2. 代码文件功能说明

### 2.1 智能体层 (agents/)

| 文件 | 功能描述 | 核心方法 |
|------|---------|---------|
| **api_testcase_agent.py** | API接口自动化测试完整执行入口 | `run()` - 执行完整流程；`parse_api_document()` - AI解析文档；`generate_test_cases()` - 生成用例；`execute_test_cases()` - 执行测试；`generate_report()` - 生成报告 |
| **case_generator_agent.py** | 功能测试用例生成智能体 | `main()` - 创建Agent并执行 |

### 2.2 工作流层 (workflow/)

| 文件 | 功能描述 | 核心类/方法 |
|------|---------|------------|
| **api_case_generator_main_workflow.py** | 接口用例生成主流程 | `ApiCaseGeneratoMainWorkFlow` - 单线程逐个生成；`ApiCaseGeneratoMainWorkFlow0` - 并发生成 |
| **api_basecase_workflow.py** | 基础用例生成工作流 | `ApiBaseCaseGeneratorWorkFlow` - 生成基础用例并保存到数据库 |
| **api_run_case_wrokflow.py** | 可执行用例生成工作流 | `ApiRunCaseGeneratorWorkFlow` - 生成可执行用例、预执行验证、保存到数据库 |
| **case_generator_workflow.py** | 功能测试用例生成工作流 | 基于RAG检索生成功能测试用例 |

### 2.3 工具层 (utils/)

| 文件 | 功能描述 | 核心类/方法 |
|------|---------|------------|
| **api_testcase_execute.py** | 测试用例执行器 | `TestExecutor` - 执行单条用例、测试套件、工作流用例 |
| **basecase.py** | 单条接口用例执行核心逻辑 | `BaseTestCase` - 变量替换、发送请求、断言验证 |
| **database_client.py** | 数据库客户端 | `DBClient` - 数据库连接与操作 |
| **test_result.py** | 测试结果记录器 | `TestResult` - 记录执行状态、日志、耗时 |
| **api_document_parser/ai_parser_api_document.py** | AI解析API文档 | `AIAPIDocumentParser` - 使用LLM解析非结构化API文档 |
| **api_document_parser/swagger_document_parser.py** | Swagger文档解析器 | 解析OpenAPI规范文档 |
| **api_document_parser/openapi_document_parser.py** | OpenAPI文档解析器 | 解析OpenAPI 3.0规范 |
| **api_document_parser/postman_json_praser.py** | Postman集合解析器 | 解析Postman JSON格式 |

### 2.4 配置层 (config/)

| 文件 | 功能描述 |
|------|---------|
| **settings.py** | 全局配置，包含LLM模型配置 |
| **prompts/api_cases_work/base_case_generator.py** | 基础用例生成提示词 |
| **prompts/api_cases_work/api_case_generator.py** | 可执行用例生成提示词 |
| **prompts/api_cases_work/base_case_check_coverage.py** | 覆盖率检查提示词 |
| **prompts/api_cases_work/supplement_case.py** | 用例补充生成提示词 |
| **prompts/workflow/*.py** | 功能测试用例生成相关提示词 |
| **prompts/agents/case_generator_agent.py** | 功能测试用例生成Agent提示词 |

### 2.5 知识库层 (LightRAG/)

| 文件 | 功能描述 |
|------|---------|
| **app.py** | RAG应用入口 |
| **rag_manager.py** | RAG管理器 |
| **document_service.py** | 文档服务 |
| **neo4j_storage.py** | Neo4j图数据库存储 |
| **embedding_func.py** | 向量化函数 |
| **llm_model_func.py** | LLM模型调用 |

### 2.6 全局工具 (mac_tools/)

| 文件 | 功能描述 | 核心工具函数 |
|------|---------|------------|
| **global_tools.py** | 测试数据生成工具 | `random_mobile()`, `random_account()`, `random_password()`, `random_email()`, `md5_encrypt()` |
| **tools.py** | Agent工具定义 | `generator_case()`, `search_requirement()` |

---

## 3. 智能体流程图

### 3.1 API接口自动化测试智能体流程

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        API接口自动化测试智能体工作流程                        │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐               │
│  │ 1.读取API文档 │───▶│ 2.AI解析文档 │───▶│ 3.生成基础用例   │               │
│  └──────────────┘    └──────────────┘    └────────┬─────────┘               │
│                                                   │                         │
│                                                   ▼                         │
│  ┌──────────────────────────────────────────────────────────────┐           │
│  │              ApiBaseCaseGeneratorWorkFlow                      │           │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │           │
│  │  │生成基础用例   │───▶│检查覆盖率    │───▶│输出并保存     │    │           │
│  │  └──────────────┘    └──────┬───────┘    └──────────────┘    │           │
│  │                             │                                 │           │
│  │              ┌───────────────┘                                 │           │
│  │              ▼                                                 │           │
│  │  ┌──────────────────────┐                                      │           │
│  │  │覆盖率不通过→补充用例  │─────────────────────────────────────│           │
│  │  └──────────────────────┘                                      │           │
│  └─────────────────────────────────────────────────────────────────┘           │
│                                                   │                         │
│                                                   ▼                         │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │              ApiRunCaseGeneratorWorkFlow（逐个/并发）                 │    │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────┐│    │
│  │  │加载工具函数  │───▶│生成可执行用例│───▶│预执行验证    │───▶│保存 ││    │
│  │  └──────────────┘    └──────────────┘    └──────┬───────┘    └─────┘│    │
│  │                                                 │                    │    │
│  │                                    ┌────────────┴────────────┐       │    │
│  │                                    ▼                         ▼       │    │
│  │                          ┌──────────────┐          ┌──────────────┐  │    │
│  │                          │状态=ready    │          │状态=disabled │  │    │
│  │                          │→保存用例     │          │→重新生成     │  │    │
│  │                          └──────────────┘          └──────────────┘  │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                   │                         │
│                                                   ▼                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │ 4.执行测试   │───▶│ 5.生成报告   │───▶│ 6.保存报告   │                   │
│  └──────────────┘    └──────────────┘    └──────────────┘                   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 功能测试用例生成智能体流程

```
┌──────────────────────────────────────────────────────────────────────────┐
│                      功能测试用例生成智能体工作流程                       │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  用户提问                                                                 │
│      │                                                                   │
│      ▼                                                                   │
│  ┌──────────────────┐                                                    │
│  │   CaseGenerator  │                                                    │
│  │      Agent       │                                                    │
│  └────────┬─────────┘                                                    │
│           │                                                               │
│           ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │                    Tool Selection                              │     │
│  │  ┌──────────────┐              ┌──────────────┐                │     │
│  │  │search_       │              │generator_   │                │     │
│  │  │requirement   │◀────────────▶│case         │                │     │
│  │  │(检索知识库)   │              │(生成用例)   │                │     │
│  │  └──────┬───────┘              └──────┬───────┘                │     │
│  │         │                             │                        │     │
│  │         ▼                             ▼                        │     │
│  │  ┌──────────────┐              ┌──────────────┐                │     │
│  │  │ LightRAG     │              │ case_generator│               │     │
│  │  │ (文档检索)   │              │ workflow      │               │     │
│  │  └──────────────┘              └──────┬───────┘                │     │
│  │                                        │                        │     │
│  └────────────────────────────────────────┼────────────────────────┘     │
│                                           ▼                             │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │              case_generator_workflow 执行流程                    │     │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │     │
│  │  │生成测试点    │───▶│验证覆盖率    │───▶│生成测试用例  │       │     │
│  │  └──────────────┘    └──────┬───────┘    └──────┬───────┘       │     │
│  │                             │                    │               │     │
│  │              ┌──────────────┴────────────────────┘               │     │
│  │              ▼                                                  │     │
│  │  ┌──────────────────────┐                                       │     │
│  │  │补充缺失测试点/用例    │───────────────────────────────────────│     │
│  │  └──────────────────────┘                                       │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│                                           │                             │
│                                           ▼                             │
│                                    输出测试用例并保存                      │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 代码调用关系

### 4.1 模块依赖关系表

| 模块 | 依赖模块 | 依赖说明 |
|------|---------|---------|
| **agents/api_testcase_agent.py** | `utils.api_document_parser.ai_parser_api_document`, `workflow.api_case_generator_main_workflow`, `utils.api_testcase_execute` | 解析文档 → 生成用例 → 执行测试 |
| **agents/case_generator_agent.py** | `mac_tools.tools`, `config.prompts.agents.case_generator_agent`, `config.settings` | 创建Agent并执行 |
| **workflow/api_case_generator_main_workflow.py** | `workflow.api_basecase_workflow`, `workflow.api_run_case_wrokflow` | 调用子工作流 |
| **workflow/api_basecase_workflow.py** | `config.prompts.api_cases_work`, `config.settings` | 使用提示词和LLM |
| **workflow/api_run_case_wrokflow.py** | `utils.api_testcase_execute`, `config.prompts.api_cases_work` | 生成可执行用例并执行 |
| **utils/api_testcase_execute.py** | `utils.basecase`, `utils.test_result`, `utils.database_client` | 执行用例并记录结果 |
| **utils/basecase.py** | `mac_tools.global_tools`, `utils.database_client`, `utils.test_result` | 执行单条用例逻辑 |
| **LightRAG/*` | `config.settings`, `neo4j`, `langchain` | RAG检索功能 |

### 4.2 数据流向图

```
API文档 → AIAPIDocumentParser → api_info (dict)
    ↓
ApiCaseGeneratoMainWorkFlow
    ↓
ApiBaseCaseGeneratorWorkFlow → base_cases (list) → MySQL(api_base_case)
    ↓
ApiRunCaseGeneratorWorkFlow → api_cases (list) → MySQL(api_test_case)
    ↓
TestExecutor → TestResult → JSON报告 → output/test_reports/
```

---

## 5. 智能体协作机制

### 5.1 协作方式

两个智能体相对独立，分别处理不同类型的测试任务：

| 智能体 | 输入 | 输出 | 应用场景 |
|-------|------|------|---------|
| **功能测试用例生成智能体** | 产品需求文档、功能说明 | 功能测试用例（自然语言描述） | 手工测试用例设计 |
| **API接口自动化测试智能体** | API文档（OpenAPI/Swagger/Markdown） | 可执行的接口测试用例 + 测试报告 | 自动化接口测试 |

### 5.2 信息共享机制

1. **数据库共享**：两个智能体共享同一个数据库，可查询彼此生成的用例
2. **RAG知识库**：功能测试用例生成智能体使用LightRAG检索需求文档
3. **文件系统**：测试报告和用例文件统一存储在 `output/` 目录

### 5.3 任务分配策略

- **功能测试用例生成**：通过自然语言对话触发，适用于黑盒测试场景
- **API接口自动化测试**：通过API文档触发，适用于接口自动化测试场景

---

## 6. 技术栈说明

### 6.1 核心技术

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| **编程语言** | Python | 3.11+ | 主要开发语言 |
| **LLM框架** | LangChain | 0.2+ | LLM集成、工具调用 |
| **工作流引擎** | LangGraph | 0.1+ | 工作流编排 |
| **知识库** | LightRAG | - | 文档检索与问答 |
| **数据库** | MySQL | 8.0+ | 用例存储 |
| **图数据库** | Neo4j | - | RAG向量存储 |
| **HTTP客户端** | requests | 2.31+ | 接口请求 |
| **JSON解析** | jmespath | 1.0+ | JSON数据提取 |
| **环境管理** | python-dotenv | 1.0+ | 环境变量配置 |

### 6.2 依赖安装

```bash
pip install langchain langgraph requests python-dotenv jmespath pymysql
```

---

## 7. 部署与运行指南

### 7.1 环境配置

#### 7.1.1 环境变量 (.env)

```ini
# 数据库配置
db_name=localhost
db_port=3306
db_user=root
db_password=123456
db_database=test

# LLM配置
MODEL_V3=deepseek-ai/DeepSeek-V3.2
GJLD_base_url=https://api.siliconflow.cn/v1
GJLD_api_key=your_api_key_here
```

#### 7.1.2 数据库表结构

```sql
-- 基础用例表
CREATE TABLE api_base_case (
    id INT PRIMARY KEY AUTO_INCREMENT,
    interface_id VARCHAR(50),
    name VARCHAR(200),
    steps TEXT,
    expected TEXT,
    status VARCHAR(20) DEFAULT 'ready',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 可执行用例表
CREATE TABLE api_test_case (
    id INT PRIMARY KEY AUTO_INCREMENT,
    base_case_id INT,
    name VARCHAR(200),
    description TEXT,
    interface_name VARCHAR(200),
    preconditions JSON,
    request JSON,
    assertions JSON,
    status VARCHAR(20) DEFAULT 'disabled',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (base_case_id) REFERENCES api_base_case(id)
);
```

### 7.2 运行方式

#### 7.2.1 运行API接口自动化测试智能体

```bash
cd d:\PythonProject\AItestcase_Agents
python agents/api_testcase_agent.py
```

**执行流程**：
1. 读取API文档 (`datas/ApiDocument/LoginApi_Doc.md`)
2. AI解析文档提取接口信息
3. 生成基础用例并保存到数据库
4. 生成可执行用例并预执行验证
5. 执行所有用例并生成报告

#### 7.2.2 运行功能测试用例生成智能体

```bash
cd d:\PythonProject\AItestcase_Agents
python agents/case_generator_agent.py
```

**执行流程**：
1. 创建Agent并绑定工具
2. 用户输入需求查询
3. Agent决定是否检索知识库
4. 生成功能测试用例
5. 输出并保存测试用例

### 7.3 输出说明

| 输出类型 | 路径 | 说明 |
|---------|------|------|
| **测试报告** | `output/test_reports/test_report_*.json` | JSON格式的测试报告 |
| **功能测试用例** | `output/{项目名称}/{模块名称}/testcases_*.json` | 功能测试用例JSON文件 |
| **日志** | `workflow/mainworkflowlog.log` | 工作流执行日志 |

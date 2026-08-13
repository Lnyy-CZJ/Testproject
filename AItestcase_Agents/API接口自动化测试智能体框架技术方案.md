# API接口自动化测试智能体框架技术方案

> **状态**: 正式发布
> **适用范围**: API接口自动化测试

---

## 目录

1. [框架概述](#1-框架概述)
2. [框架架构设计](#2-框架架构设计)
3. [接口测试用例设计规范](#3-接口测试用例设计规范与管理流程)
4. [测试脚本开发流程](#4-测试脚本开发流程)
5. [测试数据生成与管理机制](#5-测试数据生成与管理机制)
6. [测试执行与调度流程](#6-测试执行与调度流程)
7. [测试结果分析与报告生成](#7-测试结果分析与报告生成)
8. [框架扩展与维护](#8-框架扩展与维护)
9. [最佳实践](#9-最佳实践)

---

## 1. 框架概述

### 1.1 项目背景

API接口自动化测试智能体框架是一个基于大语言模型（LLM）的智能测试用例生成与执行平台。框架通过AI技术自动解析API文档、生成测试用例、执行接口测试，并生成详细的测试报告，大幅提升接口测试效率。

### 1.2 核心能力

| 能力模块 | 功能描述 |
|---------|---------|
| **智能解析** | 自动解析非结构化API文档，提取接口定义 |
| **用例生成** | 基于AI生成覆盖全面的测试用例 |
| **数据驱动** | 支持测试数据与用例分离，便于维护 |
| **自动化执行** | 批量执行测试用例，支持依赖管理 |
| **结果分析** | 自动分析测试结果，生成可视化报告 |

### 1.3 技术栈

```
┌─────────────────────────────────────────────────────────────┐
│                      技术栈概览                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  AI能力层                                                    │
│  ├── 大语言模型（deepseek-v3.5等）                          │
│  ├── LangChain框架                                          │
│  └── Prompt Engineering                                     │
│                                                             │
│  执行引擎层                                                  │
│  ├── Python 3.11+                                          │
│  ├── requests/http.client                                   │
│  └── concurrent.futures（并发执行）                         │
│                                                             │
│  数据存储层                                                  │
│  ├── MySQL（用例、结果存储）                                │
│  ├── YAML/JSON（配置文件）                                  │
│  └── 文件系统（报告、日志）                                  │
│                                                             │
│  应用框架层                                                  │
│  ├── 智能体编排（LangGraph）                               │
│  ├── 工作流引擎                                            │
│  └── 插件系统                                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 框架架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          框架整体架构                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      用户交互层                                    │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │   │
│  │  │ CLI命令行   │  │ API接口    │  │ Web界面    │             │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘             │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      智能体编排层                                  │   │
│  │  ┌───────────────────────────────────────────────────────────┐     │   │
│  │  │                    ApiTestcaseAgent                        │     │   │
│  │  │  智能体主入口，协调各工作流程                               │     │   │
│  │  └───────────────────────────────────────────────────────────┘     │   │
│  │                                    │                              │   │
│  │  ┌───────────────────────────────────────────────────────────┐     │   │
│  │  │                      Workflows                             │     │   │
│  │  │  ├── api_case_generator_main_workflow  主工作流             │     │   │
│  │  │  ├── api_basecase_workflow          基础用例生成          │     │   │
│  │  │  └── api_run_case_workflow          可执行用例生成        │     │   │
│  │  └───────────────────────────────────────────────────────────┘     │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      核心能力层                                    │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │   │
│  │  │   Parsers    │  │  Generators  │  │   Executors  │           │   │
│  │  │  文档解析器   │  │  用例生成器   │  │   测试执行器  │           │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘           │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │   │
│  │  │   Prompts    │  │    Tools     │  │    Utils     │           │   │
│  │  │  提示词模板   │  │   工具函数   │  │   公共工具   │           │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      数据存储层                                    │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │   │
│  │  │    MySQL     │  │  YAML/JSON   │  │    Files     │           │   │
│  │  │  用例库      │  │  数据文件     │  │  报告/日志   │           │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件

| 组件 | 路径 | 职责 |
|------|------|------|
| **ApiTestcaseAgent** | `agents/api_test/api_testcase_agent.py` | 智能体主入口，协调各工作流程 |
| **ApiParser** | `agents/api_test/parsers/` | 解析API文档为结构化数据 |
| **CaseGenerator** | `agents/api_test/prompts/` | AI驱动的用例生成 |
| **TestExecutor** | `agents/common/utils/api_testcase_execute.py` | 测试用例执行引擎 |
| **BaseTestCase** | `agents/common/utils/basecase.py` | 单条用例执行器 |
| **TestDataHub** | `agents/common/utils/test_data_hub.py` | 测试数据管理器 |
| **Workflows** | `agents/api_test/workflows/` | 工作流编排 |

### 2.3 模块划分

```
agents/
├── api_test/                          # API测试智能体
│   ├── api_testcase_agent.py          # 智能体主入口
│   ├── parsers/                       # 文档解析器
│   │   └── ai_parser_api_document.py  # AI解析器
│   ├── prompts/                       # 提示词模板
│   │   ├── api_document_parser.py     # 文档解析提示词
│   │   ├── api_case_generator.py      # 可执行用例生成
│   │   ├── base_case_generator.py     # 基础用例生成
│   │   └── supplement_case.py          # 用例补充
│   └── workflows/                      # 工作流
│       ├── api_case_generator_main_workflow.py  # 主流程
│       ├── api_basecase_workflow.py   # 基础用例流程
│       └── api_run_case_wrokflow.py   # 可执行用例流程
│
├── common/                            # 公共模块
│   ├── config/                        # 配置
│   │   ├── settings.py                # LLM配置
│   │   └── LightRAGTools.py          # RAG工具
│   ├── tools/                          # 工具函数
│   │   ├── tools.py                   # MCP工具
│   │   └── global_tools.py            # 全局辅助函数
│   └── utils/                          # 公共工具
│       ├── api_testcase_execute.py    # 测试执行器
│       ├── basecase.py                # 用例执行器
│       ├── database_client.py         # 数据库客户端
│       ├── test_data_hub.py           # 数据管理器
│       └── test_result.py             # 结果类
│
└── functional_test/                    # 功能测试智能体
    └── ...
```

### 2.4 模块交互关系

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         模块交互关系图                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  用户请求                                                               │
│      │                                                                  │
│      ▼                                                                  │
│  ┌─────────────────┐                                                  │
│  │ ApiTestcaseAgent │                                                  │
│  └────────┬────────┘                                                  │
│           │                                                             │
│           ▼                                                             │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                      Workflows                                    │    │
│  │                                                                   │    │
│  │   ┌──────────────────┐    ┌──────────────────┐                   │    │
│  │   │ ApiBaseCaseWorkflow │──▶│ ApiRunCaseWorkflow │               │    │
│  │   └────────┬──────────┘    └────────┬──────────┘               │    │
│  │            │                          │                          │    │
│  │            ▼                          ▼                          │    │
│  │   ┌──────────────────┐    ┌──────────────────┐                   │    │
│  │   │ BaseCaseGenerator │    │ CaseGenerator    │                   │    │
│  │   │ (Prompt)           │    │ (Prompt)          │                   │    │
│  │   └────────┬──────────┘    └────────┬──────────┘               │    │
│  │            │                          │                          │    │
│  └────────────┼──────────────────────────┼───────────────────────────┘    │
│               │                          │                              │
│               ▼                          ▼                              │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                        LLM Service                               │    │
│  │                    (OpenAI/Claude)                               │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                        执行层                                      │    │
│  │                                                                   │    │
│  │   ┌─────────────────┐    ┌─────────────────┐                     │    │
│  │   │ TestDataHub     │    │ TestExecutor    │                     │    │
│  │   │ (数据管理)       │    │ (用例执行)       │                     │    │
│  │   └────────┬────────┘    └────────┬────────┘                     │    │
│  │            │                        │                              │    │
│  │            ▼                        ▼                              │    │
│  │   ┌─────────────────────────────────────────────────────────┐      │    │
│  │   │                    BaseTestCase                          │      │    │
│  │   │   - HTTP请求  - 变量替换  - 脚本执行  - 结果记录         │      │    │
│  │   └─────────────────────────────────────────────────────────┘      │    │
│  │                                                                   │    │
│  └───────────────────────────────────────────────────────────────────┘    │
│                                    │                                    │
│                                    ▼                                    │
│                            ┌─────────────┐                             │
│                            │  测试报告    │                             │
│                            └─────────────┘                             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 接口测试用例设计规范与管理流程

### 3.1 用例分层模型

```
┌─────────────────────────────────────────────────────────────────┐
│                       用例分层模型                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  L1: 冒烟测试用例                                               │
│  ─────────────────────────────────────                          │
│  • 核心业务流程                                                  │
│  • 正向场景                                                     │
│  • 覆盖率: ~20%                                                 │
│  • 执行频率: 每次构建                                           │
│                                                                 │
│  L2: 核心功能测试用例                                           │
│  ─────────────────────────────────────                          │
│  • 主要功能点                                                   │
│  • 边界值测试                                                   │
│  • 覆盖率: ~50%                                                 │
│  • 执行频率: 每日                                                │
│                                                                 │
│  L3: 详细测试用例                                               │
│  ─────────────────────────────────────                          │
│  • 异常场景                                                     │
│  • 安全测试                                                     │
│  • 覆盖率: ~80%                                                 │
│  • 执行频率: 每周                                                │
│                                                                 │
│  L4: 探索性测试用例                                             │
│  ─────────────────────────────────────                          │
│  • 随机组合                                                     │
│  • 边界探索                                                     │
│  • 覆盖率: ~100%                                                │
│  • 执行频率: 按需                                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 用例结构定义

#### 3.2.1 基础用例结构

```json
{
  "name": "L2-T1-正常登录-用户名密码正确",
  "steps": [
    "发送POST请求到登录URL，请求体包含用户名和密码",
    "验证响应状态码为200"
  ],
  "dependencies": ["初始化-获取Token"],
  "level": "L2"
}
```

#### 3.2.2 可执行用例结构

```json
{
  "id": 1001,
  "name": "L2-T1-正常登录-用户名密码正确",
  "description": "验证用户名密码正确时能够成功登录",
  "interface": "/api/user/login",
  "request": {
    "method": "POST",
    "url": "/api/user/login",
    "base_url": "${{base_url}}",
    "headers": {
      "Content-Type": "application/json"
    },
    "body": {
      "accounts": "${{test_account}}",
      "pwd": "${{test_password}}"
    },
    "setup_script": "",
    "teardown_script": ""
  },
  "preconditions": [],
  "level": "L2"
}
```

### 3.3 参数分类规范

| 分类 | 标识 | 说明 | 测试要求 |
|------|------|------|---------|
| **固定参数** | `param_role: fixed` | 固定值，不可改变 | 使用文档指定值 |
| **必填参数** | `param_role: required` | 必填项 | 测试缺失、正常、边界 |
| **可选参数** | `param_role: optional` | 可选填 | 测试省略、显式值、默认值 |
| **条件参数** | `param_role: conditional` | 依赖其他参数 | 测试依赖关系 |

### 3.4 用例生成流程

```
┌─────────────────────────────────────────────────────────────────┐
│                       用例生成流程                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. API文档解析                                                 │
│     ┌─────────────────────────────────────────────────────┐    │
│     │  输入: 非结构化API文档                                │    │
│     │  处理: AI解析 → 结构化JSON                           │    │
│     │  输出: {path, method, parameters, requestBody, ...}  │    │
│     └─────────────────────────────────────────────────────┘    │
│                          │                                     │
│                          ▼                                     │
│  2. 基础用例生成                                                │
│     ┌─────────────────────────────────────────────────────┐    │
│     │  输入: 结构化API信息                                  │    │
│     │  处理: LLM生成测试点描述                             │    │
│     │  输出: [{name, steps, dependencies, level}]        │    │
│     └─────────────────────────────────────────────────────┘    │
│                          │                                     │
│                          ▼                                     │
│  3. 覆盖率检查                                                  │
│     ┌─────────────────────────────────────────────────────┐    │
│     │  检查: 测试点是否覆盖所有参数                        │    │
│     │  判断: 缺失则补充生成                                │    │
│     └─────────────────────────────────────────────────────┘    │
│                          │                                     │
│                          ▼                                     │
│  4. 可执行用例生成                                              │
│     ┌─────────────────────────────────────────────────────┐    │
│     │  输入: 基础用例 + 测试数据                           │    │
│     │  处理: 填充请求参数 → 语法校验                       │    │
│     │  输出: 完整可执行用例                               │    │
│     └─────────────────────────────────────────────────────┘    │
│                          │                                     │
│                          ▼                                     │
│  5. 用例保存                                                    │
│     ┌─────────────────────────────────────────────────────┐    │
│     │  存储: MySQL数据库                                  │    │
│     │  文件: 测试数据YAML                                  │    │
│     └─────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.5 用例管理

| 管理维度 | 说明 |
|---------|------|
| **版本管理** | 用例关联API版本，支持历史追溯 |
| **标签管理** | 按模块、功能、优先级标签分类 |
| **依赖管理** | 用例间依赖关系维护 |
| **变更追踪** | 记录用例创建、修改历史 |

---

## 4. 测试脚本开发流程

### 4.1 开发规范

#### 4.1.1 命名规范

| 元素 | 规范 | 示例 |
|------|------|------|
| 文件名 | 小写下划线分隔 | `test_login.py` |
| 类名 | PascalCase | `class LoginTestCase` |
| 函数名 | 小写下划线分隔 | `def test_user_login` |
| 常量 | 全大写下划线 | `MAX_RETRY_COUNT` |
| 变量 | 小写下划线 | `test_data` |

#### 4.1.2 代码结构

```python
# -*- coding: utf-8 -*-
"""
模块说明文档

功能:
    - 功能点1
    - 功能点2

使用示例:
    >>> from module import Class
    >>> obj = Class()
"""

import os
import sys
from typing import Dict, List, Optional


class ModuleClass:
    """类功能说明"""

    def __init__(self, config: Dict):
        """
        初始化方法

        Args:
            config: 配置字典
        """
        self.config = config
        self._initialized = False

    def execute(self, data: Dict) -> Dict:
        """
        执行方法

        Args:
            data: 输入数据

        Returns:
            执行结果

        Raises:
            ValueError: 参数错误
        """
        if not data:
            raise ValueError("参数data不能为空")

        self._initialized = True
        return {"status": "success", "data": data}
```

### 4.2 依赖管理

#### 4.2.1 核心依赖

```txt
# requirements.txt

# AI能力
langchain>=0.1.0
langchain-openai>=0.0.5

# HTTP请求
requests>=2.31.0

# 数据库
pymysql>=1.1.0
SQLAlchemy>=2.0.0

# 数据处理
pyyaml>=6.0
jmespath>=0.10.0

# 测试框架
pytest>=7.0.0
pytest-asyncio>=0.21.0

# 日志
loguru>=0.7.0
```

#### 4.2.2 依赖安装

```bash
# 安装所有依赖
pip install -r requirements.txt

# 安装开发依赖
pip install -r requirements-dev.txt

# 验证安装
python -c "import langchain; print(langchain.__version__)"
```

### 4.3 脚本开发模板

```python
# -*- coding: utf-8 -*-
"""
API接口测试脚本模板

Author: [作者]
Date: [日期]
"""

import os
import sys
import time
from typing import Dict, Any, Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.common.utils.api_testcase_execute import TestExecutor
from agents.common.utils.test_result import TestResult


class ApiTestSuite:
    """接口测试套件"""

    def __init__(self, env: str = "test"):
        """
        初始化测试套件

        Args:
            env: 测试环境 (test/staging/prod)
        """
        self.env = env
        self.test_env_global = self._load_env_config()
        self.executor = TestExecutor(
            test_env_global=self.test_env_global,
            db_config=[]  # 根据需要配置
        )

    def _load_env_config(self) -> Dict[str, Any]:
        """加载环境配置"""
        configs = {
            "test": {
                "base_url": "http://test-api.example.com",
                "api_key": "test_key_xxx"
            },
            "staging": {
                "base_url": "http://staging-api.example.com",
                "api_key": "staging_key_xxx"
            }
        }
        return configs.get(self.env, configs["test"])

    def run_suite(self, case_ids: list = None) -> TestResult:
        """
        运行测试套件

        Args:
            case_ids: 要执行的用例ID列表，None表示全部

        Returns:
            汇总测试结果
        """
        # 加载用例
        cases = self._load_cases(case_ids)

        # 执行用例
        results = []
        for case in cases:
            result = self.executor.execute_test_case(case)
            results.append(result)

        # 生成汇总
        return self._summarize_results(results)

    def _load_cases(self, case_ids: list = None) -> list:
        """加载测试用例"""
        # 实现用例加载逻辑
        pass

    def _summarize_results(self, results: list) -> TestResult:
        """汇总测试结果"""
        # 实现结果汇总逻辑
        pass


if __name__ == "__main__":
    suite = ApiTestSuite(env="test")
    result = suite.run_suite()
    print(f"测试完成: {result.total}个用例, "
          f"成功: {result.success}, "
          f"失败: {result.fail}")
```

---

## 5. 测试数据生成与管理机制

### 5.1 数据分层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                       测试数据分层架构                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │                    基础配置层                              │   │
│  │  • base_url, headers, content_type                       │   │
│  │  • 环境无关的配置                                          │   │
│  └───────────────────────────────────────────────────────────┘   │
│                              │                                  │
│                              ▼                                  │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │                    基准数据层 (Baseline)                   │   │
│  │  • 正向测试的参照基准                                      │   │
│  │  • 用于控制变量法                                          │   │
│  │  • 所有参数的正确值组合                                    │   │
│  └───────────────────────────────────────────────────────────┘   │
│                              │                                  │
│                              ▼                                  │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │                    测试数据层                             │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │   │
│  │  │  Boundary   │  │  Abnormal   │  │  Security   │      │   │
│  │  │  边界数据    │  │  异常数据    │  │  安全数据    │      │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘      │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 数据文件格式

#### 5.2.1 YAML格式（推荐）

```yaml
# datas/TestData/{API名}/{API名}_data.yaml

api_name: "登录接口"
api_path: "/api/user/login"
version: "1.0"

base_data:
  base_url: "${{base_url}}"
  headers:
    Content-Type: "application/json"

test_data:
  # 基准数据
  baseline:
    accounts: "testuser01"
    pwd: "TestPass123"
    type: "username"

  # 边界数据
  boundary:
    pwd_min_minus:
      _inherits: "baseline"
      _overrides:
        pwd: "test1"       # 5位
      _description: "密码长度最小值-1"

    pwd_max_plus:
      _inherits: "baseline"
      _overrides:
        pwd: "TestPasswordExceeds20Char"  # 21位
      _description: "密码长度最大值+1"

  # 异常数据
  abnormal:
    accounts_empty:
      _inherits: "baseline"
      _overrides:
        accounts: ""
      _description: "账号为空"

    pwd_empty:
      _inherits: "baseline"
      _overrides:
        pwd: ""
      _description: "密码为空"

  # 安全测试数据
  security:
    sql_injection:
      _inherits: "baseline"
      _overrides:
        accounts: "' OR '1'='1"
      _description: "SQL注入测试"
```

### 5.3 数据管理组件

| 组件 | 功能 |
|------|------|
| **TestDataHub** | 统一数据加载、解析、分发 |
| **数据生成器** | 根据API规则自动生成测试数据 |
| **变量替换** | `${{variable}}` 语法，运行时替换 |

### 5.4 变量替换机制

```
┌─────────────────────────────────────────────────────────────────┐
│                       变量替换机制                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 数据注入                                                    │
│     ┌─────────────────────────────────────────────────────┐    │
│     │ test_env_global: {                                  │    │
│     │   base_url: "http://api.example.com",               │    │
│     │   test_account: "testuser",                         │    │
│     │   test_password: "Pass123"                         │    │
│     │ }                                                   │    │
│     └─────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼                                       │
│  2. 用例模板                                                     │
│     ┌─────────────────────────────────────────────────────┐    │
│     │ request: {                                          │    │
│     │   base_url: "${{base_url}}",                       │    │
│     │   body: {                                          │    │
│     │     username: "${{test_account}}",                  │    │
│     │     password: "${{test_password}}"                  │    │
│     │   }                                                 │    │
│     │ }                                                   │    │
│     └─────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼                                       │
│  3. 替换结果                                                     │
│     ┌─────────────────────────────────────────────────────┐    │
│     │ request: {                                          │    │
│     │   base_url: "http://api.example.com",               │    │
│     │   body: {                                          │    │
│     │     username: "testuser",                           │    │
│     │     password: "Pass123"                             │    │
│     │   }                                                 │    │
│     │ }                                                   │    │
│     └─────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. 测试执行与调度流程

### 6.1 执行架构

```
┌─────────────────────────────────────────────────────────────────┐
│                       测试执行架构                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    TestExecutor                          │    │
│  │                 测试套件执行器                            │    │
│  │  • 用例加载                                             │    │
│  │  • 结果汇总                                             │    │
│  │  • 报告生成                                             │    │
│  └───────────────────────┬─────────────────────────────────┘    │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  BaseTestCase                            │    │
│  │                 单条用例执行器                            │    │
│  │  • 前置依赖执行                                         │    │
│  │  • 变量替换                                             │    │
│  │  • HTTP请求                                             │    │
│  │  • 后置脚本执行                                         │    │
│  │  • 结果记录                                             │    │
│  └───────────────────────┬─────────────────────────────────┘    │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    HTTP Engine                           │    │
│  │                  HTTP请求引擎                            │    │
│  │  • requests库封装                                       │    │
│  │  • Session复用                                          │    │
│  │  • 超时控制                                             │    │
│  │  • 重试机制                                             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 执行流程

```python
def execute_test_case(case_data: dict) -> TestResult:
    """单条用例执行流程"""

    # 1. 前置依赖执行
    for precond in case_data.get("preconditions", []):
        execute_test_case(precond)

    # 2. 变量替换
    api_info = replace_variables(case_data["request"])

    # 3. 执行前置脚本
    if case_data.get("setup_script"):
        execute_script(case_data["setup_script"])

    # 4. 发送HTTP请求
    response = send_request(api_info)

    # 5. 执行后置脚本
    if case_data.get("teardown_script"):
        execute_script(case_data["teardown_script"])

    # 6. 记录结果
    return build_result(case_data, response)
```

### 6.3 并行执行策略

| 策略 | 说明 | 适用场景 |
|------|------|---------|
| **串行执行** | 按顺序逐一执行 | 有依赖关系的用例 |
| **接口级并行** | 同一接口的用例并行 | 独立接口 |
| **全局并行** | 所有用例并行 | 用例间无依赖 |

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

class ParallelExecutor:
    """并行执行器"""

    def __init__(self, max_workers: int = 5):
        self.max_workers = max_workers

    def execute(self, cases: list) -> list:
        """并行执行用例"""
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.execute_single, case): case
                for case in cases
            }

            for future in as_completed(futures):
                case = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append(self.handle_error(case, e))

        return results
```

### 6.4 触发机制

| 触发方式 | 配置 | 说明 |
|---------|------|------|
| **手动触发** | CLI命令 | 按需执行 |
| **定时触发** | Cron表达式 | 每日/每周 |
| **Webhook触发** | HTTP回调 | 代码提交触发 |
| **API调用** | REST接口 | 集成CI/CD |

```bash
# CLI触发示例
python -m agents.api_test \
    --api-doc "datas/ApiDocument/LoginApi_Doc.md" \
    --env test \
    --cases all

# 生成测试报告
python -m agents.api_test \
    --report \
    --output "output/test_reports"
```

---

## 7. 测试结果分析与报告生成

### 7.1 结果模型

```python
@dataclass
class TestResult:
    """测试结果模型"""

    case_name: str           # 用例名称
    case_id: str            # 用例ID
    status: str             # success/fail/error/skip
    duration: float         # 执行时长(秒)
    start_time: float       # 开始时间戳
    end_time: float         # 结束时间戳

    # 响应信息
    request_url: str        # 请求URL
    request_method: str     # 请求方法
    request_headers: dict    # 请求头
    request_body: dict      # 请求体
    response_status_code: int  # 响应状态码
    response_headers: dict  # 响应头
    response_body: dict     # 响应体

    # 错误信息
    error_message: str      # 错误信息
    traceback: str         # 堆栈信息

    # 日志
    logs: list             # 执行日志
```

### 7.2 报告结构

```json
{
  "report_info": {
    "generated_at": "2026-05-11 10:30:00",
    "environment": "test",
    "total_duration": 125.5
  },
  "summary": {
    "total": 50,
    "success": 45,
    "fail": 3,
    "error": 1,
    "skip": 1,
    "pass_rate": "90.0%"
  },
  "cases": [
    {
      "case_name": "L2-T1-正常登录",
      "status": "success",
      "duration": 0.35,
      "request": {
        "method": "POST",
        "url": "/api/user/login",
        "body": {"accounts": "testuser", "pwd": "****"}
      },
      "response": {
        "status_code": 200,
        "body": {"code": 1, "message": "success"}
      }
    }
  ],
  "errors": [
    {
      "case_name": "L3-T5-SQL注入测试",
      "error": "SecurityException: SQL注入检测",
      "traceback": "..."
    }
  ]
}
```

### 7.3 结果分析维度

| 分析维度 | 指标 | 说明 |
|---------|------|------|
| **通过率** | pass_rate | 成功用例/总用例 |
| **响应时间** | avg_duration, p95_duration | 平均耗时、95分位 |
| **错误分布** | error_by_type | 按错误类型分布 |
| **接口覆盖** | api_coverage | 已测接口/总接口 |
| **场景覆盖** | scenario_coverage | 已测场景/总场景 |

---

## 8. 框架扩展与维护

### 8.1 扩展机制

#### 8.1.1 自定义工具函数

```python
# agents/common/tools/global_tools.py

def custom_data_generator(param_type: str) -> Any:
    """
    自定义测试数据生成器

    Args:
        param_type: 参数类型

    Returns:
        生成的测试数据
    """
    generators = {
        "phone": lambda: "138" + str(random.randint(10000000, 99999999)),
        "email": lambda: f"test{random.randint(1000, 9999)}@example.com",
        "id_card": generate_id_card,
    }
    return generators.get(param_type, lambda: "default_value")()
```

#### 8.1.2 自定义解析器

```python
# agents/api_test/parsers/custom_parser.py

class CustomApiParser:
    """自定义API解析器"""

    def parse(self, doc_content: str) -> dict:
        """
        解析自定义格式文档

        Args:
            doc_content: 文档内容

        Returns:
            结构化API信息
        """
        # 实现自定义解析逻辑
        pass
```

### 8.2 配置管理

```
┌─────────────────────────────────────────────────────────────────┐
│                       配置管理层次                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 环境变量 (.env)                                             │
│     ├── OPENAI_API_KEY                                          │
│     ├── DB_HOST, DB_PORT, DB_USER, DB_PASSWORD                  │
│     └── LOG_LEVEL                                               │
│                                                                 │
│  2. 项目配置 (config/)                                           │
│     ├── settings.py       # LLM配置                            │
│     ├── database.yaml      # 数据库连接                          │
│     └── environments/      # 环境配置                           │
│         ├── test.yaml                                         │
│         └── prod.yaml                                         │
│                                                                 │
│  3. 用例配置 (case_config.yaml)                                  │
│     ├── retry: 3                                              │
│     ├── timeout: 30                                           │
│     └── parallel: 5                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 8.3 维护流程

| 维护类型 | 频率 | 内容 |
|---------|------|------|
| **代码审查** | 每次提交 | 代码规范、安全检查 |
| **单元测试** | 每次提交 | 核心函数覆盖 |
| **集成测试** | 每日 | 全流程验证 |
| **版本发布** | 按需 | 回归测试 |

---

## 9. 最佳实践

### 9.1 用例设计最佳实践

1. **单一职责**：每个用例只验证一个功能点
2. **独立性**：用例间无依赖，可独立执行
3. **可重复性**：相同输入产生相同结果
4. **清晰命名**：`{Level}-{模块}-{场景}-{预期}`

### 9.2 数据管理最佳实践

1. **分离原则**：数据与用例分离
2. **环境隔离**：测试环境与生产环境数据隔离
3. **数据清理**：测试后清理产生的数据
4. **版本控制**：测试数据纳入版本控制

### 9.3 执行最佳实践

1. **分层执行**：按L1/L2/L3分层执行
2. **智能重试**：网络波动时自动重试
3. **并发优化**：无依赖用例并行执行
4. **失败隔离**：单个用例失败不影响其他用例

### 9.4 报告最佳实践

1. **及时通知**：失败用例及时通知相关人
2. **趋势分析**：历史数据分析，发现退化趋势
3. **关联追溯**：报告关联代码提交记录
4. **定期回顾**：分析失败原因，优化测试用例

---

## 附录

### A. 术语表

| 术语 | 定义 |
|------|------|
| **智能体 (Agent)** | 能够自主决策和执行任务的AI系统 |
| **工作流 (Workflow)** | 定义任务执行顺序和逻辑的结构 |
| **提示词 (Prompt)** | 与LLM交互的指令文本 |
| **Baseline Data** | 基准数据，用于正向测试的参照数据 |
| **控制变量法** | 每次只改变一个测试参数的方法 |

### B. 目录结构

```
AItestcase_Agents/
├── agents/                     # 智能体代码
│   ├── api_test/              # API测试智能体
│   ├── common/                # 公共模块
│   └── functional_test/       # 功能测试智能体
├── datas/                      # 数据目录
│   ├── ApiDocument/           # API文档
│   └── TestData/              # 测试数据
├── output/                     # 输出目录
│   └── test_reports/          # 测试报告
├── tests/                     # 测试代码
├── docs/                      # 文档
├── requirements.txt           # 依赖
└── README.md                  # 项目说明
```

### C. 参考文档

- [统一接口测试用例提示词设计文档](统一接口测试用例提示词设计文档.md)
- [项目代码规范](CODE_WIKI.md)
- [智能体运行约束](AGENTS.md)

---
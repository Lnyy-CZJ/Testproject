"""
公共模块

提供两个智能体共享的配置、工具和工具类

主要组件：
- config/                : 配置模块
    - settings.py         : LLM模型配置
    - LightRAGTools.py    : RAG工具封装
- tools/                 : 工具模块
    - tools.py            : MCP工具函数
    - global_tools.py     : 全局辅助函数
- utils/                 : 工具类模块
    - api_testcase_execute.py : 测试执行器
    - basecase.py         : 测试用例基类
    - database_client.py  : 数据库客户端
    - test_result.py      : 测试结果类

使用方法：
    # 导入LLM配置
    from agents.common.config.settings import llm

    # 导入工具
    from agents.common.tools.tools import generator_case

    # 导入执行器
    from agents.common.utils.api_testcase_execute import TestExecutor
"""

__all__ = ['config', 'tools', 'utils']

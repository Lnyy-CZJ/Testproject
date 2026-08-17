"""
API接口自动化测试智能体模块

该模块负责API接口自动化测试的全流程：
- 文档解析
- 用例生成
- 用例执行
- 报告生成

主要组件：
- agent.py               : 智能体主入口
- workflows/             : 工作流定义
- parsers/               : 文档解析器
- prompts/               : 提示词模板

使用方法：
    from agents.api_test import APITestCaseExecutor

    executor = APITestCaseExecutor(
        api_doc_path="path/to/api_doc.md",
        test_env={...},
        db_config=[...]
    )
    executor.run()
"""

__all__ = ['agent', 'workflows', 'parsers', 'prompts']

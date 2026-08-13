"""
功能测试用例生成智能体模块

该模块负责根据需求文档生成功能测试用例

主要组件：
- case_generator_agent.py : 智能体主入口
- workflows/              : 工作流定义
- prompts/                : 提示词模板

使用方法：
    from agents.functional_test.case_generator_agent import main

    # 或直接导入
    from agents.functional_test import case_generator_agent
"""

__all__ = ['case_generator_agent', 'workflows', 'prompts']

import os
import sys
import warnings

os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

import asyncio
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# 在导入 langchain 前拦截特定警告（langchain 内部会在导入时注册自己的过滤器，常规 filterwarnings 无法覆盖）
_warn_original = warnings.warn
def _suppress_langchain_warnings(message, category=UserWarning, *args, **kwargs):
    if isinstance(category, type):
        cat_name = category.__name__
        if cat_name in ('LangChainDeprecationWarning', 'LangChainPendingDeprecationWarning'):
            return
    if isinstance(message, str) and 'Mixing V1 models and V2 models' in message:
        return
    return _warn_original(message, category, *args, **kwargs)
warnings.warn = _suppress_langchain_warnings

from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import dotenv
from agents.common.tools.tools import generator_case, generator_test_points, set_tool_config
from agents.functional_test.prompts.case_generator_agent import prompt as case_generator_agent_prompt
from agents.common.config.settings import llm
# 加载.env 文件中的环境变量
dotenv.load_dotenv()

async def main():
    # 创建 prompt 模板
    prompt = ChatPromptTemplate.from_messages([
        ("system", case_generator_agent_prompt),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    
    # 创建 agent
    agent = create_tool_calling_agent(
        llm=llm,
        tools=[generator_test_points, generator_case],
        prompt=prompt
    )
    
    # 创建 AgentExecutor
    agent_executor = AgentExecutor(
        agent=agent,
        tools=[generator_test_points, generator_case],
        verbose=False,   # True 开启调试模式，打印 agent 的中间过程，False 不打印
        handle_parsing_errors=True
    )
    
    doc_path = os.path.join(os.path.dirname(__file__), '..', '..', 'PRD', 'documents', '个人中心需求文档.md')
    # 通过模块级变量传递配置（AgentExecutor 不会将 config 传递给 tool）
    set_tool_config(project_name="项目A：检索系统", module_id="模块6：个人中心功能", thread_id="user_session_2")
    # response = agent_executor.astream({"input": f"请根据需求文档 {doc_path} ，只生成个人中心需求功能的测试点，先不要生成测试用例"})
    response = agent_executor.astream({"input": f"查看需求文档 {doc_path} ，请根据我修改后的测试点文件 /Users/admin/Testproject/AItestcase_Agents/output/test_points_res/个人中心测试点.json 生成个人中心需求功能的测试用例"})
    async for chunk in response:
        if 'output' in chunk:
            print(chunk['output'], end="", flush=True)
        elif 'actions' in chunk:
            for action in chunk['actions']:
                print(f"\nAction: {action.tool} - {action.tool_input}\n")
async def shutdown():
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == '__main__':
    # 在程序结束前
    try:
        asyncio.run(main())
    finally:
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(shutdown())
        except:
            pass

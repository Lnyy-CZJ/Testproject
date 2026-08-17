import os
import dotenv
from langchain_openai import ChatOpenAI


def _optional_api_key(name: str) -> str:
    """返回可选模型的 Key；缺失时允许模块导入，但不会赋予可用凭据。

    参数说明:
        name: 可选模型供应商的环境变量名。
    返回值:
        已配置的原值，或只用于通过 Client 构造校验的不可用占位值。
    """

    return os.getenv(name) or "not-configured"


def _runtime_llm_options() -> dict:
    """只传入平台显式发布的可选参数，空值继续沿用 Provider 默认。"""

    options = {}
    if os.getenv("LLM_TEMPERATURE", "").strip():
        options["temperature"] = float(os.environ["LLM_TEMPERATURE"])
    if os.getenv("LLM_MAX_TOKENS", "").strip():
        options["max_tokens"] = int(os.environ["LLM_MAX_TOKENS"])
    if os.getenv("LLM_TIMEOUT_SECONDS", "").strip():
        options["request_timeout"] = float(os.environ["LLM_TIMEOUT_SECONDS"])
    return options

# 配置项目根目录路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# =============大模型配置================
# 加载环境变量
dotenv.load_dotenv(os.path.join(BASE_DIR, '.env'))
# RAG配置
# 内存输出路径
OUTPUT_PATH = os.path.join(os.path.join(BASE_DIR, "rag"), "output")
# RAG_STOREGE路径
STOREGE_PATH = os.path.join(os.path.join(BASE_DIR, "rag"), "rag_storage")



# 对话模型
llm_V3_2 = ChatOpenAI(
    model=os.getenv('MODEL_V3', 'deepseek-ai/DeepSeek-V3.2'),
    base_url=os.getenv('GJLD_base_url', 'https://api.siliconflow.cn/v1'),
    api_key=_optional_api_key('GJLD_api_key'),
)

llm_V4_FLASH = ChatOpenAI(
    # 平台 Runner 可按任务配置模型；未设置时保持原命令行默认值。
    model=os.getenv('LLM_MODEL', 'deepseek-v4-flash'),
    base_url=os.getenv('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
    api_key=_optional_api_key('DASHSCOPE_API_KEY'),
    **_runtime_llm_options(),
)

llm_V4_PRO = ChatOpenAI(
    model='deepseek-v4-pro',
    base_url=os.getenv('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
    api_key=_optional_api_key('DASHSCOPE_API_KEY'),
)

llm_XIAOMI = ChatOpenAI(
    model=os.getenv('xiaomi_model', 'mimo-v2.5-pro'),
    base_url=os.getenv('xiaomi_base_url', 'https://api.xiaomimimo.com/v1'),
    api_key=_optional_api_key('xiaomi_api_key'),
)
llm = llm_V4_FLASH

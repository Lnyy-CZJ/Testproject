"""
确定性 Agent 分析引擎

功能说明:
    第三阶段先冻结 Agent 分析输出结构，使用规则化分析器生成稳定报告。
    后续接入 LangGraph/真实 LLM 时，只需要替换本模块实现，保持服务层
    和 API 契约不变。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenUsageSnapshot:
    """
    Token 用量快照。

    参数说明:
        prompt_tokens: 输入 Token 估算值。
        completion_tokens: 输出 Token 估算值。
        total_tokens: 总 Token 估算值。
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class AnalysisEngineResult:
    """
    分析引擎结果。

    返回值说明:
        analysis: 根因、影响文件、风险级别等结构化分析。
        solution: 修复建议和执行步骤。
        token_usage: 本次分析的 Token 估算。
        memory_items_used: 注入分析上下文的记忆条数。
    """

    analysis: dict
    solution: dict
    token_usage: TokenUsageSnapshot
    memory_items_used: int


class DeterministicAnalysisEngine:
    """
    确定性分析引擎。

    设计说明:
        当前项目还没有真实 LLM 配置和 LangGraph 节点，本实现用于第三阶段
        契约冻结、接口联调和测试数据生成，不引入外部网络依赖。
    """

    def analyze(
        self,
        title: str,
        description: str,
        agent_type: str,
        memory_context: str = "",
    ) -> AnalysisEngineResult:
        """
        生成稳定结构的分析报告。

        参数说明:
            title: 缺陷标题。
            description: 缺陷描述。
            agent_type: 当前分析 Agent 类型。
            memory_context: 已注入的项目/迭代记忆文本。

        返回值:
            AnalysisEngineResult: 结构化分析、解决方案和 Token 估算。
        """
        prompt_text = f"{agent_type}\n{title}\n{description}\n{memory_context}"
        prompt_tokens = self._estimate_tokens(prompt_text)
        completion_tokens = self._estimate_tokens(title + description) + 80
        memory_items_used = len([line for line in memory_context.splitlines() if line.strip()])

        return AnalysisEngineResult(
            analysis={
                "rootCause": "需要结合日志、复现步骤和相关代码进一步定位",
                "affectedFiles": [],
                "riskLevel": "medium",
                "agentType": agent_type,
                "memoryItemsUsed": memory_items_used,
            },
            solution={
                "description": "建议先补充复现信息，再按影响范围分层排查",
                "steps": [
                    "确认复现路径和浏览器/环境信息",
                    "检查前端事件绑定、接口请求和控制台错误",
                    "定位后补充回归用例并进入修复流程",
                ],
            },
            token_usage=TokenUsageSnapshot(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            memory_items_used=memory_items_used,
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """
        粗略估算 Token 数。

        返回值:
            int: 至少为 1 的估算值，避免空输入导致统计缺口。
        """
        return max(1, len(text) // 4)

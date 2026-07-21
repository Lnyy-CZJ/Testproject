"""
关键词检索器

功能说明:
    提供第五阶段最小可用的代码/文档证据检索能力。当前实现基于传入的
    文档列表做路径和内容关键词匹配，不依赖外部向量库或 Git 工作区。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    """
    检索证据。

    参数说明:
        filePath: 文件路径。
        snippet: 命中的文本片段。
        score: 检索得分，分数越高越靠前。
        source: 证据来源。
        line: 命中行号；无法确定时为 1。
        symbolId: 可选符号 ID。
    """

    filePath: str
    snippet: str
    score: float
    source: str = "keyword"
    line: int = 1
    symbolId: str | None = None


class KeywordRetriever:
    """关键词检索器"""

    def __init__(self, documents: list[dict] | None = None):
        self.documents = documents or []

    def retrieve(self, text: str = "", keywords: list[str] | None = None, top_k: int = 5) -> list[Evidence]:
        """
        根据文本和关键词检索证据。

        参数说明:
            text: 用户查询文本。
            keywords: 额外关键词。
            top_k: 返回条数上限。

        返回值:
            list[Evidence]: 按 score 降序排列的证据列表。
        """
        terms = self._terms(text, keywords or [])
        if not terms:
            return []

        results: list[Evidence] = []
        for doc in self.documents:
            path = str(doc.get("filePath") or doc.get("path") or "")
            content = str(doc.get("content") or doc.get("snippet") or "")
            path_lower = path.lower()
            content_lower = content.lower()
            score = 0.0
            for term in terms:
                if term in path_lower:
                    score += 10.0
                if term in content_lower:
                    score += 3.0
            if score <= 0:
                continue
            results.append(
                Evidence(
                    filePath=path,
                    snippet=self._snippet(content, terms),
                    score=score,
                    line=int(doc.get("line") or 1),
                    symbolId=doc.get("symbolId"),
                )
            )

        return sorted(results, key=lambda item: (-item.score, item.filePath))[:top_k]

    @staticmethod
    def _terms(text: str, keywords: list[str]) -> list[str]:
        """归一化查询词，去重并过滤空字符串"""
        raw_terms = text.replace("\n", " ").split() + keywords
        normalized: list[str] = []
        for term in raw_terms:
            value = term.strip().lower()
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    @staticmethod
    def _snippet(content: str, terms: list[str]) -> str:
        """
        提取命中文本片段。

        返回值:
            str: 首个命中行；未命中时返回内容前 200 字符。
        """
        for line in content.splitlines() or [content]:
            lower_line = line.lower()
            if any(term in lower_line for term in terms):
                return line[:200]
        return content[:200]

from __future__ import annotations
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import asyncio
from typing import Any, Optional
from LightRAG.document_service import LightRAGDocumentService
class LightRAGTools:
    """LightRAG工具类，提供初始化和使用LightRAG的方法"""
    
    def __init__(self, workspace: Optional[str] = None):
        """
        初始化LightRAG工具
        
        Args:
            workspace: 工作空间名称，默认为None（使用默认工作空间）
        """
        self.workspace = workspace
        self.service: Optional[LightRAGDocumentService] = None
    
    async def initialize(self) -> None:
        """
        初始化LightRAG服务
        """
        if self.service is None:
            self.service = LightRAGDocumentService(workspace=self.workspace)
        await self.service.initialize()
    
    async def insert_document(
        self, 
        file_path: str, 
        doc_id: Optional[str] = None,
        parse_method: Optional[str] = None
    ) -> dict[str, Any]:
        """
        插入文档到LightRAG
        
        Args:
            file_path: 文件路径
            doc_id: 文档ID，默认为None（自动生成）
            parse_method: 解析方法，默认为None（自动选择）
        
        Returns:
            包含文档信息的字典
        """
        await self.initialize()
        assert self.service is not None
        return await self.service.insert_document(
            file_path=file_path,
            doc_id=doc_id,
            parse_method=parse_method
        )
    
    async def query_documents(
        self, 
        query: str, 
        mode: str = "hybrid",
        top_k: int = 5
    ) -> dict[str, Any]:
        """
        查询文档
        
        Args:
            query: 查询语句
            mode: 查询模式，可选值：local, global, hybrid, naive, mix, bypass
            top_k: 返回结果数量
        
        Returns:
            包含查询结果的字典
        """
        await self.initialize()
        assert self.service is not None
        return await self.service.query_documents(
            query=query,
            mode=mode,
            top_k=top_k
        )
    
    async def delete_document(
        self, 
        doc_id: Optional[str] = None,
        file_path: Optional[str] = None
    ) -> dict[str, Any]:
        """
        删除文档
        
        Args:
            doc_id: 文档ID
            file_path: 文件路径
        
        Returns:
            包含删除结果的字典
        """
        await self.initialize()
        assert self.service is not None
        return await self.service.delete_document(
            doc_id=doc_id,
            file_path=file_path
        )
    
    def list_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        列出所有文档
        
        Args:
            limit: 返回文档数量限制
        
        Returns:
            文档列表
        """
        if self.service is None:
            self.service = LightRAGDocumentService(workspace=self.workspace)
        return self.service.list_documents(limit=limit)
    
    def get_document(self, doc_id: str) -> Optional[dict[str, Any]]:
        """
        获取指定文档
        
        Args:
            doc_id: 文档ID
        
        Returns:
            文档信息字典，如果不存在则返回None
        """
        if self.service is None:
            self.service = LightRAGDocumentService(workspace=self.workspace)
        return self.service.get_document(doc_id)
    
    def search_document_graph(self, keyword: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        搜索文档图
        
        Args:
            keyword: 搜索关键词
            limit: 返回结果数量
        
        Returns:
            搜索结果列表
        """
        if self.service is None:
            self.service = LightRAGDocumentService(workspace=self.workspace)
        return self.service.search_document_graph(keyword, limit=limit)
    
    def close(self) -> None:
        """
        关闭LightRAG服务
        """
        if self.service is not None:
            self.service.close()


# 示例使用
async def example_usage():
    """示例使用LightRAG工具"""
    # 初始化LightRAG工具
    rag_tools = LightRAGTools(workspace="default")
    
    try:
        # 初始化服务
        await rag_tools.initialize()
        print("LightRAG服务初始化成功")
        
        # #插入文档
        # insert_result = await rag_tools.insert_document(
        #     file_path="D:\PythonProject\AItestcase_Agent\LightRAG\documents\注册功能文档.md"
        # )
        # print(f"插入文档成功: {insert_result['doc_id']}")
        
        #查询文档
        query_result = await rag_tools.query_documents(
            query="注册功能文档内容",
            mode="hybrid",
            top_k=5
        )
        print(f"查询结果: {query_result['answer']}")

        ##获取文档详情
        # doc_id = '02ba7f7c21e9346939b8927967bb6bfd'
        # doc = rag_tools.get_document(doc_id)
        # print(f"文档详情: {doc}")
        
        # # 列出文档
        # documents = rag_tools.list_documents(limit=10)
        # print(f"文档列表: {len(documents)} 个文档，文档id: {[doc['doc_id'] for doc in documents]}")

        # 删除文档
        # delete_result = await rag_tools.delete_document(
        #     doc_id="273b5ca157b8643142ff647efa049957"

        # )
        # print(f"删除文档成功: {delete_result['success']}")
               
    finally:
        # 关闭服务
        rag_tools.close()


if __name__ == "__main__":
    asyncio.run(example_usage())

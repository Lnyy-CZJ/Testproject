"""
通用 Pydantic Schema 定义

与 Go 版 API 响应格式完全兼容：
    - ApiResult[T]: {"code": 0, "data": ..., "message": "..."}
    - PaginatedResponse[T]: {"list": [...], "total": N, "page": N, "size": N}
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, model_serializer

T = TypeVar("T")


class ApiResult(BaseModel, Generic[T]):
    """
    统一 API 响应格式

    与 Go 版完全兼容:
        - code: 0 表示成功，非 0 表示失败
        - data: 响应数据
        - message: 错误信息（可选）
    """
    code: int = Field(default=0, description="状态码，0=成功")
    data: T | None = Field(default=None, description="响应数据")
    message: str | None = Field(default=None, description="错误或提示信息")

    model_config = {"populate_by_name": True}

    @classmethod
    def success(cls, data: T | None = None, message: str | None = "success") -> "ApiResult[T]":
        """
        构造成功响应。

        功能说明:
            统一业务接口成功响应格式，避免各路由手写字典导致字段不一致。

        参数说明:
            data: 接口返回数据，可为空。
            message: 提示信息，默认与 Go 版兼容使用 success。

        返回值:
            ApiResult[T]: code 固定为 0 的响应对象。
        """
        return cls(code=0, data=data, message=message)


class PaginatedResponse(BaseModel, Generic[T]):
    """
    分页响应格式

    与 Go 版完全兼容。
    同时输出 items 与 list，兼容新旧前端分页读取方式。
    """
    items: list = Field(default_factory=list, description="数据列表")
    list_: list = Field(
        default_factory=list,
        validation_alias="list",
        serialization_alias="list",
        description="Go 版列表字段兼容",
    )
    total: int = Field(default=0, description="总条数")
    page: int = Field(default=1, description="当前页码")
    size: int = Field(default=20, description="每页条数")
    pageSize: int = Field(default=20, description="前端 PaginatedData 兼容字段")

    @classmethod
    def from_items(
        cls,
        items: list,
        total: int,
        page: int,
        size: int,
    ) -> "PaginatedResponse[T]":
        """
        构造分页响应。

        功能说明:
            同时填充 `items`、`list`、`size`、`pageSize`，兼容 PRD 和现有前端。
        """
        return cls(items=items, list=items, total=total, page=page, size=size, pageSize=size)

    @model_serializer(mode="wrap")
    def serialize_legacy_list_field(self, handler) -> dict[str, Any]:
        """
        将内部 list_ 字段稳定输出为 Go 前端使用的 list。

        参数说明:
            handler: Pydantic 默认序列化处理器。

        返回值:
            dict[str, Any]: 同时含 items 与 list 的分页响应。
        """
        serialized = handler(self)
        if "list_" in serialized:
            serialized["list"] = serialized.pop("list_")
        return serialized

"""SearchService 3.0 请求参数封装。"""

from __future__ import annotations

from typing import Any

from framework.client.gateway_client import GatewayClient
from framework.models.envelope import GatewayResponse


class SearchService:
    """按客户端接口文档 3.0 委托搜索接口，不做本地业务边界拦截。

    功能说明:
        按客户端接口文档 3.0 封装搜索业务参数并委托 Gateway。
    参数说明:
        client: 统一 Gateway 客户端或实现相同 ``invoke`` 协议的离线替身。
    返回值:
        所有公共方法返回未吞掉业务状态的 :class:`GatewayResponse`。
    异常说明:
        网络、HTTP 和响应解析异常原样传播；负向业务参数也原样发送给服务端。
    """

    SERVICE_NAME = "tool.people_insight.SearchService"

    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    @staticmethod
    def _intent_params(
        *,
        client_request_id: str,
        match_strategy: str,
        clues: list[dict[str, Any]],
        additional_details: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """构造搜索创建参数，仅省略未提供的可选字段且不改写线索。"""
        params: dict[str, Any] = {
            "client_request_id": client_request_id,
            "match_strategy": match_strategy,
            "clues": clues,
        }
        if additional_details is not None:
            params["additional_details"] = additional_details
        return params

    def create_intent_task(
        self,
        *,
        access_token: str,
        client_request_id: str,
        match_strategy: str,
        clues: list[dict[str, Any]],
        additional_details: list[dict[str, Any]] | None = None,
    ) -> GatewayResponse:
        """以调用方稳定幂等 ID 创建并启动搜索任务。

        功能说明:
            以稳定幂等 ID 创建并启动搜索任务。
        参数说明:
            access_token: 最新会话 token；client_request_id: 同时进入业务参数和
            Gateway 公共上下文的稳定 ID；match_strategy/clues/additional_details:
            文档定义的匹配策略、线索和可选补充信息。
        返回值:
            创建结果的标准 Gateway 响应。
        异常说明:
            Service 不生成、替换或校验线索；Gateway 异常原样传播。
        """
        params = self._intent_params(
            client_request_id=client_request_id,
            match_strategy=match_strategy,
            clues=clues,
            additional_details=additional_details,
        )
        return self._client.invoke(
            self.SERVICE_NAME,
            "CreateIntentTask",
            params,
            auth_token=access_token,
            client_request_id=client_request_id,
        )

    def create_intent(
        self,
        *,
        access_token: str,
        client_request_id: str,
        match_strategy: str,
        clues: list[dict[str, Any]],
        additional_details: list[dict[str, Any]] | None = None,
    ) -> GatewayResponse:
        """兼容流程中仅创建搜索意图，并原样透传调用方 ID 与线索。

        功能说明:
            兼容流程中仅创建搜索意图并原样透传线索。
        参数说明:
            参数语义与 :meth:`create_intent_task` 相同，但仅创建未启动的意图。
        返回值:
            包含待启动任务信息的标准 Gateway 响应。
        异常说明:
            负向参数不在本地拦截，Gateway 异常原样传播。
        """
        params = self._intent_params(
            client_request_id=client_request_id,
            match_strategy=match_strategy,
            clues=clues,
            additional_details=additional_details,
        )
        return self._client.invoke(
            self.SERVICE_NAME,
            "CreateIntent",
            params,
            auth_token=access_token,
            client_request_id=client_request_id,
        )

    def refine_task(
        self,
        *,
        access_token: str,
        client_request_id: str,
        source_task_id: str,
        additional_details: list[dict[str, Any]],
        feedback_type: str,
        feedback_message: str,
    ) -> GatewayResponse:
        """基于来源任务、补充条件和用户反馈创建新的搜索任务。

        功能说明:
            基于来源任务、补充条件和用户反馈创建新搜索任务。
        参数说明:
            access_token: 当前最新会话 token；client_request_id: 调用方稳定幂等
            ID；source_task_id: 已完成来源任务 ID；其余字段按 3.0 文档原样传递。
        返回值:
            包含新 task、source_task_id 和 feedback_id 的标准 Gateway 响应。
        异常说明:
            不在本地校验来源或改写 ID，Gateway 调用与解析异常原样传播。
        """
        params = {
            "client_request_id": client_request_id,
            "source_task_id": source_task_id,
            "additional_details": additional_details,
            "feedback_type": feedback_type,
            "feedback_message": feedback_message,
        }
        return self._client.invoke(
            self.SERVICE_NAME,
            "RefineTask",
            params,
            auth_token=access_token,
            client_request_id=client_request_id,
        )

    def start_task(self, *, access_token: str, task_id: str) -> GatewayResponse:
        """兼容流程中启动已有任务。

        功能说明:
            兼容流程中启动已有任务。
        参数说明:
            access_token: 最新会话 token；task_id: CreateIntent 返回的任务 ID。
        返回值:
            启动结果的标准 Gateway 响应。
        异常说明:
            不发送文档明确不支持的 ``force_refresh``；Gateway 异常原样传播。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "StartTask",
            {"task_id": task_id},
            auth_token=access_token,
        )

    def get_task(
        self,
        *,
        access_token: str,
        task_id: str,
        read_timeout: float | None = None,
    ) -> GatewayResponse:
        """读取异步搜索任务快照，供等待器在总预算内轮询。

        功能说明:
            在可选剩余预算内读取异步搜索任务快照。
        参数说明:
            access_token: 最新会话 token；task_id: 待读取的搜索任务 ID；
            read_timeout: 等待器计算的可选剩余秒数，用于缩短 Gateway HTTP 超时。
        返回值:
            当前任务快照的标准 Gateway 响应。
        异常说明:
            Gateway 网络、HTTP、预算和解析异常原样传播。
        """
        invoke_kwargs: dict[str, Any] = {"auth_token": access_token}
        if read_timeout is not None:
            invoke_kwargs["read_timeout"] = read_timeout
        return self._client.invoke(
            self.SERVICE_NAME,
            "GetTask",
            {"task_id": task_id},
            **invoke_kwargs,
        )

    def list_task_candidates(
        self,
        *,
        access_token: str,
        task_id: str,
        page_size: int = 10,
        page_token: str = "",
    ) -> GatewayResponse:
        """按 task ID 和文档嵌套 page 结构查询候选列表。

        功能说明:
            按任务 ID 和嵌套分页结构查询候选列表。
        参数说明:
            access_token/task_id: 会话 token 与已成功任务；page_size/page_token:
            分页大小和续页标识。
        返回值:
            候选分页标准 Gateway 响应。
        异常说明:
            Gateway 网络、HTTP 和响应解析异常原样传播。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "ListTaskCandidates",
            {
                "task_id": task_id,
                "page": {"page_size": page_size, "page_token": page_token},
            },
            auth_token=access_token,
        )

    def get_task_candidate_detail(
        self, *, access_token: str, task_id: str, candidate_id: str
    ) -> GatewayResponse:
        """使用文档推荐的 ``task_id + candidate_id`` 查询候选详情。

        功能说明:
            使用任务与候选联合键查询候选详情。
        参数说明:
            access_token: 最新 token；task_id/candidate_id: 任务和候选联合定位键。
        返回值:
            候选详情标准 Gateway 响应。
        异常说明:
            Gateway 异常原样传播，不把候选数据写入本地日志。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "GetTaskCandidateDetail",
            {"task_id": task_id, "candidate_id": candidate_id},
            auth_token=access_token,
        )

    def list_search_history(
        self,
        *,
        access_token: str,
        page_size: int = 20,
        page_token: str = "",
        status_filter: list[str] | None = None,
    ) -> GatewayResponse:
        """分页查询搜索历史，默认不发送会遗漏记录的查询类型过滤字段。

        功能说明:
            分页查询搜索历史并按需附加状态过滤。
        参数说明:
            access_token: 最新 token；page_size/page_token: 分页参数；status_filter:
            可选任务状态列表，``None`` 时完全省略。
        返回值:
            搜索历史分页标准 Gateway 响应。
        异常说明:
            Gateway 网络、HTTP 和响应解析异常原样传播。
        """
        params: dict[str, Any] = {
            "page": {"page_size": page_size, "page_token": page_token}
        }
        if status_filter is not None:
            params["status_filter"] = status_filter
        return self._client.invoke(
            self.SERVICE_NAME,
            "ListSearchHistory",
            params,
            auth_token=access_token,
        )

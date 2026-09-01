"""内部 Evaluation Admin Gateway 请求与响应解析。"""

from collections.abc import Mapping
from typing import Any

from aidating_eval.errors import ContractError
from aidating_eval.public_gateway import JsonTransport, _parse_subresponse, _single_response


EVALUATION_SERVICE = "tool.dating.internal.DatingEvaluationService"


class EvaluationGatewayClient:
    """使用内存 Bearer Key 调用固定内部服务，不接受调用方覆盖 service。"""

    def __init__(self, transport: JsonTransport, url: str, api_key: str) -> None:
        self.transport = transport
        self.url = url
        self._api_key = api_key

    def call(
        self,
        method_name: str,
        params: Mapping[str, Any],
        *,
        client_request_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "service_name": EVALUATION_SERVICE,
            "method_name": method_name,
            "params": dict(params),
        }
        if client_request_id is not None:
            payload["client_request_id"] = client_request_id
        if reason is not None:
            payload["reason"] = reason
        response = self.transport.request_json(
            "POST",
            self.url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json_body=payload,
        )
        top_code = response.get("code")
        if top_code is not None and top_code != 0:
            raise ContractError("EVALUATION_TOP_LEVEL_CODE_NON_ZERO")
        return _parse_subresponse(_single_response(response))

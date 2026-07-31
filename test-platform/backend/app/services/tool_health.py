import httpx


def probe_tool_health(health_url: str, timeout_seconds: float) -> bool:
    """
    探测独立工具的内部健康接口。

    参数说明:
        health_url (str): 仅供平台后端使用的容器网络健康地址。
        timeout_seconds (float): 单次请求最大等待秒数。
    返回值:
        bool: HTTP 成功且响应状态字段为 ok 时返回 True，否则返回 False。
    异常说明:
        网络、超时、状态码和 JSON 解析异常都被收敛为 False，避免泄露内部地址。
    """

    try:
        response = httpx.get(health_url, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        return isinstance(payload, dict) and payload.get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False

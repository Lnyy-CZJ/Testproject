import httpx


def probe_tool_health(health_url: str, timeout_seconds: float) -> dict:
    """
    探测独立工具的内部健康接口。

    参数说明:
        health_url (str): 仅供平台后端使用的容器网络健康地址。
        timeout_seconds (float): 单次请求最大等待秒数。
    返回值:
        dict: 上游安全版本元数据；失败时返回固定 unhealthy 状态。
    异常说明:
        网络、超时、状态码和 JSON 解析异常都被收敛为 False，避免泄露内部地址。
    """

    try:
        response = httpx.get(health_url, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") not in {"ok", "ready"}:
            return {"healthy": False}
        return {
            "healthy": True,
            "version": str(payload.get("version", "unknown")),
            "revision": str(payload.get("revision", "unknown")),
            "dirty": bool(payload.get("dirty", True)),
            "runtime_environment": str(payload.get("runtime_environment", "unknown")),
        }
    except (httpx.HTTPError, ValueError):
        return {"healthy": False}

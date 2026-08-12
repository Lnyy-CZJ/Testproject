class PlatformError(Exception):
    """携带稳定错误码和安全中文信息的平台业务异常。"""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        """初始化业务异常，不接收内部异常或 Secret 作为消息。"""

        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message

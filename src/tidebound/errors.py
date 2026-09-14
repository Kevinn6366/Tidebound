"""对外可报告的业务错误，不包含模型凭据或响应原文。"""


class AgentError(Exception):
    """携带稳定错误码及安全说明的执行失败。"""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        """构造执行错误。

        Args:
            code: 用于通信和运行记录的错误码。
            message: 可直接呈现给用户的说明。
            status: 通信层对应的 HTTP 状态。
        """
        super().__init__(message)
        self.code = code
        self.status = status

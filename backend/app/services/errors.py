class BusinessRuleError(Exception):
    """业务规则违反（409）。details 可携带结构化信息（如结案阻塞项）。"""

    def __init__(self, message: str, code: str = "business_rule_violation", details: dict | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)


class NotFoundError(Exception):
    def __init__(self, message: str = "资源不存在"):
        self.message = message
        super().__init__(message)


class AuthError(Exception):
    def __init__(self, message: str = "鉴权失败"):
        self.message = message
        super().__init__(message)

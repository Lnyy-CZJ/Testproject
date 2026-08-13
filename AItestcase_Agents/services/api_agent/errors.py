"""API 测试智能体 V2 的稳定错误码和建议动作。"""

from __future__ import annotations


ERROR_ACTIONS = {
    "DOCUMENT_EMPTY": "请上传包含接口定义的文档",
    "DOCUMENT_SYNTAX_INVALID": "请根据行列信息修正文档语法",
    "DOCUMENT_FORMAT_UNSUPPORTED": "请改用 OpenAPI、Swagger 或 HTTP 接口文本",
    "CONTRACT_PARSE_FAILED": "请检查文档结构或改用文本格式",
    "CONTRACT_QUALITY_FAILED": "请进入契约 Review 处理冲突和缺失信息",
    "REVIEW_VERSION_CONFLICT": "数据已更新，请刷新后重新提交",
    "CASE_SCHEMA_INVALID": "请修正用例字段后重试",
    "CASE_VALIDATION_FAILED": "请按校验问题修正变量、依赖、断言或脚本",
    "EXECUTION_NOT_READY": "真实执行尚未通过安全授权",
    "TARGET_NOT_ALLOWED": "请选择管理员登记的非生产目标",
    "EXECUTION_TIMEOUT": "请检查用例和 Mock 执行超时配置",
    "EXECUTION_RESULT_MISSING": "执行结果缺失，请创建新 Run 重试",
    "DEFECT_DRAFT_INVALID": "请补全缺陷复现信息后重试",
}


def suggested_action(code: str) -> str:
    """返回不包含内部信息的用户建议动作。"""

    return ERROR_ACTIONS.get(code, "请查看阶段日志并从失败阶段重试")

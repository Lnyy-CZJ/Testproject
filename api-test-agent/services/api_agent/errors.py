"""API 测试智能体 V2 的稳定错误码和建议动作。"""

from __future__ import annotations


ERROR_ACTIONS = {
    "DOCUMENT_EMPTY": "请上传包含接口定义的文档",
    "DOCUMENT_SYNTAX_INVALID": "请根据行列信息修正文档语法",
    "DOCUMENT_FORMAT_UNSUPPORTED": "请改用 OpenAPI、Swagger 或 HTTP 接口文本",
    "CONTRACT_PARSE_FAILED": "请检查文档结构或改用文本格式",
    "CONTRACT_QUALITY_FAILED": "请进入契约 Review 处理冲突和缺失信息",
    "CONTRACT_VERSION_NOT_FOUND": "请返回当前契约版本或重新分析",
    "CONTRACT_VERSION_CORRUPTED": "请从解析阶段重试或恢复最近有效版本",
    "REVIEW_VERSION_CONFLICT": "数据已更新，请刷新后重新提交",
    "DOCUMENT_SOURCE_NOT_AVAILABLE": "原文不可用时仍可继续查看已生成产物",
    "DOCUMENT_VERSION_CONFLICT": "请刷新文档版本后重新保存",
    "DOCUMENT_VALIDATION_FAILED": "请按格式错误修正文档后再保存",
    "ANALYSIS_SCOPE_INVALID": "请检查 method、相对路径和文档版本",
    "REANALYZE_PREVIEW_EXPIRED": "请重新生成影响预览并确认",
    "REANALYZE_ALREADY_RUNNING": "请等待当前重新分析完成",
    "REVIEW_ISSUE_NOT_FOUND": "请刷新冲突与未解决项列表",
    "EVIDENCE_RANGE_INVALID": "请选择能直接支持字段值的原文范围",
    "REVIEW_ISSUE_STILL_BLOCKED": "请补充证据或填写人工决定依据",
    "CASE_RESPONSE_SCHEMA_INVALID": "请刷新页面；若仍出现请携带请求 ID 联系管理员",
    "CASE_SCHEMA_INVALID": "请修正用例字段后重试",
    "CASE_VALIDATION_FAILED": "请按校验问题修正变量、依赖、断言或脚本",
    "CASE_GROUNDING_FAILED": "请补充用例依据或修改无依据的步骤和预期",
    "CASE_BUSINESS_CONTEXT_UNSUPPORTED": "请删除契约未支持的业务场景",
    "CASE_EXPECTATION_UNGROUNDED": "请绑定文档响应依据或改为探索观察",
    "CASE_REQUEST_INCOMPLETE": "请补全契约要求的参数和请求体",
    "CASE_PROMPT_OUTPUT_INVALID": "模型输出不符合用例 Schema，请重新生成",
    "CASE_ENUM_NORMALIZED": "请在 Review 中核对已归一化的场景类型",
    "CASE_PROMPT_ITEM_INVALID": "请查看单条拒绝原因或仅重试 AI 补充",
    "CASE_GENERATION_PARTIAL": "请 Review 已生成用例并按需重试 AI 补充",
    "LEGACY_VALIDATION_REQUIRED": "请使用融合内核从已确认契约重新生成用例",
    "GENERATION_KERNEL_UNSUPPORTED": "请检查 API_GENERATION_KERNEL 配置",
    "MODEL_USAGE_UNAVAILABLE": "模型供应商未报告 Token，用量不会被估算",
    "STAGE_EVENT_QUERY_INVALID": "请刷新页面并重新选择阶段或 Attempt",
    "EXECUTION_NOT_READY": "真实执行尚未通过安全授权",
    "TARGET_NOT_ALLOWED": "请选择管理员登记的非生产目标",
    "EXECUTION_TIMEOUT": "请检查用例和 Mock 执行超时配置",
    "EXECUTION_RESULT_MISSING": "执行结果缺失，请创建新 Run 重试",
    "DEFECT_DRAFT_INVALID": "请补全缺陷复现信息后重试",
}


def suggested_action(code: str) -> str:
    """返回不包含内部信息的用户建议动作。"""

    return ERROR_ACTIONS.get(code, "请查看阶段日志并从失败阶段重试")

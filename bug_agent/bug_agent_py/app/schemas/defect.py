"""
缺陷相关 Pydantic Schema

与 Go 版 API 响应格式完全兼容，字段使用 camelCase。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.auth import UserProfile


class DefectCreate(BaseModel):
    """创建缺陷请求"""
    iterationId: int = Field(..., alias="iteration_id", description="迭代 ID")
    title: str = Field(..., max_length=200, description="缺陷标题")
    description: str = Field(default="", description="缺陷描述")
    severity: str = Field(default="一般", description="严重级别")
    priority: str = Field(default="P2", description="优先级")
    type: str = Field(default="功能缺陷", alias="type", description="缺陷类型")
    tags: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class DefectDraftRequest(BaseModel):
    """对话生成缺陷草稿请求"""
    iterationId: int | None = Field(default=None, alias="iteration_id")
    message: str = Field(..., min_length=1, description="用户自然语言描述")
    tags: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class DefectConfirmCreateRequest(BaseModel):
    """确认缺陷草稿并创建正式缺陷请求"""
    iterationId: int = Field(..., alias="iteration_id")
    title: str = Field(..., max_length=200)
    descriptionMarkdown: str = Field(default="", alias="description_markdown")
    severity: str = "一般"
    priority: str = "P2"
    type: str = Field(default="功能缺陷", alias="type")
    tags: list[str] = Field(default_factory=list)
    sourceMode: str | None = Field(default=None, alias="source_mode")

    model_config = {"populate_by_name": True}


class DefectDraftResponse(BaseModel):
    """缺陷草稿响应"""
    title: str
    descriptionMarkdown: str
    severity: str
    priority: str
    type: str
    tags: list[str] = Field(default_factory=list)
    suggestedIterationId: int | None = None
    missingInformation: list[str] = Field(default_factory=list)
    confidence: float = 0.6
    sourceMode: str = "manual_chat"


class DefectUpdate(BaseModel):
    """更新缺陷请求"""
    title: str | None = Field(default=None, max_length=200)
    description: str | None = None
    severity: str | None = None
    priority: str | None = None
    type: str | None = Field(default=None, alias="type")
    tags: list[str] | None = None

    model_config = {"populate_by_name": True}


class DefectListItem(BaseModel):
    """缺陷列表项（与前端 DefectList 表格列对齐）"""
    id: int
    code: str
    title: str
    severity: str
    priority: str
    type: str = Field(alias="type")
    status: str
    assigneeId: int | None = Field(default=None, alias="assignee_id")
    assigneeName: str | None = Field(default=None)
    reporterId: int = Field(alias="reporter_id")
    reporterName: str | None = Field(default=None)
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime = Field(alias="updated_at")
    iterationId: int = Field(alias="iteration_id")
    tags: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class DefectDetail(BaseModel):
    """缺陷详情（与前端 DefectDetail 页面数据对齐）"""
    id: int
    code: str
    iterationId: int = Field(alias="iteration_id")
    title: str
    description: str = ""
    severity: str
    priority: str
    type: str = Field(alias="type")
    status: str
    assigneeId: int | None = Field(default=None, alias="assignee_id")
    assignee: UserProfile | None = None
    reporterId: int = Field(alias="reporter_id")
    reporter: UserProfile | None = None
    tags: list[str] = Field(default_factory=list)
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime = Field(alias="updated_at")

    model_config = {"populate_by_name": True}


class AssignDefectRequest(BaseModel):
    """分配缺陷请求"""
    assigneeId: int = Field(..., description="被分配用户 ID")
    agentTypes: list[str] | None = Field(default=None, description="分配时选择的 Agent 身份")
    recommendationAdopted: bool | None = None
    recommendationStrategy: str | None = None


class VerifyDefectRequest(BaseModel):
    """验证缺陷请求"""
    passed: bool = Field(..., description="验证是否通过")
    comment: str | None = Field(default=None, description="验证备注")


class DefectStatusChangeRequest(BaseModel):
    """状态变更请求"""
    status: str = Field(..., description="目标状态")
    comment: str | None = Field(default=None, description="状态变更备注")


class RejectDefectRequest(BaseModel):
    """驳回缺陷请求"""
    reason: str = Field(..., min_length=1)


class ReopenDefectRequest(BaseModel):
    """重新打开缺陷请求"""
    targetStatus: str = Field(default="reopened", alias="target_status")
    comment: str | None = None

    model_config = {"populate_by_name": True}


class AssignDefectResponse(BaseModel):
    """分配缺陷响应"""
    defect: DefectDetail
    status: str
    agentAnalysisTriggered: bool = False


class VerifyDefectResponse(BaseModel):
    """验证缺陷响应"""
    defect: DefectDetail
    status: str


class ReopenDefectResponse(BaseModel):
    """重新打开缺陷响应"""
    defect: DefectDetail
    status: str


class DefectDetailResponse(BaseModel):
    """缺陷详情页聚合响应"""
    defect: DefectDetail
    comments: list["CommentDetail"] = Field(default_factory=list)
    fixTasks: list[dict] = Field(default_factory=list)
    reports: list[dict] = Field(default_factory=list)
    attachments: list["AttachmentDetail"] = Field(default_factory=list)


class CommentCreate(BaseModel):
    """创建评论请求"""
    content: str = Field(..., min_length=1)
    mentions: list[int] = Field(default_factory=list)


class CommentDetail(BaseModel):
    """评论详情"""
    id: int
    defectId: int = Field(alias="defect_id")
    userId: int = Field(alias="user_id")
    content: str
    agentType: str | None = Field(default=None, alias="agent_type")
    isAgentMessage: bool = Field(default=False, alias="is_agent_message")
    createdAt: datetime = Field(alias="created_at")
    user: UserProfile | None = None

    model_config = {"populate_by_name": True}


class AttachmentDetail(BaseModel):
    """附件详情"""
    id: int
    defectId: int = Field(alias="defect_id")
    fileName: str = Field(alias="file_name")
    fileUrl: str
    fileSize: int = Field(alias="file_size")
    fileType: str | None = Field(default=None, alias="mime_type")
    createdAt: datetime = Field(alias="created_at")

    model_config = {"populate_by_name": True}


class StatusChangeDetail(BaseModel):
    """状态变更历史详情"""
    id: int
    defectId: int = Field(alias="defect_id")
    fromStatus: str = Field(alias="from_status")
    toStatus: str = Field(alias="to_status")
    operatorId: int = Field(alias="operator_id")
    comment: str | None = None
    createdAt: datetime = Field(alias="created_at")

    model_config = {"populate_by_name": True}


class TransitionStatusRequest(BaseModel):
    """工作流状态流转请求"""
    status: str
    comment: str | None = None


class BatchTransitionRequest(BaseModel):
    """批量状态流转请求"""
    defectIds: list[int] = Field(..., alias="defect_ids")
    status: str
    comment: str | None = None

    model_config = {"populate_by_name": True}


class BatchTransitionItem(BaseModel):
    """批量流转单项结果"""
    defectId: int
    success: bool
    message: str | None = None

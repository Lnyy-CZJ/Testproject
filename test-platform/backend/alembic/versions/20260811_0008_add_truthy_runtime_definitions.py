"""补充 Truthy_Search 可热加载的运行配置定义。

Revision ID: 20260811_0008
Revises: 20260810_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0008"
down_revision: str | None = "20260810_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 这里只登记 SearchClient 在每个新 Run 开始时能够从平台快照读取的键。
# Web 监听端口、数据库路径和 Excel 开关仍属于部署级配置，避免让运行时
# Release 产生“已生效但实际需要重建容器”的误导。
DEFINITIONS = [
    ("SEARCH_HTTP_HEADERS_JSON", "请求头 JSON", "secret", "secret"),
    ("POLL_INTERVAL_SECONDS", "轮询间隔秒数", "string", "normal"),
    ("MAX_POLL_COUNT", "最大轮询次数", "int", "normal"),
    ("HTTP_TIMEOUT_SECONDS", "HTTP 超时秒数", "string", "normal"),
    ("PLATFORM", "客户端平台", "string", "normal"),
    ("APP_VERSION", "客户端版本", "string", "normal"),
    ("LOCALE", "客户端语言", "string", "normal"),
    ("TIMEZONE", "客户端时区", "string", "normal"),
    ("SEARCH_ADMIN_ENABLED", "启用 Admin 公共信息采集", "bool", "normal"),
    ("SEARCH_ADMIN_HTTP_HEADERS_JSON", "Admin 请求头 JSON", "secret", "secret"),
    ("SEARCH_ADMIN_REASON", "Admin 查询原因", "string", "normal"),
    ("SEARCH_ADMIN_DEBUG_SERVICE", "Admin 调试服务", "string", "normal"),
    ("SEARCH_ADMIN_COST_LIMIT", "Admin 成本上限", "int", "normal"),
    ("SEARCH_QUERY_LOG_ENABLED", "启用查询日志", "bool", "normal"),
    ("SEARCH_QUERY_LOG_DIR", "查询日志目录", "logical_path", "normal"),
    ("SEARCH_INPUT_FILE", "输入任务文件", "logical_path", "normal"),
    ("SEARCH_OUTPUT_DIR", "输出目录", "logical_path", "normal"),
    ("ALLOW_DUPLICATE_RUN", "允许重复运行", "bool", "normal"),
    ("SEARCH_PHOTO_ENABLED", "启用图片检索", "bool", "normal"),
    ("SEARCH_PHOTO_INPUT_DIR", "图片输入目录", "logical_path", "normal"),
    ("SEARCH_PHOTO_UPLOAD_HOST_SUFFIXES", "图片上传域名后缀", "string", "normal"),
]


def upgrade() -> None:
    """登记可由 Web 发布并在下一 Run 生效的 Truthy_Search 配置。"""

    definitions = sa.table(
        "config_definitions",
        sa.column("id", sa.String()), sa.column("key", sa.String()),
        sa.column("display_name", sa.String()), sa.column("description", sa.Text()),
        sa.column("owner_type", sa.String()), sa.column("owner_id", sa.String()),
        sa.column("group_key", sa.String()), sa.column("value_type", sa.String()),
        sa.column("sensitivity", sa.String()), sa.column("required", sa.Boolean()),
        sa.column("default_value", sa.JSON()), sa.column("validation_schema", sa.JSON()),
        sa.column("apply_mode", sa.String()), sa.column("editable", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(definitions, [
        {
            "id": f"truthy-search.{key}", "key": key,
            "display_name": display_name, "description": display_name,
            "owner_type": "tool", "owner_id": "truthy-search",
            "group_key": "credentials" if sensitivity == "secret" else "runtime",
            "value_type": value_type, "sensitivity": sensitivity,
            "required": False, "default_value": None, "validation_schema": {},
            "apply_mode": "next_task", "editable": True,
            "sort_order": 200 + index * 10,
        }
        for index, (key, display_name, value_type, sensitivity) in enumerate(DEFINITIONS)
    ])


def downgrade() -> None:
    """只删除本迁移新增且尚未被 Release 引用的配置定义。"""

    ids = [f"truthy-search.{key}" for key, *_rest in DEFINITIONS]
    op.execute(sa.text("DELETE FROM config_definitions WHERE id IN :ids").bindparams(
        sa.bindparam("ids", expanding=True, value=ids),
    ))

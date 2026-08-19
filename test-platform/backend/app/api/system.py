from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_platform
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError
from app.db.session import get_db
from app.services.version_status import (
    build_matrix,
    collect_snapshot,
    fetch_prod_snapshot,
    peer_token_matches,
)


router = APIRouter(tags=["system"])


@router.get("/system/version-matrix")
def version_matrix(
    context: Annotated[AuthContext, Depends(require_platform("platform.audit.view"))],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """返回可部分降级的 Dev、Prod 与期望版本矩阵。"""

    current = collect_snapshot(database, settings)
    prod, prod_error = (None, None)
    if settings.platform_runtime_env == "dev":
        prod, prod_error = fetch_prod_snapshot(settings)
    return build_matrix(current, prod, settings, prod_error)


@router.get("/internal/version-snapshot")
def internal_version_snapshot(
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """以独立 Bearer Token 返回不含业务数据和 Secret 的只读快照。"""

    prefix = "Bearer "
    presented = authorization[len(prefix):] if authorization and authorization.startswith(prefix) else ""
    if not peer_token_matches(settings, presented):
        raise PlatformError(401, "VERSION_PEER_UNAUTHORIZED", "版本互查鉴权失败")
    return collect_snapshot(database, settings)

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select

from app.core.security import token_hash
from app.db.session import SessionLocal
from app.models.identity import ToolClient


CLIENT_CAPABILITIES = {
    "trackevents": ["audit.write", "config.ack"],
    "log-filter": ["audit.write", "config.ack"],
    "truthy-search": ["config.read", "config.ack", "audit.write", "credential.status.write"],
    "api-autotest": [
        "config.read", "config.ack", "audit.write",
        "credential.status.write", "credential.session.write",
    ],
    "functional-test-agent": ["config.read", "config.ack", "audit.write"],
    "api-test-agent": ["config.read", "config.ack", "audit.write"],
}


def main() -> None:
    """从只读文件确定性注册工具 Client，数据库只保存 Token 哈希。"""

    environment_id = os.getenv("PLATFORM_RUNTIME_ENV", "dev")
    token_directory = Path(os.getenv("PLATFORM_CLIENT_TOKEN_DIR", "/run/platform-clients"))
    with SessionLocal() as database:
        for tool_id, capabilities in CLIENT_CAPABILITIES.items():
            # 新接入工具按环境分目录隔离 Token；既有工具继续兼容原平铺路径。
            scoped_path = token_directory / environment_id / f"{tool_id}-client-token"
            token_path = scoped_path if scoped_path.exists() else token_directory / f"{tool_id}-client-token"
            raw_token = token_path.read_text(encoding="utf-8").strip()
            if len(raw_token) < 32:
                raise RuntimeError(f"工具 Client Token 无效: {tool_id}")
            row = database.scalar(select(ToolClient).where(
                ToolClient.tool_id == tool_id,
                ToolClient.environment_id == environment_id,
            ))
            if row is None:
                row = ToolClient(
                    id=f"client_{environment_id}_{tool_id}",
                    tool_id=tool_id,
                    environment_id=environment_id,
                    token_hash=token_hash(raw_token),
                    capabilities=capabilities,
                    status="active",
                )
                database.add(row)
            else:
                row.token_hash = token_hash(raw_token)
                row.capabilities = capabilities
                row.status = "active"
        database.commit()


if __name__ == "__main__":
    main()

"""固定角色与历史业务资源迁移清单校验器。

默认只执行 dry-run 并输出可机器读取的 JSON。只有 ``--apply`` 且所有阻断项为
零时才会原子写入角色映射和业务资源快照；无法确定 owner 的历史记录必须由
运营人员在 manifest 中明确补齐，脚本绝不会猜测或把它们公开。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from app.core.security import new_id
from app.db.session import SessionLocal
from app.models.access import BusinessResourceSnapshot, Project, ProjectAccessReadiness, ProjectMembership
from app.models.identity import RoleGrant, User, UserRole
from app.models.tool import Tool


ROLES = {"platform_admin", "admin", "tester"}
RELATIONS_BY_ROLE = {"platform_admin": {"manager", "member"}, "admin": {"manager"}, "tester": {"member"}}
RESOURCE_TOOLS = {"truthy-search", "api-autotest", "functional-test-agent", "api-test-agent", "log-filter"}

# Contract 会用完全相同的有序查询重新计算摘要。摘要只覆盖会改变新授权结果或
# 历史资源归属的字段，避免无关展示字段更新导致发布门禁误报。
AUTHORIZATION_STATE_QUERIES = (
    "SELECT id, status, platform_role, permission_version FROM users ORDER BY id",
    "SELECT id, status, revision, authorization_epoch FROM projects ORDER BY id",
    "SELECT id, is_enabled, access_scope, project_id, revision, authorization_epoch FROM tools ORDER BY id",
    "SELECT project_id, user_id, relation FROM project_memberships ORDER BY project_id, user_id",
    "SELECT id, user_id, tool_id, project_id, status, expires_at, revoked_at FROM user_tool_grants ORDER BY id",
    "SELECT environment_id, tool_id, resource_type, resource_id, root_resource_id, owner_user_id, project_id_snapshot, authorization_source_snapshot FROM business_resource_snapshots ORDER BY environment_id, tool_id, resource_type, resource_id",
)


def authorization_state_digest(database: Any) -> str:
    """生成当前授权数据库状态的稳定摘要，供 apply 与 0020 防漂移校验。"""

    state = [
        [[None if value is None else str(value) for value in row] for row in database.execute(text(query)).all()]
        for query in AUTHORIZATION_STATE_QUERIES
    ]
    return hashlib.sha256(
        json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_manifest(path: Path | None) -> dict[str, Any]:
    """读取严格对象结构；空路径表示仅审计当前数据库。"""

    if path is None:
        return {"user_roles": {}, "tool_projects": {}, "memberships": [], "source_counts": {}, "resources": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("user_roles", {}), dict) or not isinstance(payload.get("resources", []), list):
        raise ValueError("manifest 必须包含对象 user_roles 与数组 resources")
    return payload


def inspect_and_apply(
    manifest: dict[str, Any], *, apply: bool, required_environment: str
) -> dict[str, Any]:
    """校验拟议角色与资源快照，并在无阻断项时选择性原子应用。"""

    database = SessionLocal()
    blockers: list[dict[str, str]] = []
    proposed_roles = manifest.get("user_roles", {})
    proposed_tool_projects = manifest.get("tool_projects", {})
    proposed_memberships = manifest.get("memberships", [])
    source_counts = manifest.get("source_counts", {})
    required_environments = manifest.get("required_environments", [])
    approved_widenings = set(manifest.get("approved_permission_widenings", []))
    resources = manifest.get("resources", [])
    try:
        users = {row.id: row for row in database.scalars(select(User)).all()}
        tools = {row.id: row for row in database.scalars(select(Tool)).all()}
        projects = {row.id: row for row in database.scalars(select(Project)).all()}
        if not isinstance(required_environments, list) or required_environment not in required_environments or not all(isinstance(item, str) and item for item in required_environments):
            blockers.append({"kind": "missing_required_environments", "id": "required_environments"})
        environment_exists = database.execute(
            text("SELECT COUNT(*) FROM environments WHERE id=:environment_id"),
            {"environment_id": required_environment},
        ).scalar_one()
        if environment_exists != 1:
            blockers.append({"kind": "unknown_required_environment", "id": required_environment})
        for user_id, user in users.items():
            role = proposed_roles.get(user_id, user.platform_role)
            if role not in ROLES:
                blockers.append({"kind": "unknown_or_no_role", "id": user_id})
        for user_id, role in proposed_roles.items():
            if user_id not in users:
                blockers.append({"kind": "unknown_user", "id": str(user_id)})
            elif role not in ROLES:
                blockers.append({"kind": "invalid_role", "id": str(user_id)})

        current_memberships = list(database.scalars(select(ProjectMembership)).all())
        for membership in current_memberships:
            user = users.get(membership.user_id)
            role = proposed_roles.get(membership.user_id, user.platform_role if user else None)
            if role not in RELATIONS_BY_ROLE or membership.relation not in RELATIONS_BY_ROLE[role]:
                blockers.append({"kind": "illegal_membership", "id": f"{membership.project_id}:{membership.user_id}"})

        normalized_memberships: set[tuple[str, str, str]] = {
            (row.project_id, row.user_id, row.relation) for row in current_memberships
        }
        for index, raw in enumerate(proposed_memberships):
            if not isinstance(raw, dict) or not {"project_id", "user_id", "relation"}.issubset(raw):
                blockers.append({"kind": "invalid_membership_row", "id": str(index)})
                continue
            item = (str(raw["project_id"]), str(raw["user_id"]), str(raw["relation"]))
            role = proposed_roles.get(item[1], users.get(item[1]).platform_role if users.get(item[1]) else None)
            if item[0] not in projects or item[1] not in users or role not in RELATIONS_BY_ROLE or item[2] not in RELATIONS_BY_ROLE[role]:
                blockers.append({"kind": "illegal_membership", "id": ":".join(item)})
            normalized_memberships.add(item)

        for tool_id, tool in tools.items():
            project_id = proposed_tool_projects.get(tool_id)
            if project_id is None:
                blockers.append({"kind": "missing_tool_project_mapping", "id": tool_id})
            elif project_id not in projects:
                blockers.append({"kind": "unknown_project", "id": str(project_id)})

        normalized: list[dict[str, str | None]] = []
        seen: set[tuple[str, str, str, str]] = set()
        required = {"environment_id", "tool_id", "resource_type", "resource_id", "root_resource_id", "owner_user_id", "authorization_source_snapshot"}
        for index, raw in enumerate(resources):
            if not isinstance(raw, dict) or not required.issubset(raw):
                blockers.append({"kind": "invalid_resource_row", "id": str(index)})
                continue
            key = (str(raw["environment_id"]), str(raw["tool_id"]), str(raw["resource_type"]), str(raw["resource_id"]))
            if key in seen:
                blockers.append({"kind": "duplicate_resource", "id": ":".join(key)})
                continue
            seen.add(key)
            if key[1] not in tools:
                blockers.append({"kind": "unknown_tool", "id": key[1]})
            if str(raw["owner_user_id"]) not in users:
                blockers.append({"kind": "unresolved_owner", "id": ":".join(key)})
            if str(raw.get("authorization_source_snapshot") or "") not in {"platform_admin", "public", "project_manager", "project_member", "extra_grant"}:
                blockers.append({"kind": "unresolved_authorization_source", "id": ":".join(key)})
            existing = database.scalar(select(BusinessResourceSnapshot).where(
                BusinessResourceSnapshot.environment_id == key[0],
                BusinessResourceSnapshot.tool_id == key[1],
                BusinessResourceSnapshot.resource_type == key[2],
                BusinessResourceSnapshot.resource_id == key[3],
            ))
            if existing and (
                existing.owner_user_id != str(raw["owner_user_id"])
                or existing.project_id_snapshot != raw.get("project_id_snapshot")
                or existing.root_resource_id != str(raw["root_resource_id"])
            ):
                blockers.append({"kind": "snapshot_conflict", "id": ":".join(key)})
            normalized.append({name: (None if raw.get(name) is None else str(raw.get(name))) for name in required | {"project_id_snapshot"}})

        # 源端导出计数是全量性证明；空 resources 只有在每个工具/环境显式声明 0 时才合法。
        actual_counts: dict[str, int] = {}
        for raw in normalized:
            count_key = f"{raw['environment_id']}:{raw['tool_id']}"
            actual_counts[count_key] = actual_counts.get(count_key, 0) + 1
        required_scopes = {f"{environment}:{tool_id}" for environment in required_environments for tool_id in RESOURCE_TOOLS}
        for count_key in sorted(required_scopes | set(actual_counts)):
            if count_key not in source_counts:
                blockers.append({"kind": "missing_source_inventory", "id": count_key})
            elif source_counts[count_key] != actual_counts.get(count_key, 0):
                blockers.append({"kind": "source_inventory_mismatch", "id": count_key})

        # 用旧 tool.view 明细与拟议新关系做 shadow 对比，任何新增访问必须显式批准。
        old_pairs = set()
        for user_role in database.scalars(select(UserRole)).all():
            for grant in database.scalars(select(RoleGrant).where(RoleGrant.role_id == user_role.role_id, RoleGrant.permission_code == "tool.view")).all():
                for tool_id in tools if grant.resource_id == "*" else (grant.resource_id,):
                    if tool_id in tools:
                        old_pairs.add((user_role.user_id, tool_id))
        for user_id, user in users.items():
            role = proposed_roles.get(user_id, user.platform_role)
            for tool_id in tools:
                project_id = proposed_tool_projects.get(tool_id)
                new_allowed = role == "platform_admin" or any(
                    membership_project == project_id and membership_user == user_id
                    for membership_project, membership_user, _relation in normalized_memberships
                )
                widening_key = f"{user_id}:{tool_id}"
                if new_allowed and (user_id, tool_id) not in old_pairs and widening_key not in approved_widenings:
                    blockers.append({"kind": "unapproved_permission_widening", "id": widening_key})

        report = {
            "mode": "apply" if apply else "dry-run",
            "users": len(users),
            "resources_in_manifest": len(resources),
            "blocker_count": len(blockers),
            "blockers": blockers,
        }
        if not apply or blockers:
            database.rollback()
            return report

        for user_id, role in proposed_roles.items():
            users[user_id].platform_role = role
        for tool_id, project_id in proposed_tool_projects.items():
            tools[tool_id].access_scope = "project"
            tools[tool_id].project_id = project_id
        for project_id, user_id, relation in normalized_memberships:
            if database.get(ProjectMembership, (project_id, user_id)) is None:
                database.add(ProjectMembership(project_id=project_id, user_id=user_id, relation=relation, created_by_user_id="system/migration"))
        for raw in normalized:
            existing = database.scalar(select(BusinessResourceSnapshot).where(
                BusinessResourceSnapshot.environment_id == raw["environment_id"],
                BusinessResourceSnapshot.tool_id == raw["tool_id"],
                BusinessResourceSnapshot.resource_type == raw["resource_type"],
                BusinessResourceSnapshot.resource_id == raw["resource_id"],
            ))
            if existing is None:
                database.add(BusinessResourceSnapshot(id=new_id("res"), **raw))
        manifest_digest = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        source_digest = hashlib.sha256(json.dumps(source_counts, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        # flush 后计算数据库真实状态，而不是继续信任 manifest 自报内容。0020 会在
        # 同一目标数据库重算；apply 后任何角色/项目/工具/成员/授权/快照写入都会
        # 令摘要不一致并阻断 contract，从而关闭在线漂移窗口。
        database.flush()
        state_digest = authorization_state_digest(database)
        readiness = database.get(ProjectAccessReadiness, "contract-v1")
        if readiness is None:
            readiness = ProjectAccessReadiness(
                id="contract-v1", environment_id=required_environment,
                manifest_digest=manifest_digest, source_digest=source_digest,
                state_digest=state_digest,
            )
            database.add(readiness)
        else:
            readiness.environment_id = required_environment
            readiness.manifest_digest = manifest_digest
            readiness.source_digest = source_digest
            readiness.state_digest = state_digest
        database.commit()
        report["applied"] = True
        return report
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()


def main() -> int:
    """命令行入口；存在阻断项时返回 2，便于发布流水线直接阻断。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--required-environment", required=True)
    args = parser.parse_args()
    report = inspect_and_apply(
        _load_manifest(args.manifest), apply=args.apply,
        required_environment=args.required_environment,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 2 if report["blocker_count"] else 0


if __name__ == "__main__":
    sys.exit(main())

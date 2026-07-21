"""
Go 版数据库 Schema 与 Python ORM 的兼容性检查工具

功能说明:
    第零阶段用于冻结数据库兼容边界。工具可以:
    1. 从 Python SQLAlchemy Base.metadata 收集期望表结构。
    2. 从 PostgreSQL information_schema 读取实际表结构。
    3. 对比表、字段、nullable 和类型族差异。

使用方式:
    python3 scripts/schema_diff.py --database-url postgresql://user:pass@host:5432/db

返回值:
    - 退出码 0: 未发现阻断差异
    - 退出码 1: 存在表或字段级差异

说明:
    当前工具聚焦第零阶段最关键的表字段兼容检查。索引、外键和默认值
    可在后续阶段按相同 SchemaMap 结构扩展。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

# 允许直接从 bug_agent_py 根目录执行脚本。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models import Base  # noqa: E402


@dataclass(frozen=True)
class ColumnSpec:
    """
    字段规格。

    功能说明:
        用统一结构表达 Python ORM 或数据库中的字段定义，便于做差异比较。

    参数说明:
        type_name: 归一化后的类型名称。
        nullable: 字段是否允许为空。
    """

    type_name: str
    nullable: bool


SchemaMap = dict[str, dict[str, ColumnSpec]]


def normalize_type(type_obj: Any) -> str:
    """
    归一化 SQL 类型名称。

    功能说明:
        SQLAlchemy 方言类型和 PostgreSQL information_schema 类型名称存在
        表达差异，此函数将它们压缩到兼容性检查需要的类型族。

    参数说明:
        type_obj: SQLAlchemy 类型对象或数据库 inspector 返回的类型对象。

    返回值:
        str: 归一化类型族，例如 bigint、string、text、boolean、datetime、json。
    """
    raw = str(type_obj).lower()
    if "bigint" in raw or "bigserial" in raw:
        return "bigint"
    if "integer" in raw or raw == "int":
        return "integer"
    if "varchar" in raw or "character varying" in raw or "string" in raw:
        return "string"
    if "text" in raw:
        return "text"
    if "bool" in raw:
        return "boolean"
    if "timestamp" in raw or "datetime" in raw:
        return "datetime"
    if "date" in raw:
        return "date"
    if "json" in raw:
        return "json"
    if "double" in raw or "float" in raw or "numeric" in raw:
        return "number"
    return raw


def collect_metadata_schema() -> SchemaMap:
    """
    收集 Python ORM 元数据结构。

    功能说明:
        遍历 Base.metadata 中已注册的全部表和字段，生成 SchemaMap。

    返回值:
        SchemaMap: 表名到字段规格的映射。
    """
    schema: SchemaMap = {}
    for table_name, table in Base.metadata.tables.items():
        schema[table_name] = {
            column.name: ColumnSpec(
                type_name=normalize_type(column.type),
                nullable=bool(column.nullable),
            )
            for column in table.columns
        }
    return schema


def collect_database_schema(engine: Engine) -> SchemaMap:
    """
    从数据库读取实际表结构。

    功能说明:
        使用 SQLAlchemy inspector 读取当前连接数据库中的表和字段。

    参数说明:
        engine (Engine): SQLAlchemy 同步数据库引擎。

    返回值:
        SchemaMap: 数据库实际表结构映射。
    """
    inspector = inspect(engine)
    schema: SchemaMap = {}
    for table_name in inspector.get_table_names():
        schema[table_name] = {
            column["name"]: ColumnSpec(
                type_name=normalize_type(column["type"]),
                nullable=bool(column["nullable"]),
            )
            for column in inspector.get_columns(table_name)
        }
    return schema


def diff_schema_maps(expected: SchemaMap, actual: SchemaMap) -> list[str]:
    """
    对比期望结构和实际结构。

    功能说明:
        检查表缺失、字段缺失、类型族不一致和 nullable 不一致。
        实际数据库中多出的表和字段只作为兼容扩展，不在第零阶段阻断。

    参数说明:
        expected (SchemaMap): Python ORM 期望结构。
        actual (SchemaMap): 数据库实际结构。

    返回值:
        list[str]: 差异描述列表，空列表表示通过。
    """
    diffs: list[str] = []

    for table_name, expected_columns in sorted(expected.items()):
        actual_columns = actual.get(table_name)
        if actual_columns is None:
            diffs.append(f"缺失表: {table_name}")
            continue

        for column_name, expected_column in sorted(expected_columns.items()):
            actual_column = actual_columns.get(column_name)
            if actual_column is None:
                diffs.append(f"缺失字段: {table_name}.{column_name}")
                continue
            if expected_column.type_name != actual_column.type_name:
                diffs.append(
                    f"字段类型不一致: {table_name}.{column_name} "
                    f"expected={expected_column.type_name} actual={actual_column.type_name}"
                )
            if expected_column.nullable != actual_column.nullable:
                diffs.append(
                    f"字段 nullable 不一致: {table_name}.{column_name} "
                    f"expected={expected_column.nullable} actual={actual_column.nullable}"
                )

    return diffs


def main() -> int:
    """
    命令行入口。

    返回值:
        int: 进程退出码，0 表示通过，1 表示存在差异。
    """
    parser = argparse.ArgumentParser(description="检查 Python ORM 与数据库 Schema 的兼容性")
    parser.add_argument("--database-url", required=True, help="PostgreSQL 同步连接 URL")
    args = parser.parse_args()

    expected = collect_metadata_schema()
    engine = create_engine(args.database_url)
    try:
        actual = collect_database_schema(engine)
    finally:
        engine.dispose()

    diffs = diff_schema_maps(expected, actual)
    if diffs:
        print("发现 Schema 兼容性差异:")
        for diff in diffs:
            print(f"- {diff}")
        return 1

    print(f"Schema 兼容性检查通过，覆盖 {len(expected)} 张 ORM 表。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

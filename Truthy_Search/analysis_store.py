"""searchTool v1.3 SQLite Schema v4、版本迁移、连接和事务管理。"""

from __future__ import annotations

import json
import sqlite3
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence


DB_SCHEMA_VERSION = 4


class UnsupportedSchemaError(RuntimeError):
    """数据库版本超出当前程序支持范围。"""


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS threshold_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL,
    thresholds_json TEXT NOT NULL,
    based_on_profile_id TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(name, version),
    FOREIGN KEY (based_on_profile_id)
        REFERENCES threshold_profiles(profile_id)
);

CREATE TABLE IF NOT EXISTS evaluations (
    evaluation_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    thresholds_json TEXT NOT NULL DEFAULT '{}',
    threshold_profile_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_file TEXT NOT NULL,
    checksum TEXT NOT NULL UNIQUE,
    query_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_queries (
    dataset_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    person_id TEXT,
    person_id_source TEXT NOT NULL DEFAULT 'UNSPECIFIED',
    query_stage TEXT NOT NULL,
    match_strategy TEXT NOT NULL DEFAULT 'UNION',
    clues_json TEXT NOT NULL,
    additional_details_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY (dataset_id, query_id),
    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL,
    dataset_id TEXT,
    run_label TEXT NOT NULL,
    system_version TEXT NOT NULL,
    source_type TEXT NOT NULL,
    status TEXT NOT NULL,
    result_schema_version TEXT NOT NULL,
    results_file TEXT,
    failures_file TEXT,
    source_checksum TEXT UNIQUE,
    total_queries INTEGER NOT NULL DEFAULT 0,
    success_queries INTEGER NOT NULL DEFAULT 0,
    failed_queries INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    message TEXT NOT NULL DEFAULT '',
    evaluation_phase TEXT NOT NULL DEFAULT 'UNSPECIFIED',
    created_at TEXT NOT NULL,
    FOREIGN KEY (evaluation_id) REFERENCES evaluations(evaluation_id),
    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
);

CREATE TABLE IF NOT EXISTS run_queries (
    run_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    person_id TEXT,
    person_id_source TEXT NOT NULL DEFAULT 'UNSPECIFIED',
    query_stage TEXT,
    task_id TEXT,
    status TEXT NOT NULL,
    current_stage TEXT NOT NULL DEFAULT '',
    candidate_count_total INTEGER,
    candidate_count_listed INTEGER NOT NULL DEFAULT 0,
    detail_success_count INTEGER NOT NULL DEFAULT 0,
    detail_failure_count INTEGER NOT NULL DEFAULT 0,
    llm_cost REAL,
    third_party_cost REAL,
    total_cost REAL,
    pdl_called INTEGER,
    search_duration_ms INTEGER,
    result_status TEXT,
    public_fields_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (run_id, query_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS candidates (
    candidate_pk TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    candidate_rank INTEGER NOT NULL,
    rank_score REAL,
    detail_status TEXT NOT NULL,
    detail_error TEXT NOT NULL DEFAULT '',
    ui_sections_json TEXT,
    detail_data_json TEXT,
    list_item_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, query_id, candidate_rank),
    FOREIGN KEY (run_id, query_id)
        REFERENCES run_queries(run_id, query_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS raw_records (
    raw_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    query_id TEXT,
    candidate_pk TEXT,
    stage TEXT NOT NULL,
    sequence_no INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (candidate_pk) REFERENCES candidates(candidate_pk)
);

CREATE TABLE IF NOT EXISTS failures (
    failure_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    query_id TEXT,
    candidate_id TEXT,
    scope TEXT NOT NULL,
    stage TEXT NOT NULL,
    error TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS field_schemas (
    schema_version TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    definitions_json TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS baseline_sets (
    baseline_version TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_file TEXT NOT NULL,
    checksum TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS baseline_people (
    baseline_version TEXT NOT NULL,
    person_id TEXT NOT NULL,
    display_name TEXT,
    fields_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    available_fields_json TEXT NOT NULL DEFAULT '[]',
    available_fields_source TEXT NOT NULL DEFAULT 'UNSPECIFIED',
    PRIMARY KEY (baseline_version, person_id),
    FOREIGN KEY (baseline_version)
        REFERENCES baseline_sets(baseline_version) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS run_query_person_history (
    history_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    old_person_id TEXT,
    new_person_id TEXT,
    change_source TEXT NOT NULL,
    sync_dataset INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    changed_at TEXT NOT NULL,
    FOREIGN KEY (run_id, query_id)
        REFERENCES run_queries(run_id, query_id) ON DELETE CASCADE,
    FOREIGN KEY (baseline_version)
        REFERENCES baseline_sets(baseline_version)
);

CREATE TABLE IF NOT EXISTS process_runs (
    process_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    baseline_version TEXT,
    rule_version TEXT NOT NULL,
    status TEXT NOT NULL,
    error_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id),
    FOREIGN KEY (schema_version) REFERENCES field_schemas(schema_version),
    FOREIGN KEY (baseline_version) REFERENCES baseline_sets(baseline_version)
);

CREATE TABLE IF NOT EXISTS processed_candidates (
    process_id TEXT NOT NULL,
    candidate_pk TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    empty_fields_json TEXT NOT NULL,
    processing_errors_json TEXT NOT NULL,
    PRIMARY KEY (process_id, candidate_pk),
    FOREIGN KEY (process_id) REFERENCES process_runs(process_id) ON DELETE CASCADE,
    FOREIGN KEY (candidate_pk) REFERENCES candidates(candidate_pk)
);

CREATE TABLE IF NOT EXISTS processed_queries (
    process_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    result_status TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    empty_fields_json TEXT NOT NULL,
    processing_errors_json TEXT NOT NULL,
    PRIMARY KEY (process_id, query_id),
    FOREIGN KEY (process_id)
        REFERENCES process_runs(process_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id, query_id)
        REFERENCES run_queries(run_id, query_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    process_id TEXT NOT NULL,
    candidate_pk TEXT NOT NULL,
    judgement TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    field_scores_json TEXT NOT NULL,
    reviewer TEXT,
    review_note TEXT,
    reviewed_at TEXT,
    classification_source TEXT NOT NULL DEFAULT 'SUGGESTED',
    is_primary_hit INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (process_id, candidate_pk),
    FOREIGN KEY (process_id, candidate_pk)
        REFERENCES processed_candidates(process_id, candidate_pk) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL,
    baseline_process_id TEXT,
    candidate_process_id TEXT NOT NULL,
    report_type TEXT NOT NULL,
    status TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    html_file TEXT NOT NULL,
    excel_file TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (evaluation_id) REFERENCES evaluations(evaluation_id),
    FOREIGN KEY (baseline_process_id) REFERENCES process_runs(process_id),
    FOREIGN KEY (candidate_process_id) REFERENCES process_runs(process_id)
);

CREATE INDEX IF NOT EXISTS idx_runs_evaluation_created
    ON runs(evaluation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_run_queries_status_stage
    ON run_queries(run_id, status, query_stage);
CREATE INDEX IF NOT EXISTS idx_run_queries_person_stage
    ON run_queries(person_id, query_stage);
CREATE INDEX IF NOT EXISTS idx_candidates_run_query_rank
    ON candidates(run_id, query_id, candidate_rank);
CREATE INDEX IF NOT EXISTS idx_failures_run_scope_stage
    ON failures(run_id, scope, stage);
CREATE INDEX IF NOT EXISTS idx_process_runs_run_created
    ON process_runs(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_processed_queries_process_status
    ON processed_queries(process_id, result_status);
CREATE INDEX IF NOT EXISTS idx_reviews_process_judgement
    ON reviews(process_id, judgement);
CREATE INDEX IF NOT EXISTS idx_person_history_run_query
    ON run_query_person_history(run_id, query_id, changed_at);
"""


def utc_now_text() -> str:
    """返回带时区的 UTC ISO 8601 时间。"""

    return datetime.now(timezone.utc).isoformat()


class AnalysisStore:
    """管理单个 searchTool SQLite 数据库。

    功能说明:
        统一设置外键、WAL 和 busy timeout，提供幂等 Schema v4 初始化、
        v1到v4连续事务迁移、显式事务以及少量通用只读查询。
        业务导入逻辑不放在本类中。
    """

    def __init__(self, db_path: Path | str) -> None:
        """保存数据库路径，实际文件在 initialize 或 connection 时打开。"""

        self.db_path = Path(db_path).resolve()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """打开一个应用统一 PRAGMA 的连接并在使用后关闭。

        返回值:
            通过上下文管理器提供 ``sqlite3.Connection``，行类型为
            ``sqlite3.Row``。

        异常说明:
            SQLite 打开或 PRAGMA 失败时原样抛出，避免继续使用异常连接。
        """

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """开启显式写事务，成功提交，任一异常时完整回滚。"""

        with self.connection() as connection:
            try:
                connection.execute("BEGIN")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _execute_schema_sql(connection: sqlite3.Connection) -> None:
        """在当前事务中逐条执行 Schema SQL。

        功能说明:
            避免 ``sqlite3.executescript`` 的隐式提交破坏迁移原子性。
            当前 Schema 不包含触发器，按分号拆分 DDL 可保持语义稳定。

        参数说明:
            connection: 已开启写事务的 SQLite 连接。

        返回值:
            无；所有 DDL 均成功后返回。

        异常说明:
            任一 DDL 失败时原样抛出，由外层事务完整回滚。
        """

        for statement in SCHEMA_SQL.split(";"):
            sql = statement.strip()
            if sql:
                connection.execute(sql)

    @staticmethod
    def _column_names(
        connection: sqlite3.Connection,
        table_name: str,
    ) -> set[str]:
        """返回指定表或视图的现有列名，供幂等迁移判断。"""

        return {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table_name})")
        }

    @classmethod
    def _add_column_if_missing(
        cls,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_sql: str,
    ) -> None:
        """仅在旧表缺少目标列时执行 ALTER TABLE。

        参数说明:
            connection: 当前迁移事务连接。
            table_name: 内部固定的目标表名。
            column_name: 待新增列名。
            column_sql: 包含列名、类型和默认值的完整列定义。

        返回值:
            无；已有列保持不变，新列只添加一次。

        异常说明:
            表缺失、目标是视图或 SQLite 拒绝 DDL 时原样抛出，
            由外层事务回滚此前迁移步骤。
        """

        if column_name in cls._column_names(connection, table_name):
            return
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")

    @staticmethod
    def _legacy_available_fields(fields_json: str) -> list[str]:
        """从旧 Baseline 的非空字段派生可评估字段键。

        参数说明:
            fields_json: Schema v1 ``baseline_people.fields_json`` 原文。

        返回值:
            保持原 JSON 键顺序的字段名数组。``False`` 和数字0是有效
            基准值；None、空白字符串及空容器不进入数组。

        异常说明:
            旧 JSON 损坏或不是对象时返回空数组，原文仍原样保留。
        """

        try:
            fields = json.loads(fields_json)
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(fields, dict):
            return []
        available: list[str] = []
        for field_key, value in fields.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, (list, dict)) and not value:
                continue
            available.append(str(field_key))
        return available

    @classmethod
    def _migrate_v1_to_v2(cls, connection: sqlite3.Connection) -> None:
        """在单个事务内把 Schema v1 增量升级到v2。

        功能说明:
            新增阶段、公共字段、Baseline可用字段和Query处理快照；
            同时根据旧状态与旧Baseline数据生成兼容值。不会删除、
            重命名或覆盖 Raw、Process、Review 和 Report。

        参数说明:
            connection: 已开启写事务且当前 schema_version 为1的连接。

        返回值:
            无；成功后把 schema_info 更新为2。

        异常说明:
            任一 DDL、数据转换或约束失败时原样抛出，外层事务回滚
            所有新增列、数据更新和版本号。
        """

        cls._add_column_if_missing(
            connection,
            "evaluations",
            "thresholds_json",
            "thresholds_json TEXT NOT NULL DEFAULT '{}'",
        )
        cls._add_column_if_missing(
            connection,
            "runs",
            "evaluation_phase",
            "evaluation_phase TEXT NOT NULL DEFAULT 'UNSPECIFIED'",
        )
        cls._add_column_if_missing(
            connection,
            "run_queries",
            "result_status",
            "result_status TEXT",
        )
        cls._add_column_if_missing(
            connection,
            "run_queries",
            "third_party_cost",
            "third_party_cost REAL",
        )
        cls._add_column_if_missing(
            connection,
            "run_queries",
            "search_duration_ms",
            "search_duration_ms INTEGER",
        )
        cls._add_column_if_missing(
            connection,
            "run_queries",
            "public_fields_json",
            "public_fields_json TEXT NOT NULL DEFAULT '{}'",
        )
        cls._add_column_if_missing(
            connection,
            "baseline_people",
            "available_fields_json",
            "available_fields_json TEXT NOT NULL DEFAULT '[]'",
        )
        cls._add_column_if_missing(
            connection,
            "baseline_people",
            "available_fields_source",
            "available_fields_source TEXT NOT NULL DEFAULT 'UNSPECIFIED'",
        )

        # 补齐 v2 新表和索引；CREATE IF NOT EXISTS 不改变现有 v1 表。
        cls._execute_schema_sql(connection)
        connection.execute(
            """
            UPDATE run_queries
            SET result_status = CASE
                WHEN status IN ('FAILED', 'EXECUTION_FAILED')
                    THEN 'EXECUTION_FAILED'
                WHEN status IN ('NO_CANDIDATE', 'NO_CANDIDATES')
                    THEN 'NO_CANDIDATES'
                WHEN status IN (
                    'SUCCESS', 'PARTIAL_DETAIL_FAILED', 'HAS_CANDIDATES'
                ) AND COALESCE(candidate_count_listed, 0) > 0
                    THEN 'HAS_CANDIDATES'
                WHEN status IN ('SUCCESS', 'PARTIAL_DETAIL_FAILED')
                    THEN 'NO_CANDIDATES'
                ELSE NULL
            END
            """
        )
        baseline_rows = connection.execute(
            """
            SELECT baseline_version, person_id, fields_json
            FROM baseline_people
            """
        ).fetchall()
        for row in baseline_rows:
            available_fields = cls._legacy_available_fields(row["fields_json"])
            connection.execute(
                """
                UPDATE baseline_people
                SET available_fields_json = ?,
                    available_fields_source = ?
                WHERE baseline_version = ? AND person_id = ?
                """,
                (
                    json.dumps(
                        available_fields,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "DERIVED_LEGACY" if available_fields else "UNSPECIFIED",
                    row["baseline_version"],
                    row["person_id"],
                ),
            )
        connection.execute(
            """
            UPDATE schema_info SET value = ?
            WHERE key = 'schema_version'
            """,
            ("2",),
        )

    @classmethod
    def _migrate_v2_to_v3(cls, connection: sqlite3.Connection) -> None:
        """在同一事务内增加版本化参考线方案和 Evaluation 方案标识。

        历史 ``thresholds_json`` 不做解析或重写；新增关联列默认为空，
        因而旧 Evaluation 明确保持“历史自定义参考线”语义。
        """

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS threshold_profiles (
                profile_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL,
                thresholds_json TEXT NOT NULL,
                based_on_profile_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(name, version),
                FOREIGN KEY (based_on_profile_id)
                    REFERENCES threshold_profiles(profile_id)
            )
            """
        )
        cls._add_column_if_missing(
            connection,
            "evaluations",
            "threshold_profile_id",
            "threshold_profile_id TEXT",
        )
        cls._execute_schema_sql(connection)
        connection.execute(
            """
            UPDATE schema_info SET value = ?
            WHERE key = 'schema_version'
            """,
            ("3",),
        )

    @classmethod
    def _migrate_v3_to_v4(cls, connection: sqlite3.Connection) -> None:
        """在单个事务内升级人物关联和身份归类结构。

        功能说明:
            为 Dataset/Run Query 增加人物来源，为 Review 增加最终分类来源
            和主要命中标记，并建立人物关联审计表。历史已复核 HIT 按同一
            Process、Query 的最小候选排名选出唯一主要命中。

        参数说明:
            connection: 已开启写事务且 schema_version 为3的连接。

        返回值:
            无；成功后把 schema_info 更新为4。

        异常说明:
            任一 DDL 或历史数据迁移失败时原样抛出，由外层事务回滚全部
            v4 变更。历史同 Query 多个最终 HIT 会发出 RuntimeWarning，
            但仍按排名最小者完成兼容迁移。
        """

        cls._add_column_if_missing(
            connection,
            "dataset_queries",
            "person_id_source",
            "person_id_source TEXT NOT NULL DEFAULT 'UNSPECIFIED'",
        )
        cls._add_column_if_missing(
            connection,
            "run_queries",
            "person_id_source",
            "person_id_source TEXT NOT NULL DEFAULT 'UNSPECIFIED'",
        )
        cls._add_column_if_missing(
            connection,
            "reviews",
            "classification_source",
            "classification_source TEXT NOT NULL DEFAULT 'SUGGESTED'",
        )
        cls._add_column_if_missing(
            connection,
            "reviews",
            "is_primary_hit",
            "is_primary_hit INTEGER NOT NULL DEFAULT 0",
        )
        cls._execute_schema_sql(connection)

        connection.execute(
            """
            UPDATE dataset_queries
            SET person_id_source = CASE
                WHEN person_id IS NULL OR TRIM(person_id) = ''
                    THEN 'UNSPECIFIED'
                ELSE 'INPUT'
            END
            """
        )
        connection.execute(
            """
            UPDATE run_queries
            SET person_id_source = CASE
                WHEN person_id IS NULL OR TRIM(person_id) = ''
                    THEN 'UNSPECIFIED'
                ELSE 'DATASET'
            END
            """
        )
        connection.execute(
            """
            UPDATE reviews
            SET classification_source = CASE
                    WHEN reviewed_at IS NULL THEN 'SUGGESTED'
                    ELSE 'MANUAL'
                END,
                is_primary_hit = 0
            """
        )
        duplicate_hit_queries = connection.execute(
            """
            SELECT r.process_id, c.run_id, c.query_id, COUNT(*) AS hit_count
            FROM reviews AS r
            JOIN candidates AS c ON c.candidate_pk = r.candidate_pk
            WHERE r.reviewed_at IS NOT NULL AND r.judgement = 'HIT'
            GROUP BY r.process_id, c.run_id, c.query_id
            HAVING COUNT(*) > 1
            ORDER BY r.process_id, c.run_id, c.query_id
            """
        ).fetchall()
        if duplicate_hit_queries:
            examples = ", ".join(
                f"{row['process_id']}/{row['query_id']}={row['hit_count']}"
                for row in duplicate_hit_queries[:5]
            )
            warnings.warn(
                "Schema v4 迁移发现同一 Query 存在多个历史最终 HIT，"
                f"已按 candidate_rank 最小者设为主要命中: {examples}",
                RuntimeWarning,
                stacklevel=2,
            )
        primary_hits = connection.execute(
            """
            SELECT r.process_id, r.candidate_pk, c.run_id, c.query_id
            FROM reviews AS r
            JOIN candidates AS c ON c.candidate_pk = r.candidate_pk
            WHERE r.reviewed_at IS NOT NULL AND r.judgement = 'HIT'
            ORDER BY r.process_id, c.run_id, c.query_id,
                     c.candidate_rank, c.candidate_pk
            """
        ).fetchall()
        seen_queries: set[tuple[str, str, str]] = set()
        for row in primary_hits:
            key = (row["process_id"], row["run_id"], row["query_id"])
            if key in seen_queries:
                continue
            seen_queries.add(key)
            connection.execute(
                """
                UPDATE reviews SET is_primary_hit = 1
                WHERE process_id = ? AND candidate_pk = ?
                """,
                (row["process_id"], row["candidate_pk"]),
            )
        connection.execute(
            """
            UPDATE schema_info SET value = ?
            WHERE key = 'schema_version'
            """,
            (str(DB_SCHEMA_VERSION),),
        )

    def initialize(self) -> None:
        """幂等初始化 Schema v4，并在单事务内连续迁移旧版本。

        异常说明:
            UnsupportedSchemaError: 数据库版本无效、高于4或低于1。
            sqlite3.Error: 建表或迁移失败，且迁移事务已经回滚。
        """

        with self.transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_info(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT value FROM schema_info WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                self._execute_schema_sql(connection)
                connection.execute(
                    """
                    INSERT INTO schema_info(key, value)
                    VALUES ('schema_version', ?)
                    """,
                    (str(DB_SCHEMA_VERSION),),
                )
                return
            try:
                current_version = int(row["value"])
            except (TypeError, ValueError) as exc:
                raise UnsupportedSchemaError("数据库 Schema 版本无效") from exc
            if current_version < 1 or current_version > DB_SCHEMA_VERSION:
                raise UnsupportedSchemaError(
                    f"数据库 Schema 版本为 {current_version}，"
                    f"当前程序支持 1 到 {DB_SCHEMA_VERSION}"
                )
            if current_version == 1:
                self._migrate_v1_to_v2(connection)
                current_version = 2
            if current_version == 2:
                self._migrate_v2_to_v3(connection)
                current_version = 3
            if current_version == 3:
                self._migrate_v3_to_v4(connection)
                return
            self._execute_schema_sql(connection)

    def schema_version(self) -> int:
        """读取已初始化数据库的 Schema 版本。"""

        row = self.fetch_one(
            "SELECT value FROM schema_info WHERE key = 'schema_version'"
        )
        if row is None:
            raise UnsupportedSchemaError("数据库尚未初始化")
        return int(row["value"])

    def fetch_one(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> sqlite3.Row | None:
        """执行一条参数化只读查询并返回首行。"""

        with self.connection() as connection:
            return connection.execute(sql, parameters).fetchone()

    def fetch_all(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> list[sqlite3.Row]:
        """执行一条参数化只读查询并返回全部行。"""

        with self.connection() as connection:
            return list(connection.execute(sql, parameters).fetchall())

    def create_evaluation(
        self,
        evaluation_id: str,
        name: str,
        notes: str = "",
        thresholds: dict[str, object] | None = None,
        threshold_profile_id: str | None = None,
    ) -> None:
        """创建一个评测容器，供后续 Run 导入引用。

        参数说明:
            evaluation_id: 非空唯一标识。
            name: 非空评测名称。
            notes: 可选说明。
            thresholds: 已由业务层校验的可选参考线对象。
            threshold_profile_id: 可选的版本化参考线方案标识。

        异常说明:
            ValueError: 标识或名称为空。
            sqlite3.IntegrityError: 标识已存在。
        """

        if not evaluation_id.strip() or not name.strip():
            raise ValueError("evaluation_id 和 name 不能为空")
        now = utc_now_text()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO evaluations(
                    evaluation_id, name, notes, thresholds_json,
                    threshold_profile_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation_id,
                    name,
                    notes,
                    json.dumps(
                        thresholds or {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    threshold_profile_id,
                    now,
                    now,
                ),
            )

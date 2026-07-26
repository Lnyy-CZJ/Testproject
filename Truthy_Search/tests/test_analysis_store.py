"""SQLite Schema v2、v1迁移与事务行为测试。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from analysis_store import AnalysisStore, UnsupportedSchemaError


class AnalysisStoreTests(unittest.TestCase):
    """验证数据库初始化、约束、事务回滚和重新打开。"""

    @staticmethod
    def _create_legacy_v1_database(db_path: Path) -> None:
        """创建包含迁移边界数据的最小 Schema v1 数据库。

        功能说明:
            只建立 v1→v2 迁移直接依赖的旧表，并写入多种 Query 状态和
            Baseline 空值；其余 v1 表由 v2 初始化脚本补齐。

        参数说明:
            db_path: 待创建的临时 SQLite 文件。

        返回值:
            无；成功后文件中的 schema_version 固定为1。

        异常说明:
            SQLite 建表或写入失败时原样抛出，让迁移测试立即失败。
        """

        connection = sqlite3.connect(db_path)
        connection.executescript(
            """
            CREATE TABLE schema_info(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT INTO schema_info(key, value)
            VALUES ('schema_version', '1');

            CREATE TABLE evaluations (
                evaluation_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO evaluations
            VALUES ('eval-v1', '迁移评测', '', 'now', 'now');

            CREATE TABLE runs (
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
                created_at TEXT NOT NULL
            );
            INSERT INTO runs(
                run_id, evaluation_id, run_label, system_version,
                source_type, status, result_schema_version,
                total_queries, success_queries, failed_queries, created_at
            ) VALUES (
                'run-v1', 'eval-v1', 'legacy', 'v1', 'JSONL_IMPORT',
                'COMPLETED', '1.3', 5, 4, 1, 'now'
            );

            CREATE TABLE run_queries (
                run_id TEXT NOT NULL,
                query_id TEXT NOT NULL,
                person_id TEXT,
                query_stage TEXT,
                task_id TEXT,
                status TEXT NOT NULL,
                current_stage TEXT NOT NULL DEFAULT '',
                candidate_count_total INTEGER,
                candidate_count_listed INTEGER NOT NULL DEFAULT 0,
                detail_success_count INTEGER NOT NULL DEFAULT 0,
                detail_failure_count INTEGER NOT NULL DEFAULT 0,
                llm_cost REAL,
                total_cost REAL,
                pdl_called INTEGER,
                error TEXT NOT NULL DEFAULT '',
                started_at TEXT,
                finished_at TEXT,
                PRIMARY KEY (run_id, query_id)
            );
            INSERT INTO run_queries(
                run_id, query_id, status, candidate_count_listed
            ) VALUES
                ('run-v1', 'query-success', 'SUCCESS', 2),
                ('run-v1', 'query-empty', 'NO_CANDIDATE', 0),
                ('run-v1', 'query-partial', 'PARTIAL_DETAIL_FAILED', 1),
                ('run-v1', 'query-failed', 'FAILED', 0),
                ('run-v1', 'query-pending', 'PENDING', 0);

            CREATE TABLE baseline_sets (
                baseline_version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_file TEXT NOT NULL,
                checksum TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            INSERT INTO baseline_sets
            VALUES ('baseline-v1', '旧基准', 'JSONL', 'baseline.jsonl',
                    'baseline-checksum', 'now');

            CREATE TABLE baseline_people (
                baseline_version TEXT NOT NULL,
                person_id TEXT NOT NULL,
                display_name TEXT,
                fields_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                PRIMARY KEY (baseline_version, person_id)
            );
            INSERT INTO baseline_people
            VALUES (
                'baseline-v1',
                'person-v1',
                'Legacy Person',
                '{"name":"Legacy Person","active":false,"score":0,'
                || '"empty_text":"","empty_list":[],"missing":null}',
                '{}'
            );
            """
        )
        connection.commit()
        connection.close()

    def test_schema_initialization_is_idempotent_and_reopenable(self):
        """重复初始化保持 Schema v2，并能由新 Store 实例重新打开。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "searchtool.db"
            store = AnalysisStore(db_path)
            store.initialize()
            store.initialize()
            store.create_evaluation("eval-1", "阶段2测试")

            reopened = AnalysisStore(db_path)
            reopened.initialize()
            tables = {
                row["name"]
                for row in reopened.fetch_all(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            with reopened.connection() as connection:
                foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
                journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

            evaluation_columns = {
                row["name"]
                for row in reopened.fetch_all("PRAGMA table_info(evaluations)")
            }
            run_columns = {
                row["name"] for row in reopened.fetch_all("PRAGMA table_info(runs)")
            }
            query_columns = {
                row["name"]
                for row in reopened.fetch_all("PRAGMA table_info(run_queries)")
            }

            self.assertEqual(2, reopened.schema_version())
            self.assertEqual(1, foreign_keys)
            self.assertEqual("wal", journal_mode.lower())
            self.assertTrue(
                {
                    "evaluations",
                    "datasets",
                    "runs",
                    "run_queries",
                    "candidates",
                    "raw_records",
                    "failures",
                    "baseline_sets",
                    "baseline_people",
                    "processed_queries",
                    "reports",
                }.issubset(tables)
            )
            self.assertIn("thresholds_json", evaluation_columns)
            self.assertIn("evaluation_phase", run_columns)
            self.assertTrue(
                {
                    "result_status",
                    "third_party_cost",
                    "search_duration_ms",
                    "public_fields_json",
                }.issubset(query_columns)
            )
            self.assertEqual(
                "阶段2测试",
                reopened.fetch_one(
                    "SELECT name FROM evaluations WHERE evaluation_id = ?",
                    ("eval-1",),
                )["name"],
            )

    def test_schema_v1_migrates_to_v2_and_preserves_legacy_meaning(self):
        """v1数据迁移后保留记录，并生成状态和基准可用字段。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy-v1.db"
            self._create_legacy_v1_database(db_path)

            store = AnalysisStore(db_path)
            store.initialize()
            store.initialize()

            self.assertEqual(2, store.schema_version())
            evaluation = store.fetch_one(
                "SELECT * FROM evaluations WHERE evaluation_id = 'eval-v1'"
            )
            run = store.fetch_one("SELECT * FROM runs WHERE run_id = 'run-v1'")
            statuses = {
                row["query_id"]: row["result_status"]
                for row in store.fetch_all(
                    """
                    SELECT query_id, result_status
                    FROM run_queries WHERE run_id = 'run-v1'
                    """
                )
            }
            baseline = store.fetch_one(
                """
                SELECT available_fields_json, available_fields_source
                FROM baseline_people
                WHERE baseline_version = 'baseline-v1'
                  AND person_id = 'person-v1'
                """
            )

            self.assertEqual("{}", evaluation["thresholds_json"])
            self.assertEqual("UNSPECIFIED", run["evaluation_phase"])
            self.assertEqual(
                {
                    "query-success": "HAS_CANDIDATES",
                    "query-empty": "NO_CANDIDATES",
                    "query-partial": "HAS_CANDIDATES",
                    "query-failed": "EXECUTION_FAILED",
                    "query-pending": None,
                },
                statuses,
            )
            self.assertEqual(
                '["name","active","score"]',
                baseline["available_fields_json"],
            )
            self.assertEqual(
                "DERIVED_LEGACY",
                baseline["available_fields_source"],
            )
            self.assertIsNotNone(
                store.fetch_one(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name = 'processed_queries'
                    """
                )
            )

    def test_schema_v1_migration_failure_rolls_back_all_ddl(self):
        """迁移中途失败时版本号和已执行的ALTER TABLE全部回滚。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "broken-v1.db"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE schema_info(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT INTO schema_info(key, value)
                VALUES ('schema_version', '1');
                CREATE TABLE evaluations(
                    evaluation_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE runs(
                    run_id TEXT PRIMARY KEY,
                    evaluation_id TEXT NOT NULL,
                    run_label TEXT NOT NULL,
                    system_version TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_schema_version TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE VIEW run_queries AS SELECT 'broken' AS query_id;
                """
            )
            connection.commit()
            connection.close()

            with self.assertRaises(sqlite3.OperationalError):
                AnalysisStore(db_path).initialize()

            connection = sqlite3.connect(db_path)
            version = connection.execute(
                """
                SELECT value FROM schema_info
                WHERE key = 'schema_version'
                """
            ).fetchone()[0]
            evaluation_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(evaluations)")
            }
            run_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(runs)")
            }
            connection.close()

            self.assertEqual("1", version)
            self.assertNotIn("thresholds_json", evaluation_columns)
            self.assertNotIn("evaluation_phase", run_columns)

    def test_transaction_rolls_back_all_rows_on_error(self):
        """事务中任一写入失败时，不保留此前已写入的数据。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            store = AnalysisStore(Path(temp_dir) / "searchtool.db")
            store.initialize()

            with self.assertRaises(sqlite3.IntegrityError):
                with store.transaction() as connection:
                    connection.execute(
                        """
                        INSERT INTO evaluations(
                            evaluation_id, name, notes, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        ("eval-rollback", "回滚测试", "", "now", "now"),
                    )
                    connection.execute(
                        """
                        INSERT INTO runs(
                            run_id, evaluation_id, run_label, system_version,
                            source_type, status, result_schema_version,
                            source_checksum, total_queries, success_queries,
                            failed_queries, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "run-invalid",
                            "missing-evaluation",
                            "candidate",
                            "v1",
                            "JSONL_IMPORT",
                            "COMPLETED",
                            "1.3",
                            "checksum",
                            0,
                            0,
                            0,
                            "now",
                        ),
                    )

            self.assertIsNone(
                store.fetch_one(
                    "SELECT evaluation_id FROM evaluations WHERE evaluation_id = ?",
                    ("eval-rollback",),
                )
            )

    def test_newer_schema_version_is_rejected(self):
        """数据库版本高于程序支持版本时停止初始化，避免误写。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "newer.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE schema_info(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO schema_info(key, value) VALUES ('schema_version', '3')"
            )
            connection.commit()
            connection.close()

            with self.assertRaises(UnsupportedSchemaError):
                AnalysisStore(db_path).initialize()

    def test_sqlite_online_backup_can_be_restored(self):
        """SQLite backup 快照可恢复，并保留 Schema 和业务记录。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "source.db"
            backup_path = root / "backup.db"
            source = AnalysisStore(source_path)
            source.initialize()
            source.create_evaluation("eval-backup", "备份恢复验收")

            # 使用 SQLite backup API 生成一致性快照，避免直接复制 WAL 数据库。
            with source.connection() as source_connection:
                with sqlite3.connect(backup_path) as backup_connection:
                    source_connection.backup(backup_connection)

            restored = AnalysisStore(backup_path)
            restored.initialize()
            self.assertEqual(2, restored.schema_version())
            self.assertEqual(
                "备份恢复验收",
                restored.fetch_one(
                    """
                    SELECT name FROM evaluations
                    WHERE evaluation_id = 'eval-backup'
                    """
                )["name"],
            )


if __name__ == "__main__":
    unittest.main()

"""Tests for the offline JSONL-to-Excel exporter.

The tests use synthetic data and never read credentials, call HTTP APIs, or mutate
the real output directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPORTER = PROJECT_ROOT / "result_to_excel.py"


def write_jsonl(path: Path, records: list[dict]) -> None:
    """Write synthetic JSONL records used by a test.

    Args:
        path: Destination JSONL file.
        records: JSON objects to write, one per line.

    Returns:
        None.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def candidate(
    candidate_id: str,
    profile_label: str = "Full Name",
    photo_payload: str = "",
    rank_score: float | None = None,
) -> dict:
    """Build a representative candidate fixture.

    Args:
        candidate_id: Candidate identifier used for traceability checks.
        profile_label: Dynamic Profile label included in this candidate.
        photo_payload: Optional large value used to exercise Raw sheet splitting.
        rank_score: Optional ranking score returned by ListTaskCandidates.

    Returns:
        A result item with all five ui_sections modules.
    """

    photos_data = {
        "baseline_photo_url": "https://example.test/base.jpg",
        "identity_match_rate": 0.75,
        "authenticity_photos": [{"url": "https://example.test/a.jpg"}],
        "match_photos": [],
    }
    if photo_payload:
        photos_data["authenticity_photos"] = [{"payload": photo_payload}]

    result = {
        "candidate_id": candidate_id,
        "ui_sections": {
            "insights": {
                "status": "data",
                "data": {
                    "count": 1,
                    "items": [
                        {
                            "description": "Known public profile",
                            "links": [
                                {
                                    "platform": "web",
                                    "title": "Evidence",
                                    "type": "source",
                                    "url": "https://example.test/evidence",
                                }
                            ],
                        }
                    ],
                },
            },
            "photos": {"status": "data", "data": photos_data},
            "profile": {
                "status": "data",
                "data": {
                    "sections": [
                        {
                            "title": "Identity",
                            "items": [{"label": profile_label, "value": "Example Person"}],
                        }
                    ]
                },
            },
            "social": {
                "status": "data",
                "data": {
                    "profiles": [
                        {
                            "display_handle": "first",
                            "platform": "linkedin",
                            "url": "https://linkedin.test/first",
                        },
                        {
                            "display_handle": "second",
                            "platform": "x",
                            "url": "https://x.test/second",
                        },
                    ]
                },
            },
            "summary": {
                "status": "data",
                "data": {
                    "avatar_url": "https://example.test/avatar.jpg",
                    "confidence_level": "HIGH",
                    "primary_image": {"url": "https://example.test/primary.jpg"},
                    "social_links": [
                        {
                            "platform": "linkedin",
                            "title": "LinkedIn",
                            "url": "https://linkedin.test/first",
                        }
                    ],
                    "web_links": [
                        {
                            "platform": "web",
                            "title": "Official site",
                            "url": "https://example.test/profile",
                        }
                    ],
                    "display_name": "Example Person",
                    "location": "Shanghai",
                    "match_score": 95,
                    "is_top_result": True,
                    "is_best_match": True,
                },
            },
        },
    }
    if rank_score is not None:
        result["rank_score"] = rank_score
    return result


class ResultToExcelTests(unittest.TestCase):
    """End-to-end tests for model construction and workbook export."""

    def run_exporter(
        self,
        arguments: list[str],
        model_path: Path,
        *,
        create_workbook: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run the public Python entry point with a test-only model sidecar.

        Args:
            arguments: CLI arguments after the script name.
            model_path: Path receiving the internal model for deterministic assertions.
            create_workbook: Whether to run the slower artifact-tool export path.

        Returns:
            Completed subprocess result.

        Raises:
            AssertionError: When the exporter returns a non-zero status.
        """

        env = os.environ.copy()
        env["SEARCHTOOL_MODEL_OUTPUT"] = str(model_path)
        if not create_workbook:
            env["SEARCHTOOL_SKIP_WORKBOOK"] = "1"
        result = subprocess.run(
            [sys.executable, str(EXPORTER), *arguments],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(0, result.returncode, msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        return result

    def test_single_run_extracts_requested_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "current"
            write_jsonl(
                run_dir / "results.jsonl",
                [
                    {
                        "input_id": "query-1",
                        "task_id": "task-1",
                        "candidate_count_total": 8,
                        "results": [candidate("c1", photo_payload="R" * 33000, rank_score=0.91)],
                    }
                ],
            )
            write_jsonl(run_dir / "failures.jsonl", [])
            metadata_path = root / "metadata.jsonl"
            write_jsonl(
                metadata_path,
                [
                    {
                        "query_id": "query-1",
                        "person_id": "person-1",
                        "query_type": "Q1",
                        "person_group": "C",
                        "difficulty": "medium",
                        "tags": ["common_name", "few_clues"],
                    }
                ],
            )
            output_path = root / "single.xlsx"
            model_path = root / "model.json"

            self.run_exporter(
                [
                    "single",
                    "--results-file",
                    str(run_dir / "results.jsonl"),
                    "--failures-file",
                    str(run_dir / "failures.jsonl"),
                    "--run-label",
                    "current",
                    "--system-version",
                    "v1",
                    "--evaluation-id",
                    "eval-1",
                    "--metadata",
                    str(metadata_path),
                    "--output",
                    str(output_path),
                ],
                model_path,
                create_workbook=True,
            )

            model = json.loads(model_path.read_text(encoding="utf-8"))
            row = model["candidateRows"][0]
            self.assertEqual("query-1", row["query_id"])
            self.assertEqual("person-1", row["person_id"])
            self.assertEqual(8, row["candidate_count_total"])
            self.assertEqual(1, row["candidate_rank"])
            self.assertEqual(0.91, row["rank_score"])
            self.assertEqual("Known public profile", row["insights_description"])
            self.assertEqual(
                "Evidence：https://example.test/evidence",
                row["insights_links"],
            )
            self.assertEqual("data", row["photos_status"])
            self.assertEqual("Example Person", row["profile.Identity.Full Name"])
            self.assertEqual("first\nsecond", row["social_display_handles"])
            self.assertEqual("linkedin\nx", row["social_platforms"])
            self.assertEqual("HIGH", row["summary_confidence_level"])
            self.assertEqual("https://example.test/primary.jpg", row["summary_primary_image_url"])
            self.assertEqual(
                "LinkedIn：https://linkedin.test/first",
                row["summary_social_links"],
            )
            self.assertEqual(
                "Official site：https://example.test/profile",
                row["summary_web_links"],
            )
            self.assertEqual(
                model["candidateHeaders"].index("task_id") + 1,
                model["candidateHeaders"].index("candidate_id"),
            )
            for removed_header in [
                "system_version",
                "person_group",
                "difficulty",
                "tags",
                "insights_data",
                "photos_data",
                "profile_data",
                "social_profiles",
                "summary_display_name",
                "identity_judgement",
                "review_comment",
            ]:
                self.assertNotIn(removed_header, model["candidateHeaders"])
            field_catalog = {item["当前表头"]: item for item in model["fieldCatalogRows"]}
            self.assertEqual("整数或空值", field_catalog["candidate_count_total"]["内容格式"])
            self.assertIn("ListTaskCandidates", field_catalog["rank_score"]["来源路径/生成规则"])
            self.assertEqual("是", field_catalog["rank_score"]["是否保留"])
            self.assertEqual("否", field_catalog["system_version"]["是否保留"])
            self.assertIn("title：url", field_catalog["insights_links"]["处理规则/备注"])
            self.assertTrue(output_path.is_file())
            with zipfile.ZipFile(output_path) as archive:
                self.assertIn("xl/workbook.xml", archive.namelist())
                workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
                self.assertIn("Raw数据", workbook_xml)

    def test_single_mode_reads_file_settings_from_env_file(self):
        """Explicit .env export settings can replace all single-mode file arguments."""

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "env-run"
            write_jsonl(
                run_dir / "20260722_tasks_v01_results.jsonl",
                [{"input_id": "query-env", "task_id": "task-env", "results": []}],
            )
            write_jsonl(run_dir / "20260722_tasks_v01_failures.jsonl", [])
            output_path = root / "from-env.xlsx"
            model_path = root / "model.json"
            env_path = root / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        f"EXCEL_RESULTS_FILE={run_dir / '20260722_tasks_v01_results.jsonl'}",
                        f"EXCEL_FAILURES_FILE={run_dir / '20260722_tasks_v01_failures.jsonl'}",
                        f"EXCEL_OUTPUT_FILE={output_path}",
                        "EXCEL_RUN_LABEL=current",
                        "EXCEL_SYSTEM_VERSION=v-env",
                        "EXCEL_EVALUATION_ID=eval-env",
                    ]
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["SEARCHTOOL_MODEL_OUTPUT"] = str(model_path)
            env["SEARCHTOOL_SKIP_WORKBOOK"] = "1"
            result = subprocess.run(
                [sys.executable, str(EXPORTER), "single", "--env-file", str(env_path)],
                cwd=PROJECT_ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )

            self.assertEqual(0, result.returncode, msg=result.stderr)
            model = json.loads(model_path.read_text(encoding="utf-8"))
            self.assertEqual("query-env", model["queryRows"][0]["query_id"])

    def test_compare_uses_union_of_profile_columns_and_aligns_queries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = root / "baseline"
            candidate_run = root / "candidate"
            write_jsonl(
                baseline / "results.jsonl",
                [{"input_id": "query-1", "task_id": "task-b", "results": [candidate("b1", "Full Name")]}],
            )
            write_jsonl(baseline / "failures.jsonl", [])
            write_jsonl(
                candidate_run / "results.jsonl",
                [{"input_id": "query-1", "task_id": "task-c", "results": [candidate("c1", "Location")]}],
            )
            write_jsonl(candidate_run / "failures.jsonl", [])
            output_path = root / "compare.xlsx"
            model_path = root / "model.json"

            self.run_exporter(
                [
                    "compare",
                    "--baseline-dir",
                    str(baseline),
                    "--baseline-version",
                    "base",
                    "--candidate-dir",
                    str(candidate_run),
                    "--candidate-version",
                    "next",
                    "--evaluation-id",
                    "eval-2",
                    "--output",
                    str(output_path),
                ],
                model_path,
            )

            model = json.loads(model_path.read_text(encoding="utf-8"))
            self.assertEqual(
                ["profile.Identity.Full Name", "profile.Identity.Location"],
                model["profileColumns"],
            )
            self.assertEqual(["baseline", "candidate"], [row["run_label"] for row in model["candidateRows"]])
            query_row = model["queryRows"][0]
            self.assertEqual("SUCCESS", query_row["baseline_status"])
            self.assertEqual("SUCCESS", query_row["candidate_status"])
            self.assertEqual(1, query_row["baseline_candidate_count"])
            self.assertEqual(1, query_row["candidate_candidate_count"])

    def test_long_json_is_split_and_reconstructable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "current"
            large_value = "中" * 70000
            write_jsonl(
                run_dir / "results.jsonl",
                [
                    {
                        "input_id": "query-long",
                        "task_id": "task-long",
                        "results": [candidate("long-candidate", photo_payload=large_value)],
                    }
                ],
            )
            output_path = root / "long.xlsx"
            model_path = root / "model.json"

            self.run_exporter(
                [
                    "single",
                    "--run-dir",
                    str(run_dir),
                    "--run-label",
                    "current",
                    "--system-version",
                    "v1",
                    "--evaluation-id",
                    "eval-long",
                    "--output",
                    str(output_path),
                ],
                model_path,
            )

            model = json.loads(model_path.read_text(encoding="utf-8"))
            raw_rows = [
                row
                for row in model["rawRows"]
                if row["field_name"] == "photos_authenticity_photos"
            ]
            self.assertEqual(3, len(raw_rows))
            self.assertTrue(all(len(row["content"]) <= 30000 for row in raw_rows))
            reconstructed = "".join(row["content"] for row in sorted(raw_rows, key=lambda row: row["chunk_index"]))
            expected = json.dumps(
                candidate("long-candidate", photo_payload=large_value)["ui_sections"]["photos"]["data"][
                    "authenticity_photos"
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            self.assertEqual(expected, reconstructed)
            self.assertTrue(
                model["candidateRows"][0]["photos_authenticity_photos"].startswith(
                    "[超长内容见 Raw数据] RAW:"
                )
            )


if __name__ == "__main__":
    unittest.main()

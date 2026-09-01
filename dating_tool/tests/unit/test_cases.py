import json
import tempfile
import unittest
from pathlib import Path

from aidating_eval.cases import load_cases
from aidating_eval.domain import EvaluationAnalysisCase, EvaluationReplyCase
from aidating_eval.errors import CaseValidationError


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cases"


def _messages(count: int, *, text: str = "hello") -> list[dict[str, str]]:
    """构造满足双方数量约束且 ID 唯一的字面测试消息。"""

    return [
        {
            "message_id": f"m{index + 1}",
            "message_type": "text",
            "speaker": "other" if index % 2 == 0 else "self",
            "text": text,
        }
        for index in range(count)
    ]


def _eval_case(kind: str, count: int = 4) -> dict[str, object]:
    case: dict[str, object] = {
        "schema_version": "aidating.eval.case.v1",
        "case_id": f"case-{kind}-{count}",
        "task_kind": kind,
        "locale": "en-US",
        "transcript": {
            "schema_version": "dating.transcript.v1",
            "messages": _messages(count),
        },
        "expect": {
            "task_status": "succeeded",
            "result_schema": (
                "dating.reply_generation.v1"
                if kind == "reply"
                else "dating.relationship_analysis.v1"
            ),
        },
    }
    if kind == "reply":
        case.update(
            dating_goal="serious_relationship",
            your_voice="warm_direct",
        )
    return case


def _write_jsonl(case: dict[str, object], directory: str) -> Path:
    path = Path(directory) / "cases.jsonl"
    path.write_text(json.dumps(case, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


class CaseLoaderTests(unittest.TestCase):
    """Case Loader 必须在网络调用前阻断越权字段和非法边界。"""

    def test_e2e_reply_resolves_media_inside_explicit_fixture_root(self):
        case = json.loads((FIXTURES / "e2e-reply-valid.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "media").mkdir()
            (root / "media" / "reply.png").write_bytes(b"fixture-placeholder")
            case["media"] = [{"path": "media/reply.png"}]
            path = root / "reply.json"
            path.write_text(json.dumps(case), encoding="utf-8")
            loaded = load_cases(path, "e2e", fixture_root=root)
        self.assertEqual("reply", loaded[0].task_kind)
        self.assertEqual("e2e-reply-valid", loaded[0].case_id)

    def test_eval_maps_self_to_user_and_counts_utf8_bytes(self):
        cases = load_cases(FIXTURES / "eval-mixed-valid.jsonl", "eval")
        reply = next(case for case in cases if case.task_kind == "reply")
        self.assertIsInstance(reply, EvaluationReplyCase)
        self.assertEqual("user", reply.messages[1].speaker)
        self.assertEqual(
            sum(len(message.text.encode("utf-8")) for message in reply.messages),
            reply.text_bytes,
        )

    def test_eval_rejects_reply_fields_on_analysis(self):
        for field, value in (
            ("background", "unsupported"),
            ("dating_goal", "serious_relationship"),
            ("your_voice", "warm_direct"),
            ("requested_intent", "flirt"),
        ):
            case = _eval_case("analysis")
            case[field] = value
            with tempfile.TemporaryDirectory() as directory:
                with self.subTest(field=field), self.assertRaises(CaseValidationError):
                    load_cases(_write_jsonl(case, directory), "eval")

    def test_eval_message_count_boundaries_are_exact(self):
        for kind, valid_counts, invalid_counts in (
            ("reply", (4, 300), (3, 301)),
            ("analysis", (4, 301, 500), (3, 501)),
        ):
            for count in valid_counts:
                with tempfile.TemporaryDirectory() as directory:
                    loaded = load_cases(
                        _write_jsonl(_eval_case(kind, count), directory), "eval"
                    )
                self.assertEqual(count, len(loaded[0].messages))
            for count in invalid_counts:
                with tempfile.TemporaryDirectory() as directory:
                    with self.subTest(kind=kind, count=count), self.assertRaises(
                        CaseValidationError
                    ):
                        load_cases(
                            _write_jsonl(_eval_case(kind, count), directory), "eval"
                        )

    def test_analysis_single_message_utf8_limit_is_exact(self):
        for size, valid in ((4096, True), (4097, False)):
            case = _eval_case("analysis")
            case["transcript"]["messages"][0]["text"] = "a" * size
            with tempfile.TemporaryDirectory() as directory:
                path = _write_jsonl(case, directory)
                if valid:
                    loaded = load_cases(path, "eval")
                    self.assertIsInstance(loaded[0], EvaluationAnalysisCase)
                else:
                    with self.assertRaises(CaseValidationError):
                        load_cases(path, "eval")

    def test_reply_background_and_intent_constraints(self):
        case = _eval_case("reply")
        case["background"] = "a" * 1000
        case["requested_intent"] = "advance"
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(1, len(load_cases(_write_jsonl(case, directory), "eval")))

        for mutation in (
            {"background": "a" * 1001},
            {"requested_intent": "manipulate"},
        ):
            invalid = _eval_case("reply")
            invalid.update(mutation)
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(CaseValidationError):
                    load_cases(_write_jsonl(invalid, directory), "eval")

    def test_duplicate_ids_and_insufficient_party_messages_are_rejected(self):
        duplicate = _eval_case("analysis")
        duplicate["transcript"]["messages"][1]["message_id"] = "m1"
        insufficient = _eval_case("analysis")
        insufficient["transcript"]["messages"][1]["speaker"] = "other"
        insufficient["transcript"]["messages"][3]["speaker"] = "other"
        for case in (duplicate, insufficient):
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(CaseValidationError):
                    load_cases(_write_jsonl(case, directory), "eval")

    def test_reserved_and_unknown_fields_are_rejected(self):
        for field in ("model", "prompt", "app_id", "user_id", "service_name", "method_name"):
            case = _eval_case("reply")
            case[field] = "forbidden"
            with tempfile.TemporaryDirectory() as directory:
                with self.subTest(field=field), self.assertRaises(CaseValidationError):
                    load_cases(_write_jsonl(case, directory), "eval")

    def test_public_reply_requires_preferences(self):
        case = json.loads((FIXTURES / "e2e-reply-valid.json").read_text())
        del case["preferences"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reply.json"
            path.write_text(json.dumps(case), encoding="utf-8")
            with self.assertRaises(CaseValidationError):
                load_cases(path, "e2e", fixture_root=Path(directory))

    def test_controlled_negative_requires_matching_stable_error(self):
        case = _eval_case("reply")
        case["negative_variant"] = "message_count_below_min"
        case["expect"] = {
            "task_status": None,
            "result_schema": None,
            "business_error_code": "INPUT_INVALID",
        }
        with tempfile.TemporaryDirectory() as directory:
            loaded = load_cases(_write_jsonl(case, directory), "eval")
        self.assertEqual("message_count_below_min", loaded[0].negative_variant)

        invalid = _eval_case("reply")
        invalid["negative_variant"] = "raw_payload"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CaseValidationError):
                load_cases(_write_jsonl(invalid, directory), "eval")

    def test_e2e_rejects_media_outside_fixture_root(self):
        with self.assertRaises(CaseValidationError):
            load_cases(
                FIXTURES / "e2e-path-traversal.json",
                "e2e",
                fixture_root=FIXTURES / "media",
            )

    def test_case_ids_must_be_unique_and_path_safe(self):
        one = _eval_case("reply")
        two = _eval_case("analysis")
        two["case_id"] = one["case_id"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicates.jsonl"
            path.write_text(
                "\n".join(json.dumps(item) for item in (one, two)) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(CaseValidationError):
                load_cases(path, "eval")

        unsafe = _eval_case("reply")
        unsafe["case_id"] = "../escape"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CaseValidationError):
                load_cases(_write_jsonl(unsafe, directory), "eval")


if __name__ == "__main__":
    unittest.main()

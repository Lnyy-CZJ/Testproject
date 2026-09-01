import json
from pathlib import Path
import tempfile
import unittest
from io import BytesIO

from PIL import Image

from aidating_eval.application import RunApplicationService
from aidating_eval.web.input_store import DraftRecord, WebInputStore


class WebInputStoreTests(unittest.TestCase):
    def test_creates_private_e2e_draft_with_ordered_media_and_case(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WebInputStore(Path(directory) / "drafts")
            draft = store.create_e2e_draft(
                task_kind="analysis",
                locale="en-US",
                media=(
                    ("first.png", b"png-one"),
                    ("second.jpg", b"jpg-two"),
                ),
                case_options={"other_person_name": "Alex", "background": "Met twice."},
            )

            self.assertIsInstance(draft, DraftRecord)
            self.assertEqual("e2e", draft.mode)
            self.assertEqual("analysis", draft.task_kind)
            self.assertTrue(draft.dataset_path.is_file())
            self.assertEqual(2, len(draft.media_paths))
            self.assertEqual("first.png", draft.media_paths[0].name.split("-", 1)[-1])
            self.assertEqual(0o700, draft.root.stat().st_mode & 0o777)
            self.assertEqual(0o600, draft.dataset_path.stat().st_mode & 0o777)
            payload = json.loads(draft.dataset_path.read_text(encoding="utf-8"))
            self.assertEqual("aidating.e2e.case.v1", payload["schema_version"])
            self.assertEqual("analysis", payload["task_kind"])
            self.assertEqual("media/0001-first.png", payload["media"][0]["path"])
            self.assertEqual("media/0002-second.jpg", payload["media"][1]["path"])

    def test_eval_draft_claim_is_atomic_and_delete_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WebInputStore(Path(directory) / "drafts")
            draft = store.create_eval_draft(
                b'{"schema_version":"aidating.eval.case.v1"}\n',
                filename="cases.jsonl",
                case_id="case-1",
                eval_concurrency=4,
            )
            claimed = store.claim(draft.draft_id)
            self.assertEqual(draft.draft_id, claimed.draft_id)
            with self.assertRaises(ValueError):
                store.claim(draft.draft_id)
            store.delete(draft.draft_id)
            store.delete(draft.draft_id)
            with self.assertRaises(ValueError):
                store.get(draft.draft_id)

    def test_rejects_unsafe_names_and_stale_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WebInputStore(Path(directory) / "drafts")
            with self.assertRaises(ValueError):
                store.create_eval_draft(b"{}\n", filename="../escape.jsonl")
            outside = Path(directory) / "outside"
            outside.mkdir()
            (Path(directory) / "drafts").mkdir(parents=True, exist_ok=True)
            (Path(directory) / "drafts" / "draft-link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                store.get("draft-link")

    def test_generated_e2e_fixture_is_accepted_by_shared_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            stream = BytesIO()
            Image.new("RGB", (64, 64), "white").save(stream, format="PNG")
            store = WebInputStore(Path(directory) / "drafts")
            draft = store.create_e2e_draft(
                task_kind="analysis",
                locale="en-US",
                media=(("chat.png", stream.getvalue()),),
            )
            summary = RunApplicationService().validate(
                __import__("aidating_eval.application", fromlist=["RunRequest"]).RunRequest(
                    mode="e2e",
                    dataset_path=draft.dataset_path,
                    fixture_root=draft.fixture_root,
                )
            )
            self.assertEqual(1, summary.case_count)
            self.assertEqual(1, summary.media_count)


if __name__ == "__main__":
    unittest.main()

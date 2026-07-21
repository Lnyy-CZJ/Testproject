import tempfile
import unittest
from pathlib import Path

from trackevents_web import HTML, resolve_log_text


class TrackEventsWebTest(unittest.TestCase):
    def test_resolve_log_text_reads_default_log_when_payload_is_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            default_log = Path(tmpdir) / "default.log"
            default_log.write_text("default log content", encoding="utf-8")

            self.assertEqual(resolve_log_text("", default_log), "default log content")

    def test_resolve_log_text_uses_uploaded_log_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            default_log = Path(tmpdir) / "default.log"
            default_log.write_text("default log content", encoding="utf-8")

            self.assertEqual(resolve_log_text("uploaded log content", default_log), "uploaded log content")

    def test_web_page_has_paste_input_and_paste_takes_priority(self):
        self.assertIn('id="logText"', HTML)
        self.assertIn("const pastedLog = logTextInput.value", HTML)
        self.assertIn("hasPastedLog ? pastedLog : (file ? await file.text() : '')", HTML)

    def test_event_details_has_action_filter(self):
        self.assertIn('id="moduleFilter"', HTML)
        self.assertIn('id="actionFilter"', HTML)
        self.assertIn("addEventListener('change', applyFilters)", HTML)
        self.assertNotIn('id="applyActionFilter"', HTML)

    def test_event_details_shows_extra_field_values(self):
        self.assertIn('item.extra_params', HTML)
        self.assertIn('疑似多传字段值：', HTML)

    def test_web_page_has_common_param_check_panel(self):
        self.assertIn('id="commonParamsPanel"', HTML)
        self.assertIn('data.common_param_summary', HTML)
        self.assertIn('公参实际值', HTML)
        self.assertIn('缺失必填公参', HTML)

    def test_expected_counts_support_line_format(self):
        self.assertIn('function parseExpectedCounts(text)', HTML)
        self.assertIn("const match = value.match(/^(.+?)(\\d+)?$/)", HTML)
        self.assertIn("counts[action] = match[2] ? Number(match[2]) : 1", HTML)


if __name__ == "__main__":
    unittest.main()

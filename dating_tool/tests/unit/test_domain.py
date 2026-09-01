import unittest

from aidating_eval.domain import DoctorStatus


class DomainTypeTests(unittest.TestCase):
    def test_doctor_status_members_are_distinct_string_enums(self):
        self.assertFalse(DoctorStatus.PASS == DoctorStatus.FAIL)
        self.assertFalse(DoctorStatus.FAIL == DoctorStatus.DEFERRED)
        self.assertEqual("PASS", DoctorStatus.PASS)
        self.assertEqual("PASS", str(DoctorStatus.PASS))
        self.assertIn("DoctorStatus.PASS", repr(DoctorStatus.PASS))


if __name__ == "__main__":
    unittest.main()

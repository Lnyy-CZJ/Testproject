# 核心断言逻辑
from utils.log import Log
class AssertCore:
    @staticmethod
    def assert_equal(actual, expected, msg=""):
        if actual == expected:
            Log.info(f"[ASSERT PASS] {actual} == {expected}")
        else:
            Log.error(f"[ASSERT FAIL] {actual} != {expected} | {msg}")
            assert actual == expected, msg or f"{actual} != {expected}"

    @staticmethod
    def assert_in(member, container, msg=""):
        if member in container:
            Log.info(f"[ASSERT PASS] {member} in {container}")
        else:
            Log.error(f"[ASSERT FAIL] {member} not in {container} | {msg}")
            assert member in container, msg or f"{member} not in {container}"

    @staticmethod
    def assert_true(condition, msg=""):
        if condition:
            Log.info("[ASSERT PASS] condition is True")
        else:
            Log.error(f"[ASSERT FAIL] condition is False | {msg}")
            assert condition, msg or "Condition is False"
from utils.asserts.assert_core import AssertCore
from utils.asserts.soft_assert import SoftAssert
from utils.log import Log
class AssertManager:

    def __init__(self, soft=False):
        self.soft = soft
        self.soft_assert = SoftAssert() if soft else None
        Log.info(f"[AssertManager INIT] soft={self.soft}")

    def equal(self, actual, expected, msg=""):
        desc = msg or f"{actual} == {expected}"

        if self.soft:
            self.soft_assert.check(actual == expected, desc)
        else:
            AssertCore.assert_equal(actual, expected, desc)

    def contains(self, member, container, msg=""):
        desc = msg or f"{member} in {container}"

        if self.soft:
            self.soft_assert.check(member in container, desc)
        else:
            AssertCore.assert_in(member, container, desc)

    def is_true(self, condition, msg=""):
        desc = msg or "condition is True"

        if self.soft:
            self.soft_assert.check(condition, desc)
        else:
            AssertCore.assert_true(condition, desc)

    def assert_all(self):
        if self.soft:
            Log.info("[AssertManager] assert_all triggered")
            self.soft_assert.assert_all()


#使用示例（接口自动化）
"""
def test_api_login():
    resp = {
        "code": 200,
        "msg": "success",
        "data": {"token": "abc123"}
    }

    am = AssertManager(soft=True)

    am.equal(resp["code"], 200, "状态码错误")
    am.equal(resp["msg"], "success")
    am.contains("token", resp["data"])

    # 即使上面失败，也会继续执行
    am.assert_all()
"""
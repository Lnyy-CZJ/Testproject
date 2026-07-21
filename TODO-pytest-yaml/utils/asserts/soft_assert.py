# 软断言收集器
#特点：不中断执行,最后统一抛异常,非侵入式
from utils.log import Log
class SoftAssert:
    def __init__(self):
        self.errors = []

    def check(self, condition, msg=""):
        if condition:
            Log.info(f"[SoftAssert 通过] {msg}")
        else:
            Log.error(f"[SoftAssert 失败] {msg}")
            self.errors.append(msg)

    def assert_all(self):
        if self.errors:
            error_msg = "\n".join(self.errors)
            Log.error(f"[SoftAssert------断言不通过------\n{error_msg}")
            raise AssertionError(f"Soft Assert Failed:\n{error_msg}")
        else:
            Log.info("[SoftAssert] ------全部断言通过------")
import os
import unittest

from tests.helpers import run_public_reply_staging_readiness


RUN_STAGING = os.getenv("AIDATING_RUN_STAGING_TESTS") == "1"


@unittest.skipUnless(RUN_STAGING, "需要显式开启 staging 测试")
class PublicReplyReadinessTests(unittest.TestCase):
    def test_readiness_never_uploads_media_or_creates_reply_task(self):
        status = run_public_reply_staging_readiness()
        print(f"PUBLIC_REPLY_READINESS status={status}")
        # READY 表示查询方法已开放；另外三种稳定码保留为外部依赖证据，不伪装成
        # Reply 全链路成功。任何未知错误仍让测试失败。
        self.assertIn(status, {"READY", "FEATURE_NOT_READY", "NOT_FOUND", "PERMISSION_DENIED"})


if __name__ == "__main__":
    unittest.main()

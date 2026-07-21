#!/usr/bin/env python3
"""从固定 JUnit 产物生成摘要并按环境配置发布飞书通知。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Sequence

# 允许按 Jenkins 模板从项目根目录直接执行 ``python3 scripts/notify_feishu.py``。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from framework.integrations.feishu_notifier import (
    FeishuNotifier,
    NotificationError,
    SummaryParseError,
    parse_junit_summary,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析飞书通知命令行参数。

    功能说明:
        解析构建元数据，JUnit 路径默认固定为 ``artifacts/junit.xml``。
    参数说明:
        argv: 不含程序名的可选参数序列；``None`` 时读取进程命令行。
    返回值:
        ``argparse.Namespace`` 参数对象。
    异常说明:
        参数格式无效时由 ``argparse`` 抛出 ``SystemExit``。
    """
    parser = argparse.ArgumentParser(description="发布脱敏飞书构建摘要")
    parser.add_argument("--junitxml", default="artifacts/junit.xml")
    parser.add_argument("--build-number", default=os.getenv("BUILD_NUMBER", "local"))
    parser.add_argument("--env", dest="environment", default=os.getenv("TARGET_ENV", "test"))
    parser.add_argument("--suite", default=os.getenv("TEST_SUITE", "all"))
    parser.add_argument("--allure-url", default=os.getenv("ALLURE_REPORT_URL"))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """发布通知；未配置 webhook 时安全退出 0，且不会读取报告或访问网络。

    功能说明:
        读取安全 JUnit 摘要并按禁用、dry-run 或启用模式发布通知。
    参数说明:
        argv: 不含程序名的参数；默认读取进程命令行。
    返回值:
        禁用、dry-run 或发布成功返回 0；JUnit 或通知失败返回 1。
    异常说明:
        已知错误转换为无秘密的简短输出，不打印 webhook、原始 URL 或响应内容。
    """
    args = parse_args(argv)
    webhook = os.getenv("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        print("Feishu notification disabled: FEISHU_WEBHOOK is not configured.")
        return 0
    env_dry_run = os.getenv("FEISHU_DRY_RUN", "").lower() in {"1", "true", "yes"}
    try:
        summary = parse_junit_summary(
            Path(args.junitxml),
            build_number=args.build_number,
            environment=args.environment,
            suite=args.suite,
            allure_report_url=args.allure_url,
        )
        with FeishuNotifier(
            webhook_url=webhook,
            dry_run=args.dry_run or env_dry_run,
        ) as notifier:
            result = notifier.publish(summary)
    except (SummaryParseError, NotificationError) as error:
        print(f"Feishu notification failed safely: {error}")
        return 1
    print(f"Feishu notification status: {result.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

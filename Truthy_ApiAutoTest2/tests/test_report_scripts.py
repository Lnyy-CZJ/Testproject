"""报告发布与 Jenkins 拉取脚本自测（设计 16 阶段 4、17.4）。

功能说明:
    通过子进程调用 scripts/publish_allure_report.sh 与
    scripts/fetch_jenkins_report.sh，覆盖原子发布、锁、中断残留清理、
    版本切换以及 Jenkins HTTP API 构建选择逻辑。全部用例基于临时目录
    与本地假 Jenkins 服务，不访问真实网络。
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLISH_SCRIPT = PROJECT_ROOT / "scripts" / "publish_allure_report.sh"
FETCH_SCRIPT = PROJECT_ROOT / "scripts" / "fetch_jenkins_report.sh"


def make_report_source(tmp_path: Path, name: str = "src") -> Path:
    """构造一个最小可用的 Allure HTML 报告源目录（含 index.html）。"""

    source = tmp_path / name
    source.mkdir(parents=True, exist_ok=True)
    (source / "index.html").write_text("<html><body>report</body></html>", encoding="utf-8")
    (source / "app.js").write_text("// asset", encoding="utf-8")
    return source


def run_publish(
    source: Path,
    report_root: Path,
    source_kind: str = "manual",
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """调用发布脚本并返回进程结果。"""

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [str(PUBLISH_SCRIPT), str(source), str(report_root), source_kind],
        env=merged_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def current_target(report_root: Path) -> Path:
    """返回 allure-current 符号链接指向的绝对路径。"""

    return (report_root / "allure-current").resolve()


# ---------------- 发布脚本：基础发布 ----------------


def test_publish_normal_source_creates_version_and_current(tmp_path: Path) -> None:
    source = make_report_source(tmp_path)
    report_root = tmp_path / "reports"

    result = run_publish(source, report_root)

    assert result.returncode == 0, result.stderr
    version = result.stdout.strip()
    assert version.startswith("manual-")
    version_dir = report_root / "allure-reports" / version
    assert (version_dir / "index.html").is_file()
    assert (report_root / "allure-current").is_symlink()
    assert current_target(report_root) == version_dir.resolve()
    meta = json.loads((version_dir / "report-meta.json").read_text(encoding="utf-8"))
    assert meta["source"] == "manual"
    assert meta["generated_at"]
    assert meta["allure_version"] == "unknown"


def test_publish_jenkins_source_writes_build_meta(tmp_path: Path) -> None:
    source = make_report_source(tmp_path)
    report_root = tmp_path / "reports"

    result = run_publish(
        source,
        report_root,
        "jenkins",
        env={
            "PUBLISH_JOB_NAME": "truthy-api-autotest",
            "PUBLISH_BUILD_NUMBER": "14",
            "PUBLISH_BUILD_RESULT": "FAILURE",
            "PUBLISH_BUILD_URL": "http://jenkins/job/truthy-api-autotest/14/",
            "PUBLISH_ALLURE_VERSION": "3.14.3",
        },
    )

    assert result.returncode == 0, result.stderr
    version = result.stdout.strip()
    assert version == "jenkins-truthy-api-autotest-14"
    meta = json.loads(
        (report_root / "allure-reports" / version / "report-meta.json").read_text(
            encoding="utf-8"
        )
    )
    assert meta["source"] == "jenkins"
    assert meta["job_name"] == "truthy-api-autotest"
    assert meta["build_number"] == 14
    assert isinstance(meta["build_number"], int)
    assert meta["build_result"] == "FAILURE"
    assert meta["build_url"] == "http://jenkins/job/truthy-api-autotest/14/"
    assert meta["allure_version"] == "3.14.3"


def test_publish_rejects_source_without_index_html(tmp_path: Path) -> None:
    source = tmp_path / "empty-src"
    source.mkdir()
    report_root = tmp_path / "reports"

    result = run_publish(source, report_root)

    assert result.returncode == 2
    assert not (report_root / "allure-current").exists()


def test_publish_rejects_invalid_source_kind(tmp_path: Path) -> None:
    source = make_report_source(tmp_path)
    report_root = tmp_path / "reports"

    result = run_publish(source, report_root, "jenkinss")

    assert result.returncode == 2


# ---------------- 发布脚本：版本切换与旧版本清理 ----------------


def test_second_publish_switches_current_and_removes_old_version(
    tmp_path: Path,
) -> None:
    report_root = tmp_path / "reports"
    first = run_publish(make_report_source(tmp_path, "src1"), report_root)
    assert first.returncode == 0, first.stderr
    first_version = first.stdout.strip()

    second = run_publish(make_report_source(tmp_path, "src2"), report_root)
    assert second.returncode == 0, second.stderr
    second_version = second.stdout.strip()
    assert second_version != first_version

    # 只保留 current 指向的一份（确认项 6）。
    versions = list((report_root / "allure-reports").iterdir())
    assert [p.name for p in versions] == [second_version]
    assert current_target(report_root) == (
        report_root / "allure-reports" / second_version
    ).resolve()


def test_republish_same_jenkins_build_replaces_version(tmp_path: Path) -> None:
    report_root = tmp_path / "reports"
    env = {
        "PUBLISH_JOB_NAME": "truthy-api-autotest",
        "PUBLISH_BUILD_NUMBER": "9",
        "PUBLISH_BUILD_RESULT": "FAILURE",
        "PUBLISH_BUILD_URL": "http://jenkins/9/",
    }
    first = run_publish(make_report_source(tmp_path, "src1"), report_root, "jenkins", env)
    assert first.returncode == 0, first.stderr
    # 切换前先发布第二份（占住 current），再重复发布同一构建号，
    # 验证同名版本替换不产生 404 空窗且旧内容被清理。
    second = run_publish(make_report_source(tmp_path, "src2"), report_root)
    assert second.returncode == 0, second.stderr

    third = run_publish(make_report_source(tmp_path, "src3"), report_root, "jenkins", env)
    assert third.returncode == 0, third.stderr
    assert third.stdout.strip() == "jenkins-truthy-api-autotest-9"

    versions = sorted(p.name for p in (report_root / "allure-reports").iterdir())
    assert versions == ["jenkins-truthy-api-autotest-9"]
    assert current_target(report_root) == (
        report_root / "allure-reports" / "jenkins-truthy-api-autotest-9"
    ).resolve()


def test_legacy_real_directory_current_is_migrated(tmp_path: Path) -> None:
    report_root = tmp_path / "reports"
    legacy = report_root / "allure-current"
    legacy.mkdir(parents=True)
    (legacy / "index.html").write_text("legacy", encoding="utf-8")

    result = run_publish(make_report_source(tmp_path), report_root)

    assert result.returncode == 0, result.stderr
    assert (report_root / "allure-current").is_symlink()
    # 历史实体目录与临时产物均被清理。
    assert not list(report_root.glob(".legacy-current.*"))


# ---------------- 发布脚本：锁与并发 ----------------


def test_publish_fails_fast_when_lock_is_held(tmp_path: Path) -> None:
    report_root = tmp_path / "reports"
    report_root.mkdir(parents=True)
    lock = report_root / ".publish.lock"
    lock.mkdir()

    result = run_publish(make_report_source(tmp_path), report_root)

    assert result.returncode == 3
    assert not (report_root / "allure-current").exists()


def test_stale_lock_is_reclaimed(tmp_path: Path) -> None:
    report_root = tmp_path / "reports"
    report_root.mkdir(parents=True)
    lock = report_root / ".publish.lock"
    lock.mkdir()
    # 残留锁超过安全时间（600s）后允许回收。
    stale = time.time() - 700
    os.utime(lock, (stale, stale))

    result = run_publish(make_report_source(tmp_path), report_root)

    assert result.returncode == 0, result.stderr
    assert not lock.exists()


def test_concurrent_publish_keeps_current_consistent(tmp_path: Path) -> None:
    report_root = tmp_path / "reports"
    source = make_report_source(tmp_path)

    def publish_once() -> subprocess.CompletedProcess:
        return run_publish(source, report_root)

    threads = [threading.Thread(target=lambda: results.append(publish_once())) for _ in range(2)]
    results: list[subprocess.CompletedProcess] = []
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    codes = sorted(r.returncode for r in results)
    # 锁串行化：要么先后都成功（0,0），要么一个拿到锁成功另一个快速失败（0,3）。
    assert codes in ([0, 0], [0, 3]), codes
    assert (report_root / "allure-current").is_symlink()
    assert (current_target(report_root) / "index.html").is_file()
    # 无论谁赢，最终只保留一份版本目录。
    assert len(list((report_root / "allure-reports").iterdir())) == 1


# ---------------- 发布脚本：中断残留清理 ----------------


def test_stale_staging_dirs_from_interrupted_publish_are_cleaned(
    tmp_path: Path,
) -> None:
    report_root = tmp_path / "reports"
    first = run_publish(make_report_source(tmp_path, "src1"), report_root)
    assert first.returncode == 0, first.stderr
    first_version = first.stdout.strip()

    # 模拟一次中断发布留下的暂存目录（足够旧才会被清理）。
    stale_tmp = report_root / "allure-reports" / ".manual-interrupted.tmp"
    stale_tmp.mkdir(parents=True)
    (stale_tmp / "index.html").write_text("half", encoding="utf-8")
    stale_time = time.time() - 4000
    os.utime(stale_tmp, (stale_time, stale_time))

    second = run_publish(make_report_source(tmp_path, "src2"), report_root)
    assert second.returncode == 0, second.stderr
    second_version = second.stdout.strip()

    assert not stale_tmp.exists()
    versions = sorted(p.name for p in (report_root / "allure-reports").iterdir())
    assert versions == [second_version]
    assert first_version != second_version


def test_interrupted_publish_never_breaks_existing_current(
    tmp_path: Path,
) -> None:
    report_root = tmp_path / "reports"
    first = run_publish(make_report_source(tmp_path, "src1"), report_root)
    assert first.returncode == 0, first.stderr
    first_version = first.stdout.strip()

    # 启动一次发布并立即终止，模拟切换前中断；旧 current 必须保持可用。
    process = subprocess.Popen(
        [str(PUBLISH_SCRIPT), str(make_report_source(tmp_path, "src2")), str(report_root), "manual"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        process.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        # 脚本可能在信号送达前已自然结束，不影响本用例断言。
        pass
    process.wait(timeout=10)

    assert (report_root / "allure-current").is_symlink()
    assert (current_target(report_root) / "index.html").is_file()

    # 后续发布仍能正常进行（锁未泄漏或可回收）。
    third = run_publish(make_report_source(tmp_path, "src3"), report_root)
    if third.returncode == 3:
        # 极端情况：SIGTERM 时锁尚未释放且未超龄；人为回收后重试。
        lock = report_root / ".publish.lock"
        stale = time.time() - 700
        os.utime(lock, (stale, stale))
        third = run_publish(make_report_source(tmp_path, "src3"), report_root)
    assert third.returncode == 0, third.stderr


# ---------------- fetch 脚本：假 Jenkins HTTP API ----------------

ARTIFACT_DIR = "allure-report-publish"
ARTIFACT_ENTRY = f"{ARTIFACT_DIR}/index.html"


def build_report_zip() -> bytes:
    """构造包含 allure-report-publish/index.html 的归档 zip。"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{ARTIFACT_DIR}/index.html", "<html><body>jenkins report</body></html>"
        )
        archive.writestr(f"{ARTIFACT_DIR}/app.js", "// asset")
    return buffer.getvalue()


class FakeJenkinsHandler(BaseHTTPRequestHandler):
    """最小 Jenkins JSON API 替身：构建列表、构建详情、归档下载。"""

    # 由测试按用例覆写：{构建号: {"result": ..., "has_report": bool}}
    builds: dict = {}

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        """静默默认访问日志，避免污染测试输出。"""

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        # 真实 Jenkins 匿名访问返回 403：这里同样要求 Basic 认证。
        if not self.headers.get("Authorization", "").startswith("Basic "):
            self.send_response(403)
            self.end_headers()
            return

        path = self.path.split("?")[0]
        parts = [p for p in path.split("/") if p]

        if path == "/job/truthy-api-autotest/api/json":
            self._send_json(
                {
                    "builds": [
                        {
                            "number": number,
                            "result": info["result"],
                            "url": f"http://fake/job/truthy-api-autotest/{number}/",
                        }
                        for number, info in sorted(
                            self.builds.items(), reverse=True
                        )
                    ]
                }
            )
            return

        # /job/<job>/<n>/api/json：构建详情（归档清单或 result/url）。
        if (
            len(parts) == 5
            and parts[0] == "job"
            and parts[2].isdigit()
            and parts[3] == "api"
            and parts[4] == "json"
        ):
            number = int(parts[2])
            info = self.builds.get(number)
            if info is None:
                self.send_response(404)
                self.end_headers()
                return
            if "artifacts" in self.path:
                artifacts = (
                    [{"relativePath": ARTIFACT_ENTRY}] if info["has_report"] else []
                )
                self._send_json({"artifacts": artifacts})
            else:
                self._send_json(
                    {
                        "result": info["result"],
                        "url": f"http://fake/job/truthy-api-autotest/{number}/",
                    }
                )
            return

        # /job/<job>/<n>/artifact/...zip：归档打包下载。
        if (
            parts[0] == "job"
            and len(parts) >= 4
            and parts[2].isdigit()
            and parts[3] == "artifact"
            and path.endswith(".zip")
        ):
            number = int(parts[2])
            info = self.builds.get(number)
            if info and info["has_report"]:
                body = build_report_zip()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(404)
        self.end_headers()


@pytest.fixture()
def fake_jenkins():
    """启动本地假 Jenkins 服务，返回 (base_url, handler_class)。"""

    handler = type("ConfiguredFakeJenkins", (FakeJenkinsHandler,), {"builds": {}})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", handler
    server.shutdown()
    server.server_close()


def run_fetch(
    base_url: str,
    report_root: Path,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    merged_env = os.environ.copy()
    merged_env.update(
        {
            "JENKINS_URL": base_url,
            "JENKINS_USER": "fake-user",
            "JENKINS_TOKEN": "fake-token",
        }
    )
    if env:
        merged_env.update(env)
    return subprocess.run(
        [str(FETCH_SCRIPT), str(report_root)],
        env=merged_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_fetch_selects_newest_completed_build_with_artifact(
    tmp_path: Path, fake_jenkins
) -> None:
    base_url, handler = fake_jenkins
    # 15 仍在进行（result=None 跳过）、14 失败但有报告、13 成功有报告。
    handler.builds = {
        15: {"result": None, "has_report": False},
        14: {"result": "FAILURE", "has_report": True},
        13: {"result": "SUCCESS", "has_report": True},
    }

    result = run_fetch(base_url, tmp_path / "reports")

    assert result.returncode == 0, result.stderr
    meta_path = (
        tmp_path / "reports" / "allure-reports" / "jenkins-truthy-api-autotest-14"
        / "report-meta.json"
    )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # 不按 SUCCESS/FAILURE 过滤：失败构建的报告同样应被选中。
    assert meta["build_number"] == 14
    assert meta["build_result"] == "FAILURE"
    assert (tmp_path / "reports" / "allure-current" / "index.html").is_file()


def test_fetch_skips_builds_without_report_artifact(tmp_path: Path, fake_jenkins) -> None:
    base_url, handler = fake_jenkins
    handler.builds = {
        20: {"result": "UNSTABLE", "has_report": False},
        19: {"result": "SUCCESS", "has_report": True},
    }

    result = run_fetch(base_url, tmp_path / "reports")

    assert result.returncode == 0, result.stderr
    meta = json.loads(
        (
            tmp_path / "reports" / "allure-reports"
            / "jenkins-truthy-api-autotest-19" / "report-meta.json"
        ).read_text(encoding="utf-8")
    )
    assert meta["build_number"] == 19
    assert meta["build_result"] == "SUCCESS"


def test_fetch_explicit_build_number_overrides_scan(tmp_path: Path, fake_jenkins) -> None:
    base_url, handler = fake_jenkins
    handler.builds = {
        14: {"result": "FAILURE", "has_report": True},
        13: {"result": "SUCCESS", "has_report": True},
    }

    result = run_fetch(base_url, tmp_path / "reports", env={"BUILD_NUMBER": "13"})

    assert result.returncode == 0, result.stderr
    meta = json.loads(
        (
            tmp_path / "reports" / "allure-reports"
            / "jenkins-truthy-api-autotest-13" / "report-meta.json"
        ).read_text(encoding="utf-8")
    )
    assert meta["build_number"] == 13


def test_fetch_fails_when_no_build_has_report(tmp_path: Path, fake_jenkins) -> None:
    base_url, handler = fake_jenkins
    handler.builds = {
        21: {"result": "SUCCESS", "has_report": False},
    }

    result = run_fetch(base_url, tmp_path / "reports")

    assert result.returncode == 5
    assert not (tmp_path / "reports" / "allure-current").exists()


def test_fetch_fails_when_credentials_missing(tmp_path: Path, fake_jenkins) -> None:
    base_url, _ = fake_jenkins

    env = os.environ.copy()
    env.update({"JENKINS_URL": base_url})
    env.pop("JENKINS_USER", None)
    env.pop("JENKINS_TOKEN", None)
    result = subprocess.run(
        [str(FETCH_SCRIPT), str(tmp_path / "reports")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 2

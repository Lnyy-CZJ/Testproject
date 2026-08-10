"""用例库清单（catalog）单元测试。

功能说明:
    真实项目快照验证 API/Case/Flow 三类清单可完整解析；伪造项目验证
    空目录与坏 Flow 文件只进入 errors 数组而不导致整体失败。
    全部为只读解析，不发真实请求。
"""

from __future__ import annotations

from pathlib import Path

from web.catalog import build_catalog


class TestRealProjectSnapshot:
    """真实 data/ 目录快照：既有框架数据必须可被完整解析。"""

    def test_snapshot_parses_without_errors(self, project_root: Path):
        snapshot = build_catalog(project_root)
        assert snapshot["errors"] == []

    def test_apis_listed_with_route_fields(self, project_root: Path):
        snapshot = build_catalog(project_root)
        assert len(snapshot["apis"]) >= 14
        api_ids = {api["id"] for api in snapshot["apis"]}
        assert "CreateAnonymousSession" in api_ids
        assert "GetMe" in api_ids
        for api in snapshot["apis"]:
            assert api["id"]
            assert isinstance(api["service_name"], str)
            assert isinstance(api["method_name"], str)

    def test_cases_listed_with_tags(self, project_root: Path):
        snapshot = build_catalog(project_root)
        assert len(snapshot["cases"]) >= 5
        for single_case in snapshot["cases"]:
            assert single_case["api"]
            assert single_case["id"]
            assert single_case["name"]
            assert isinstance(single_case["tags"], list)

    def test_flows_listed_with_steps(self, project_root: Path):
        snapshot = build_catalog(project_root)
        flow_names = {flow["name"] for flow in snapshot["flows"]}
        assert {
            "AnonymousSessionMediaSearch",
            "NameWithConditionsSearch",
            "NameWithConditionsAndPhotoSearch",
        } <= flow_names
        for flow in snapshot["flows"]:
            assert flow["step_count"] > 0
            assert isinstance(flow["apis"], list)


class TestErrorIsolation:
    """错误隔离：局部问题只产生错误条目，不阻断整体清单。"""

    def test_empty_data_dirs_produce_directory_level_errors(
        self, fake_project: Path
    ):
        snapshot = build_catalog(fake_project)
        files = {error["file"] for error in snapshot["errors"]}
        # 空 apis/cases 目录由加载器拒绝，呈现为目录级错误条目。
        assert "data/apis/" in files
        assert "data/cases/" in files
        assert snapshot["apis"] == []
        assert snapshot["cases"] == []

    def test_broken_flow_lands_in_errors(self, fake_project: Path):
        # 伪造骨架中的 Flow 均无 steps，解析失败应逐文件进入 errors。
        (fake_project / "data" / "flows" / "Broken.yaml").write_text(
            "name: Broken\ntags: []\n", encoding="utf-8"
        )
        (fake_project / "data" / "scenarios" / "Broken.yaml").write_text(
            "input: {}\n", encoding="utf-8"
        )
        snapshot = build_catalog(fake_project)
        files = {error["file"] for error in snapshot["errors"]}
        assert "data/flows/Broken.yaml" in files
        assert "data/flows/DemoFlow.yaml" in files
        # 坏文件不得混入正常清单。
        assert all(flow["name"] != "Broken" for flow in snapshot["flows"])
        for error in snapshot["errors"]:
            assert error["message"]

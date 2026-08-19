"""自由脑图草稿、编译和结构快照回归测试。"""

import json
from pathlib import Path

import pytest

from services.common.errors import ServiceError
from services.common.mindmap_review import (
    compile_case_mindmap,
    compile_point_mindmap,
    draft_content_sha256,
    project_case_mindmap,
    project_point_mindmap,
)
from services.common.task_store import TaskStore, new_task_id
from services.common.versioned_review import TEST_CASE_SPEC, VersionedReviewStore


def test_point_tree_compiles_non_standard_hierarchy_with_quality_issue() -> None:
    """非推荐层级可以编译，不应在编辑阶段被拒绝。"""

    rows = [{"id": "TP001", "module": "登录", "feature": "密码", "scenario": "正常", "test_point": "登录成功", "risk_level": "P1", "extra": 1}]
    mindmap = project_point_mindmap(rows, "测试点")
    point = next(node for node in mindmap["nodes"] if node["node_type"] == "test_point")
    module = next(node for node in mindmap["nodes"] if node["node_type"] == "module")
    point["parent_id"] = module["node_id"]
    compiled, issues = compile_point_mindmap(mindmap, rows)
    assert compiled[0]["id"] == "TP001"
    assert compiled[0]["module"] == "登录"
    assert compiled[0]["feature"] == ""
    assert compiled[0]["extra"] == 1
    assert any(issue["code"] == "MINDMAP_HIERARCHY_INVALID" for issue in issues)


def test_case_tree_uses_four_direct_content_nodes_and_preserves_text_test_data() -> None:
    """每条用例只使用四个直接内容节点，非 JSON 测试数据保留为文本。"""

    rows = [{
        "case_id": "TC001", "test_point_id": "TP001", "module": "登录", "feature": "密码",
        "scenario": "正常", "case_name": "登录成功", "priority": "P1",
        "preconditions": ["用户存在"], "test_steps": ["输入账号", "点击登录"],
        "test_data": {"user": "tester"}, "expected_result": "进入首页", "actual_result": "",
    }]
    mindmap = project_case_mindmap(rows, "测试用例")
    case_node = next(node for node in mindmap["nodes"] if node["node_type"] == "case")
    children = [node for node in mindmap["nodes"] if node["parent_id"] == case_node["node_id"]]
    assert {node["node_type"] for node in children} == {
        "preconditions_content", "steps_content", "expected_content", "test_data_content",
    }
    assert not any(node["node_type"] == "case_detail_group" for node in mindmap["nodes"])
    next(node for node in children if node["node_type"] == "test_data_content")["text"] = "user=tester"
    compiled, issues = compile_case_mindmap(mindmap, rows)
    assert compiled[0]["test_steps"] == ["输入账号", "点击登录"]
    assert compiled[0]["test_data"] == "user=tester"
    assert any(issue["code"] == "CASE_TEST_DATA_TEXT" for issue in issues)


def test_draft_sha_protects_rows_and_mindmap() -> None:
    """rows 不变但根标题变化时，CAS SHA 也必须变化。"""

    rows = [{"id": "TP001", "module": "M", "feature": "F", "scenario": "S", "test_point": "P", "risk_level": "P1"}]
    mindmap = project_point_mindmap(rows, "测试点")
    before = draft_content_sha256(rows, mindmap)
    mindmap["root"]["text"] = "新根标题"
    assert draft_content_sha256(rows, mindmap) != before


def test_confirmed_snapshot_is_immutable_and_created_before_marker(tmp_path: Path) -> None:
    """结构快照和标准 JSON 使用固定版本且不可覆盖。"""

    store = TaskStore(tmp_path)
    task_id = new_task_id()
    store.task_dir(task_id, create=True)
    files = VersionedReviewStore(store, TEST_CASE_SPEC)
    rows = [{"case_id": "TC001"}]
    mindmap = project_case_mindmap(rows, "测试用例")
    marker, snapshot = files.create_confirmed_with_mindmap(task_id, 1, rows, mindmap)
    assert marker.is_file() and snapshot.is_file()
    assert json.loads(snapshot.read_text(encoding="utf-8"))["root"]["node_type"] == "root"
    with pytest.raises(ServiceError):
        files.create_confirmed_with_mindmap(task_id, 1, rows, mindmap)

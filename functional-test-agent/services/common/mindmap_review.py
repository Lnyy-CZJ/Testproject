"""自由脑图 Review 的投影、结构检查、编译与稳定指纹。"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

from services.common.errors import ServiceError

NODE_TYPES = frozenset({
    "root", "module", "feature", "scenario", "test_point", "case",
    "preconditions_content", "steps_content", "expected_content", "test_data_content",
})
POINT_PARENT_TYPES = {
    "module": {"root"}, "feature": {"module"}, "scenario": {"feature"},
    "test_point": {"scenario"},
}
CASE_PARENT_TYPES = {
    "module": {"root"}, "feature": {"module"}, "scenario": {"feature"},
    "test_point": {"feature", "scenario"}, "case": {"test_point"},
    "preconditions_content": {"case"}, "steps_content": {"case"},
    "expected_content": {"case"}, "test_data_content": {"case"},
}
MAX_MINDMAP_NODES = 10_000


def _stable_id(prefix: str, *parts: Any) -> str:
    """根据语义路径生成稳定 UI ID，旧 rows 每次投影都得到相同结果。"""

    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:20]}"


def _node(node_id: str, node_type: str, parent_id: str, order: int, text: Any, binding_id: Any = None) -> dict[str, Any]:
    """创建最小可持久化节点，将显示文本强制转为安全字符串。"""

    if isinstance(text, (dict, list)):
        value = json.dumps(text, ensure_ascii=False, sort_keys=True)
    elif text is None:
        value = ""
    else:
        value = str(text)
    return {
        "node_id": node_id, "node_type": node_type, "parent_id": parent_id,
        "order": order, "binding_id": binding_id, "text": value,
    }


def _append_group(
    nodes: list[dict[str, Any]], cache: dict[tuple[str, ...], str],
    path: tuple[str, ...], node_type: str, parent_id: str, text: str,
) -> str:
    """在投影过程中复用同一语义路径的分组节点。"""

    if path in cache:
        return cache[path]
    node_id = _stable_id(node_type, *path)
    order = sum(1 for item in nodes if item["parent_id"] == parent_id)
    nodes.append(_node(node_id, node_type, parent_id, order, text))
    cache[path] = node_id
    return node_id


def project_point_mindmap(rows: list[Any], root_title: str = "测试点") -> dict[str, Any]:
    """将旧测试点 rows 投影为推荐脑图结构，不改写原数据。"""

    root_id = _stable_id("root", "points", root_title)
    nodes: list[dict[str, Any]] = []
    groups: dict[tuple[str, ...], str] = {}
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        module = str(item.get("module", ""))
        feature = str(item.get("feature", ""))
        scenario = str(item.get("scenario", ""))
        module_id = _append_group(nodes, groups, (module,), "module", root_id, module)
        feature_id = _append_group(nodes, groups, (module, feature), "feature", module_id, feature)
        scenario_id = _append_group(nodes, groups, (module, feature, scenario), "scenario", feature_id, scenario)
        binding = item.get("id") or f"row:{index}"
        node_id = _stable_id("test_point", binding, index)
        order = sum(1 for node in nodes if node["parent_id"] == scenario_id)
        nodes.append(_node(node_id, "test_point", scenario_id, order, item.get("test_point", ""), binding))
    return {"root": {"node_id": root_id, "node_type": "root", "text": str(root_title)}, "nodes": nodes}


def _content_text(value: Any, *, numbered: bool = False) -> str:
    """将数组或嵌套值转为脑图中的单节点多行文本。"""

    if isinstance(value, list):
        if numbered:
            return "\n".join(f"{index}. {item}" for index, item in enumerate(value, 1))
        return "\n".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    return "" if value is None else str(value)


def project_case_mindmap(rows: list[Any], root_title: str = "测试用例") -> dict[str, Any]:
    """将用例 rows 投影为主节点和四个直接内容节点。"""

    root_id = _stable_id("root", "cases", root_title)
    nodes: list[dict[str, Any]] = []
    groups: dict[tuple[str, ...], str] = {}
    content_fields = (
        ("preconditions_content", "preconditions", False),
        ("steps_content", "test_steps", True),
        ("expected_content", "expected_result", False),
        ("test_data_content", "test_data", False),
    )
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        module = str(item.get("module", ""))
        feature = str(item.get("feature", ""))
        point = str(item.get("test_point_id", ""))
        module_id = _append_group(nodes, groups, (module,), "module", root_id, module)
        feature_id = _append_group(nodes, groups, (module, feature), "feature", module_id, feature)
        point_id = _append_group(nodes, groups, (module, feature, point), "test_point", feature_id, point)
        binding = item.get("case_id") or f"row:{index}"
        case_id = _stable_id("case", binding, index)
        order = sum(1 for node in nodes if node["parent_id"] == point_id)
        nodes.append(_node(case_id, "case", point_id, order, item.get("case_name", ""), binding))
        for content_order, (node_type, field, numbered) in enumerate(content_fields):
            nodes.append(_node(
                _stable_id(node_type, binding, index), node_type, case_id, content_order,
                _content_text(item.get(field), numbered=numbered), binding,
            ))
    return {"root": {"node_id": root_id, "node_type": "root", "text": str(root_title)}, "nodes": nodes}


def canonical_draft_bytes(rows: list[Any], mindmap: dict[str, Any]) -> bytes:
    """稳定序列化整个草稿正文，避免 rows 和结构分别 CAS。"""

    return json.dumps(
        {"rows": rows, "mindmap": mindmap}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def draft_content_sha256(rows: list[Any], mindmap: dict[str, Any]) -> str:
    """计算 rows 和 mindmap 联合 SHA-256。"""

    return hashlib.sha256(canonical_draft_bytes(rows, mindmap)).hexdigest()


def _validated_tree(mindmap: Any, *, expected: dict[str, set[str]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """检查自由树的硬安全边界，并返回可定位质量问题。"""

    if not isinstance(mindmap, dict) or not isinstance(mindmap.get("root"), dict) or not isinstance(mindmap.get("nodes"), list):
        raise ServiceError(422, "MINDMAP_INVALID", "脑图草稿必须包含 root 和 nodes")
    root = mindmap["root"]
    if root.get("node_type") != "root" or not isinstance(root.get("node_id"), str) or not root.get("node_id"):
        raise ServiceError(422, "MINDMAP_INVALID", "脑图根节点不合法")
    raw_nodes = mindmap["nodes"]
    if len(raw_nodes) > MAX_MINDMAP_NODES:
        raise ServiceError(422, "MINDMAP_NODE_LIMIT_EXCEEDED", "脑图节点数超过上限")
    nodes: dict[str, dict[str, Any]] = {root["node_id"]: root}
    issues: list[dict[str, Any]] = []
    for index, node in enumerate(raw_nodes):
        if not isinstance(node, dict):
            raise ServiceError(422, "MINDMAP_INVALID", f"第 {index + 1} 个脑图节点不是对象")
        node_id = node.get("node_id")
        node_type = node.get("node_type")
        if not isinstance(node_id, str) or not node_id or node_id in nodes or node_type not in NODE_TYPES or node_type == "root":
            raise ServiceError(422, "MINDMAP_INVALID", "脑图节点 ID 或类型不合法")
        if any(str(key).startswith("_") for key in node):
            raise ServiceError(422, "MINDMAP_INVALID", "脑图节点包含保留内部字段")
        if "\x00" in str(node.get("text", "")):
            raise ServiceError(422, "TEXT_CONTAINS_NUL", "脑图文本不能包含 NUL")
        nodes[node_id] = node
    root_id = root["node_id"]
    for node in raw_nodes:
        parent_id = node.get("parent_id")
        if parent_id not in nodes:
            raise ServiceError(422, "MINDMAP_INVALID", "脑图节点父级不存在", {"node_id": node["node_id"]})
        seen: set[str] = set()
        cursor = node
        while cursor.get("node_id") != root_id:
            current_id = str(cursor.get("node_id"))
            if current_id in seen:
                raise ServiceError(422, "MINDMAP_CYCLE_DETECTED", "脑图不能形成循环", {"node_id": node["node_id"]})
            seen.add(current_id)
            cursor = nodes.get(str(cursor.get("parent_id")), root)
        parent_type = nodes[str(parent_id)].get("node_type")
        if node["node_type"] in expected and parent_type not in expected[node["node_type"]]:
            issues.append({
                "level": "warning", "code": "MINDMAP_HIERARCHY_INVALID",
                "message": "节点层级不符合推荐结构", "node_id": node["node_id"], "field": "parent_id",
            })
    return nodes, issues


def _ancestors(node: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """从近到远返回节点祖先；结构已经过循环检查。"""

    result: list[dict[str, Any]] = []
    parent_id = node.get("parent_id")
    while parent_id in nodes:
        parent = nodes[str(parent_id)]
        result.append(parent)
        if parent.get("node_type") == "root":
            break
        parent_id = parent.get("parent_id")
    return result


def _nearest(ancestors: list[dict[str, Any]], node_type: str) -> str:
    """返回最近语义祖先文本。"""

    return next((str(item.get("text", "")) for item in ancestors if item.get("node_type") == node_type), "")


def _ordered(nodes: dict[str, dict[str, Any]], node_type: str) -> list[dict[str, Any]]:
    """按父级、order 和 ID 稳定排序指定类型节点。"""

    return sorted(
        (node for node in nodes.values() if node.get("node_type") == node_type),
        key=lambda item: (str(item.get("parent_id", "")), int(item.get("order", 0) or 0), str(item.get("node_id", ""))),
    )


def _base_by_binding(rows: list[Any], key: str) -> dict[str, dict[str, Any]]:
    """为编译器建立旧 row 索引，用于保留未知扩展字段。"""

    return {
        str(item.get(key)): dict(item) for item in rows
        if isinstance(item, dict) and item.get(key) not in (None, "")
    }


def compile_point_mindmap(mindmap: Any, base_rows: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """将自由测试点树编译为标准 rows，非标准结构只产生质量问题。"""

    nodes, issues = _validated_tree(mindmap, expected=POINT_PARENT_TYPES)
    old = _base_by_binding(base_rows, "id")
    rows: list[dict[str, Any]] = []
    for index, node in enumerate(_ordered(nodes, "test_point")):
        binding = str(node.get("binding_id") or "")
        row = dict(old.get(binding, {}))
        ancestors = _ancestors(node, nodes)
        row.update({
            "id": row.get("id", binding if not binding.startswith("row:") else ""),
            "module": _nearest(ancestors, "module"),
            "feature": _nearest(ancestors, "feature"),
            "scenario": _nearest(ancestors, "scenario"),
            "test_point": str(node.get("text", "")),
            "risk_level": row.get("risk_level", ""),
        })
        rows.append(row)
        for field in ("module", "feature", "scenario"):
            if not row[field]:
                issues.append({
                    "level": "warning", "code": "MINDMAP_ANCESTOR_MISSING",
                    "message": f"测试点缺少 {field} 祖先", "node_id": node["node_id"], "field": field,
                    "row_index": index,
                })
    return rows, issues


def _split_lines(value: Any) -> list[str]:
    """将多行内容转为非空数组，同时移除展示编号。"""

    return [
        re.sub(r"^\s*\d+[\.\u3001\)]\s*", "", line.strip())
        for line in str(value or "").splitlines() if line.strip()
    ]


def compile_case_mindmap(mindmap: Any, base_rows: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """将自由用例树编译为对象 rows，内容节点类型异常只提示。"""

    nodes, issues = _validated_tree(mindmap, expected=CASE_PARENT_TYPES)
    old = _base_by_binding(base_rows, "case_id")
    children: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in nodes.values():
        if item.get("node_type") != "root":
            children[str(item.get("parent_id"))].append(item)
    rows: list[dict[str, Any]] = []
    for index, node in enumerate(_ordered(nodes, "case")):
        binding = str(node.get("binding_id") or "")
        row = dict(old.get(binding, {}))
        ancestors = _ancestors(node, nodes)
        content = {item.get("node_type"): item for item in children[node["node_id"]]}
        test_data_text = str((content.get("test_data_content") or {}).get("text", ""))
        try:
            test_data: Any = json.loads(test_data_text) if test_data_text.strip() else ""
        except json.JSONDecodeError:
            test_data = test_data_text
            issues.append({
                "level": "warning", "code": "CASE_TEST_DATA_TEXT",
                "message": "测试数据不是 JSON，已作为普通文本保留", "node_id": (content.get("test_data_content") or node)["node_id"],
                "field": "test_data", "row_index": index,
            })
        row.update({
            "case_id": row.get("case_id", binding if not binding.startswith("row:") else ""),
            "test_point_id": _nearest(ancestors, "test_point"),
            "module": _nearest(ancestors, "module"),
            "feature": _nearest(ancestors, "feature"),
            "scenario": _nearest(ancestors, "scenario") or row.get("scenario", ""),
            "case_name": str(node.get("text", "")),
            "priority": row.get("priority", ""),
            "preconditions": _split_lines((content.get("preconditions_content") or {}).get("text", "")),
            "test_steps": _split_lines((content.get("steps_content") or {}).get("text", "")),
            "test_data": test_data,
            "expected_result": str((content.get("expected_content") or {}).get("text", "")),
            "actual_result": row.get("actual_result", ""),
        })
        rows.append(row)
    return rows, issues

"""setup/teardown Python 脚本的静态 AST 安全策略。"""

from __future__ import annotations

import ast

from services.api_agent.models import ReviewIssue


FORBIDDEN_MODULES = {
    "subprocess", "socket", "ctypes", "multiprocessing", "importlib", "pathlib", "shutil",
}
FORBIDDEN_NAMES = {"eval", "exec", "compile", "__import__", "open", "breakpoint", "input"}
FORBIDDEN_ATTRIBUTES = {
    "system", "popen", "spawn", "fork", "kill", "remove", "unlink", "rmdir", "write_text", "write_bytes",
}


def validate_script(script: str, field_path: str) -> list[ReviewIssue]:
    """校验脚本语法及危险节点；静态策略不能代替运行时隔离。"""

    if not script:
        return []
    try:
        tree = ast.parse(script, mode="exec")
    except SyntaxError as exc:
        return [ReviewIssue(
            code="SCRIPT_SYNTAX_INVALID", field_path=field_path,
            message=f"脚本语法错误（行 {exc.lineno}）", severity="blocker",
        )]
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [alias.name.split(".", 1)[0] for alias in node.names] if isinstance(node, ast.Import) else [str(node.module or "").split(".", 1)[0]]
            if any(module in FORBIDDEN_MODULES for module in modules):
                issues.append(_issue(field_path, "SCRIPT_IMPORT_FORBIDDEN", "脚本导入了禁止模块"))
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            issues.append(_issue(field_path, "SCRIPT_CALL_FORBIDDEN", f"脚本使用了禁止函数 {node.id}"))
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in FORBIDDEN_ATTRIBUTES:
                issues.append(_issue(field_path, "SCRIPT_ATTRIBUTE_FORBIDDEN", f"脚本访问了禁止属性 {node.attr}"))
    unique = {(item.code, item.message): item for item in issues}
    return list(unique.values())


def _issue(field_path: str, code: str, message: str) -> ReviewIssue:
    """构造统一阻断问题。"""

    return ReviewIssue(code=code, field_path=field_path, message=message, severity="blocker")

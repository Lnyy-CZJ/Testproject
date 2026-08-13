"""
测试数据中枢管理器（TestDataHub）

功能：
    - 从YAML/JSON文件加载测试数据
    - 按命名空间隔离不同API的数据
    - 提供数据引用解析能力
    - 管理基础数据与测试数据的合并
    - 支持_inherits+_overrides继承语法
    - 支持数据lineage溯源

不包含：
    - 断言执行逻辑
    - 数据验证逻辑

使用示例：
    from agents.common.utils.test_data_hub import TestDataHub, get_test_data_hub

    # 方式1：使用单例
    hub = get_test_data_hub()
    hub.load_data_file("LoginApi_data.yaml", namespace="LoginApi")
    data = hub.get_data("test_data.normal", namespace="LoginApi")

    # 方式2：直接创建实例
    hub = TestDataHub(data_dir="datas/TestData")
    hub.load_data_file("LoginApi_data.yaml")

    # 方式3：带lineage的数据解析
    result = hub.resolve_case_data_with_lineage("test_data.boundary.pwd_min_minus", namespace="LoginApi")
    # result = {"resolved_data": {...}, "lineage": {...}}
"""

import os
import yaml
import json
import copy
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class TestDataSet:
    """测试数据集"""
    name: str
    description: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    base_data: Dict[str, Any] = field(default_factory=dict)


class TestDataHub:
    """测试数据中枢管理器"""

    def __init__(self, data_dir: str = None):
        """
        初始化测试数据管理器

        Args:
            data_dir: 数据文件根目录，默认为 datas/TestData
        """
        self.data_dir = data_dir or self._get_default_data_dir()
        self.data_pool: Dict[str, TestDataSet] = {}

    def _get_default_data_dir(self) -> str:
        """获取默认数据目录"""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        ))))
        return os.path.join(base_dir, "datas", "TestData")

    def load_data_file(self, file_path: str, namespace: str = None) -> bool:
        """
        加载数据文件

        Args:
            file_path: 文件路径（相对或绝对路径）
            namespace: 命名空间，用于隔离不同模块的数据，不传则使用api_name

        Returns:
            加载是否成功
        """
        if not os.path.isabs(file_path):
            file_path = os.path.join(self.data_dir, file_path)
        if not os.path.exists(file_path):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)
            ))))
            test_data_root = os.path.join(project_root, "datas", "TestData")
            fallback_path = os.path.join(test_data_root, os.path.basename(file_path))
            if os.path.exists(fallback_path):
                file_path = fallback_path
            else:
                for root, _, files in os.walk(test_data_root):
                    if os.path.basename(file_path) in files:
                        file_path = os.path.join(root, os.path.basename(file_path))
                        break

        if not os.path.exists(file_path):
            print(f"[TestDataHub] 文件不存在: {file_path}")
            return False

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                if file_path.endswith('.yaml') or file_path.endswith('.yml'):
                    raw_data = yaml.safe_load(f)
                elif file_path.endswith('.json'):
                    raw_data = json.load(f)
                else:
                    print(f"[TestDataHub] 不支持的文件格式，仅支持 .yaml/.yml/.json")
                    return False

            namespace = namespace or raw_data.get('api_name', 'default')

            data_set = TestDataSet(
                name=namespace,
                description=raw_data.get('description', ''),
                data=raw_data.get('test_data', {}),
                base_data=raw_data.get('base_data', {})
            )

            self.data_pool[namespace] = data_set
            print(f"[TestDataHub] 加载成功: {namespace}, 包含 {len(data_set.data)} 个数据分类")
            return True

        except Exception as e:
            print(f"[TestDataHub] 加载失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_data(self, ref: str, namespace: str = None) -> Optional[Dict]:
        """
        获取数据

        Args:
            ref: 数据引用，支持两种格式：
                - 短格式：如 "normal"、"boundary"
                - 长格式：如 "test_data.normal"、"test_data.boundary.username_min"
            namespace: 命名空间，不传则从所有命名空间中查找

        Returns:
            数据字典，未找到返回None
        """
        parts = ref.split('.') if ref else []

        if len(parts) == 1:
            key = parts[0]
            for ns, ds in self.data_pool.items():
                if namespace and ns != namespace:
                    continue
                if key in ds.data:
                    return ds.data[key]

        elif len(parts) >= 2:
            path_parts = parts[1:] if parts[0] == "test_data" else parts
            for ns, ds in self.data_pool.items():
                if namespace and ns != namespace:
                    continue
                current = ds.data
                for path_part in path_parts:
                    if not isinstance(current, dict) or path_part not in current:
                        current = None
                        break
                    current = current[path_part]
                if current is not None:
                    return current

        return None

    @staticmethod
    def _deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
        """
        深度合并两个字典，overrides优先

        Args:
            base: 基础字典
            overrides: 覆盖字典

        Returns:
            合并后的字典
        """
        result = copy.deepcopy(base) if isinstance(base, dict) else {}
        if not isinstance(overrides, dict):
            return result
        for key, value in overrides.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
                and not key.startswith("_")
            ):
                result[key] = TestDataHub._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    @staticmethod
    def _strip_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        移除元数据字段，只保留可执行的数据字段

        Args:
            data: 输入数据字典

        Returns:
            移除元数据后的数据字典
        """
        if not isinstance(data, dict):
            return {}
        return {
            key: copy.deepcopy(value)
            for key, value in data.items()
            if not key.startswith("_") and key != "description"
        }

    @staticmethod
    def _normalize_inherit_ref(inherit_ref: str) -> str:
        """
        标准化继承引用路径

        Args:
            inherit_ref: 原始引用，如 "baseline" 或 "test_data.baseline"

        Returns:
            标准化后的引用，如 "test_data.baseline"
        """
        if not inherit_ref:
            return ""
        if inherit_ref.startswith("test_data."):
            return inherit_ref
        return f"test_data.{inherit_ref}"

    def get_baseline_data(self, namespace: str = None) -> Dict[str, Any]:
        """
        获取基准数据（Baseline Data）

        Args:
            namespace: 命名空间

        Returns:
            基准数据字典
        """
        baseline = self.get_data("test_data.baseline", namespace=namespace)
        return self._strip_metadata(baseline or {})

    def resolve_case_data_with_lineage(self, data_ref: str, namespace: str = None) -> Dict[str, Any]:
        """
        解析测试数据并保留继承关系lineage

        支持_inherits + _overrides语法：
        - _inherits: 指定继承的数据分组路径，如 "baseline"
        - _overrides: 指定要覆盖的字段及其新值

        数据文件格式示例：
        ```yaml
        test_data:
          baseline:
            accounts: "czj11"
            pwd: "czj111"

          boundary:
            pwd_min_minus:
              _inherits: "baseline"
              _overrides:
                pwd: "12345"
        ```

        Args:
            data_ref: 数据引用路径，如 "test_data.boundary.pwd_min_minus"
            namespace: 命名空间

        Returns:
            {
                "resolved_data": 扁平可执行数据,
                "lineage": {
                    "data_ref": 原始引用,
                    "inherits": 继承的数据路径,
                    "overrides": 覆盖的字段映射,
                    "resolved_at_generation": True
                }
            }
        """
        data = self.get_data(data_ref, namespace)

        empty_lineage = {
            "data_ref": data_ref,
            "inherits": None,
            "overrides": {},
            "resolved_at_generation": True,
        }

        if not data:
            print(f"[TestDataHub] 未找到数据引用: {data_ref}")
            return {"resolved_data": {}, "lineage": empty_lineage}

        # 提取_inherits和_overrides
        inherits = data.get("_inherits") if isinstance(data, dict) else None
        baseline_data = {}

        # 如果指定了_inherits，加载对应的baseline数据
        if inherits:
            normalized_ref = self._normalize_inherit_ref(inherits)
            baseline_data = self._strip_metadata(self.get_data(normalized_ref, namespace) or {})
            if not baseline_data:
                baseline_data = self.get_baseline_data(namespace=namespace)
        # 如果没有指定inherits且不是直接请求baseline，则尝试加载baseline
        elif not data_ref.endswith(".baseline") and ".baseline." not in data_ref:
            baseline_data = self.get_baseline_data(namespace=namespace)

        # 提取_overrides
        if isinstance(data, dict) and "_overrides" in data:
            overrides = self._strip_metadata(data.get("_overrides") or {})
            override_prefix = f"{data_ref}._overrides"
        else:
            overrides = self._strip_metadata(data or {})
            override_prefix = data_ref

        # 合并数据：baseline + overrides
        resolved = self._deep_merge(baseline_data or {}, overrides)

        # 合并base_data（环境配置）
        if namespace and namespace in self.data_pool:
            resolved = self._deep_merge(self.data_pool[namespace].base_data, resolved)

        # 构建lineage
        lineage = {
            "data_ref": data_ref,
            "inherits": self._normalize_inherit_ref(inherits) if inherits else (
                "test_data.baseline" if baseline_data and ".baseline." not in data_ref else None
            ),
            "overrides": {key: f"{override_prefix}.{key}" for key in overrides},
            "resolved_at_generation": True,
        }

        return {"resolved_data": resolved, "lineage": lineage}

    def resolve_case_data(self, data_ref: str, namespace: str = None) -> Dict[str, Any]:
        """
        解析用例数据引用，返回展平的数据字典

        Args:
            data_ref: data_ref字段值，如 "test_data.normal"
            namespace: 命名空间

        Returns:
            展平后的数据字典，可直接用于变量替换
        """
        # 优先使用带lineage的解析方法
        result = self.resolve_case_data_with_lineage(data_ref, namespace)
        return result.get("resolved_data", {})

    def save_data_file(self, namespace: str, data: Dict, output_path: str = None) -> bool:
        """
        保存数据文件

        Args:
            namespace: 命名空间，用于生成默认文件名
            data: 数据内容字典，应包含test_data字段
            output_path: 输出路径，不传则使用默认路径

        Returns:
            保存是否成功
        """
        if not output_path:
            output_path = os.path.join(self.data_dir, f"{namespace}_data.yaml")

        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            if 'test_data' in data:
                output_data = {
                    'api_name': data.get('api_name', namespace),
                    'api_path': data.get('api_path', ''),
                    'last_updated': self._get_timestamp(),
                    'test_data': data['test_data']
                }
            else:
                output_data = {
                    'api_name': namespace,
                    'last_updated': self._get_timestamp(),
                    'test_data': data
                }

            with open(output_path, 'w', encoding='utf-8') as f:
                yaml.dump(output_data, f, allow_unicode=True, default_flow_style=False)

            print(f"[TestDataHub] 保存成功: {output_path}")
            return True
        except Exception as e:
            print(f"[TestDataHub] 保存失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def list_namespaces(self) -> list:
        """列出所有已加载的命名空间"""
        return list(self.data_pool.keys())

    def clear(self):
        """清空数据池"""
        self.data_pool.clear()
        print("[TestDataHub] 数据池已清空")


# 全局单例
_test_data_hub_instance = None


def get_test_data_hub() -> TestDataHub:
    """获取测试数据管理器单例"""
    global _test_data_hub_instance
    if _test_data_hub_instance is None:
        _test_data_hub_instance = TestDataHub()
    return _test_data_hub_instance


def reset_test_data_hub():
    """重置测试数据管理器单例（用于测试）"""
    global _test_data_hub_instance
    if _test_data_hub_instance is not None:
        _test_data_hub_instance.clear()
    _test_data_hub_instance = None

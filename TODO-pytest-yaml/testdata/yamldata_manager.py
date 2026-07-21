import yaml
import threading
from copy import deepcopy
import sys
import os
# 获取项目根目录（假设当前文件在 utils 目录下）
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)  # 向上到项目根目录
# 将项目根目录添加到 Python 路径
if project_root not in sys.path:
    sys.path.insert(0, project_root)

class YAMLDataManager:
    """
    YAML 数据管理器（线程安全 + 缓存 + 可扩展）
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """单例模式"""
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._cache = {}
        return cls._instance

    def _load_yaml(self, file_path):
        """加载 YAML（带缓存）"""
        abs_path = os.path.abspath(file_path)

        if abs_path in self._cache:
            return self._cache[abs_path]

        with self._lock:
            if abs_path in self._cache:
                return self._cache[abs_path]

            with open(abs_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            self._cache[abs_path] = data
            return data

    def get_common(self, file_path):
        """获取公共参数"""
        data = self._load_yaml(file_path)
        return data.get("case_common", {})

    def get_cases(self, file_path, case_key):
        """
        获取测试用例数据（自动合并 common）
        """
        data = self._load_yaml(file_path)

        common = data.get("case_common", {})
        cases = data.get(case_key, [])

        result = []

        for case in cases:
            merged = deepcopy(common)

            # 合并逻辑：case 覆盖 common
            merged.update(case)

            # headers 特殊处理（深度合并）
            if "headers" in common and "headers" in case:
                merged["headers"] = {
                    **common.get("headers", {}),
                    **case.get("headers", {})
                }

            result.append(merged)

        return result

    def clear_cache(self):
        """清除缓存（热更新用）"""
        with self._lock:
            self._cache.clear()

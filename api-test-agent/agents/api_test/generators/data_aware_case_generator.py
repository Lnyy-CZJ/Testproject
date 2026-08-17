"""
数据感知型测试用例生成器

功能：
    - 解析API文档中的验证规则
    - 根据规则自动生成边界值、异常值数据
    - 生成符合TestDataHub格式的数据文件
    - 生成带data_ref引用的用例模板

不包含：
    - 断言生成逻辑
    - 期望值定义

使用示例：
    from agents.api_test.generators import DataAwareCaseGenerator
    from agents.common.utils.test_data_hub import get_test_data_hub

    generator = DataAwareCaseGenerator()

    # 解析API文档中的验证规则
    api_info = {
        "method": "POST",
        "path": "/api/user/login",
        "requestBody": {
            "body": [
                {"name": "username", "type": "string", "required": True, "description": "用户名，长度6-18位"}
            ]
        }
    }
    rules = generator.parse_validation_rules(api_info)

    # 生成测试数据
    generator.generate_test_data(rules)

    # 导出数据文件
    hub = get_test_data_hub()
    generator.set_data_hub(hub)
    generator.export_data_file("LoginApi", "/api/user/login", "datas/TestData/LoginApi_data.yaml")
"""

import os
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


@dataclass
class ValidationRule:
    """参数验证规则"""
    param_name: str
    param_type: str
    required: bool = True
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    min_value: Optional[int] = None
    max_value: Optional[int] = None
    pattern: Optional[str] = None
    enum_values: Optional[List[Any]] = None
    description: str = ""


@dataclass
class GeneratedDataItem:
    """生成的数据项"""
    category: str
    key: str
    data: Dict[str, Any]
    description: str = ""


class DataAwareCaseGenerator:
    """数据感知型用例生成器"""

    def __init__(self, test_data_hub=None):
        """
        初始化数据生成器

        Args:
            test_data_hub: 测试数据管理器实例
        """
        self.test_data_hub = test_data_hub
        self.validation_rules: Dict[str, List[ValidationRule]] = {}
        self.generated_data: Dict[str, Dict[str, Any]] = {}
        self.generated_cases: List[Dict[str, Any]] = []

    def set_data_hub(self, hub):
        """设置数据管理器"""
        self.test_data_hub = hub

    def parse_validation_rules(self, api_info: Dict) -> Dict[str, List[ValidationRule]]:
        """
        从API信息中解析验证规则

        Args:
            api_info: AI解析后的API信息，应包含：
                - method: HTTP方法
                - path: API路径
                - requestBody: 请求体定义
                - parameters: 参数定义（可选）

        Returns:
            参数验证规则字典，格式：{param_name: [ValidationRule]}

        解析逻辑：
            1. 从requestBody.body解析请求体参数
            2. 从parameters解析header、path、query参数
            3. 从description中提取长度、范围等约束
        """
        rules = {}

        # 解析请求体参数
        request_body = api_info.get('requestBody', {})
        if isinstance(request_body, dict):
            body_params = request_body.get('body', [])
        else:
            body_params = request_body

        for param in body_params:
            if not isinstance(param, dict):
                continue

            rule = self._parse_single_param(param)
            if rule:
                rules[param.get('name', '')] = [rule]

        # 解析header参数
        parameters = api_info.get('parameters', {})
        if isinstance(parameters, dict):
            header_params = parameters.get('header', [])
            for param in header_params:
                if not isinstance(param, dict):
                    continue
                rule = self._parse_single_param(param)
                if rule and param.get('name'):
                    rules[f"header_{param['name']}"] = [rule]

        self.validation_rules = rules
        return rules

    def _parse_single_param(self, param: Dict) -> Optional[ValidationRule]:
        """
        解析单个参数的定义

        Args:
            param: 参数定义字典

        Returns:
            ValidationRule对象
        """
        if not param:
            return None

        param_name = param.get('name', '')
        param_type = param.get('type', 'string')
        required = param.get('required', True)
        description = param.get('description', '')

        rule = ValidationRule(
            param_name=param_name,
            param_type=param_type,
            required=required,
            description=description
        )

        # 从描述中提取长度约束
        length_info = self._extract_length_info(description)
        rule.min_length = length_info.get('min')
        rule.max_length = length_info.get('max')

        # 从描述中提取数值范围
        range_info = self._extract_range_info(description)
        rule.min_value = range_info.get('min')
        rule.max_value = range_info.get('max')

        # 提取枚举值
        enum_info = self._extract_enum_values(description)
        if enum_info:
            rule.enum_values = enum_info

        return rule

    def _extract_length_info(self, description: str) -> Dict[str, Optional[int]]:
        """
        从描述中提取长度信息

        支持格式：
            - "长度6-18位"
            - "长度 6-18 位"
            - "6-18个字符"
            - "min_length:6"
            - "最长20字符"
        """
        result = {'min': None, 'max': None}

        if not description:
            return result

        # 格式1: 6-18位/字符
        patterns = [
            r'(\d+)\s*-\s*(\d+)\s*(?:位|字符|字符长)',
            r'长度\s*(\d+)\s*-\s*(\d+)',
            r'(\d+)\s*到\s*(\d+)\s*(?:位|字符)',
        ]

        for pattern in patterns:
            match = re.search(pattern, description)
            if match:
                result['min'] = int(match.group(1))
                result['max'] = int(match.group(2))
                return result

        # 格式2: 最长X
        match = re.search(r'最长(\d+)', description)
        if match:
            result['max'] = int(match.group(1))

        # 格式3: 最短X
        match = re.search(r'最短(\d+)', description)
        if match:
            result['min'] = int(match.group(1))

        return result

    def _extract_range_info(self, description: str) -> Dict[str, Optional[int]]:
        """
        从描述中提取数值范围

        支持格式：
            - "范围1-100"
            - "取值1~100"
            - "min:1"
        """
        result = {'min': None, 'max': None}

        if not description:
            return result

        # 格式1: 1-100
        match = re.search(r'(\d+)\s*-\s*(\d+)', description)
        if match:
            result['min'] = int(match.group(1))
            result['max'] = int(match.group(2))

        return result

    def _extract_enum_values(self, description: str) -> Optional[List[Any]]:
        """
        从描述中提取枚举值

        支持格式：
            - "枚举值：A、B、C"
            - "可选值：male,female"
        """
        if not description:
            return None

        match = re.search(r'(?:枚举值|可选值)[:：]\s*([\w,\s]+)', description)
        if match:
            values_str = match.group(1).replace('，', ',').replace('、', ',')
            values = values_str.split(',')
            return [v.strip() for v in values if v.strip()]

        return None

    def generate_test_data(self, rules: Dict[str, List[ValidationRule]] = None) -> Dict[str, Dict[str, Any]]:
        """
        根据验证规则生成测试数据

        Args:
            rules: 参数验证规则，不传则使用上次解析的规则

        Returns:
            生成的测试数据字典

        数据分类：
            - normal: 正向数据
            - boundary: 边界值数据
            - abnormal: 异常数据
            - security: 安全测试数据
        """
        if rules is None:
            rules = self.validation_rules

        self.generated_data = {
            'normal': {},
            'boundary': {},
            'abnormal': {},
            'security': {}
        }

        for param_name, param_rules in rules.items():
            if not param_rules:
                continue

            rule = param_rules[0]

            # 生成正向数据（直接的数据字典，不是嵌套的）
            normal_data = self._generate_normal_data(param_name, rule)
            if normal_data:
                self.generated_data['normal'].update(normal_data)

            # 生成边界值数据
            boundary_data = self._generate_boundary_data(param_name, rule)
            self.generated_data['boundary'].update(boundary_data)

            # 生成异常数据
            abnormal_data = self._generate_abnormal_data(param_name, rule)
            self.generated_data['abnormal'].update(abnormal_data)

            # 生成安全测试数据
            security_data = self._generate_security_data(param_name, rule)
            self.generated_data['security'].update(security_data)

        return self.generated_data

    def _generate_normal_data(self, param_name: str, rule: ValidationRule) -> Dict[str, Any]:
        """
        生成正向测试数据

        Args:
            param_name: 参数名
            rule: 验证规则

        Returns:
            正向数据字典，格式：{param_name: value}
        """
        if rule.param_type == 'string':
            if rule.min_length and rule.max_length:
                # 生成中间长度
                mid_length = (rule.min_length + rule.max_length) // 2
                value = 'a' * mid_length
            elif rule.min_length:
                value = 'a' * rule.min_length
            else:
                value = 'valid_value'
        elif rule.param_type == 'integer' or rule.param_type == 'number':
            if rule.min_value is not None and rule.max_value is not None:
                value = (rule.min_value + rule.max_value) // 2
            elif rule.min_value is not None:
                value = rule.min_value + 1
            else:
                value = 100
        elif rule.param_type == 'boolean':
            value = True
        else:
            value = 'valid_value'

        return {param_name: value}

    def _generate_boundary_data(self, param_name: str, rule: ValidationRule) -> Dict[str, Dict[str, Any]]:
        """
        生成边界值测试数据

        Args:
            param_name: 参数名
            rule: 验证规则

        Returns:
            边界值数据字典，格式：{key: {param_name: value, _description: desc}}
        """
        boundary = {}

        if rule.param_type == 'string':
            # 字符串边界值
            if rule.min_length is not None:
                # 最小长度-1
                if rule.min_length > 1:
                    key = f'{param_name}_min_minus'
                    boundary[key] = {
                        param_name: 'a' * (rule.min_length - 1),
                        '_description': f'字符串长度最小值-1（{rule.min_length - 1}位）'
                    }
                # 最小值
                key = f'{param_name}_min'
                boundary[key] = {
                    param_name: 'a' * rule.min_length,
                    '_description': f'字符串长度最小值（{rule.min_length}位）'
                }

            if rule.max_length is not None:
                # 最大值
                key = f'{param_name}_max'
                boundary[key] = {
                    param_name: 'a' * rule.max_length,
                    '_description': f'字符串长度最大值（{rule.max_length}位）'
                }
                # 最大值+1
                key = f'{param_name}_max_plus'
                boundary[key] = {
                    param_name: 'a' * (rule.max_length + 1),
                    '_description': f'字符串长度最大值+1（{rule.max_length + 1}位）'
                }

        elif rule.param_type == 'integer' or rule.param_type == 'number':
            # 数值边界值
            if rule.min_value is not None:
                key = f'{param_name}_min_minus'
                boundary[key] = {
                    param_name: rule.min_value - 1,
                    '_description': f'数值最小值-1'
                }
                key = f'{param_name}_min'
                boundary[key] = {
                    param_name: rule.min_value,
                    '_description': f'数值最小值'
                }

            if rule.max_value is not None:
                key = f'{param_name}_max'
                boundary[key] = {
                    param_name: rule.max_value,
                    '_description': f'数值最大值'
                }
                key = f'{param_name}_max_plus'
                boundary[key] = {
                    param_name: rule.max_value + 1,
                    '_description': f'数值最大值+1'
                }

        return boundary

    def _generate_abnormal_data(self, param_name: str, rule: ValidationRule) -> Dict[str, Dict[str, Any]]:
        """
        生成异常测试数据

        Args:
            param_name: 参数名
            rule: 验证规则

        Returns:
            异常数据字典，格式：{key: {param_name: value, _description: desc}}
        """
        abnormal = {}

        # 空字符串
        key = f'{param_name}_empty'
        abnormal[key] = {
            param_name: '',
            '_description': '空字符串'
        }

        # None/null
        key = f'{param_name}_null'
        abnormal[key] = {
            param_name: None,
            '_description': 'null值'
        }

        # 特殊字符
        if rule.param_type == 'string':
            key = f'{param_name}_special_chars'
            abnormal[key] = {
                param_name: '!@#$%^&*()_+-=[]{}|;:,.<>?',
                '_description': '特殊字符'
            }

            key = f'{param_name}_emoji'
            abnormal[key] = {
                param_name: '测试数据😀🎉',
                '_description': '包含Emoji'
            }

            key = f'{param_name}_chinese'
            abnormal[key] = {
                param_name: '测试用户名',
                '_description': '纯中文'
            }

        elif rule.param_type == 'integer' or rule.param_type == 'number':
            key = f'{param_name}_not_number'
            abnormal[key] = {
                param_name: 'not_a_number',
                '_description': '非数字类型'
            }

            key = f'{param_name}_negative'
            abnormal[key] = {
                param_name: -1,
                '_description': '负数'
            }

        elif rule.param_type == 'boolean':
            key = f'{param_name}_invalid_type'
            abnormal[key] = {
                param_name: 'true',
                '_description': '类型错误'
            }

        return abnormal

    def _generate_security_data(self, param_name: str, rule: ValidationRule) -> Dict[str, Dict[str, Any]]:
        """
        生成安全测试数据

        Args:
            param_name: 参数名
            rule: 验证规则

        Returns:
            安全测试数据字典，格式：{key: {param_name: value, _description: desc}}
        """
        security = {}

        if rule.param_type == 'string':
            # SQL注入
            key = f'{param_name}_sql_injection'
            security[key] = {
                param_name: "' OR '1'='1",
                '_description': 'SQL注入测试'
            }

            # XSS攻击
            key = f'{param_name}_xss'
            security[key] = {
                param_name: '<script>alert("xss")</script>',
                '_description': 'XSS攻击测试'
            }

            # 命令注入
            key = f'{param_name}_command_injection'
            security[key] = {
                param_name: '| cat /etc/passwd',
                '_description': '命令注入测试'
            }

        return security

    def export_data_file(self, api_name: str, api_path: str, output_path: str) -> bool:
        """
        导出数据文件

        Args:
            api_name: API名称
            api_path: API路径
            output_path: 输出文件路径

        Returns:
            是否导出成功
        """
        if not self.test_data_hub:
            from agents.common.utils.test_data_hub import TestDataHub
            self.test_data_hub = TestDataHub()

        # 直接使用generated_data，不需要再包装
        data = {
            'api_name': api_name,
            'api_path': api_path,
            'test_data': self.generated_data
        }

        return self.test_data_hub.save_data_file(api_name, data, output_path)

    def generate_case_templates(self, api_info: Dict, api_name: str) -> List[Dict[str, Any]]:
        """
        生成用例模板

        Args:
            api_info: API信息
            api_name: API名称

        Returns:
            用例模板列表，每个用例包含：
                - case_name: 用例名称
                - data_ref: 数据引用路径
                - request: 请求模板（带变量引用）
        """
        self.generated_cases = []

        method = api_info.get('method', 'POST')
        path = api_info.get('path', '/')

        for category, items in self.generated_data.items():
            for key, data_item in items.items():
                # 处理两种数据格式
                if isinstance(data_item, dict) and not data_item.get('_description'):
                    # 格式1: {param_name: value} - 用于normal类别
                    case_data = data_item.copy()
                    description = ''
                elif isinstance(data_item, dict):
                    # 格式2: {param_name: value, _description: desc}
                    case_data = {k: v for k, v in data_item.items() if not k.startswith('_')}
                    description = data_item.get('_description', '')
                else:
                    continue

                case = {
                    'case_name': f"{category}-{key}",
                    'description': description,
                    'data_ref': f"test_data.{category}.{key}",
                    'request': {
                        'method': method,
                        'url': path,
                        'body': case_data
                    }
                }

                self.generated_cases.append(case)

        return self.generated_cases

    def get_data_summary(self) -> Dict[str, int]:
        """
        获取生成数据的摘要统计

        Returns:
            各分类的数据条数统计
        """
        summary = {}
        for category, items in self.generated_data.items():
            if isinstance(items, dict):
                summary[category] = len(items)
            else:
                summary[category] = 0
        return summary

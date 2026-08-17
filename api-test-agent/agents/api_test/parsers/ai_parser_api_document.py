
"""
通过AI解析接口文档
"""
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
from typing import Dict, List, Optional, Any
from urllib.parse import urlsplit

from agents.api_test.prompts import api_document_parser
from agents.common.config.settings import llm
from pydantic import BaseModel, Field
from langchain_core.output_parsers import JsonOutputParser


class Parameter(BaseModel):
    """用于提取接口参数的模型"""
    name: str = Field(description="参数名称")
    description: str = Field(description="参数描述")
    required: bool = Field(description="参数是否必填")
    type: Dict = Field(description="参数类型")
    param_role: str = Field(default="required", description="参数角色: required/optional/fixed")
    fixed_value: Optional[Any] = Field(default=None, description="固定值参数的不可变取值")
    default_value: Optional[Any] = Field(default=None, description="选填参数的默认值")
    allow_omit: bool = Field(default=False, description="请求时是否允许省略该参数")
    source_note: Optional[str] = Field(default=None, description="参数分类依据")
    baseline_value: Optional[Any] = Field(default=None, description="Baseline value used by positive and control-variable cases")
    data_category: str = Field(default="baseline", description="Data category: baseline/boundary/abnormal/security")
    param_category: str = Field(default="required", description="Parameter category: required/optional/conditional/fixed")
    dependencies: List[str] = Field(default_factory=list, description="Parameters that this parameter depends on")
    mutex_group: Optional[str] = Field(default=None, description="Mutually exclusive parameter group name")
    test_strategy: List[str] = Field(default_factory=list, description="Recommended strategies for this parameter")


class BodyParameter(BaseModel):
    """用于提取接口参数的模型"""
    name: str = Field(description="参数名称")
    description: str = Field(description="参数描述")
    required: bool = Field(description="参数是否必填")
    type: Dict = Field(description="参数类型")
    param_role: str = Field(default="required", description="参数角色: required/optional/fixed")
    fixed_value: Optional[Any] = Field(default=None, description="固定值参数的不可变取值")
    default_value: Optional[Any] = Field(default=None, description="选填参数的默认值")
    allow_omit: bool = Field(default=False, description="请求时是否允许省略该参数")
    source_note: Optional[str] = Field(default=None, description="参数分类依据")
    baseline_value: Optional[Any] = Field(default=None, description="Baseline value used by positive and control-variable cases")
    data_category: str = Field(default="baseline", description="Data category: baseline/boundary/abnormal/security")
    param_category: str = Field(default="required", description="Parameter category: required/optional/conditional/fixed")
    dependencies: List[str] = Field(default_factory=list, description="Parameters that this parameter depends on")
    mutex_group: Optional[str] = Field(default=None, description="Mutually exclusive parameter group name")
    test_strategy: List[str] = Field(default_factory=list, description="Recommended strategies for this parameter")
    nested_fields: Optional[List[Dict[str, Any]]] = Field(description="嵌套字段", default=None)
    array_item_fields: Optional[List[Dict[str, Any]]] = Field(description="数组项字段", default=None)


class RequestBodyModel(BaseModel):
    """请求体的模型"""
    content_type: str = Field(description="请求体类型，如 application/json，无请求体时为null")
    body: List[BodyParameter] = Field(description="请求体参数")


class ParametersModel(BaseModel):
    """用于提取接口参数的模型"""
    header: List[Parameter] = Field(description="请求头参数")
    path: List[Parameter] = Field(description="路径参数")
    query: List[Parameter] = Field(description="查询参数")


class ResponsesModel(BaseModel):
    """用于提取接口响应的模型"""
    http_code: str = Field(description="响应状态码")
    description: str = Field(description="响应描述")
    media_type: str = Field(description="响应内容类型，如 application/json")
    response_body: Dict = Field(description="响应体参数")


class InterfaceDocumentParserModel(BaseModel):
    """用于提取接口解析结果的模型"""
    base_url: Optional[str] = Field(default=None, description="API base URL, for example http://host/index.php?s=")
    raw_url: Optional[str] = Field(default=None, description="Original URL from the document before normalization")
    path: str = Field(description="接口路径")
    method: str = Field(description="接口请求方式")
    summary: str = Field(description="接口描述")
    parameters: ParametersModel = Field(description="接口的参数分类，包含请求头、路径参数、查询参数")
    requestBody: Optional[RequestBodyModel] = Field(description="接口请求体参数", default_factory=dict)
    responses: ResponsesModel = Field(description="接口响应示例")


class AIAPIDocumentParser:
    """
    通过AI解析接口文档,将接口文档转换为特点的结构化数据
    """

    VALID_PARAM_ROLES = {"required", "optional", "conditional", "fixed"}
    ROLE_ALIASES = {
        "required": "required",
        "must": "required",
        "mandatory": "required",
        "必填": "required",
        "必填参数": "required",
        "optional": "optional",
        "not_required": "optional",
        "non_required": "optional",
        "conditional": "conditional",
        "dependent": "conditional",
        "mutex": "conditional",
        "mutually_exclusive": "conditional",
        "条件": "conditional",
        "条件参数": "conditional",
        "依赖": "conditional",
        "依赖参数": "conditional",
        "互斥": "conditional",
        "互斥参数": "conditional",
        "可选": "optional",
        "选填": "optional",
        "选填参数": "optional",
        "非必填": "optional",
        "fixed": "fixed",
        "const": "fixed",
        "constant": "fixed",
        "固定": "fixed",
        "固定值": "fixed",
        "固定值参数": "fixed",
    }
    FIXED_MARKERS = ("固定值", "固定参数", "固定", "不可变", "不可更改", "fixed value", "fixed", "constant")
    OPTIONAL_MARKERS = ("选填参数", "选填", "可选", "非必填", "optional", "not required")
    REQUIRED_MARKERS = ("必填参数", "必填", "required", "mandatory", "must")
    CONDITIONAL_MARKERS = ("条件参数", "条件必填", "依赖参数", "互斥参数", "二选一", "conditional", "depends on", "mutually exclusive")

    @classmethod
    def _normalize_role_value(cls, role):
        """将模型输出或文档标识统一映射为 required/optional/fixed。"""
        if role is None:
            return None
        role_text = str(role).strip()
        return cls.ROLE_ALIASES.get(role_text, cls.ROLE_ALIASES.get(role_text.lower()))

    @classmethod
    def _classify_parameter(cls, parameter: dict) -> str:
        """按固定值、选填、必填、默认必填的优先级识别参数角色。"""
        explicit_role = (
            parameter.get("param_role")
            or parameter.get("parameter_role")
            or parameter.get("role")
            or parameter.get("category")
        )
        role = cls._normalize_role_value(explicit_role)
        if role:
            return role

        if parameter.get("fixed_value") is not None:
            return "fixed"

        description = str(parameter.get("description") or "")
        description_lower = description.lower()
        if any(marker in description or marker in description_lower for marker in cls.FIXED_MARKERS):
            return "fixed"
        if any(marker in description or marker in description_lower for marker in cls.OPTIONAL_MARKERS):
            return "optional"
        if any(marker in description or marker in description_lower for marker in cls.CONDITIONAL_MARKERS):
            return "conditional"
        if any(marker in description or marker in description_lower for marker in cls.REQUIRED_MARKERS):
            return "required"
        if parameter.get("dependencies") or parameter.get("depends_on") or parameter.get("mutex_group"):
            return "conditional"
        if parameter.get("default") is not None or parameter.get("defaultValue") is not None:
            return "optional"
        if parameter.get("required") is False:
            return "optional"
        return "required"

    @staticmethod
    def _first_present_value(parameter: dict, field_names: list):
        """从多个候选字段中读取第一个显式提供的值。"""
        for field_name in field_names:
            if field_name in parameter and parameter.get(field_name) is not None:
                return parameter.get(field_name)
        return None

    @classmethod
    def _normalize_parameter(cls, parameter: dict):
        """补齐参数分类字段,并保持 fixed/optional/required 语义一致。"""
        if not isinstance(parameter, dict):
            return parameter

        role = cls._classify_parameter(parameter)
        if role not in cls.VALID_PARAM_ROLES:
            role = "required"

        parameter["param_role"] = role
        parameter["param_category"] = role
        parameter["required"] = role in {"required", "conditional", "fixed"}
        parameter["allow_omit"] = role == "optional"

        if parameter.get("default_value") is None:
            parameter["default_value"] = cls._first_present_value(parameter, ["default", "defaultValue"])

        if parameter.get("fixed_value") is None:
            parameter["fixed_value"] = cls._first_present_value(
                parameter,
                ["value", "const_value", "constant_value", "example", "sample"],
            )

        if role != "fixed":
            parameter["fixed_value"] = None

        if parameter.get("baseline_value") is None:
            if role == "fixed":
                parameter["baseline_value"] = parameter.get("fixed_value")
            else:
                parameter["baseline_value"] = cls._first_present_value(
                    parameter,
                    ["baseline", "valid_value", "validValue", "example", "sample", "value"],
                )
        if parameter.get("baseline_value") is None and parameter.get("default_value") is not None:
            parameter["baseline_value"] = parameter.get("default_value")

        if not parameter.get("data_category"):
            parameter["data_category"] = "baseline"

        dependencies = parameter.get("dependencies") or parameter.get("depends_on") or []
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        parameter["dependencies"] = dependencies

        if "mutex_group" not in parameter and parameter.get("mutexGroup") is not None:
            parameter["mutex_group"] = parameter.get("mutexGroup")

        strategies = parameter.get("test_strategy") or parameter.get("test_strategies") or []
        if isinstance(strategies, str):
            strategies = [strategies]
        if not strategies:
            strategies = ["control_variable"]
        parameter["test_strategy"] = strategies

        if not parameter.get("source_note"):
            parameter["source_note"] = (
                "文档标注为固定值参数" if role == "fixed"
                else "文档标注为选填参数" if role == "optional"
                else "文档标注为条件参数" if role == "conditional"
                else "文档标注为必填参数或未标注按必填处理"
            )

        for child_field in ("nested_fields", "array_item_fields"):
            children = parameter.get(child_field)
            if isinstance(children, list):
                parameter[child_field] = [cls._normalize_parameter(child) for child in children]
        return parameter

    @classmethod
    def _strip_base_url_from_path(cls, raw_path: str, base_url: Optional[str] = None) -> str:
        """
        Normalize an API URL into an executable relative path.

        Args:
            raw_path: URL/path extracted from the API document or generated case.
            base_url: Optional base URL used to remove duplicated prefixes.

        Returns:
            str: Relative request path such as /api/user/login.

        Exception handling:
            This helper is deliberately tolerant. Invalid or empty input returns
            an empty string so callers can fall back to the original API path.
        """
        if raw_path is None:
            return ""
        path = str(raw_path).strip()
        if not path:
            return ""

        for prefix in ("${{base_url}}", "{{base_url}}", "${base_url}", "{base_url}"):
            if path.startswith(prefix):
                path = path[len(prefix):].strip()

        if base_url:
            base_url_text = str(base_url).strip()
            if base_url_text and path.startswith(base_url_text):
                path = path[len(base_url_text):].strip()

        parts = urlsplit(path)
        if parts.scheme in {"http", "https"}:
            if base_url and path.startswith(str(base_url).strip()):
                path = path[len(str(base_url).strip()):].strip()
            elif parts.query.startswith("s="):
                path = parts.query[2:]
            else:
                path = parts.path or ""
                if parts.query:
                    path = f"{path}?{parts.query}"

        for marker in ("/index.php?s=", "index.php?s="):
            if path.startswith(marker):
                path = path[len(marker):]

        if path.startswith("?s="):
            path = path[3:]

        return path if not path or path.startswith("/") else f"/{path}"

    @classmethod
    def _normalize_endpoint(cls, api_info: dict) -> dict:
        """
        Preserve document URL semantics and normalize path/base_url fields.

        Args:
            api_info: Parsed interface document dictionary.

        Returns:
            dict: The same dictionary with raw_url preserved and path normalized.
        """
        if not isinstance(api_info, dict):
            return api_info

        base_url = api_info.get("base_url") or api_info.get("baseURL") or api_info.get("baseUrl")
        raw_url = api_info.get("raw_url") or api_info.get("url") or api_info.get("path")
        normalized_path = cls._strip_base_url_from_path(raw_url, base_url)
        if normalized_path:
            api_info["path"] = normalized_path
        if raw_url is not None:
            api_info["raw_url"] = raw_url
        if base_url:
            api_info["base_url"] = base_url
        return api_info

    @classmethod
    def normalize_parameter_roles(cls, api_info):
        """标准化单接口或批量接口的参数分类结果。"""
        if isinstance(api_info, list):
            return [cls.normalize_parameter_roles(item) for item in api_info]
        if not isinstance(api_info, dict):
            return api_info

        api_info = cls._normalize_endpoint(api_info)

        parameters = api_info.get("parameters")
        if isinstance(parameters, dict):
            for group_name in ("header", "path", "query"):
                group = parameters.get(group_name)
                if isinstance(group, list):
                    parameters[group_name] = [cls._normalize_parameter(item) for item in group]

        request_body = api_info.get("requestBody")
        if isinstance(request_body, dict):
            body = request_body.get("body")
            if isinstance(body, list):
                request_body["body"] = [cls._normalize_parameter(item) for item in body]

        return api_info

    def parser(self, api_document: str):
        """
        :param api_document:
        :param document_type:
        :return:
        """
        # 定义一个结果提取器
        parser = JsonOutputParser(pydantic_object=InterfaceDocumentParserModel)
        # 创建一个调用链
        chain = api_document_parser.prompt | llm | parser
        # 调用大模型对接口文档进行解析
        response = chain.invoke({"input_text": api_document})
        return self.normalize_parameter_roles(response)


if __name__ == '__main__':
    document2 = """
    ### 1.4 修改用户信息

```
PUT /api/users/{userId}
```

**请求参数**:

| 参数名   | 类型   | 必填 | 描述                     | 示例                                |
| -------- | ------ | ---- | ------------------------ | ----------------------------------- |
| nickname | string | 否   | ≤20字符                  | "新昵称"                            |
| avatar   | string | 否   | 图片URL                  | "https://mstest.com/new-avatar.jpg" |
| phone    | string | 否   | 手机号                   | 13800138000                         |
| gender   | string | 否   | "MALE"/"FEMALE"/"SECRET" | "MALE"                              |

**响应示例**:

```json
{
  "message": "更新成功"
}
```

### 
    """

    data = """
           ### 2.1 创建用户档案
           ```
           POST /api/users/{userId}/profile
           ```

           **路径参数**:
           | 参数名 | 类型   | 必填 | 描述   | 示例 |
           | ------ | ------ | ---- | ------ | ---- |
           | userId | string | 是   | 用户ID | 123  |

           **请求头参数**:
           | 参数名        | 类型   | 必填 | 描述         | 示例                    |
           | ------------- | ------ | ---- | ------------ | ----------------------- |
           | Authorization | string | 是   | 认证令牌     | Bearer abc123           |
           | Content-Type  | string | 是   | 内容类型     | application/json        |

           **查询参数**:
           | 参数名       | 类型    | 必填 | 描述           | 示例  |
           | ------------ | ------- | ---- | -------------- | ----- |
           | validate_only| boolean | 否   | 仅验证不保存   | false |

           **请求体 (JSON)**:
           ```json
           {
             "basic_info": {
               "first_name": "张",
               "last_name": "三",
               "birth_date": "1990-05-15",
               "gender": "male"
             },
             "contact_info": {
               "email": "zhangsan@example.com",
               "phone": "+86-13800138000",
               "emergency_contact": {
                 "name": "李四",
                 "relationship": "配偶",
                 "phone": "+86-13900139000"
               }
             },
             "addresses": [
               {
                 "type": "home",
                 "street": "北京市朝阳区建国路88号",
                 "city": "北京",
                 "postal_code": "100025",
                 "is_default": true
               }
             ],
             "preferences": {
               "language": "zh-CN",
               "notifications": {
                 "email_enabled": true,
                 "sms_enabled": false
               }
             },
             "skills": [
               {
                 "name": "Python",
                 "level": "advanced",
                 "certifications": [
                   {
                     "name": "Python Institute PCAP",
                     "issuer": "Python Institute",
                     "issue_date": "2022-03-15"
                   }
                 ]
               }
             ]
           }
           ```

           **请求体字段说明**:
           - basic_info (object, 必填): 用户基本信息
             - first_name (string, 必填): 名
             - last_name (string, 必填): 姓
             - birth_date (string, 可选): 出生日期，格式YYYY-MM-DD
             - gender (string, 可选): 性别，值为 male/female/other
           - contact_info (object, 必填): 联系信息
             - email (string, 必填): 电子邮箱
             - phone (string, 必填): 手机号码
             - emergency_contact (object, 可选): 紧急联系人
               - name (string, 必填): 联系人姓名
               - relationship (string, 必填): 关系
               - phone (string, 必填): 联系人电话
           - addresses (array, 必填): 地址列表
             - type (string, 必填): 地址类型，值为 home/work/billing
             - street (string, 必填): 街道地址
             - city (string, 必填): 城市
             - postal_code (string, 必填): 邮政编码
             - is_default (boolean, 可选): 是否默认地址
           - preferences (object, 可选): 用户偏好
             - language (string, 可选): 首选语言
             - notifications (object, 可选): 通知设置
               - email_enabled (boolean, 可选): 邮件通知开关
               - sms_enabled (boolean, 可选): 短信通知开关
           - skills (array, 可选): 技能列表
             - name (string, 必填): 技能名称
             - level (string, 必填): 技能水平，值为 beginner/intermediate/advanced/expert
             - certifications (array, 可选): 认证列表
               - name (string, 必填): 认证名称
               - issuer (string, 必填): 颁发机构
               - issue_date (string, 可选): 颁发日期

           **响应示例**:
           ```json
           {
             "success": true,
             "message": "用户档案创建成功",
             "data": {
               "profile_id": "prof_123456",
               "user_id": "123",
               "created_at": "2024-01-15T10:30:00Z"
             }
           }
           ```
       """
    api_parser = AIAPIDocumentParser()
    document = api_parser.parser(document2)
    import json

    print(json.dumps(document, indent=4, ensure_ascii=False))

"""


"""

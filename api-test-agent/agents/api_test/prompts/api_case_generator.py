
"""
结构化用例生成提示词

功能说明:
    本模块负责将基础测试用例（测试步骤描述）转换为完整可执行的接口测试用例。
    这是两阶段生成流程的第二阶段：可执行用例生成

参数说明:
    - api_case_output_format (dict): 用例输出格式定义，包含各字段的详细说明
    - case_info (str): 基础用例信息，包含用例名称和测试步骤描述
    - case_api (str): 目标接口的完整文档信息
    - other_api (str): 依赖接口的完整文档信息
    - test_data (dict): 测试数据，包含环境变量和测试参数
    - files_list (list): 可用于文件上传的测试文件列表
    - function_list (list): 可用的动态函数列表
    - additional_info (str): 补充说明信息

返回值:
    - Dict: 符合api_case_output_format定义的完整可执行测试用例

使用限制:
    - 本提示词专注于将测试步骤转换为可执行用例，填充具体的请求参数
    - 不包含断言逻辑，采用探索式测试模式
    - 除 param_role=fixed 的固定值参数外，所有测试数据必须通过变量引用，不能硬编码

依赖关系:
    - 输入来自base_case_generator.py生成的基础用例
    - 输出可直接被BaseTestCase执行器运行

设计理念:
    - 遵循探索式测试：只记录实际响应，不预设断言
    - 测试人员根据实际响应自行判断接口是否符合预期
"""
from langchain_core.prompts import PromptTemplate
from typing import Any, Dict, List

prompt = PromptTemplate(
    input_variables=[
        'api_case_output_format',
        'case_info',
        'case_api',
        'other_api',
        'test_data',
        'files_list',
        'function_list',
        'additional_info'
    ],
    template=r"""
你是一位资深的接口测试专家，精通 HTTP 协议、RESTful API 设计、JSON 数据结构和测试用例编写规范。
你同时具备将复杂测试需求结构化表达的能力，能够高效生成标准化、高质量的自动化测试用例。

## 核心设计理念

本提示词遵循**探索式测试**模式：
- 首要目标：了解接口的实际行为，记录真实的响应数据
- 不预设断言：测试人员根据实际响应自行判断接口是否符合预期
- 测试驱动开发：先发现接口实际表现，再确定期望行为

## URL字段强制规范
- request.base_url 和 preconditions[].request.base_url 必须固定输出为 `${{base_url}}`
- request.url 和 preconditions[].request.url 只能输出相对接口路径, 例如 `/api/user/login`
- url 字段禁止包含 `http://`、`https://`、`${{base_url}}`、`{{base_url}}`、 或 `/index.php?s=`
- 如果文档给出完整URL, 需要拆分: base_url 使用 `${{base_url}}`, url 只保留接口路径部分

---

## 一、测试用例分类体系

### 1.1 测试层次分类（按测试粒度）

#### L1-接口层测试
验证接口的基本功能和协议合规性：
- HTTP 方法是否正确（GET/POST/PUT/DELETE）
- URL 路径和参数是否正确
- Content-Type 是否与请求体匹配
- 基础鉴权是否生效

#### L2-参数层测试
验证参数的处理逻辑：
- 必填参数校验
- 参数类型校验
- 参数格式校验
- 参数长度校验
- 边界值处理

#### L3-业务层测试
验证业务逻辑的正确性：
- 参数间依赖关系
- 状态流转验证
- 权限控制检查
- 业务流程完整性

#### L4-安全层测试
验证接口的安全性：
- SQL 注入尝试
- XSS 攻击尝试
- 路径遍历尝试
- 特殊字符处理
- 未授权访问

#### L5-异常层测试
验证异常情况的处理：
- 错误参数组合
- 重复提交处理
- 并发请求处理
- 超时场景
- 网络异常

### 1.2 测试类型分类（按测试目标）

#### T1-正向测试
验证正常场景下的功能正确性：
- 使用有效参数发起请求
- 验证返回状态码为 2xx
- 记录完整的响应数据结构

#### T2-异常测试
验证异常输入的处理：
- 缺失必填参数
- 参数类型错误
- 参数格式错误
- 空值和 null 值
- 错误的数据组合

#### T3-边界测试
验证边界条件：
- 数值边界（0、负数、最大值、最小值）
- 字符串长度（空字符串、最大长度、最小长度）
- 集合大小（空数组、最大数量）
- 时间边界（最大超时、最小延迟）

#### T4-组合测试
验证多参数组合场景：
- 多个参数同时异常
- 参数间存在依赖关系
- 状态相关的参数组合
- 跨接口的数据组合

---

## 二、参数检查方法体系

### 2.1 基础验证
| 检查项 | 方法 | 关注点 |
|--------|------|--------|
| 必填参数 | 逐一置空验证 | 每个必填参数单独测试 |
| 参数类型 | 错误类型注入 | 期望字符串输入数字 |
| 空值处理 | null/空字符串测试 | 验证默认值或友好提示 |
| 默认值 | 不传参数测试 | 验证默认值是否生效 |

### 2.2 边界值分析
| 参数类型 | 边界点 | 测试值示例 |
|----------|--------|------------|
| 整数 | 0, ±1, 最大值, 溢出 | 0, -1, 1, 2147483647, 2147483648 |
| 字符串 | 0字符, 1字符, 最大长度, 超长 | "", "a", 255字符, 256字符 |
| 数组 | 空数组, 单元素, 最大数量 | [], [x], [max], [max+1] |
| 特殊值 | 0, 负数, 科学计数法 | 0, -1, 1e10 |

### 2.3 安全性检查
- SQL 注入：`' OR '1'='1`, `; DROP TABLE users;`
- XSS 攻击：`<script>alert(1)</script>`, `javascript:alert(1)`
- 路径遍历：`../../../etc/passwd`, `..\..\windows\system32`
- 特殊字符：`\n\t\r`, Unicode 编码, Emoji

### 2.4 业务逻辑检查
- 参数依赖：如修改密码需要旧密码
- 状态约束：如订单完成后不能修改
- 权限检查：如只有管理员能删除数据
- 业务规则：如用户名不能重复

---

## 三、生成测试用例时的详细规则说明

### 3.1 参数来源分析原则
必须逐一分析主接口中每个参数的来源，不能遗漏：
- 来自 **前置接口返回值** → 在 `preconditions.extract` 中定义提取规则，并在主请求中用 `${{变量名}}` 引用
- 来自 **测试数据** → 必须写 `${{变量名}}`，不能直接写固定值；param_role=fixed 的字段例外，必须直接写 fixed_value
- 来自 **动态生成** → 必须写在 `setup_script` 中生成，并通过 `test.save_test_env_variables` 保存为变量
- 如果用例是针对某一个参数值异常或者缺失的情况进行测试，请保存其他的参数的正确性和完整性

### 3.1.1 参数分类执行规则

接口文档中的参数可能带有 `param_role`、`fixed_value`、`default_value`、`allow_omit`、`baseline_value` 字段。生成可执行用例时必须严格遵守：

- `param_role=fixed`: 固定值参数。baseline_value = fixed_value，正常用例和非目标参数中必须直接使用 `fixed_value`，不得使用变量引用；只有当基础用例明确测试"固定值被篡改"时，才允许改为错误值。
- `param_role=required`: 必填参数。baseline_value 用于正向测试；除"必填参数缺失"专项用例外，请始终包含该字段。
- `param_role=optional`: 选填参数。baseline_value 和 default_value 都可能存在；需生成省略/显式default/显式baseline三种场景。
- `param_role=conditional`: 条件参数。需根据 dependencies 和 mutex_group 规则处理。
- 未出现 `param_role` 的历史参数按 required 处理。

**Baseline Data 核心规则**：

```
生成规则：
  1. 正向测试：所有参数使用 baseline_value 或 fixed_value
  2. 单参数测试：只改变目标参数，其他参数保持 baseline_value/fixed_value
  3. 禁止：同时改变多个参数
  4. 禁止：非目标参数使用错误值
```

**Optional 参数测试规则**：

```
当 optional 参数作为目标参数时：
  - 省略该参数
  - 显式传 default_value（若存在）
  - 显式传 baseline_value（若存在且不同于 default_value）

当 optional 参数不是目标参数时：
  - 正向测试：使用 baseline_value 或 default_value
  - 单参数异常测试：默认省略
```

**控制变量法规则**：

```
单参数测试必须构造 baseline_request：
  baseline_request = fixed_value + baseline_value + default_value

测试时只改变目标参数，其他参数保持 baseline：
  ✅ 正确示例：
      测试 pwd 边界-最小值-1
      body: {{type: "username", accounts: "czj11", pwd: ""}}

  ❌ 禁止示例：
      同时改变 type 和 accounts
      body: {{type: "wrong", accounts: "", pwd: ""}}
```

- 一条异常用例只改变目标参数，其它 fixed/required 参数保持文档要求的正确值。

特别注意：
- **命名不规范的参数**（例如接口文档写 `project` 实际表示 `project_id`）必须识别并处理
- **鉴权信息**：必须确认是否需要 token，并正确提取/引用
- **引用资源 id**：如 `user` 实际表示 `user_id`，必须从前置接口提取

### 3.2 依赖参数识别方法
常见必须从前置接口获取的字段：
- 认证令牌：`token`、`access_key`、`authorization`
- 资源 ID：`user_id`、`order_id`、`project_id`、`file_id`
- 状态/步骤：`status`、`step`、`phase`、`progress`
- 关联对象：`reference_id`、`parent_id`、`related_id`

### 3.3 multipart/form-data 类型接口的处理
- `Content-Type=multipart/form-data` 时：
  ```json
  "body": {{{{}}}},
  "files": {{
    "pic": ["文件名", "文件路径", "文件类型"],
    "name": "张三",
    "age": 18
  }}
  ```
- 文件必须从 {files_list} 中选择
- 如果不是 multipart，则：
  ```json
  "body": {{...}},
  "files": {{{{}}}}
  ```

### 3.4 脚本执行上下文可用变量

脚本通过 `exec()` 执行，上下文中注入了以下变量：

| 变量名 | 类型 | 说明 | 可用阶段 |
|--------|------|------|---------|
| `test` | BaseTestCase | 当前测试用例执行器实例 | setup + teardown |
| `global_function` | module | 工具函数模块（见下方函数列表） | setup + teardown |
| `test_env_variables` | dict | 环境变量字典，可直接读写 | setup + teardown |
| `get` | function | 便捷读取环境变量：`get(key, default="")` | setup + teardown |
| `db` | DBClient | 数据库客户端实例 | setup + teardown |
| `response` | Response | HTTP 响应对象（仅 teardown 可用） | teardown |

#### `test` 对象可用方法

| 方法 | 说明 | 示例 |
|------|------|------|
| `test.save_test_env_variables(name, value)` | 保存环境变量，后续步骤可引用 | `test.save_test_env_variables("token", token)` |
| `test.get_test_env_variables(name)` | 读取环境变量 | `token = test.get_test_env_variables("token")` |
| `test.json_extract(jmespath, response)` | 从响应中提取数据 | `uid = test.json_extract("data.id", response)` |

#### `global_function` 可用函数列表

| 函数 | 说明 |
|------|------|
| `global_function.random_mobile()` | 随机生成手机号 |
| `global_function.random_account()` | 随机生成6-18位账号 |
| `global_function.random_password()` | 随机生成8-16位密码 |
| `global_function.random_email()` | 随机生成邮箱 |
| `global_function.random_name()` | 随机生成中文名字 |
| `global_function.random_ssn()` | 随机生成身份证号 |
| `global_function.random_addr()` | 随机生成地址 |
| `global_function.random_city()` | 随机生成城市名 |
| `global_function.random_company()` | 随机生成公司名 |
| `global_function.random_postcode()` | 随机生成邮编 |
| `global_function.random_date()` | 随机生成日期 |
| `global_function.radom_date_time()` | 随机生成日期时间 |
| `global_function.random_ipv4()` | 随机生成IPv4地址 |
| `global_function.get_timestamp()` | 获取当前时间戳 |
| `global_function.base64_encode(data)` | Base64编码 |
| `global_function.md5_encrypt(data)` | MD5加密 |
| `global_function.rsa_encrypt(msg, pub_key)` | RSA加密 |

#### `response` 对象结构（仅 teardown_script 可用）

| 属性/方法 | 说明 | 示例 |
|-----------|------|------|
| `response.status_code` | HTTP 状态码 | `code = response.status_code` |
| `response.text` | 响应体原始文本 | `raw = response.text` |
| `response.json()` | 解析后的 JSON 对象 | `data = response.json()` |
| `response.headers` | 响应头字典 | `ct = response.headers.get("Content-Type")` |

#### 读取环境变量的三种方式

```python
# 方式1：通过 get() 函数（推荐）
token = get("token", default="")

# 方式2：通过 test 对象
token = test.get_test_env_variables("token")

# 方式3：直接读字典
token = test_env_variables.get("token", "")
```

### 3.5 setup_script 规则
- 用途：生成动态数据并保存为环境变量
- 工具函数：来自 {function_list}
- 示例：
  ```python
  mobile = global_function.random_mobile()
  test.save_test_env_variables("mobile", mobile)
  ```
- 约束：
  - 不能出现 `print`、`assert`、非必要 import
  - 保存环境变量后，在 body/headers 中引用时必须写 `${{变量名}}`
  - setup_script 中 **禁止直接硬编码到 body**

### 3.6 teardown_script 规则
- 用途：清理或提取数据，不写断言逻辑
- 可使用 `test`、`global_function`、`get()`、`response`
- 示例：
  ```python
  order_id = test.json_extract("data.order_id", response)
  test.save_test_env_variables("order_id", order_id)
  ```
- 约束：
  - 必须是合法 Python 代码，可被 `exec` 执行
  - 若无逻辑，必须输出 `""`

#### 严格禁止的写法

| 错误写法 | 正确写法 | 说明 |
|----------|----------|------|
| `request.response_body` | `response.text` 或 `response.json()` | 上下文中没有 `request` 变量 |
| `global_function.get("key")` | `get("key")` | `global_function` 没有 `get` 方法 |
| `response["status_code"]` | `response.status_code` | response 是对象，不是字典 |

### 3.7 变量提取与引用
- 提取：`extract` 使用二维数组形式：
  ```json
  "extract": [
    ["变量名", "jmespath表达式"]
  ]
  ```
- 引用：`${{变量名}}`
- 特别注意：
  - 不能在 JSON 中直接写函数调用（如 `global_function.xxx`），必须先在脚本中赋值保存为变量

### 3.8 测试数据引用规范
- 所有 {test_data} 提供的变量必须引用，不能硬编码；param_role=fixed 的固定值参数例外，必须直接使用文档中的 fixed_value
- 当用例使用数据文件中的 baseline/boundary/abnormal/security 数据时，必须在顶层输出 `data_ref`，例如 `test_data.baseline` 或 `test_data.boundary.pwd_min_minus`
- `data_ref` 指向的数据会由系统解析为 `_test_data`，并保留 `_data_lineage`；你不要在请求体中写 `{{baseline.xxx}}` 或 `${{baseline.xxx}}` 这类继承引用
- 请求 body/headers 中仍只使用 `${{变量名}}` 普通变量语法；baseline 继承和覆盖关系只存在于数据文件和 `_data_lineage`
- 例如：
  ```json
  "body": {{
    "username": "${{username}}",
    "password": "${{password}}"
  }}
  ```

### 3.9 请求头设置
- 有请求体时，必须写 `"Content-Type"`
- 鉴权必须正确拼接，例如：
  ```json
  "Authorization": "Bearer ${{token}}"
  ```

### 3.10 路径参数
- 若 URL 中存在动态参数（如 `/api/users/{{id}}`），必须用 `${{变量}}` 形式替换

### 3.11 空值约束
- 无内容时必须显式输出：
  - 对象：`{{}}`
  - 数组：`[]`
  - 字符串：`""`

---

## 四、用户提供的输入信息

### 4.1 测试用例基础信息（来自基础用例生成阶段）
{case_info}

### 4.2 当前测试用例接口文档
{case_api}

### 4.3 依赖接口文档
{other_api}

### 4.4 测试数据
{test_data}

### 4.5 可用文件列表
{files_list}

### 4.6 动态函数列表
{function_list}

---

## 五、补充说明
{additional_info}

---

## 六、输出要求

### 6.1 输出格式定义
请严格按照以下 JSON Schema 输出测试用例集：

{api_case_output_format}

### 6.2 用例命名规范
采用 `[层次]-[类型]-[场景]-[输入]` 格式：
- 示例：`L2-T2-参数缺失-用户名必填`
- 示例：`L4-T4-SQL注入-字符串参数`
- 示例：`L1-T1-正向测试-正常登录`

### 6.3 用例描述编写规范
每个用例的 `description` 应包含：
1. **测试目标**：验证什么，期望什么结果
2. **观察要点**：重点关注哪些方面
3. **探索点**：可能存在的潜在问题

### 6.4 输出约束
- 输出必须为合法 JSON 数据（不能带 markdown 格式或解释）
- 输出的用例字段不得遗漏或虚构新增
- 格式必须严格遵循 Schema 定义
- 空对象/数组必须显式写出
- 字段顺序必须与格式定义一致

### 6.5 质量标准
- **独立性**：每个用例可单独执行
- **可重复**：相同输入产生相同结果
- **清晰性**：命名和描述无歧义
- **可追溯**：与接口文档字段一一对应

---

请根据上述信息生成完整的可执行测试用例，确保符合探索式测试模式的要求。
"""
)
api_case_output_format = {
    "name": "用例名称（格式：[层次]-[类型]-[场景]-[输入]，例如：L2-T2-参数缺失-用户名必填）",
    "description": "用例描述（说明测试目标、观察要点和探索点，引导测试人员关注正确的验证方向）",
    "interface": "接口路径（与被测主接口对应，例如 /api/users/register）",
    "data_ref": "可选，测试数据引用路径，例如 test_data.baseline 或 test_data.boundary.pwd_min_minus；无数据引用时为空字符串",
    "preconditions": [
        {
            "name": "前置步骤名称（说明依赖接口的用途）",
            "request": {
                "interface_id": "前置接口ID（唯一标识，可与接口文档保持一致）",
                "method": "HTTP方法（如：GET、POST、PUT、DELETE）",
                "url": "接口路径（如 /api/users/login）",
                "base_url": "测试环境的基础地址（必须严格使用 ${{base_url}} 格式，禁止硬编码完整URL或省略$符号）",
                "headers": "请求头信息（必须包含Content-Type，若需鉴权则包含Authorization）",
                "params": "查询参数（URL上的?key=value形式参数，若无则为空对象）",
                "body": "请求体（application/json请求体参数，若无则为空对象）",
                "files": "仅multipart/form-data时使用，文件参数需从文件列表选择，非文件参数也放在此处",
                "setup_script": "前置脚本（Python代码，用于生成动态数据并保存环境变量，禁止直接写死到body）",
                "teardown_script": "后置脚本（Python代码，用于清理或提取必要数据，若无则为空字符串）"
            },
            "extract": [
                ["变量名", "jmespath表达式（从接口响应中提取的字段路径，例如 token 或 data.id）"]
            ]
        }
    ],
    "request": {
        "interface_id": "主接口ID（唯一标识，用于区分不同接口）",
        "method": "HTTP方法（如：POST）",
        "url": "接口路径（例如 /api/users/register）",
        "base_url": "测试环境的基础地址（必须写为 ${{base_url}}）",
        "headers": "请求头信息（必须根据接口类型配置，例如 application/json 或 multipart/form-data）",
        "params": "查询参数（键值对形式，若无则为空对象）",
        "body": "请求体参数（除param_role=fixed的固定值外，所有测试数据必须用 ${{变量}} 引用，不能硬编码）",
        "files": "当Content-Type为multipart/form-data时必填，否则固定为空对象",
        "setup_script": "前置脚本（Python代码，用于生成本用例需要的动态变量，调用global_function后必须用test.save_test_env_variables保存）",
        "teardown_script": "后置脚本（Python代码，执行清理或额外数据提取，若无则为空字符串）",
        "_test_data": "可选，由系统根据data_ref解析后注入，包含扁平化可执行数据；生成时可为空对象",
        "_baseline_data": "基准数据字典，包含所有参数的baseline_value，用于正向测试和控制变量法参照",
        "_data_lineage": "【新增】数据溯源信息，记录字段来源和继承关系"
    }
}


def generate_baseline_data(api_info: Dict, test_data: Dict = None) -> Dict[str, Any]:
    """
    从API信息和测试数据生成基准数据

    根据Baseline Data判定规则：
    1. fixed参数：baseline_value = fixed_value
    2. required参数：从test_data或规则生成
    3. optional参数：可使用default_value或baseline_value

    Args:
        api_info: API解析后的信息
        test_data: 测试数据文件中的baseline数据

    Returns:
        基准数据字典 {param_name: baseline_value}
    """
    baseline = {}

    request_body = api_info.get('requestBody', {})
    if isinstance(request_body, dict):
        body_params = request_body.get('body', [])
    else:
        body_params = []

    for param in body_params:
        if not isinstance(param, dict):
            continue

        param_name = param.get('name', '')
        param_role = param.get('param_role', 'required')
        fixed_value = param.get('fixed_value')
        baseline_value = param.get('baseline_value')
        default_value = param.get('default_value')

        if param_role == 'fixed' and fixed_value is not None:
            baseline[param_name] = fixed_value
        elif baseline_value is not None:
            baseline[param_name] = baseline_value
        elif test_data and param_name in test_data:
            baseline[param_name] = test_data[param_name]
        elif default_value is not None:
            baseline[param_name] = default_value
        else:
            baseline[param_name] = _generate_reasonable_baseline(param)

    return baseline


def _generate_reasonable_baseline(param: Dict) -> str:
    """
    根据参数信息生成合理的baseline值

    Args:
        param: 参数定义字典

    Returns:
        生成的baseline值
    """
    param_type = param.get('type', 'string')
    description = param.get('description', '').lower()

    if param_type == 'string':
        if 'account' in description or 'user' in description:
            return 'testuser001'
        elif 'pwd' in description or 'password' in description:
            return 'TestPass123'
        elif 'name' in description or 'title' in description:
            return '测试名称'
        elif 'mobile' in description or 'phone' in description:
            return '13800138000'
        elif 'email' in description:
            return 'test@example.com'
        else:
            return 'test_value'

    elif param_type in ('integer', 'number'):
        return 100

    elif param_type == 'boolean':
        return True

    return 'test_value'


def build_case_with_baseline(
    case_template: Dict,
    baseline_data: Dict,
    test_value: Any,
    target_param: str
) -> Dict[str, Any]:
    """
    使用控制变量法构建测试用例

    核心规则：
    - baseline_request = fixed_value + baseline_value + default_value
    - 只改变目标参数，其他参数保持baseline

    Args:
        case_template: 用例模板
        baseline_data: 基准数据
        test_value: 测试目标参数的值
        target_param: 目标参数名

    Returns:
        构建后的用例
    """
    case = case_template.copy()

    body = case.get('request', {}).get('body', {})
    for param_name, baseline_value in baseline_data.items():
        if param_name == target_param:
            body[param_name] = test_value
        else:
            body[param_name] = baseline_value

    if 'request' not in case:
        case['request'] = {}
    case['request']['body'] = body

    return case

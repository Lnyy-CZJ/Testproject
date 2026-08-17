from langchain_core.prompts import PromptTemplate

prompt = PromptTemplate(
    input_variables=["document", "missing_testcases", "existing_cases", "additional_context", "format_instructions"],
    template="""
你是一名资深测试架构师。

请根据【缺失测试点】生成补充测试用例。
生成数量必须与【缺失测试点】一一对应：每一个缺失测试点必须输出一个补充测试用例。

根据：

缺失测试点
已有测试用例
需求文档

生成新的测试用例。

如果【需求文档】以“结构化需求测试点生成上下文”开头，表示输入来自 requirement_decomposition 的 test_seed 聚合结果：

1. 补充用例时优先参考其中的测试对象、业务约束、权限规则、有效状态流转、无效状态流转、预期结果、负向建议和风险标签。

2. 不确定项只能生成“需确认”类测试用例，case_name 和 expected_result 必须体现“需确认”，不得写成已确认需求事实。

3. 仍必须以【缺失测试点】为主，不得脱离缺失测试点额外扩展新用例。

输入格式：

{{
"test_point_id":"TP001",
"module":"",
"feature":"",
"scenario":"",
"test_point":"",
"risk_level":"P1",
"reason":""
}}

字段说明：

test_point_id：
关联测试点ID

module：
业务模块

feature：
功能点

scenario：
对象节点

test_point：
叶子测试点

risk_level：
风险等级

reason：
缺失原因

输出格式：

{{
"case_id":"TC001",
"test_point_id":"TP001",
"module":"",
"feature":"",
"scenario":"",
"case_name":"",
"priority":"P1",
"preconditions":[],
"test_steps":[],
"test_data":{{}},
"expected_result":"",
"actual_result":""
}}

规则1：

一个缺失测试点生成一个测试用例。

本批次输入 N 个缺失测试点，输出必须为 N 条测试用例。

规则2：

case_name格式：

Feature-Scenario-TestPoint

例如：

密码登录-用户名-为空

规则3：

priority直接继承risk_level。

禁止重新评估优先级。

规则4：

test_point_id必须保留。

用于建立测试点与测试用例关联。

规则5：

测试步骤必须围绕当前测试点。

禁止跨测试点设计。

规则6：

按测试点语义生成可执行步骤：

- 业务约束：验证规则是否生效
- 权限规则：包含角色或权限状态
- 有效状态流转：包含起始状态、触发动作、目标状态
- 无效状态流转：包含非法状态或非法动作，并验证系统阻断
- 负向建议、风险标签、异常、边界、兼容、并发、幂等：测试数据和预期结果必须覆盖对应风险
- 不确定项、需确认、待确认：用例必须标记为需确认类，不得作为已确认需求事实

正确示例：

测试点：

用户名 → 为空

生成：

用户名为空

错误示例：

用户名为空 + 密码为空

已有测试用例：

{existing_cases}

生成前必须检查：

test_point_id

只允许用 test_point_id 判断是否已存在同一测试点的用例。

以下情况视为重复：

test_point_id相同

则禁止生成。

case_name 相似、验证目标相近、UI 聚合名称相同，但 test_point_id 不同，不视为重复，不得过滤。

{document}

测试设计补充要求（非需求事实）：
{additional_context}
说明：补充要求只能用于调整覆盖侧重点，不得覆盖、修改或虚构需求文档中的事实。

{missing_testcases}

必须提供：

合法测试数据
当前测试点需要的数据

例如：

测试点：

用户名为空

则：

{{
"username":"",
"password":"Test123456"
}}

必须：

明确
可验证
可执行

禁止：

登录正常

允许：

提示用户名不能为空，登录失败

case_id连续递增：

TC001
TC002
TC003

...

如果已有最大编号：

TC020

则新增从：

TC021

开始。

{format_instructions}

格式定义：

[
{{
"case_id":"TC021",
"module":"登录",
"feature":"密码登录",
"scenario":"用户名",
"case_name":"密码登录-用户名-超过最大长度",
"priority":"P1",
"preconditions":[
"用户进入登录页面"
],
"test_steps":[
"输入长度超过限制的用户名",
"输入正确密码",
"点击登录按钮"
],
"test_data":{{
"username":"abcdefghijklmnopqrstu",
"password":"Test123456"
}},
"expected_result":"系统提示用户名长度超过限制，登录失败",
"actual_result":""
}}
]

禁止输出：

✗ 分析过程

✗ 推理过程

✗ Markdown

✗ 解释说明

✗ JSON之外的任何内容

如果没有需要补充的测试用例：

[]

必须输出合法JSON。

必须能够通过：

json.loads()

直接解析。
"""
)

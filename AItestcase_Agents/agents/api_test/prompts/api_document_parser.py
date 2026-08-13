
from langchain_core.prompts import PromptTemplate

# 接口文档解析提示词
prompt = PromptTemplate(
    input_variables=["input_text"],
    template="""
    你是一个接口分析专家，请你从下方提供的接口文本描述中提取接口关键信息，
    并转换为统一结构化 JSON 格式

    ### 重要约束
        - 严禁编造或推测文档中未明确提及的信息
        - 只提取文档中明确存在的字段和参数
        - 如果某个字段在文档中不存在，请设置为 null 或空数组
        - 不要添加任何文档中没有的示例数据或默认值

    ### 规则说明
        - 每个参数都包含name,type,description,required这几个字段
        - 请求体中每个字段都需标注 required，若文档无明确说明，默认true（保守原则）
        - 每个参数还必须输出参数分类字段: param_role、fixed_value、default_value、allow_omit、source_note
        - param_role 只能取 required、optional、conditional、fixed 四个值:
          * 文档标注为"固定值/固定参数/不可变/constant/fixed value"的字段，param_role=fixed，required=true，allow_omit=false，fixed_value 必须等于文档指定值
          * 文档标注为"选填参数/选填/可选/非必填/optional"的字段，param_role=optional，required=false，allow_omit=true
          * 文档标注为"必填参数/必填/required"的字段，param_role=required，required=true，allow_omit=false
          * 文档标注为"条件参数/依赖参数/conditional"的字段，param_role=conditional，保留dependencies字段
          * 未标注参数默认 param_role=required，required=true，allow_omit=false
        - 如果文档给出默认值，必须写入 default_value；如果没有默认值，default_value 为 null
        - 固定值只能来自文档明确给出的值或示例值，严禁凭空推断固定值
        - source_note 需要简要记录分类依据，例如"文档标注为固定值"或"未标注按必填处理"

        ### Baseline Data 判定规则（新增）
        - baseline_value: 参数的基准数据值，用于正向测试和控制变量法的参照基准
          * param_role=fixed 时，baseline_value = fixed_value
          * 文档明确标注"基准数据"/"有效数据"时，baseline_value = 文档值
          * 未标注但出现在正常请求示例中的值，可作为baseline_value
          * 没有任何数据时，根据参数类型和约束生成合理baseline
        - data_category: 数据分类，可选 baseline/boundary/abnormal/security
          * 大多数参数默认 data_category = baseline
          * 仅当参数有特殊测试需求时才标注其他分类

        ### 参数关系定义（新增）
        - dependencies: 当前参数依赖的其它参数列表，如 city 依赖 province
        - mutex_group: 互斥参数组名称，表示哪些参数不能同时使用

        - 如果文档包含 baseURL/base_url/baseUrl, 必须写入 base_url
        - 如果文档包含接口 url, 必须写入 raw_url; path 必须只保留相对接口路径, 不能包含 base_url 或完整域名
        - 参数需要按类型分类到 header、path、query 三个数组中,
        - 对于常见的非必填请求头无需保存到header中,比如：Accept-Encoding，Accept-Language、Origin等等
        - 路径参数识别：URL中用{{}}包围的变量（如{{userId}}、{{id}}，{{user_id}}）
        - 无请求体时，requestBody 各字段均填 null
        - 响应需要包含 http_code、description、media_type 和 response_body
        - 如果文档中没有明确的响应示例，response_body 设置为空对象 {{}}
        - nested_fields 字段：仅当字段 type 为 "object" 时才包含此字段，用于描述对象内部的字段结构
        - array_item_fields 字段：仅当字段 type 为 "array" 时才包含此字段，用于描述数组元素的字段结构
        - 对于 string、integer、boolean、number 等基础类型，不要包含 nested_fields 和 array_item_fields 字段

    ### 输出格式要求如下：
        {{
          "base_url": "文档中明确提供的基础地址,如 http://host/index.php?s=; 未提供则为 null",
          "raw_url": "文档中接口原始URL,可以是完整URL或相对路径",
          "path": "规范化后的API相对路径,必须是不含base_url的路径,如 /api/user/login",
          "method": "HTTP方法(GET/POST/PUT/DELETE等)",
          "summary": "接口的简要名称",
          "parameters": {{
            "header": [{{
                "name": "参数名",
                "type": "参数类型",
                "description": "参数说明",
                "required": true/false,
                "param_role": "required|optional|fixed",
                "fixed_value": "固定值参数的文档指定值，非固定值为null",
                "default_value": "默认值，无默认值为null",
                "allow_omit": true/false,
                "source_note": "参数分类依据"
            }}],
            "path": [{{
                "name": "参数名",
                "type": "参数类型",
                "description": "参数说明",
                "required": true/false,
                "param_role": "required|optional|fixed",
                "fixed_value": "固定值参数的文档指定值，非固定值为null",
                "default_value": "默认值，无默认值为null",
                "allow_omit": true/false,
                "source_note": "参数分类依据"
            }}],
            "query": [{{
                "name": "参数名",
                "type": "参数类型",
                "description": "参数说明",
                "required": true/false,
                "param_role": "required|optional|fixed",
                "fixed_value": "固定值参数的文档指定值，非固定值为null",
                "default_value": "默认值，无默认值为null",
                "allow_omit": true/false,
                "source_note": "参数分类依据"
            }}]
          }},
          "requestBody": {{
            "content_type": "请求体类型，如 application/json，无请求体时为null",
            "body": [
              {{
                "name": "字段名",
                "type": "string|integer|boolean|number等基础类型",
                "description": "字段说明",
                "required": true/false,
                "param_role": "required|optional|fixed",
                "fixed_value": "固定值参数的文档指定值，非固定值为null",
                "default_value": "默认值，无默认值为null",
                "allow_omit": true/false,
                "source_note": "参数分类依据"
              }},
              {{
                "name": "对象字段名",
                "type": "object",
                "description": "对象字段说明",
                "required": true/false,
                "param_role": "required|optional|fixed",
                "fixed_value": "固定值参数的文档指定值，非固定值为null",
                "default_value": "默认值，无默认值为null",
                "allow_omit": true/false,
                "source_note": "参数分类依据",
                "nested_fields": [{{
                  "name": "嵌套字段名",
                  "type": "字段类型",
                  "description": "嵌套字段说明",
                  "required": true/false,
                  "param_role": "required|optional|fixed",
                  "fixed_value": "固定值参数的文档指定值，非固定值为null",
                  "default_value": "默认值，无默认值为null",
                  "allow_omit": true/false,
                  "source_note": "参数分类依据"
                }}]
              }},
              {{
                "name": "数组字段名",
                "type": "array",
                "description": "数组字段说明",
                "required": true/false,
                "param_role": "required|optional|fixed",
                "fixed_value": "固定值参数的文档指定值，非固定值为null",
                "default_value": "默认值，无默认值为null",
                "allow_omit": true/false,
                "source_note": "参数分类依据",
                "array_item_fields": [{{
                  "name": "数组元素字段名",
                  "type": "字段类型",
                  "description": "数组元素字段说明",
                  "required": true/false,
                  "param_role": "required|optional|fixed",
                  "fixed_value": "固定值参数的文档指定值，非固定值为null",
                  "default_value": "默认值，无默认值为null",
                  "allow_omit": true/false,
                  "source_note": "参数分类依据"
                }}]
              }}
            ]
          }},
          "responses": [{{
            "http_code": "状态码",
            "description": "响应描述",
            "media_type": "响应内容类型，如 application/json",
            "response_body": {{"示例响应数据": "值"}}
          }}]
        }}
    请处理以下接口数据，输出结构化结果
    {input_text}
""")


"""
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$session.UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
Invoke-WebRequest -UseBasicParsing -Uri "http://106.54.233.149:15899/api/TestInterFace/interfaces/?project=1" `
-WebSession $session `
-Headers @{
"Accept"="application/json, text/plain, */*"
  "Accept-Encoding"="gzip, deflate"
  "Accept-Language"="zh-CN,zh;q=0.9"
  "Authorization"="Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzU2NjQzMTE5LCJpYXQiOjE3NTY1NTY3MTksImp0aSI6IjVlNmZmMTY0OGJlNjQ3ZjhiZmRjMjBhZjFiYTJiZjQ4IiwidXNlcl9pZCI6MX0.AwdsFWjflMScN-1J5LhFkfOy8JMFeERNl0_dQHaDk9U"
  "Origin"="http://www.mstest.vip:5899"
  "Referer"="http://www.mstest.vip:5899/"
}

"""

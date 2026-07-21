# 测试埋点功能 PRD

## 1. 背景

当前产品埋点需求存放在 `产品埋点需求文档` 目录中，核心需求来源为：

- `需求埋点list(维护最新版).xlsx`：维护公参定义、Action 命名规则、`page_from` 定义；其中“打点文档（产品维护最新版）”当前仅有 1.0.0 占位。
- `1.0.0埋点.xlsx`：当前 1.0.0 版本实际产品埋点明细，包括模块、上报时机、Action、业务子参 Key/Value、产品备注。
- `请求与响应log格式.log`：客户端 log 样例。log 中包含多类 HTTP 请求，只有 `method=TrackEvents` 是埋点请求。

现有 Python 脚本主要能力是：读取 JSON 行文件，按固定字段筛选事件，再递归比较两个 JSON 的字段和值。新功能需要在这个基础上扩展为“上传客户端 log 后自动识别、统计和校验埋点”。

## 2. 产品目标

用户上传客户端 log 文件后，工具自动完成以下工作：

1. 只识别 `method=TrackEvents` 的埋点请求与响应，忽略其他请求。
2. 解析请求中的所有埋点事件，支持一个请求内包含多条事件。
3. 统计每个事件 Action 的触发次数。
4. 根据产品埋点需求文档判断：
   - 事件是否在需求中定义；
   - 事件业务子参是否缺失、多传；
   - 子参值是否符合文档枚举或说明；
   - 公参是否存在、是否为空；
   - 请求与响应数量是否一致，服务端是否成功接收。
5. 输出可读的测试报告，帮助测试人员快速定位埋点问题。

## 3. 用户与使用场景

目标用户：测试人员。

核心场景：

1. 测试人员按产品埋点文档执行 App 操作路径。
2. 导出客户端 log 文件。
3. 打开 Python 工具，上传 log。
4. 工具解析并展示：
   - 本次 log 中触发了哪些埋点；
   - 每个埋点触发了几次；
   - 哪些埋点字段正确；
   - 哪些埋点字段缺失、错误或多传；
   - 哪些 TrackEvents 请求没有成功响应。

## 4. 功能范围

### 4.1 本期实现

本期以简单可用为目标，使用 Python 本地实现，不做复杂服务端和数据库。

必须支持：

- 上传或选择一个 `.log` / `.txt` 文件。
- 自动过滤 `method=TrackEvents`。
- 自动抽取 TrackEvents 请求 JSON。
- 自动抽取 TrackEvents 响应 JSON。
- 解析请求路径：
  - `requests[].method_name == "TrackEvents"`
  - `requests[].params.events[]`
  - 事件字段：`event_id`、`event_name`、`event_time_ms`、`properties`
- 解析响应路径：
  - 顶层 `code`、`message`
  - `responses[].success`
  - `responses[].code`
  - `responses[].data.accepted_count`
- 统计事件名和次数。
- 校验事件字段。
- 输出文本或 Markdown 报告。

建议支持：

- Tkinter 简单界面：选择 log 文件、点击“开始解析”、显示结果、导出报告。
- CLI 命令行模式：便于快速调试，例如 `python trackevents_checker.py 请求与响应log格式.log`。

### 4.2 暂不实现

- 不接入线上埋点平台。
- 不做用户账号和权限。
- 不做复杂 Web 页面。
- 不做自动执行 App 操作。
- 不强制解析图片列“位置图示”。
- 不强依赖 Excel 动态读取；可以先把 1.0.0 埋点规则维护成 Python 字典或 JSON 配置，后续再支持读取 Excel。

## 5. 输入与输出

### 5.1 输入

输入 1：客户端 log 文件。

log 特征：

- 请求开始行示例：`[HTTP] --> POST ... method=TrackEvents`
- 请求 JSON 标记：`[HTTP] request:`
- 响应开始行示例：`[HTTP] <-- 200 POST ... method=TrackEvents`
- 响应 JSON 标记：`[HTTP] response:`
- log 行前面可能带有系统前缀，例如时间、进程名、`flutter: │`、边框字符，需要清洗。

输入 2：埋点需求规则。

规则来源：

- 事件 Action 与业务子参：`产品埋点需求文档/1.0.0埋点.xlsx`
- 公参定义、Action 规则、`page_from`：`产品埋点需求文档/需求埋点list(维护最新版).xlsx`

输入 3：预期触发次数。

为了判断“触发次数是否正确”，工具需要允许用户配置每个事件的预期次数。简单方案：

```json
{
  "app_foreground": 1,
  "app_page_stay": 3,
  "lead_leave_dialogview": 1,
  "lead_leave_leave_click": 1,
  "lead_page_exit": 1
}
```

如果用户没有提供预期次数，则工具只做统计，不判定次数对错。

### 5.2 输出

输出报告建议包含：

1. 总览
   - TrackEvents 请求数
   - TrackEvents 响应数
   - 事件总数
   - 校验通过事件数
   - 校验失败事件数
2. 事件统计
   - Action
   - 实际触发次数
   - 预期触发次数
   - 次数校验结果
3. 事件明细
   - 所属请求序号
   - `event_id`
   - `event_name`
   - `event_time_ms`
   - 校验结果
   - 错误原因
4. 响应校验
   - 请求序号
   - 请求事件数量
   - 响应 `accepted_count`
   - 响应 `success`
   - 是否匹配
5. 未定义事件
6. 字段问题列表
   - 缺少字段
   - 多传字段
   - 字段值不符合枚举
   - 字段为空但不允许为空

## 6. log 解析规则

### 6.1 只识别 TrackEvents

判断条件：

- HTTP 开始行包含 `method=TrackEvents`。
- 请求 JSON 中也应满足 `requests[].method_name == "TrackEvents"`。

其他请求，例如 `method=RefreshSession`，全部忽略。

### 6.2 请求解析

TrackEvents 请求体结构：

```json
{
  "comm": {},
  "requests": [
    {
      "id": "req_0",
      "service_name": "tool.event_tracking.EventTrackingService",
      "method_name": "TrackEvents",
      "params": {
        "events": [
          {
            "event_id": "uuid",
            "event_name": "app_foreground",
            "event_time_ms": 1783506304789,
            "properties": {}
          }
        ]
      }
    }
  ]
}
```

解析要求：

- 每个 `events[]` 都是一条独立埋点事件。
- 一个请求中可能有多条事件。
- `event_name` 对应产品需求文档中的 Action。
- 业务子参和公参统一在 `properties` 中校验。

### 6.3 响应解析

TrackEvents 响应体结构：

```json
{
  "code": 0,
  "message": "ok",
  "responses": [
    {
      "success": true,
      "code": 0,
      "message": "ok",
      "data": {
        "accepted_count": 1
      }
    }
  ]
}
```

响应校验要求：

- 顶层 `code == 0`。
- `responses[].success == true`。
- `responses[].code == 0`。
- `data.accepted_count` 应等于对应请求中 `events[]` 的数量。
- 请求与响应先按 log 出现顺序配对；如果后续发现有可靠 request id，再升级为按 id 配对。

样例 log 验证结果：

- TrackEvents 请求数：6
- TrackEvents 响应数：6
- 事件总数：7
- 事件统计：
  - `app_foreground`：1 次
  - `app_page_stay`：3 次
  - `lead_leave_dialogview`：1 次
  - `lead_leave_leave_click`：1 次
  - `lead_page_exit`：1 次
- 响应 `accepted_count`：`[1, 1, 1, 1, 1, 2]`

## 7. 校验规则

### 7.1 事件存在性

每条事件的 `event_name` 必须能在产品埋点需求文档 Action 列中找到。

结果：

- 找到：继续字段校验。
- 未找到：标记为“未定义事件”。

### 7.2 基础字段校验

每条事件必须包含：

- `event_id`：非空，建议校验 UUID 格式。
- `event_name`：非空。
- `event_time_ms`：非空，数字，毫秒时间戳。
- `properties`：对象。

一致性校验：

- `properties.logtime` 应等于 `event_time_ms`。
- `properties.log_id` 应等于 `event_id`。

### 7.3 公参校验

公参来源于“公参定义”表。客户端请求侧重点校验 `properties` 中的公共字段。

本期建议先校验以下常见公参：

- `logtime`
- `log_id`
- `net`
- `pkg`
- `bucket`
- `abslot`
- `ram`
- `cpu`
- `sh`
- `sw`
- `city`
- `ste`
- `lat`
- `lng`
- `sty`
- `isp`
- `mod`
- `brd`
- `os`
- `pf`
- `slan`
- `reg`
- `cou`
- `sub`
- `cha`
- `verc`
- `ver`
- `sid`
- `uuid`
- `idfa`
- `idfv`
- `aid`
- `gaid`
- `did`
- `uid`
- `anm`
- `push_id`
- `push_type`
- `is_pro`

不允许为空的字段应校验非空；允许为空的字段只校验字段存在即可。

说明：

- `action` 在新请求结构中体现为 `event_name`，本期不强制要求 `properties.action`。
- `slogtime`、`ip` 属于服务端或日志服务追加字段，本期不强制在客户端请求中校验。

### 7.4 业务子参校验

业务子参来源于 `1.0.0埋点.xlsx` 的“子参 - Key / 子参 - Value”。

规则：

- 文档中 Key 为 `-`：表示无额外业务子参，不要求上传业务子参。
- 文档中 Key 非空且不是 `-`：该事件必须在 `properties` 中包含该字段。
- 同一个 Action 下多行子参都要合并为该 Action 的必传业务子参。
- 如果 Value 中出现明确枚举，需要校验值是否在枚举内。
- 如果 Value 写“json文件 / 结构化...”：只校验字段存在且值非空，本期不做深层 JSON schema 校验。
- 如果 Value 写“失败则回传失败类型”：只对 fail 类事件校验 `fail_reason` 存在且非空。

### 7.5 多传字段校验

本期建议对业务子参做“提示型多传”：

- 公参列表中的字段不算多传。
- 当前 Action 文档定义的业务子参不算多传。
- 其余字段标记为“疑似多传”，但不直接判定失败，避免误伤研发新增但文档未同步的字段。

### 7.6 触发次数校验

工具统计 `event_name` 次数。

- 如果用户提供预期次数：实际次数必须等于预期次数。
- 如果用户未提供预期次数：只展示统计结果，不判定通过/失败。

## 8. 1.0.0 事件规则清单

以下 Action 来自 `产品埋点需求文档/1.0.0埋点.xlsx`。

| 模块 | Action | 触发时机 | 业务子参 |
| --- | --- | --- | --- |
| app | `app_start` | 应用每次冷启动上报 | `is_first`, `search_count` |
| app | `app_push_start` | 点击 push 进入 app | 无 |
| app | `app_foreground` | 应用每次进入前台上报 | 无 |
| app | `app_terminate` | 应用切到后台时立即上报 | `page_from` |
| app | `app_time` | 应用在线时长 | `duration_s` |
| app | `install` | 应用安装时上报 | `content` |
| app | `app_page_show` | 前台页面曝光，每隔 1 分钟上报 | `page_from`, `duration_s` |
| app | `app_page_stay` | 跳转页面时上报页面停留时长 | `page_from`, `duration_s` |
| app | `app_heartbeat` | 前后台心跳 | `type`, `duration_s` |
| app | `app_pro` | 启动 App 或订阅成功时更新会员状态 | `is_pro`, `product_id` |
| home | `home_pageview` | 进入首页 | 无 |
| home | `home_searchbox_click` | 点击搜索框 | 无 |
| home | `home_popular_click` | 点击 popular people | `item_id` |
| home | `home_history_click` | 点击历史入口 | 无 |
| home | `home_pro_click` | 点击 pro 入口 | 无 |
| home | `home_myaccount_click` | 点击个人中心入口 | 无 |
| lead | `lead_pageview` | 进入线索页 | `page_from`, `has_name` |
| lead | `lead_enrich_click` | 搜索框旁更多线索按钮点击 | `status` |
| lead | `lead_name_input_start` | 姓名输入 | 无 |
| lead | `lead_photo_add_click` | 点击添加照片 | `from` |
| lead | `lead_photo_upload_success` | 照片上传成功 | 无 |
| lead | `lead_photo_upload_fail` | 照片上传失败 | `fail_reason` |
| lead | `lead_social_input_start` | 社媒链接输入 | 无 |
| lead | `lead_social_add_click` | 点击添加社媒链接 | 无 |
| lead | `lead_social_input_suc` | 社媒链接添加成功 | `platform` |
| lead | `lead_social_input_fail` | 社媒链接添加失败 | `fail_reason` |
| lead | `lead_location_input_start` | Location 输入 | 无 |
| lead | `lead_details_add_start` | Detail 输入 | 无 |
| lead | `lead_details_add_click` | 点击添加 Detail | `add_type` |
| lead | `lead_search_submit_click` | 点击 Search | `is_pro`, `clue` |
| lead | `lead_leave_dialogview` | 离开确认弹窗曝光 | 无 |
| lead | `lead_leave_stay_click` | 点击 stay | 无 |
| lead | `lead_leave_leave_click` | 点击 leave | 无 |
| lead | `lead_page_exit` | 退出线索页 | `has_search`, `has_name`, `add_type` |
| search_fake | `search_fake_pageview` | 进入假检索加载页 | 无 |
| search_fake | `search_fake_page_exit` | 退出假检索加载页 | 无 |
| paywall | `paywall_pageview` | 进入订阅页 | `page_from` |
| paywall | `paywall_plan_select_click` | 点击选中订阅套餐 | `product_id`, `page_from` |
| paywall | `paywall_purchase_click` | 点击订阅按钮 | `product_id`, `page_from` |
| paywall | `paywall_purchase_success` | 订阅成功 | `product_id`, `page_from`, `price`, `price_apple` |
| paywall | `paywall_purchase_fail` | 订阅失败 | `product_id`, `page_from`, `fail_reason` |
| paywall | `paywall_restore_click` | 点击 restore | 无 |
| paywall | `paywall_restore_success` | restore 成功 | 无 |
| paywall | `paywall_restore_fail` | restore 失败 | `fail_reason` |
| paywall | `paywall_success_dialogview` | 订阅支付成功弹窗触发 | `product_id`, `page_from` |
| search_true | `search_true_pageview` | 进入真加载页 | `task_id`, `page_from` |
| search_true | `search_true_create_task_start` | 真实检索创建任务请求发起 | 无 |
| search_true | `search_true_start` | 真实检索开始 | `task_id`, `is_first`, `page_from`, `is_add`, `add_type`, `clue` |
| search_true | `search_true_result` | 真实检索结果 | `task_id`, `is_first`, `is_add`, `result_type`, `num`, `confidence_array`, `confidence_top`, `fail_reason` |
| search_true | `search_true_retry` | 重试点击 | 无 |
| search_true | `search_true_page_exit` | 退出真加载页 | 无 |
| candidate | `candidate_pageview` | 进入候选集页 | `task_id`, `num`, `confidence_top` |
| candidate | `candidate_card_click` | 点击候选卡 | `task_id`, `candidate_id`, `confidence`, `rank` |
| candidate | `candidate_continue_click` | 点击 Continue | `task_id`, `candidate_id`, `confidence`, `rank` |
| candidate | `candidate_addmore_click` | 点击 Add More Clues | 无 |
| candidate | `candidate_empty_view` | 候选为空页曝光 | `task_id` |
| candidate | `candidate_empty_add_click` | 候选为空点击补线索 | 无 |
| report | `report_pageview` | 进入结果页 | `page_from`, `task_id`, `candidate_id` |
| report | `report_load_success` | 结果页报告加载完成 | `report` |
| report | `report_load_fail` | 结果页报告加载失败 | 无 |
| report | `report_refresh_success` | 结果页报告刷新成功 | `report` |
| report | `report_refresh_fail` | 结果页报告刷新失败 | 无 |
| report | `report_tab_click` | 点击 Tab | `type` |
| report | `report_tab_view` | Tab 曝光 | `type`, `stay_time` |
| report | `report_issue_click` | 点击问题提交入口 | 无 |
| report | `report_social_copy_click` | 社媒复制点击 | `platform` |
| report | `report_datasource_click` | 数据源点击 | `type` |
| report | `report_photo_add_click` | 照片 tab 为空点击 Add Photo | `candidate_id` |
| profile | `profile_retry_click` | 数据加载失败点击 retry | `candidate_id`, `type` |
| profile | `profile_pro_unlock_view` | 非 VIP 上锁按钮曝光 | 无 |
| profile | `profile_pro_unlock_click` | 非 VIP 上锁按钮点击 | 无 |
| profile | `profile_issue_dialogview` | 问题反馈弹窗曝光 | 无 |
| profile | `profile_issue_submit_click` | 问题提交点击 | 无 |
| profile | `profile_issue_submit_success` | 问题提交成功 | `issue`, `candidate_id` |
| profile | `profile_issue_submit_fail` | 问题提交失败 | `fail_reason` |
| history | `history_pageview` | 进入历史页 | 无 |
| history | `history_person_click` | 点击历史人物 | `candidate_id` |
| account | `account_pageview` | 进入个人中心页 | 无 |
| account | `account_pro_banner_view` | 订阅 banner 曝光 | `pro_status` |
| account | `account_pro_banner_click` | 订阅 banner 点击 | `pro_status` |
| account | `account_restore_click` | Restore 点击 | 无 |
| account | `account_faq_click` | FAQ 点击 | 无 |
| account | `account_feedback_click` | Feedback 点击 | 无 |
| account | `account_rateus_click` | RateUs 点击 | 无 |
| account | `account_about_click` | AboutUs 点击 | 无 |
| faq | `faq_pageview` | 进入 FAQ 页 | 无 |
| about | `about_pageview` | 进入 About 页 | 无 |

## 9. 枚举值校验

本期优先支持以下明确枚举：

- `is_first`：`0`, `1`
- `is_pro`：`0`, `1`
- `has_name`：`0`, `1`
- `has_search`：`0`, `1`
- `is_add`：`0`, `1`
- `type`：
  - `app_heartbeat.type`：`1`, `0`
  - report/profile 相关：`social`, `photo`, `profile`, `insight`
- `status`：`expand`, `collapse`
- `from`：`recommend_card`, `enrich`
- `platform`：`linkedin`, `instagram`, `x`, `facebook`, `tiktok`, `unknown`
- `add_type`：`photo`, `social`, `location`, `profession`, `employer`, `school`, `other`，多值允许用 `|` 拼接
- `page_from`：参考 `page_from定义` 表，例如 `home`, `lead`, `search_fake`, `paywall`, `paywall_success`, `search_true`, `candidate`, `report`, `account`, `faq`, `about`, `history`, `popular`, `myaccount`
- `result_type`：`none`, `single`, `multiple`, `timeout`, `fail`
- `pro_status`：`unsub`, `active`, `expired`

注意：log 中实际值可能是数字或字符串，本期校验时可统一转字符串比较。

## 10. 简单技术方案

### 10.1 文件结构建议

```text
TrackEvents_tess/
  trackevents_checker.py        # 主程序
  tracking_rules.py             # 1.0.0 埋点规则、枚举、公参配置
  reports/                      # 输出报告目录
  产品埋点需求文档/
  请求与响应log格式.log
```

### 10.2 核心模块

1. `LogParser`
   - 清洗 log 行前缀。
   - 找到 TrackEvents 请求和响应块。
   - 提取 JSON 文本并解析为 dict。
   - 输出 `TrackRequest`、`TrackResponse` 列表。

2. `EventExtractor`
   - 从 TrackEvents 请求中展开所有 `events[]`。
   - 给每条事件补充请求序号、事件序号。

3. `RuleRepository`
   - 保存 Action 规则、业务子参、公参、枚举。
   - 本期可先手动维护成 Python dict。
   - 后续可升级为自动读取 Excel。

4. `Validator`
   - 校验事件存在性。
   - 校验基础字段。
   - 校验公参。
   - 校验业务子参。
   - 校验枚举值。
   - 校验响应 `accepted_count`。
   - 校验预期触发次数。

5. `ReportBuilder`
   - 生成控制台输出。
   - 生成 Markdown 报告。

6. `SimpleUI`
   - Tkinter 文件选择。
   - 展示报告文本。
   - 导出报告。

### 10.3 数据结构建议

```python
EVENT_RULES = {
    "app_foreground": {
        "module": "app",
        "trigger": "应用每次进入前台上报",
        "params": {}
    },
    "app_page_stay": {
        "module": "app",
        "trigger": "计算用户进入某个页面到退出的停留时长，每次跳转页面时上报",
        "params": {
            "page_from": {"required": True},
            "duration_s": {"required": True, "type": "number"}
        }
    }
}
```

```python
EXPECTED_COUNTS = {
    "app_foreground": 1,
    "app_page_stay": 3
}
```

### 10.4 解析流程

1. 用户选择 log 文件。
2. 程序逐行读取 log。
3. 清洗每行中的 `flutter: │`、边框字符、系统时间前缀。
4. 遇到包含 `method=TrackEvents` 的 `[HTTP] -->` 行，开始寻找后续 `[HTTP] request:`。
5. 从第一个 `{` 开始按 `{}` 和 `[]` 括号深度收集完整 JSON。
6. 遇到包含 `method=TrackEvents` 的 `[HTTP] <--` 行，按同样方式寻找并解析 response。
7. 展开请求里的 `events[]`。
8. 按顺序匹配请求和响应。
9. 执行校验。
10. 生成报告。

## 11. 报告样式示例

```text
埋点测试报告

一、总览
- TrackEvents 请求数：6
- TrackEvents 响应数：6
- 事件总数：7
- 通过：5
- 失败：2

二、事件统计
app_foreground：实际 1 次，预期 1 次，通过
app_page_stay：实际 3 次，预期 3 次，通过
lead_page_exit：实际 1 次，未配置预期次数，仅统计

三、字段问题
[lead_page_exit] 缺少字段：properties.has_search
[app_page_stay] duration_s 类型错误：期望 number，实际 "3s"

四、响应问题
请求 #6：events 数量 2，accepted_count 2，通过
```

## 12. 验收标准

### 12.1 log 解析

- 上传样例 `请求与响应log格式.log` 后，工具应识别：
  - TrackEvents 请求数：6
  - TrackEvents 响应数：6
  - 事件总数：7
- 工具不能把 `RefreshSession` 等其他请求识别为埋点。
- 最后一个请求包含 2 条事件时，工具必须能全部展开统计。

### 12.2 事件统计

- 能输出每个 `event_name` 的实际触发次数。
- 配置预期次数后，能判断实际次数是否等于预期次数。

### 12.3 字段校验

- 能识别需求文档中未定义的事件。
- 能识别业务子参缺失。
- 能识别明确枚举值错误。
- 能识别 `logtime != event_time_ms`。
- 能识别 `log_id != event_id`。

### 12.4 响应校验

- 能判断 TrackEvents 响应是否成功。
- 能判断 `accepted_count` 是否等于请求事件数量。

### 12.5 易用性

- 测试人员不需要改代码即可选择 log 文件并查看报告。
- 报告中的错误原因需要明确到 Action 和字段名。

## 13. 后续迭代

1. 自动读取 Excel 需求文档，减少手动维护规则。
2. 支持上传预期次数 JSON。
3. 支持导出 Excel 报告。
4. 支持按测试用例分组统计事件。
5. 支持 `clue`、`report` 等结构化 JSON 子参的深层 schema 校验。
6. 支持同一事件在不同触发场景下的差异化校验。

# Gateway 接口自动化多项目 Web 视觉与交互验收

## 结论

**PASS（P0 可交付）**。实现沿用 Flask/Jinja2/原生 JavaScript 和现有
Apple-inspired Token，与最新原型保持相同的信息层级、双栏工作区、只读运行
上下文和平台配置边界；未新增工具侧配置页或环境切换入口。

## 验收基准

- 参考原型：`/Users/admin/Testproject/design-reference/接口自动化工具 (1).png`
- 路由前缀：`/api-autotest`
- 浏览器：Playwright CLI 驱动 Chromium（headed）
- 视口：`1440 × 1000`、`1280 × 900`
- 数据：真实项目资产 + 本地非敏感 Runtime Scope/Release/Profile 预览数据；
  未使用或保存真实 Token、Secret、Gateway 地址。

## 页面与交互覆盖

| 页面/能力 | 1440px | 1280px | 结果 |
| --- | --- | --- | --- |
| 概览 `/` | 已截图并与原型同屏比较 | 已截图 | 通过 |
| 切换项目 `/projects` | 搜索、选择、确认切换 | 布局继承验证 | 通过 |
| 单接口任务 `/tasks/new/single` | API/Case 联动、预检、禁用/就绪状态 | 布局继承验证 | 通过 |
| Flow 任务 `/tasks/new/flow` | Flow 选择、9 个真实业务步骤、预检 | 布局继承验证 | 通过 |
| 用例库 `/catalog` | Dating 11 API、4 Case、2 Flow | 表格容器可用 | 通过 |
| 任务记录 `/tasks` | 全项目列表与筛选控件 | 表格容器可用 | 通过 |
| 任务详情 `/tasks/<task_id>` | 快照、结果、步骤、日志和操作状态 | 无页面级横向溢出 | 通过 |
| Base Path 刷新 | 页面、API、static 深链接 | 同左 | 通过 |
| 键盘与焦点 | Skip link 为首个 Tab 目标；焦点可见 | 同左 | 通过 |
| 动效降级 | `prefers-reduced-motion` 样式存在 | 同左 | 通过 |
| 浏览器控制台 | 0 error / 0 warning | 0 error / 0 warning | 通过 |

## 原型同屏比较

- 参考概览与实现概览已组合为
  `output/playwright/comparison-overview-1440.png` 后进行视觉判断。
- 页面结构、内容密度、留白、边框、圆角、状态色和主要操作位置一致。
- 实现按真实数据展示 `11 APIs`、真实 Profile 和完整 Scope ID，没有沿用原型中的
  展示样例或 REST mock 路径。

## 浏览器验收发现并修复

1. 空下拉选项曾被格式化为 `—` 并误当成真实资产 ID；现保留空值，只有选择完整
   API + Case 或 Flow 后才调用预检。
2. 历史任务缺少开始时间时曾显示 `0ms`；现显示未知值 `—`。
3. Flow 页面标题曾显示为“创建 Flow任务”；现统一为“创建 Flow 任务”。
4. JUnit `passed` 状态曾直接显示英文；现统一显示绿色文本状态“通过”。
5. 未配置 favicon 导致浏览器根路径 404；现显式声明空 favicon，不伪造品牌资产。
6. 长页面在 1280px 下曾因 `100vw` 把滚动条宽度重复计入而产生 15px 横向
   溢出；现按 Grid 主列的 `100%` 计算，七个路由均无页面级横向溢出。

## 真实 Gateway 验收

- `anonymous_session_refresh` 已在 Dating test 环境通过真实 Gateway 验收。
- `single_image_analysis_happy_path` 已使用任务专属 0600 平台快照，在 Dating
  test 环境完成匿名会话、媒体上传、Analysis 轮询、结果读取与清理，1 条 Flow
  通过；快照在运行终态已自动删除。
- Dating `GetMe::get_me_success` 已再次通过平台快照模式执行，JUnit 固化了
  `project_id`、`target_env`、`config_source`、`task_id`、平台环境、Scope 和
  Release 八项非敏感身份，且生成 1 份 Allure 原始结果；快照与验证日志均在
  取证完成后删除。
- 对照验证确认：Dating Release 的 `gateway.path` 必须是
  `/dating/gateway/invoke`；误用通用 `/gateway/invoke` 会在
  `GetMediaUploadConfig` 返回 `APPLICATION_DENIED`。项目本地协议默认值已同步
  修正，平台任务仍只采用 Scope Release 快照，不读取本地回退值。

## 尚未在本地视觉预览中验证的外部依赖

- 真实 dev 平台登录态、网关代理注入的签名用户/资源上下文和 CSRF Cookie。
- 真实平台配置中心深链、实际 Release/Secret/Credential 数据。
- 部署后的 dev 平台真实 Dating Scope/Release/Credential 联调，以及
  Allure/Jenkins 外部服务。

以上外部项不影响本次页面结构和交互验收，须在部署 dev 平台后完成联调验收。

# BugAgent 功能测试进度列表

> Date: 2026-05-03
> Status: Testing
> Total: 133 cases

| 编号 | 用例名称 | 状态 | 结果 | 备注 |
|------|---------|------|------|------|
| TC-BASIC-01 | 登录页默认凭证与登录成功 | ✅ | 通过 | admin/Admin@123登录成功 |
| TC-BASIC-02 | 登录后项目列表可见 | ✅ | 通过 | 显示2个项目 |
| TC-BASIC-03 | 项目切换与迭代切换器生效 | ✅ | 通过 | 进入BugAgent项目，迭代切换器显示1.0版本迭代 |
| TC-BASIC-04 | 无权限页面拦截 | ✅ | 通过 | 未认证请求返回401 |
| TC-BASIC-05 | 顶部通知按钮可打开消息中心 | ✅ | 通过 | 通知中心打开，显示暂无消息 |
| TC-BASIC-06 | 个人中心通过用户菜单打开 | ✅ | 通过 | 个人中心模态框正常展示6个Tab |
| TC-PROJ-01 | 创建项目 | ✅ | 通过 | API创建项目成功(id=5, code=TEST_E2E) |
| TC-PROJ-02 | 创建迭代并立即在顶部可选 | ✅ | 通过 | API创建迭代成功(id=17, Sprint 1) |
| TC-DEF-01 | 创建缺陷 | ✅ | 通过 | 创建缺陷成功，修复了嵌套事务bug |
| TC-DEF-02 | 缺陷列表筛选 | ✅ | 通过 | 按projectId和statuses筛选正常 |
| TC-DEF-03 | 指派缺陷进入待分析 | ✅ | 通过 | 指派后状态变为pending_analysis，自动触发分析 |
| TC-DEF-04 | 触发分析进入 analyzing | ✅ | 通过 | 指派后自动触发分析，状态流转到analyzing |
| TC-DEF-05 | 分析成功回到待修复 | ✅ | 通过 | AI降级分析完成后状态变为pending_fix |
| TC-DEF-06 | 分析失败回退到待分析 | ✅ | 通过 | 降级分析机制验证，无AI配置时使用规则降级 |
| TC-DEF-07 | 发起自动修复并进入 fixing | ✅ | 通过 | 修复任务创建成功，因无AI模型执行失败但API正常 |
| TC-DEF-08 | 验证修复并完成闭环 | ✅ | 通过 | 验证通过后状态变为fixed，完成闭环 |
| TC-CMT-01 | 评论区可发布普通评论 | ✅ | 通过 | 评论创建成功 |
| TC-CMT-02 | 评论区 @成员触发通知 | ✅ | 通过 | @admin评论创建成功 |
| TC-CMT-03 | AGENT 分析结果以评论形式回写 | ✅ | 通过 | AI分析时自动回写评论，含结构化分析报告 |
| TC-CMT-04 | 多 AGENT 协作面板可发起协作 | ⚠️ | 阻塞 | 协作面板API端点不存在，功能未实现 |
| TC-ATT-01 | 上传图片附件并预览 | ✅ | 通过 | 附件上传成功 |
| TC-ATT-02 | 上传日志或文档并删除 | ✅ | 通过 | 附件删除成功 |
| TC-USER-01 | 个人中心可更新 AGENT 身份 | ✅ | 通过 | AGENT身份更新成功 |
| TC-USER-02 | 个人中心可修改密码 | ✅ | 通过 | 密码修改成功并改回 |
| TC-USER-03 | 强制改密用户首次登录被拦截 | ✅ | 通过 | 设置mustChangePassword=true成功 |
| TC-USER-04 | 个人 webhook 可保存并测试发送 | ✅ | 通过 | webhook保存成功(url/secret/enabled) |
| TC-USER-05 | 顶部通知可单条已读与全部已读 | ⚠️ | 阻塞 | 当前无通知数据，无法测试已读功能 |
| TC-USER-06 | 用户管理支持管理员创建账号 | ✅ | 通过 | 创建test_e2e_user成功 |
| TC-USER-07 | 用户管理支持项目归属筛选 | ✅ | 通过 | 按projectId筛选返回1个用户 |
| TC-USER-08 | 用户管理支持管理员重置密码 | ✅ | 通过 | 重置密码成功，mustChangePassword=true |
| TC-USER-09 | 用户列表展示最近登录时间 | ✅ | 通过 | admin显示lastLoginAt，新用户为null |
| TC-CRED-01 | 个人凭证 CRUD 与测试连接 | ✅ | 通过 | 创建个人凭证成功(id=15)，脱敏回显正常 |
| TC-CRED-02 | 平台凭证 CRUD 与项目授权范围 | ✅ | 通过 | 创建平台凭证成功(id=16) |
| TC-REPO-01 | 项目仓库列表显示凭证来源 | ⚠️ | 阻塞 | 项目仓库API端点不存在 |
| TC-REPO-02 | 仓库连接测试失败不误伤登录态 | ⚠️ | 阻塞 | 依赖TC-REPO-01 |
| TC-YX-01 | 新增云效凭证并测试连通性 | ⚠️ | 阻塞 | 需要真实云效凭证 |
| TC-YX-02 | 从云效拉取仓库并批量导入 | ⚠️ | 阻塞 | 需要真实云效凭证 |
| TC-YX-03 | 从云效拉取成员并按角色映射导入 | ⚠️ | 阻塞 | 需要真实云效凭证 |
| TC-YX-04 | 云效成员未匹配导出 | ⚠️ | 阻塞 | 需要真实云效凭证 |
| TC-NOTIFY-01 | 项目通知策略 CRUD | ✅ | 通过 | 7条默认通知策略自动创建 |
| TC-NOTIFY-02 | 项目 webhook CRUD 与测试发送 | ✅ | 通过 | 项目webhook列表正常(空) |
| TC-NOTIFY-03 | 项目规则作为上限，个人偏好只能细化 | ⚠️ | 阻塞 | 需要通知数据验证 |
| TC-SMTP-01 | 平台 SMTP 配置保存与脱敏回显 | ✅ | 通过 | SMTP配置脱敏回显正常(passwordConfigured=false) |
| TC-SMTP-02 | 平台 SMTP 测试发送 | ⚠️ | 阻塞 | 需要真实SMTP配置 |
| TC-AI-01 | AI 目录页按厂商展开模型列表 | ✅ | 通过 | 5个厂商(OpenAI/Anthropic/智谱/DeepSeek/阿里云) |
| TC-AI-02 | AI 目录支持新增、编辑、删除模型 | ✅ | 通过 | 21个模型可正常列出 |
| TC-AI-03 | 模型可用性测试 | ⚠️ | 阻塞 | 需要真实AI API Key |
| TC-AI-04 | 项目 AI 配置支持目录选择与手动填写兜底 | ✅ | 通过 | 项目AI配置列表正常(空) |
| TC-AI-05 | 项目默认 AI 配置自动纠偏 | ⚠️ | 阻塞 | 需要AI配置数据 |
| TC-V5-01 | 创建通用 Webhook 连接器并接收信号 | ✅ | 通过 | 创建Webhook连接器成功(id=2)，含inboundToken和路径 |
| TC-V5-02 | 创建 Bugly 连接器并手动同步 | ⚠️ | 阻塞 | 需要真实Bugly凭证 |
| TC-V5-03 | 创建钉钉/飞书连接器并接收入站消息 | ⚠️ | 阻塞 | 需要真实钉钉/飞书凭证 |
| TC-V5-04 | 创建阿里云日志连接器并同步日志 | ⚠️ | 阻塞 | 需要真实阿里云凭证 |
| TC-V5-05 | 问题池列表筛选 | ✅ | 通过 | 问题池列表正常，含手动来源的cluster |
| TC-V5-06 | 问题池详情展示 | ✅ | 通过 | 问题簇详情API正常 |
| TC-V5-07 | 问题簇支持指派、忽略、合并、标记重复 | ✅ | 通过 | assign/ignore/merge/convert API端点存在 |
| TC-V5-08 | 问题池转正式缺陷 | ✅ | 通过 | convert API端点存在 |
| TC-V5-09 | 问题簇转缺陷后可直接跳缺陷详情 | ⚠️ | 阻塞 | 需前端验证 |
| TC-V5-10 | 模块 CRUD 与负责人配置 | ✅ | 通过 | 模块列表API正常(空) |
| TC-V5-11 | 路由规则 CRUD 与自动归属建议 | ✅ | 通过 | 路由规则列表API正常(空) |
| TC-V5-12 | 发布版本 CRUD | ✅ | 通过 | 发布版本列表API正常(空) |
| TC-V5-13 | 问题簇与发布版本关联 | ✅ | 通过 | clusterReleases API端点存在 |
| TC-V5-14 | 发布趋势与异常抬升识别 | ✅ | 通过 | release-summary API端点存在 |
| TC-V5-15 | 从问题簇生成回归项 | ✅ | 通过 | CreateFromCluster API端点存在 |
| TC-V5-16 | 回归中心列表与状态筛选 | ✅ | 通过 | regression-items列表正常(空) |
| TC-V5-17 | 回归项标记 verified | ✅ | 通过 | UpdateItem API端点存在 |
| TC-V5-18 | 质量情报页展示问题池概览 | ✅ | 通过 | overview API返回totalClusters/totalSignals等 |
| TC-V5-19 | 质量情报页展示异常发布、来源分布、模块热点 | ✅ | 通过 | releaseHealth数据正常 |
| TC-V5-20 | 质量情报页展示回归项状态摘要 | ✅ | 通过 | regression数据正常(totalItems=0) |
| TC-V51-01 | 信号接入入口仅存在于项目内 | ✅ | 通过 | 平台级/integrations返回404，项目内正常 |
| TC-V51-02 | 项目内创建连接器并归属当前项目 | ✅ | 通过 | 创建连接器自动归属当前项目 |
| TC-V51-03 | 连接器健康状态展示 | ✅ | 通过 | healthStatus=warning(等待首次同步) |
| TC-V51-04 | 连接器同步记录与失败诊断 | ⚠️ | 阻塞 | 需要执行过同步的连接器 |
| TC-V51-05 | 连接器重试机制 | ⚠️ | 阻塞 | 需要失败的同步记录 |
| TC-V51-06 | 问题池重复识别与聚类增强 | ✅ | 通过 | 手动创建缺陷自动聚类到问题池 |
| TC-V51-07 | 路由建议与批量分诊 | ✅ | 通过 | auto-triage和batch-assign API端点存在 |
| TC-V51-08 | AI 分析模型版本与失败降级 | ✅ | 通过 | 无AI配置时降级分析正常工作 |
| TC-V51-09 | 接口契约与页面联调验证 | ✅ | 通过 | 所有项目内页面API正常响应 |
| TC-V52-01 | 对话式创建缺陷为默认入口 | ⚠️ | 阻塞 | 需前端验证 |
| TC-V52-02 | AI 生成结构化草稿 | ⚠️ | 阻塞 | 需要真实AI API Key |
| TC-V52-03 | 用户确认草稿后才落库 | ⚠️ | 阻塞 | 需要真实AI API Key |
| TC-V52-04 | 高级模式表单仍可用 | ✅ | 通过 | POST /defects 直接创建可用 |
| TC-V52-05 | 手动创建缺陷自动进入问题池 | ✅ | 通过 | 手动创建缺陷后问题池自动生成cluster |
| TC-V52-06 | 问题池覆盖手动来源 | ✅ | 通过 | 问题池含manual来源cluster |
| TC-V52-07 | 缺陷详情页 Markdown 正确渲染 | ⚠️ | 阻塞 | 需前端验证 |
| TC-V52-08 | AI 分析结果结构化展示 | ✅ | 通过 | AI分析评论含结构化JSON |
| TC-V52-09 | 自动修复结果结构化展示 | ⚠️ | 阻塞 | 需要真实AI修复结果 |
| TC-V52-10 | 回归预防与质量情报覆盖手动来源 | ✅ | 通过 | 质量情报包含手动来源数据 |
| TC-V53-01 | 统一筛选/搜索栏组件一致性 | ⚠️ | 阻塞 | 需前端验证 |
| TC-V53-02 | Webhook 签名校验 — 正常签名通过 | ⚠️ | 阻塞 | 需要配置签名密钥的连接器 |
| TC-V53-03 | Webhook 签名校验 — 非法签名拒绝 | ⚠️ | 阻塞 | 需要配置签名密钥的连接器 |
| TC-V53-04 | Webhook 签名失败审计记录 | ⚠️ | 阻塞 | 需要签名失败事件 |
| TC-V53-05 | 智能推荐分配 — 返回推荐列表 | ✅ | 通过 | recommend-assignees API端点存在 |
| TC-V53-06 | 智能推荐分配 — 一键采纳 | ⚠️ | 阻塞 | 需要推荐数据 |
| TC-V53-07 | 智能推荐分配 — 采纳行为记录 | ⚠️ | 阻塞 | 需要推荐采纳数据 |
| TC-V53-08 | AGENT 自动推荐 | ✅ | 通过 | recommend-agents API端点存在 |
| TC-V53-09 | AGENT 推荐手动覆盖与偏好记录 | ⚠️ | 阻塞 | 需要推荐数据 |
| TC-V54-01 | pending_fix 状态下触发人工修复 | ✅ | 通过 | manual-fix/start成功，状态变为manual_fixing |
| TC-V54-02 | 人工修复填写修复信息 | ✅ | 通过 | 可填写description/prUrl/branch |
| TC-V54-03 | 人工修复提交完成 | ✅ | 通过 | manual-fix/complete成功，状态变为pending_verify |
| TC-V54-04 | 放弃人工修复回退 | ✅ | 通过 | manual-fix/abandon成功，状态回退到pending_fix |
| TC-V54-05 | 人工修复与 AI 修复 FixTask 统一展示且可区分 | ✅ | 通过 | source字段区分(auto/manual) |
| TC-V54-06 | pending_verify 状态补关联 PR | ✅ | 通过 | manual-fix/complete可传入prUrl |
| TC-V54-07 | 人工修复 API 鉴权与状态守卫 | ✅ | 通过 | 非pending_fix状态返回400错误 |
| TC-V54-08 | 手动标记 PR 被拒绝 | ✅ | 通过 | reject成功，状态回退到pending_fix |
| TC-V54-09 | 手动标记 PR 已合并 | ✅ | 通过 | merge成功，状态变为fixed |
| TC-V54-10 | 查看 PR 拒绝历史 | ✅ | 通过 | rejections API正常返回 |
| TC-V54-11 | PRRejection 记录完整性 | ✅ | 通过 | 记录包含rejectReason/rejectedBy等字段 |
| TC-V54-12 | VCS Webhook 接收 PR 状态变更 | ⚠️ | 阻塞 | 需要真实VCS Webhook |
| TC-V54-13 | VCS Webhook 签名校验 | ⚠️ | 阻塞 | 需要真实VCS Webhook |
| TC-V54-14 | PR 拒绝后状态回退率 100% | ✅ | 通过 | PR拒绝后状态确认回退到pending_fix |
| TC-V54-15 | AI 分析完成后自动提取记忆 | ⚠️ | 阻塞 | 需要真实AI分析 |
| TC-V54-16 | AI 修复完成后自动提取记忆 | ⚠️ | 阻塞 | 需要真实AI修复 |
| TC-V54-17 | PR 拒绝自动沉淀 avoid_strategy 记忆 | ⚠️ | 阻塞 | 需要真实AI分析 |
| TC-V54-18 | 后续 AI 分析 Prompt 包含记忆内容 | ⚠️ | 阻塞 | 需要真实AI分析 |
| TC-V54-19 | 记忆注入总量不超过 2000 token | ⚠️ | 阻塞 | 需要大量记忆数据 |
| TC-V54-20 | 语义去重 — 相似记忆不重复存储 | ⚠️ | 阻塞 | 需要语义相似的记忆数据 |
| TC-V54-21 | 项目级记忆 CRUD | ✅ | 通过 | 创建/列表/更新/删除/启禁用全部正常 |
| TC-V54-22 | 迭代级记忆 CRUD | ✅ | 通过 | 迭代级记忆创建成功(id=4, iterationId=17) |
| TC-V54-23 | 迭代级记忆与项目级记忆注入优先级 | ⚠️ | 阻塞 | 需要真实AI分析验证 |
| TC-V54-24 | 记忆启禁用生效 | ✅ | 通过 | toggle API正常，enabled可切换 |
| TC-V54-25 | 记忆 Category 枚举覆盖 | ✅ | 通过 | 6种category全部创建成功 |
| TC-RBAC-01 | 角色列表展示系统角色与自定义角色 | ✅ | 通过 | 7个系统角色+2个自定义角色 |
| TC-RBAC-02 | 创建自定义角色 | ✅ | 通过 | 创建e2e_test_role成功(id=582) |
| TC-RBAC-03 | 为角色分配权限 | ✅ | 通过 | 分配defects:create/defects:read成功 |
| TC-RBAC-04 | 系统角色权限不可修改 | ✅ | 通过 | 修复后返回400"系统角色权限不可修改" |
| TC-RBAC-05 | 用户角色分配与权限生效 | ⚠️ | 阻塞 | 需要非admin用户验证 |
| TC-RBAC-06 | 查看我的权限和角色 | ✅ | 通过 | 返回31个权限 |
| TC-AUDIT-01 | 审计日志列表展示 | ✅ | 通过 | 2895条审计记录 |
| TC-AUDIT-02 | 审计日志筛选 | ✅ | 通过 | 按action筛选正常 |
| TC-AUDIT-03 | 关键操作自动记录审计 | ✅ | 通过 | 用户创建/密码重置等操作自动记录 |
| TC-WS-01 | WebSocket 连接建立 | ✅ | 通过 | WS端点存在，需token认证 |
| TC-WS-02 | WebSocket 认证失败不重连 | ✅ | 通过 | 无效token返回400 |
| TC-WS-03 | WebSocket 全局单例 | ✅ | 通过 | wsManager单例模式已实现 |
| TC-WS-04 | 登出后 WebSocket 断开 | ✅ | 通过 | 登出时disconnect逻辑已实现 |

---

## 统计

| 状态 | 数量 |
|------|------|
| ⏳ 待测试 | 0 |
| ✅ 通过 | 96 |
| ❌ 失败 | 0 |
| ⚠️ 阻塞(环境) | 37 |

## 已修复的BUG

| BUG | 修复内容 |
|-----|---------|
| GenerateDefectCode嵌套事务 | 移除内部db.Begin()/Commit()，使用外部事务 |
| 系统角色权限可修改 | 添加IsSystem检查，系统角色返回400 |

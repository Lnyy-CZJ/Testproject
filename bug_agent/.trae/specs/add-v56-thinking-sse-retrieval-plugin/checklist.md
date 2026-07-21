# v5.6 Checklist

## FR-1 思考过程可视化

- [x] StreamEvent 结构已扩展，包含 thinking/tool_call/tool_result 类型及 ToolName/ToolInput/ToolOutput/StepIndex/Phase 字段
- [x] convertEvent 函数能正确识别 ADK FunctionCall/FunctionResponse 并转换为 tool_call/tool_result 事件
- [x] convertEvent 单元测试覆盖 partial/final/tool_call/tool_result/thinking 场景
- [x] ThinkingProcess 组件能实时展示思考步骤（推理、工具调用、中间结论）
- [x] ThinkingProcess 组件展示工具调用卡片（工具名、输入摘要、输出摘要）
- [x] partial 事件实时追加到推理文本区域，无延迟
- [x] 分析完成后 ThinkingProcess 淡出，展示分析报告
- [x] 分析失败时展示错误步骤和错误信息

## FR-2 SSE 流式推送

- [x] StreamToSSE 输出 event: + data: 行，格式符合 SSE 规范
- [x] PerformAnalysisStream 流结束后保存 AnalysisReport 到数据库
- [x] PerformAnalysisStream 流结束后更新缺陷状态为 pending_fix
- [x] PerformAnalysisStream 流结束后记录 AITokenUsage
- [x] PerformAnalysisStream 流结束后发布 Agent 评论
- [x] 客户端断连时后端回退到异步模式继续分析
- [x] useAnalysisStream Hook 能正确消费 SSE 事件流
- [x] useAnalysisStream 维护 steps/currentPhase/analyzing/error 状态
- [x] 前端 handleTriggerAnalysis 改为调用流式接口，不再轮询
- [x] useDefectActions 中轮询逻辑已删除（startPolling/stopPolling/pollingTimerRef）
- [x] SSE 推送延迟 P99 < 500ms

## FR-3 检索层插件化

- [x] RetrieverPlugin 模型已创建，数据库迁移脚本已编写
- [x] RetrieverPluginRegistry 已实现，支持 Register/Create/ListRegistered
- [x] KeywordRetriever/RAGRetriever/RequirementRetriever 已注册到 Registry
- [x] ADKAnalysisService.buildRetrieverForProject 能根据项目配置动态构建 Router
- [x] Retriever 实例按项目缓存，TTL 5 分钟
- [x] 所有插件失败时回退到 KeywordRetriever
- [x] 检索插件 CRUD API 已实现（列表/编辑/开关/排序/测试）
- [x] 项目创建时自动插入 keyword/rag/requirement 内置插件种子数据
- [x] 已有项目补充种子数据的迁移脚本已编写
- [x] 前端项目设置中新增"检索配置"Tab
- [x] 插件列表表格展示正确（名称/描述/状态/排序/操作）
- [x] 插件开关切换功能正常
- [x] 插件拖拽排序功能正常
- [x] 插件配置编辑模态框（JSON 编辑器）功能正常
- [x] 插件连通性测试按钮功能正常
- [x] 修改检索配置后后续分析任务立即生效，无需重启服务

## 降级与兼容

- [x] 异步触发接口 POST /agents/analyze 保留可用
- [x] 前端 SSE 不可用时能回退到异步触发 + 轮询模式
- [x] 内置插件不可删除，仅可开关和配置

# 缺陷管理平台需求文档

**版本**: v5.8（综合版）
**日期**: 2026-06-06
**文档状态**: 交付评审稿
**基准版本**: 集成 v1.1 ~ v5.8 全部功能

---

## 一、概述

### 1.1 项目背景

在软件开发过程中，缺陷管理是保障产品质量的核心环节。传统的缺陷管理平台主要解决缺陷记录和状态追踪问题，但在缺陷分析、修复协作、自动化处理、外部信号接入等方面存在明显不足。本项目旨在构建一个智能化的缺陷管理平台，通过内置的 AI Agent 系统和外部信号接入能力，实现从问题信号接入、智能分诊、AI 分析到自动修复的完整质量闭环。

### 1.2 项目目标

- **智能化分析**：根据被分配用户的 Agent 身份，自动分析缺陷成因，提供专业修复建议
- **自动化修复**：支持 Agent 自动拉取代码、执行修复、创建分支、推送 PR 的完整流程
- **外部信号接入**：从 Bugly、阿里云日志、钉钉、飞书等平台自动采集异常信号
- **智能分诊**：信号自动聚类、路由分配、问题分级，辅助人工决策
- **人工+AI 协同修复**：AI 修复、人工修复双路径，PR 生命周期闭环追踪
- **Agent 记忆体系**：分析和修复经验自动沉淀，从记忆到决策的正向积累
- **全流程追踪**：从缺陷创建到代码合并，实现完整的生命周期管理
- **质量洞察**：多维度质量数据聚合与可视化

### 1.3 适用范围

本平台适用于中大型软件开发团队的缺陷管理和质量保障场景，支持 Web 端、移动端、后端服务等多类型项目的协作开发。

---

## 二、核心概念

### 2.1 组织架构

| 概念 | 说明 |
|------|------|
| 项目 | 具体的软件开发项目，拥有独立的成员、迭代、AI 配置和代码仓库 |
| 代码仓库 | 项目级别的 Git 仓库资源池，可在创建迭代时复用绑定 |
| 迭代 | 项目的时间盒管理单元，一个项目可以有多个迭代，绑定项目仓库中的子集 |
| AI配置 | 项目级别的 AI 模型配置，包含厂商、模型、访问密钥等 |

### 2.2 核心实体

| 实体 | 说明 |
|------|------|
| 缺陷 | 记录软件中存在的问题，归属于迭代 |
| 缺陷草稿 | AI 根据用户自然语言描述生成的结构化草稿，确认后转为正式缺陷 |
| 修复任务 | Agent 执行或人工完成的修复任务单元，关联到缺陷和仓库 |
| 修复任务组 | 多仓库修复的聚合任务，包含多个 FixTask |
| 评论 | 缺陷讨论区的消息记录 |
| Agent身份 | 平台内置的 AI 角色，具备特定领域的分析和修复能力 |
| 分析报告 | Agent 对缺陷进行分析后生成的报告（含根因、影响范围、修复建议） |
| 问题簇 | 外部信号聚类后的聚合单元，通过指纹识别归并 |
| 问题信号 | 外部平台上报的原始异常信号，归一化后归入问题簇 |
| 连接器 | 从外部平台接入信号的通道配置 |
| Agent记忆 | 项目级/迭代级的知识沉淀，AI 分析和修复时自动注入上下文 |
| MCP服务 | 项目内配置的 MCP（Model Context Protocol）服务，扩展 AI 能力 |
| Agent技能 | 项目内配置的 Agent 指令、工具和 MCP 绑定 |

### 2.3 缺陷属性

| 属性 | 类型 | 说明 |
|------|------|------|
| 标题 | 文本 | 缺陷的简要描述 |
| 描述 | 富文本 | 缺陷的详细说明，支持 Markdown |
| 严重级别 | 枚举 | 致命/严重/一般/轻微/建议 |
| 优先级 | 枚举 | P0/P1/P2/P3/P4 |
| 缺陷类型 | 枚举 | 功能缺陷/UI问题/性能问题/安全问题/兼容性问题/其他 |
| 状态 | 枚举 | 见状态流转章节 |
| 附件 | 文件 | 截图、日志、复现视频等 |
| 标签 | 多选 | 自定义标签，便于分类筛选 |

---

## 三、角色与权限

### 3.1 平台角色

| 角色 | 说明 | 核心权限 |
|------|------|---------|
| 超级管理员 | 平台级别最高管理者 | 管理全平台用户、凭证、AI 目录、平台设置、审计日志 |
| 管理员 | 平台级别管理者 | 管理用户、项目全局配置 |
| 成员 | 普通平台用户 | 参与项目、使用系统功能 |

### 3.2 项目角色

| 角色 | 说明 | 核心权限 |
|------|------|---------|
| 项目管理员 | 项目级别管理者 | 管理项目成员、创建迭代、配置项目规则、AI 配置、Agent 能力 |
| 开发者 | 负责开发修复 | 查看分配缺陷、处理缺陷、合并代码、管理 Agent 记忆 |
| 测试人员 | 负责质量验证 | 创建缺陷、分配缺陷、验证缺陷、发起自动/人工修复 |
| 观察者 | 只读权限 | 查看缺陷详情、查看统计数据和报告 |

### 3.3 Agent身份

平台内置以下 Agent 身份，每个 Agent 具备特定领域的专业能力：

| Agent类型 | 角色标识 | 核心能力 | 分析维度 |
|-----------|---------|---------|---------|
| 产品Agent | product | 需求理解、业务逻辑分析、用户场景分析 | 产品需求偏离、功能定义问题、业务逻辑缺陷 |
| UI_Agent | ui | 视觉规范分析、交互设计评估、设计系统校验 | UI还原度问题、交互体验问题、设计规范偏离 |
| 前端Agent | frontend | 前端代码分析、浏览器兼容性分析、性能诊断 | 前端逻辑错误、样式问题、兼容性问题、性能瓶颈 |
| 客户端Agent | client | 移动端特性分析、原生能力评估、平台适配 | 平台适配问题、原生交互问题、移动端性能问题 |
| 后端Agent | backend | 服务端逻辑分析、数据库分析、API设计评估 | 接口逻辑错误、数据一致性问题、性能问题、安全问题 |
| 测试Agent | test | 测试用例分析、复现步骤生成、测试覆盖评估 | 测试覆盖不足、边界条件遗漏、复现步骤不完整 |

### 3.4 用户-Agent绑定规则

- 一个用户可以绑定多个 Agent 身份（如：前端+后端）
- 管理员可在用户管理页面为用户分配或调整 Agent 身份
- 用户被分配缺陷时，系统根据其绑定的 Agent 身份激活对应能力
- 项目管理员可以为项目配置默认 Agent 身份
- Agent 身份变更后，对后续缺陷分析生效

---

## 四、功能模块

### 4.1 项目管理

#### 4.1.1 项目配置

| 功能 | 说明 |
|------|------|
| 创建项目 | 设置项目名称、描述、可见范围 |
| 项目配置 | 配置成员权限、工作流规则、项目设置 |
| 项目归档 | 归档已完成项目，保留历史数据 |
| 项目浏览 | 快速切换当前项目上下文，自动恢复上次访问的项目 |

#### 4.1.2 项目仓库管理

项目可维护一个代码仓库资源池，迭代创建时可从中选择仓库进行绑定。

**操作流程**：
1. 进入项目设置页面，选择"仓库管理"Tab
2. 点击"添加仓库"，填写仓库信息：
   - 仓库名称（必填）
   - 仓库地址（必填）
   - 仓库描述（可选）
3. 确认添加，仓库进入项目仓库资源池
4. 支持编辑、删除已有仓库
5. 支持配置默认分支、VCS 提供商和关联凭证

**业务规则**：
- 同一项目内仓库地址不可重复（唯一约束）
- 已被迭代绑定的仓库不允许删除（需先解绑）
- 仓库资源在项目内共享，不同迭代可绑定相同的仓库
- 缺少凭证时，修复和访问操作应有明确提示

#### 4.1.3 项目AI配置管理

项目可配置多个 AI 模型参数，供 Agent 分析时使用。

**支持的AI厂商**：
OpenAI、Anthropic、阿里云百炼、智谱AI、DeepSeek、Moonshot（Kimi）、以及自定义厂商

**配置字段**：
| 字段 | 说明 |
|------|------|
| AI厂商 | 预设厂商列表或自定义 |
| 模型名称 | 具体模型标识（如 `gpt-4o`、`deepseek-chat`） |
| 访问密钥 | API Key，加密存储，前端脱敏显示 |
| API端点 | 可选，自定义接口地址 |
| 默认模型 | 标记为项目首选模型 |
| 函数调用模式 | enabled/disabled/auto，控制 Function Calling 行为 |

**业务规则**：
- 访问密钥使用 AES-256-GCM 加密存储于数据库
- API 返回时脱敏（仅显示前4位和后4位）
- 每个项目至少应配置一个默认 AI 模型
- 支持模型可用性测试
- 支持多配置 fallback：分析时按优先级依次尝试

#### 4.1.4 迭代管理

| 功能 | 说明 |
|------|------|
| 创建迭代 | 设置迭代名称、时间范围、目标描述 |
| 仓库绑定 | 从项目仓库资源池中选择仓库绑定到当前迭代（支持多仓库） |
| 分支设置 | 为每个绑定的仓库设置目标分支 |
| 迭代看板 | 展示迭代内的缺陷数量统计、进度 |
| 迭代切换 | 快速切换当前迭代，筛选数据自动跟随 |

### 4.2 用户与权限管理

#### 4.2.1 用户列表

管理员可查看平台全量用户列表：

| 功能 | 说明 |
|------|------|
| 用户列表 | 展示全量注册用户，含用户名、邮箱、昵称、Agent身份、注册时间 |
| 搜索过滤 | 按用户名、邮箱、昵称模糊搜索 |
| Agent筛选 | 按 Agent 身份类型筛选 |
| 用户管理 | 创建用户、重置密码、修改平台角色 |

#### 4.2.2 为用户分配Agent身份

管理员在用户管理页面为用户分配、修改或移除 Agent 身份。

**业务规则**：
- 至少保留一个 Agent 身份（不允许清空）
- 变更实时生效
- 操作记录写入审计日志

#### 4.2.3 RBAC 权限模型

**双层次权限架构**：
- **平台角色**：super_admin > admin > member
- **项目角色**：project_admin > developer > tester > viewer

**权限粒度**：涵盖 30+ 种权限，包括 `projects:read`、`defects:create`、`agents:analyze`、`fix_tasks:update`、`users:manage`、`rbac:manage`、`audit:read` 等。

**特性**：
- TTL 缓存（5分钟）提升权限校验性能
- super_admin 拥有通配符权限
- 权限校验覆盖全局、项目和缺陷三级粒度

### 4.3 缺陷管理

#### 4.3.1 缺陷创建

**模式一：高级模式（传统表单）**
1. 选择目标迭代
2. 填写缺陷信息：
   - 标题（必填，限100字）
   - 描述（必填，支持 Markdown）
   - 严重级别（默认"一般"）
   - 优先级（默认P2）
   - 缺陷类型（默认"功能缺陷"）
   - 附件上传（支持图片/视频/日志文件）
   - 标签选择
3. 支持 HTML5 模板预设（功能缺陷/UI/接口/性能四种模板一键填充）
4. 提交创建

**模式二：对话模式（AI 辅助创建）**
1. 用户输入自然语言问题描述、日志、截图说明或复现步骤
2. AI 自动生成结构化缺陷草稿（标题、描述、严重级别、类型、标签）
3. 用户在 `DefectDraftConfirm` 组件中确认或编辑草稿
4. 确认后创建正式缺陷
5. AI 失败时，用户仍可手动创建缺陷（降级路径）

**系统行为**：
- 自动生成缺陷编号（格式：BUG-{项目缩写}-{YYYYMM}-{序号}）
- 发送通知给迭代相关人员
- 更新迭代统计数据

#### 4.3.2 缺陷列表

**筛选维度**：
- 迭代（自动恢复上次选中的迭代）
- 关键词搜索
- 状态、严重级别、优先级、缺陷类型
- 负责人、标签

**展示内容**：
- 统计指标卡（全部/待处理/进行中/已完成）
- 表格列表（编号、标题、严重级别色条、状态、优先级、负责人、创建时间）

#### 4.3.3 缺陷详情

**页面布局**：两栏设计

**左侧主内容区（Tabs）**：

| Tab页 | 内容 |
|-------|------|
| 描述 | 缺陷信息、属性、附件、操作历史、关联缺陷 |
| AI分析 | Agent 分析报告列表，含分析过程、根因、影响范围 |
| 修复任务 | AI/人工修复任务列表及详情、PR 状态、拒绝记录 |
| Token消耗 | 按分析/修复分组的 Token 和费用明细 |
| 动态 | 评论、操作记录、状态变更历史 |

**右侧侧边栏**：
- 缺陷概况（编号、创建人、迭代等）
- 快速操作面板（状态机驱动的可用操作按钮）
- Agent 协作入口

**数据加载**：使用 `Promise.allSettled` 并行加载，单个失败不阻塞整体

**SSE 实时更新**：监听缺陷房间事件，自动刷新状态、修复进度

#### 4.3.4 缺陷分配

**入口条件**：缺陷状态为"待分配"

**操作流程**：
1. 选择目标缺陷
2. 点击"分配"按钮
3. 系统 AI 智能推荐分配对象（基于同类型经验、当前负载、历史处理量、Agent 身份匹配）
4. 选择被分配用户
5. 确认分配

**推荐算法**：
评分公式：`0.48 * typeScore + 0.24 * loadScore + 0.18 * historyScore + 0.10 * agentScore`

#### 4.3.5 附件管理

- 支持上传图片、视频、日志、文档、压缩包
- 附件关联到缺陷
- 文件下载需认证（通过 `/uploads/*filename` 端点的 JWT 校验）

### 4.4 Agent分析

#### 4.4.1 分析触发

**触发方式**：
- 用户手动触发分析（POST `/agents/analyze` 或流式版本 `/agents/analyze/stream`）
- 从待修复状态点击"重新分析"
- 重新打开缺陷后进入待分析状态

**触发流程**：
1. 系统获取被分配用户的 Agent 身份列表
2. 根据缺陷类型智能选择主 Agent：
   - "UI问题" → 优先 UI_Agent
   - "功能缺陷" → 根据系统模块判断前端/后端 Agent
   - "性能问题" → 前端/后端 Agent 协作
   - "安全问题" → 后端 Agent
   - "兼容性问题" → 前端/客户端 Agent

#### 4.4.2 分析执行流程（ADK 模式）

```
1. 加载缺陷和AI配置（多配置兜底）
2. 更新缺陷状态为 analyzing
3. 获取代码上下文（Git克隆 + 检索器检索）
4. Planner探索阶段：
   a. Planner Agent 输出结构化探索计划
   b. Executor 按计划调用工具（search_code/read_file/list_directory/trace_call/find_api_handler）
   c. 收集代码证据
5. Analysis Pipeline 运行（LLM Agent + 工具调用）
6. 后处理：
   a. JSON 提取和字段归一化
   b. 证据修复（normalizeAnalysisByRepoEvidence）
   c. 存储 AnalysisReport
   d. 记录 Token 用量
   e. 异步提取 Agent 记忆
7. 分析成功 → 缺陷进入待修复
8. 分析失败 → 展示明确失败原因，缺陷主流程不被阻断
```

#### 4.4.3 流式分析

支持 SSE 流式输出分析过程，前端实时展示：
- 思考步骤（Thinking Steps）
- 当前阶段（retrieval / analysis / validation）
- 工具调用和结果
- 最终分析报告

**降级机制**：流式分析失败时，自动切换到轮询模式（3秒间隔，40轮超时），保证用户始终能看到分析结果。

#### 4.4.4 分析报告结构

```json
{
  "reportId": "AR-202501-001",
  "defectId": "BUG-DEMO-202501-001",
  "agentType": "frontend",
  "createTime": "2026-01-15T10:30:00Z",
  "analysis": {
    "rootCause": "根本原因分析（不超过2句话）",
    "affectedFiles": ["src/components/Form.vue", "src/utils/validator.js"],
    "affectedScope": "影响范围描述（不超过1句话）",
    "riskLevel": "high/medium/low"
  },
  "solution": {
    "description": "修复方案描述",
    "steps": [
      {
        "step": 1,
        "action": "修改文件，增加空值校验（不超过1句话）",
        "code": "示例代码片段"
      }
    ],
    "estimatedEffort": "低/中/高"
  },
  "references": [
    { "type": "code", "path": "src/components/Form.vue", "line": 45 }
  ],
  "provider": "openai",
  "model": "gpt-4o",
  "tokenUsage": {
    "promptTokens": 1200,
    "completionTokens": 800
  }
}
```

#### 4.4.5 分析范围限定

AI 分析报告中涉及的文件路径，在进入修复阶段时会通过 `FixAnalysisScopeService` 进行仓库范围限定：
- 递归遍历分析报告的 JSON 结构
- 对 filePath/path/targetFile 等字段执行路径归一化
- 按目标仓库智能过滤 affectedFiles

#### 4.4.6 Agent调度

**优先级调度**：
- `PriorityUser(0)` > `PriorityAuto(1)` > `PriorityBackground(2)`
- 用户触发的分析优先于自动触发
- 并发控制：可配置最大并发数（默认3）
- 任务去重：同一缺陷不可重复提交
- 队列状态可通过 API 查询

**取消机制**：
- 支持取消正在运行或队列中的分析任务
- 取消后已消耗的 Token 仍记录
- 已产出的部分结果保存为 cancelled 状态的报告

### 4.5 修复管理

#### 4.5.1 AI自动修复

**入口条件**：缺陷状态为"待修复"，已有至少一份分析报告

**修复执行流程（8步流水线）**：

```
1. 克隆仓库（浅克隆）
2. 创建修复分支
3. AI 生成修复代码（多配置兜底，最多3次重试）
   └─ CodeGenerator: 结构化补丁 + oldContent 精确匹配 + 语法验证
4. 应用代码变更（applyContentHunks）
5. Git 提交
6. 构建验证（可选，含 baseline 对比）
7. Git 推送
8. 创建 PR（GitHub/GitLab）
```

**AI 代码生成关键保障**：
- **结构化补丁**：AI 输出 JSON 格式补丁，包含 filePath 和 hunks 数组
- **精确匹配**：oldContent 在当前代码中必须恰好匹配一次
- **语法验证**：Go 文件使用 `go/parser` 做语法检查
- **重试机制**：失败时回传错误信息给 AI 自我修正，最多 3 次
- **无变更检测**：AI 判定无需代码变更时标记为 no_changes，跳过剩余步骤

#### 4.5.2 人工修复

**入口条件**：缺陷状态为"待修复"

**操作流程**：
1. 在缺陷详情页点击"人工修复"按钮
2. 状态流转为 `manual_fixing`
3. 用户在外部修改代码后回系统登记：
   - 修复描述（必填）
   - 关联 PR URL（选填，可后续补填）
   - 修复分支名（选填）
4. 点击"提交修复完成"
5. 系统创建 FixTask（`source=manual`）
6. 状态流转为 `pending_verify`

**其他操作**：
- 放弃人工修复：回退到 `pending_fix`，可选择 AI 修复
- 补关联 PR：`pending_verify` 状态下仍可补填 PR URL

#### 4.5.3 修复任务组

当缺陷涉及多个仓库时，系统自动创建 `FixTaskGroup` 聚合多个仓库的 FixTask，统一管理修复进度和 PR 状态。

### 4.6 PR生命周期

#### 4.6.1 PR状态跟踪

FixTask 关联 PR 后，系统跟踪其全生命周期：

| PR状态 | 说明 |
|--------|------|
| open | PR 已创建，待审核 |
| merged | PR 已合并，缺陷自动推进到 fixed |
| rejected | PR 被拒绝（closed without merge），缺陷回退到 pending_fix |
| closed | PR 被关闭（不合并） |

#### 4.6.2 PR拒绝处理

**触发条件**：
- VCS Webhook 回调（GitHub `pull_request` event / GitLab `Merge Request` event）
- 手动标记（Webhook 不可用时的降级方案）

**处理逻辑**：
1. 创建 PRRejection 记录（含拒绝人、原因、时间）
2. 更新 FixTask.PRStatus = "rejected"
3. 缺陷状态回退到 `pending_fix`
4. 在评论区发布通知
5. 拒绝原因异步沉淀为 Agent 记忆

#### 4.6.3 PR合并处理

- FixTask.PRStatus 更新为 "merged"
- 缺陷状态推进到 `fixed`

### 4.7 问题池与信号接入

#### 4.7.1 外部信号接入

**支持的连接器类型**：

| 连接器 | 说明 |
|--------|------|
| Bugly | 腾讯 Bugly 异常信号接入 |
| 阿里云日志 | 阿里云日志服务信号接入 |
| 钉钉 | 钉钉群机器人消息接入 |
| 飞书 | 飞书群机器人消息接入 |
| 通用 Webhook | 支持自定义签名校验的通用 Webhook |

**接入流程**：
```
外部平台 → POST /api/v1/inbound/connectors/:token
├─ 创建/更新 IntegrationSyncRecord
├─ 事务内逐条处理
│   ├─ 字段归一化（NormalizePayload）
│   ├─ 来源差异化补全（enrichPayloadForSource）
│   └─ 指纹生成（SHA256）→ 聚类入库
├─ IssueCluster 聚类（同指纹归入同一簇）
├─ IssueSignal 去重入库（source_event_id）
└─ 自动路由匹配（ApplyClusterRouting）
```

**字段归一化**：支持从不同来源的 payload 中按优先级提取标题、描述、堆栈、指纹等信息。

#### 4.7.2 问题簇管理

| 功能 | 说明 |
|------|------|
| 列表浏览 | 按项目展示问题簇列表，含簇数、信号数、状态、严重级别 |
| 簇详情 | 查看簇内所有信号列表、来源分布、版本分布 |
| 分配负责人 | 手动分配问题簇处理人 |
| 忽略 | 忽略问题簇（标记为误报或已处理） |
| 合并 | 合并疑似重复的问题簇 |
| 转换为缺陷 | 将问题簇转为正式缺陷，保留关联关系 |
| 批量操作 | 批量分配、忽略、转换 |
| 自动分诊 | AI 自动建议项目归属、责任人、严重级别和优先级 |

#### 4.7.3 路由规则

**路由匹配引擎**：按 sort_order 依次匹配，支持五种匹配方式：

| 匹配方式 | 说明 |
|----------|------|
| source_type | 按信号来源类型匹配 |
| platform | 按平台匹配（iOS/Android/Web） |
| app_version | 按应用版本匹配 |
| fingerprint_pattern | 按指纹正则表达式匹配 |
| stack_keyword | 按堆栈关键词匹配 |

匹配成功后自动设置问题簇的模块、负责人、优先级和严重级别。

### 4.8 Agent能力管理

#### 4.8.1 Agent记忆

**两级记忆架构**：

| 维度 | 作用域 | 生命周期 | 典型内容 |
|------|--------|----------|----------|
| 迭代级记忆 | 单个迭代 | 随迭代归档 | "本次迭代在做支付模块重构" |
| 项目级记忆 | 整个项目 | 持久 | "本项目使用 Next.js App Router" |

**记忆来源**：
1. **自动提取**：AI 分析/修复完成后，从结果中提取可复用知识
2. **人工录入**：用户在项目/迭代设置中手动添加
3. **PR拒绝反馈**：拒绝原因自动沉淀为避免策略

**记忆注入**：
- AI 分析和修复时，自动注入匹配的记忆条目
- 按相关性评分排序，总量控制在 2000 token 以内
- 去重机制：Jaccard 相似度检测，相似度 > 0.8 时合并更新

#### 4.8.2 MCP服务管理

项目内可管理 MCP 服务配置：
- 添加/编辑/删除 MCP 服务器
- 支持启用/禁用
- 支持连通性测试
- Agent 运行时自动加载已启用的 MCP 工具

#### 4.8.3 Agent技能管理

项目内可配置 Agent 技能（Skill）：
- 按 Agent 类型配置指令和工具
- 支持绑定 MCP 服务
- 支持启用/禁用记忆注入
- 配置变更即时生效，无需重启服务

### 4.9 检索器插件

支持插件化检索器，按项目启用：

| 检索器 | 说明 | 状态 |
|--------|------|------|
| 关键词检索 | 文件路径匹配 + 文件内容搜索，加权排序 TopK | 已实现 |
| RepoWiki | HTTP 调用外部 repo-wiki 服务的符号搜索 | 已实现 |
| RAG 检索 | 向量检索（预留） | 骨架 |
| 需求检索 | 需求文档检索（预留） | 骨架 |

### 4.10 通知管理

#### 4.10.1 通知渠道

| 渠道 | 说明 |
|------|------|
| 站内通知 | 系统内通知列表，支持标记已读/全部已读 |
| 邮件 | SMTP 发送邮件通知 |
| Webhook | 自定义 Webhook 回调 |

#### 4.10.2 通知策略

**项目级通知策略**：
- 按事件类别配置（缺陷创建、状态变更、修复完成等）
- 支持配置邮件和 Webhook 目标
- Webhook 支持签名密钥和签名校验

**个人通知偏好**：
- 用户可自定义接收哪些类别的通知
- 个人偏好不得突破项目允许范围
- 通知推送失败不影响主流程

### 4.11 质量洞察与回归预防

#### 4.11.1 质量洞察

**聚合数据维度**：
- 问题池摘要（簇数、信号数、待处理数）
- 回归摘要（活跃回归项数、覆盖率）
- 版本健康（各版本异常等级、信号趋势）
- AI 统计（分析成功率、修复成功率、平均耗时、Token 费用）
- 来源分布（各连接器来源的簇数和信号数）
- 模块热点（按模块统计簇数、开放数、转化数）
- 异常版本排名

#### 4.11.2 回归预防

- 从问题簇创建回归检测项
- 回归项状态：Draft → Active → Verified → Archived
- 支持验证时间记录
- 自动去重（相同 cluster_id 不重复创建）

### 4.12 报表与统计

#### 4.12.1 仪表盘

- 今日新增/解决缺陷数
- 各状态缺陷分布
- 严重级别分布
- 周趋势图
- 团队工作量指标

#### 4.12.2 Token与成本统计

**统计维度**：
| 维度 | 说明 |
|------|------|
| 单缺陷 | 总 Token 数、费用、按分析/修复分组明细 |
| 单迭代 | 迭代内所有缺陷的汇总 |
| 项目级 | 项目内所有迭代的汇总、趋势 |

**记录字段**：Provider、Model、Prompt Tokens、Completion Tokens、EstimatedCostUSD、Fallback 标记、耗时

**数据准确性**：99% 以上 AI 调用有 Token 记录

#### 4.12.3 数据导出

支持 CSV 和 JSON 两种格式导出缺陷数据。

### 4.13 平台治理

#### 4.13.1 凭证管理

| 凭证类型 | 范围 | 说明 |
|----------|------|------|
| 个人凭证 | 创建者个人 | 仅创建者可用 |
| 平台凭证 | 全局 | 可绑定项目并设置启用状态 |

**仓库认证解析优先级**：仓库绑定的凭证 → 项目默认凭证 → 操作者个人凭证

**安全措施**：
- AES-256-GCM 加密存储
- API 返回脱敏
- 支持连接测试（浅克隆验证）

#### 4.13.2 AI目录管理

平台管理员可管理全局 AI 厂商和模型目录：
- 新增/编辑/删除 AI 提供商
- 新增/编辑/删除 AI 模型
- 测试模型可用性
- 模型目录为项目级 AI 配置提供可选列表

#### 4.13.3 平台设置

- SMTP 邮件服务器配置（含测试发送）
- 安全策略配置（强制改密、会话有效期）

#### 4.13.4 审计日志

**必须审计的事件**：
1. Webhook 签名失败
2. 凭证新增、编辑、删除
3. 用户强制改密
4. PR 被拒绝
5. AI 任务取消
6. Agent 高风险工具操作
7. 用户权限变更

**实现方式**：缓冲队列批量写入（最多500条/2秒间隔），支持优雅关闭排空。

### 4.14 协作讨论

#### 4.14.1 缺陷评论

- 评论支持 Markdown 格式
- 支持 @ 成员引入其 Agent 身份参与分析
- AI 分析和修复完成后自动在评论区发布报告

#### 4.14.2 多Agent协作

支持同时调度多个 Agent 对同一缺陷进行并行分析：

```
POST /collaborations
├─ 创建 CollaborationTask
├─ 每个 agentType 创建一个 LLM Agent
├─ 超过1个Agent时使用 ParallelAgent 并行化
├─ 收集所有 Agent 的分析结果
└─ 生成汇总报告 (CollaborationReport)
```

---

## 五、状态模型

### 5.1 状态定义

| 状态 | 说明 | 可操作角色 |
|------|------|-----------|
| `new` | 新建 | 测试人员 |
| `pending_assign` | 待分配 | 测试人员 |
| `pending_analysis` | 待分析 | 系统（自动流转） |
| `analyzing` | 分析中 | 系统（自动流转） |
| `pending_fix` | 待修复 | 测试人员、被分配用户 |
| `fixing` | AI修复中 | 系统（自动流转） |
| `manual_fixing` | 人工修复中 | 被分配用户 |
| `pending_verify` | 待验证 | 测试人员 |
| `fixed` | 已修复 | 被分配用户 |
| `completed` | 已完成 | 所有人员（只读） |
| `rejected` | 驳回 | 被分配用户 |
| `suspended` | 暂停 | 被分配用户 |
| `reopened` | 重新打开 | 被分配用户 |

### 5.2 状态流转图

```
                    ┌──────────────────────┐
                    │        new           │
                    └──────────┬───────────┘
                               │ 提交
                    ┌──────────▼───────────┐
                    │   pending_assign     │
                    └──────────┬───────────┘
                               │ 分配
                    ┌──────────▼───────────┐
              ┌─────│   pending_analysis   │←──────┐
              │     └──────────┬───────────┘       │
              │ 驳回           │ 开始分析          │ 重新分析
              ▼                ▼                   │
         ┌──────────┐   ┌──────────┐               │
         │ rejected │   │ analyzing│               │
         └────┬─────┘   └────┬─────┘               │
              │ 重新打开      │ 分析完成            │
              │    ┌──────────▼───────────┐         │
              └───→│    reopened    │     │         │
                   └──────────┬───────────┘         │
                              │                    │
           ┌──────────────────┘                    │
           ▼                                       │
     ┌──────────────┐                              │
     │ pending_fix  │──────────────────────────────┘
     └──┬───────┬───┘
        │       │
        │ AI    │ 人工
        ▼       ▼
   ┌────────┐ ┌──────────────┐
   │ fixing │ │ manual_fixing│
   └───┬────┘ └──────┬───────┘
       │ 修复完成     │ 提交/放弃
       ▼              ▼
   ┌──────────────────────┐
   │   pending_verify     │
   └──────────┬───────────┘
       ┌──────┴──────┐
       │ 通过        │ 失败
       ▼             │
   ┌────────┐        │
   │ fixed  │        │
   └───┬────┘        │
       │ 合并代码     │
       ▼              │
   ┌──────────┐       │
   │completed │       │
   └──────────┘       │
                      └─────→ 回到 pending_fix

  可中断路径:
  pending_analysis → rejected (被分配用户驳回)
  pending_fix → rejected/suspended
  fixing/pending_verify → rejected (PR拒绝回退)
  any → suspended
  rejected → reopened → pending_analysis/analyzing/pending_fix
```

### 5.3 状态流转规则

| 当前状态 | 目标状态 | 触发条件 | 操作人 |
|---------|---------|---------|--------|
| new | pending_assign | 提交缺陷 | 测试人员 |
| pending_assign | pending_analysis | 分配缺陷 | 测试人员 |
| pending_analysis | analyzing | 开始分析 | 用户/系统 |
| pending_analysis | rejected | 认为不是缺陷 | 被分配用户 |
| analyzing | pending_fix | AI分析完成 | 系统自动 |
| pending_fix | fixing | 发起自动修复 | 测试人员 |
| pending_fix | manual_fixing | 发起人工修复 | 测试人员 |
| pending_fix | pending_analysis | 重新分析 | 测试人员 |
| pending_fix | rejected | 驳回 | 被分配用户 |
| pending_fix | suspended | 暂停处理 | 被分配用户 |
| fixing | pending_verify | AI修复完成 | 系统自动 |
| manual_fixing | pending_verify | 提交修复完成 | 被分配用户 |
| manual_fixing | pending_fix | 放弃人工修复 | 被分配用户 |
| pending_verify | fixed | PR合并 | VCS Webhook/手动 |
| pending_verify | pending_fix | PR拒绝/验证失败 | VCS Webhook/手动 |
| fixed | completed | 代码合并完成 | 被分配用户 |
| completed | — | 终态 | — |
| rejected | reopened | 重新打开 | 被分配用户 |
| rejected | pending_analysis | 重新打开到待分析 | 被分配用户 |
| reopened | pending_analysis | 回到待分析 | 被分配用户 |
| reopened | analyzing | 直接重新分析 | 被分配用户 |
| reopened | pending_fix | 跳过分析直接修复 | 被分配用户 |
| reopened | rejected | 驳回 | 被分配用户 |
| suspended | pending_fix | 恢复处理 | 被分配用户 |

---

## 六、实时通信

### 6.1 SSE 推送架构

使用 Server-Sent Events（SSE）替代 WebSocket，实现服务端到客户端的单向实时推送。

**连接方式**：`GET /api/v1/sse?token={jwt}&rooms=defect:1,project:5`

**支持的事件类型**：

| 事件 | 说明 |
|------|------|
| `defect:status_changed` | 缺陷状态变更 |
| `defect:created` / `defect:updated` | 缺陷创建/更新 |
| `analysis:started/progress/completed/failed` | AI分析过程 |
| `fix_task:created/progress/completed/failed` | 自动修复过程 |
| `comment:added` | 评论添加 |
| `collaboration:started/progress/completed` | 多Agent协作 |
| `notification` | 系统通知 |

**Broker 架构**：发布订阅模式，按房间（room）管理订阅者，channel buffer 1024，慢客户端自动断开。

**前端实现**：
- `SSEManager` 单例类：EventSource 连接、房间订阅、16 种事件解析
- 指数退避重连机制（3s → 30s，最多 10 次）
- `useSSE`/`useSSEEvent` React Hook 封装

### 6.2 流式分析

- Fetch ReadableStream 读取分析进度
- 自动降级到轮询模式（3s 间隔，40 轮超时）
- 页面刷新后恢复分析轮询（`restorePolling`）

---

## 七、安全架构

### 7.1 认证与授权

| 机制 | 说明 |
|------|------|
| JWT认证 | golang-jwt/v5，HS256 签名，Token黑名单支持撤销 |
| 密码哈希 | bcrypt |
| RBAC | 平台角色 + 项目角色双层次，TTL缓存加速 |
| 强制改密 | `must_change_password=true` 的用户登录后必须改密 |

### 7.2 数据安全

| 措施 | 说明 |
|------|------|
| 凭据加密 | AES-256-GCM 加密存储仓库凭证和 AI API Key |
| 密钥脱敏 | API 返回时仅显示前4位和后4位 |
| 邀请码签名 | HMAC-SHA256 签名防篡改 |
| 仓库隔离 | 按缺陷隔离工作目录，修复完成后删除，定时清理残留 |

### 7.3 安全中间件

| 中间件 | 说明 |
|--------|------|
| 限流 | 基于 Redis 的滑动窗口限流 |
| CORS | 可配置的跨域白名单 |
| 审计日志 | 所有敏感操作记录审计，含操作人、时间、来源 |
| 口令变更保护 | 密码修改后强制重新登录 |

### 7.4 Agent安全

| 措施 | 说明 |
|------|------|
| SafetyGate | 只读工具（search_code/read_file）自动批准，写操作需评估 |
| 工具权限 | 按 Agent 类型白名单过滤工具集 |
| MCP命令白名单 | 仅允许 `mcp-server` 和 `mcp` 命令 |
| RolloutRecorder | 完整记录 Agent 对话和操作事件，可审计追溯 |

---

## 八、数据模型

### 8.1 核心数据表

#### 用户表 (users)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| username | varchar(50) | 用户名，唯一 |
| email | varchar(100) | 邮箱，唯一 |
| password | varchar(255) | 密码（bcrypt加密） |
| nickname | varchar(50) | 昵称 |
| avatar | varchar(255) | 头像URL |
| agent_types | varchar(200) | Agent身份列表，逗号分隔 |
| platform_role | varchar(30) | 平台角色（super_admin/admin/member） |
| must_change_password | boolean | 是否强制改密 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

#### 项目表 (projects)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| name | varchar(100) | 项目名称 |
| description | text | 项目描述 |
| owner_id | bigint | 创建者ID |
| status | varchar(20) | 状态(active/archived) |
| memory_enabled | boolean | 是否启用Agent记忆 |
| defect_seq | int | 缺陷序号计数器 |
| defect_seq_year_month | varchar(6) | 当前序号对应年月 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

#### 项目成员表 (project_members)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| project_id | bigint | 项目ID |
| user_id | bigint | 用户ID |
| role | varchar(20) | 项目角色（project_admin/developer/tester/viewer） |

#### 项目仓库表 (project_repos)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| project_id | bigint | 项目ID |
| name | varchar(100) | 仓库名称 |
| repo_url | varchar(500) | 仓库地址（项目内唯一） |
| description | text | 仓库描述 |
| default_branch | varchar(100) | 默认分支 |
| vcs_provider | varchar(20) | VCS提供商（github/gitlab） |
| credential_id | bigint | 关联凭证ID |

#### 项目AI配置表 (project_ai_configs)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| project_id | bigint | 项目ID |
| provider | varchar(50) | AI厂商 |
| model_name | varchar(100) | 模型名称 |
| api_key | text | 访问密钥，AES-256-GCM加密 |
| api_endpoint | varchar(500) | API端点 |
| is_default | boolean | 是否为默认配置 |
| function_calling_mode | varchar(20) | 函数调用模式（enabled/disabled/auto） |

#### 迭代表 (iterations)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| project_id | bigint | 项目ID |
| name | varchar(100) | 迭代名称 |
| start_date | date | 开始日期 |
| end_date | date | 结束日期 |
| status | varchar(20) | 状态(planning/active/completed) |

#### 迭代仓库绑定表 (iteration_repos)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| iteration_id | bigint | 迭代ID |
| repo_id | bigint | 项目仓库ID |
| branch | varchar(100) | 绑定的目标分支 |

#### 缺陷表 (defects)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| code | varchar(50) | 缺陷编号（BUG-XXX-YYYYMM-NNN） |
| iteration_id | bigint | 迭代ID |
| title | varchar(200) | 标题 |
| description | text | 描述 |
| severity | varchar(20) | 严重级别 |
| priority | varchar(10) | 优先级 |
| type | varchar(30) | 缺陷类型 |
| status | varchar(20) | 状态 |
| assignee_id | bigint | 被分配用户ID |
| reporter_id | bigint | 报告人ID |
| tags | text | 标签，逗号分隔 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

#### 分析报告表 (analysis_reports)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| defect_id | bigint | 缺陷ID |
| agent_type | varchar(20) | Agent类型 |
| analysis | jsonb | 分析内容（rootCause/affectedFiles/riskLevel） |
| solution | jsonb | 解决方案（description/steps） |
| provider | varchar(50) | AI厂商 |
| model | varchar(100) | 模型名称 |
| status | varchar(20) | 状态（completed/failed/cancelled） |
| is_obsolete | boolean | 是否已失效（重新分析后标记） |
| created_at | timestamp | 创建时间 |

#### 修复任务组表 (fix_task_groups)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| defect_id | bigint | 缺陷ID |
| target_branch | varchar(100) | 目标分支 |
| summary | text | 修复摘要 |
| ai_provider | varchar(50) | AI厂商 |
| ai_model | varchar(100) | 模型名称 |
| status | varchar(20) | 状态 |

#### 修复任务表 (fix_tasks)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| fix_task_group_id | bigint | 所属任务组ID |
| defect_id | bigint | 缺陷ID |
| repo_id | bigint | 仓库ID |
| agent_type | varchar(20) | Agent类型 |
| source | varchar(20) | 来源（auto/manual） |
| status | varchar(20) | 状态 |
| plan | jsonb | 修复计划 |
| result | jsonb | 修复结果 |
| pr_url | varchar(500) | PR链接 |
| pr_status | varchar(20) | PR状态（open/merged/closed/rejected） |
| manual_description | text | 人工修复描述 |
| created_at | timestamp | 创建时间 |
| completed_at | timestamp | 完成时间 |

#### 评论表 (comments)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| defect_id | bigint | 缺陷ID |
| user_id | bigint | 用户ID |
| content | text | 内容 |
| agent_type | varchar(20) | Agent类型(如果是Agent发布) |
| is_agent_message | boolean | 是否为Agent消息 |
| created_at | timestamp | 创建时间 |

#### 附件表 (attachments)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| defect_id | bigint | 缺陷ID |
| file_name | varchar(255) | 文件名 |
| file_path | varchar(500) | 文件路径 |
| file_size | bigint | 文件大小 |
| mime_type | varchar(100) | MIME类型 |
| uploaded_by | bigint | 上传者ID |
| created_at | timestamp | 创建时间 |

#### 问题簇表 (issue_clusters)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| project_id | bigint | 项目ID |
| fingerprint | varchar(64) | 信号指纹（SHA256） |
| title | varchar(500) | 问题标题 |
| triage_status | varchar(20) | 分诊状态 |
| severity | varchar(20) | 严重级别 |
| priority | varchar(10) | 优先级 |
| signal_count | int | 信号数量 |
| linked_defect_id | bigint | 关联缺陷ID |
| assignee_id | bigint | 负责人ID |
| first_seen_at | timestamp | 首次发现时间 |
| last_seen_at | timestamp | 最后发现时间 |

#### 问题信号表 (issue_signals)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| cluster_id | bigint | 所属问题簇ID |
| connector_id | bigint | 来源连接器ID |
| source_event_id | varchar(200) | 来源事件ID（去重键） |
| payload | jsonb | 原始负载 |
| platform | varchar(50) | 平台 |
| app_version | varchar(50) | 应用版本 |
| stack_trace | text | 堆栈信息 |
| fingerprint | varchar(64) | 信号指纹 |
| first_seen_at | timestamp | 首次发现时间 |
| last_seen_at | timestamp | 最后发现时间 |

#### 集成连接器表 (integration_connectors)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| project_id | bigint | 项目ID |
| type | varchar(30) | 类型（bugly/aliyun/dingtalk/feishu/webhook） |
| name | varchar(100) | 连接器名称 |
| config | jsonb | 连接配置 |
| status | varchar(20) | 状态（active/inactive/error） |
| health_message | text | 健康状态信息 |
| token | varchar(64) | 接入令牌 |
| created_at | timestamp | 创建时间 |

#### Agent记忆表 (agent_memories)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| project_id | bigint | 项目ID |
| iteration_id | bigint | 迭代ID（nil=项目级） |
| category | varchar(30) | 分类（architecture/convention/common_error/fix_strategy/avoid_strategy） |
| content | text | 记忆内容 |
| source | varchar(20) | 来源（auto_extract/manual/pr_rejection） |
| source_ref_id | bigint | 来源关联ID |
| relevance_score | float | 相关性评分 |
| enabled | boolean | 是否启用 |
| created_by | bigint | 创建者 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

#### Token用量表 (ai_token_usage)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| project_id | bigint | 项目ID |
| defect_id | bigint | 缺陷ID |
| iteration_id | bigint | 迭代ID |
| provider | varchar(50) | AI厂商 |
| model | varchar(100) | 模型名称 |
| prompt_tokens | int | Prompt Token数 |
| completion_tokens | int | Completion Token数 |
| estimated_cost_usd | decimal(10,6) | 预估费用（USD） |
| is_fallback | boolean | 是否为Fallback调用 |
| duration_ms | int | 调用耗时（毫秒） |
| source | varchar(20) | 来源（analysis/fix/memory_extraction） |
| created_at | timestamp | 创建时间 |

#### 其他表
| 表名 | 说明 |
|------|------|
| roles | RBAC角色定义 |
| permissions | RBAC权限定义 |
| role_permissions | 角色-权限关联 |
| user_roles | 用户-角色关联 |
| status_changes | 缺陷状态变更历史 |
| notifications | 站内通知记录 |
| notification_templates | 通知模板 |
| notification_preferences | 用户通知偏好 |
| project_webhooks | 项目Webhook配置 |
| project_notification_policies | 项目通知策略 |
| platform_settings | 平台设置（SMTP等） |
| pr_rejections | PR拒绝记录 |
| analysis_tasks | 分析任务记录 |
| retriever_plugins | 检索器插件配置 |
| rollout_records | Agent会话日志 |
| collaboration_tasks | 多Agent协作任务 |
| collaboration_reports | 协作汇总报告 |
| repo_credentials | 仓库凭证 |
| platform_credential_projects | 平台凭证-项目关联 |
| invite_codes | 邀请码 |
| audit_logs | 审计日志 |
| project_mcp_servers | MCP服务配置 |
| project_agent_skills | Agent技能配置 |
| project_modules | 项目模块 |
| issue_routing_rules | 信号路由规则 |
| app_releases | 应用发布版本 |
| regression_items | 回归预防项 |
| integration_sync_records | 集成同步记录 |
| project_ai_catalog | AI厂商目录 |
| ai_model_catalog | AI模型目录 |

---

## 九、接口设计

### 9.1 认证接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/register` | 用户注册 |
| POST | `/api/v1/auth/login` | 用户登录 |
| POST | `/api/v1/auth/logout` | 登出（Token加入黑名单） |
| GET | `/api/v1/users/me` | 获取当前用户信息 |
| PUT | `/api/v1/users/me` | 更新个人信息 |
| PUT | `/api/v1/users/me/password` | 修改密码 |
| POST | `/api/v1/users/me/avatar` | 上传头像 |
| PUT | `/api/v1/users/me/agent-types` | 更新自己的Agent身份 |

### 9.2 用户管理接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/users` | users:read | 获取用户列表（支持keyword/agentType筛选） |
| GET | `/api/v1/users/:id` | users:read | 获取用户详情 |
| POST | `/api/v1/users` | users:manage | 创建用户 |
| POST | `/api/v1/users/:id/reset-password` | users:manage | 重置密码 |
| PUT | `/api/v1/users/:id/agent-types` | users:manage | 分配Agent身份 |
| PUT | `/api/v1/users/:id/platform-role` | users:manage | 修改平台角色 |

### 9.3 项目管理接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/projects` | — | 获取项目列表 |
| POST | `/api/v1/projects` | projects:create | 创建项目 |
| GET | `/api/v1/projects/:id` | projects:read | 获取项目详情 |
| PUT | `/api/v1/projects/:id` | projects:update | 更新项目 |
| POST | `/api/v1/projects/:id/members` | projects:update | 添加成员 |
| DELETE | `/api/v1/projects/:id/members/:memberId` | projects:update | 移除成员 |
| GET | `/api/v1/user/projects` | — | 获取用户参与的项目列表 |
| GET | `/api/v1/projects/:id/stats` | projects:read | 获取项目统计 |

### 9.4 仓库管理接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/projects/:id/repos` | projects:read | 获取项目仓库列表 |
| POST | `/api/v1/projects/:id/repos` | projects:update | 添加仓库 |
| PUT | `/api/v1/projects/:id/repos/:repoId` | projects:update | 更新仓库 |
| DELETE | `/api/v1/projects/:id/repos/:repoId` | projects:update | 删除仓库 |
| GET | `/api/v1/admin/repos/orphaned` | users:manage | 获取孤立仓库列表 |
| POST | `/api/v1/admin/repos/cleanup` | users:manage | 触发仓库清理 |

### 9.5 AI配置管理接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/projects/:id/ai-configs` | projects:read | 获取AI配置列表 |
| POST | `/api/v1/projects/:id/ai-configs` | projects:update | 添加AI配置 |
| PUT | `/api/v1/projects/:id/ai-configs/:configId` | projects:update | 更新AI配置 |
| DELETE | `/api/v1/projects/:id/ai-configs/:configId` | projects:update | 删除AI配置 |

### 9.6 迭代管理接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/v1/projects/:id/iterations` | projects:update | 创建迭代 |
| GET | `/api/v1/projects/:id/iterations` | projects:read | 获取迭代列表 |
| GET | `/api/v1/projects/:id/iterations/:iterationId` | projects:read | 获取迭代详情 |
| PUT | `/api/v1/projects/:id/iterations/:iterationId` | projects:update | 更新迭代 |
| POST | `/api/v1/projects/:id/iterations/:iterationId/repos` | projects:update | 绑定仓库到迭代 |
| DELETE | `/api/v1/projects/:id/iterations/:iterationId/repos/:repoId` | projects:update | 解绑仓库 |
| PUT | `/api/v1/projects/:id/iterations/:iterationId/repos/:iterRepoId/branch` | projects:update | 更新迭代仓库分支 |
| GET | `/api/v1/projects/:id/repos/:repoId/branches` | projects:read | 获取仓库分支列表 |
| GET | `/api/v1/projects/:id/iterations/:iterationId/defects` | projects:read | 获取迭代内缺陷 |

### 9.7 缺陷管理接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/defects` | defects:read | 缺陷列表（支持多维度筛选） |
| POST | `/api/v1/defects` | defects:create | 创建缺陷 |
| GET | `/api/v1/defects/:id` | defects:read | 缺陷详情 |
| PUT | `/api/v1/defects/:id` | defects:update | 更新缺陷 |
| PUT | `/api/v1/defects/:id/assign` | defects:update | 分配缺陷 |
| PUT | `/api/v1/defects/:id/status` | defects:update | 变更状态 |
| PUT | `/api/v1/defects/:id/verify` | defects:update | 验证缺陷 |
| PUT | `/api/v1/defects/:id/merge` | defects:update | 合并缺陷 |
| PUT | `/api/v1/defects/:id/reject` | defects:update | 驳回缺陷 |
| POST | `/api/v1/defects/:id/reopen` | defects:update | 重新打开缺陷 |
| POST | `/api/v1/defects/:id/reanalyze` | defects:update | 重新分析 |
| POST | `/api/v1/defects/:id/manual-fix/start` | fix_tasks:create | 开始人工修复 |
| POST | `/api/v1/defects/:id/manual-fix/complete` | fix_tasks:update | 提交人工修复完成 |
| POST | `/api/v1/defects/:id/manual-fix/abandon` | fix_tasks:update | 放弃人工修复 |
| GET | `/api/v1/defects/:id/recommend-assignees` | defects:read | 推荐负责人 |
| GET | `/api/v1/defects/:id/recommend-agents` | defects:read | 推荐Agent类型 |
| POST | `/api/v1/projects/:id/defects/draft-from-chat` | projects:update | 创建缺陷草稿（对话模式） |
| POST | `/api/v1/projects/:id/defects/confirm-create` | projects:update | 确认创建缺陷（从草稿） |

### 9.8 附件接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/v1/defects/:id/attachments` | defects:update | 上传附件 |
| GET | `/api/v1/defects/:id/attachments` | defects:read | 获取附件列表 |
| DELETE | `/api/v1/defects/:id/attachments/:attachmentId` | defects:update | 删除附件 |
| GET | `/api/v1/uploads/*filename` | JWT认证 | 下载附件 |

### 9.9 Agent分析接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/v1/agents/analyze` | agents:analyze | 触发分析 |
| POST | `/api/v1/agents/analyze/stream` | agents:analyze | 触发流式分析 |
| GET | `/api/v1/agents/reports/:reportId` | agents:read_report | 获取分析报告 |
| POST | `/api/v1/agents/analyze/:id/cancel` | agents:analyze | 取消分析 |
| GET | `/api/v1/agents/analyze/queue` | agents:analyze | 队列状态 |
| GET | `/api/v1/agents/analyze/:id/history` | agents:analyze | 分析历史 |
| GET | `/api/v1/defects/:id/reports` | agents:read_report | 获取缺陷的分析报告列表 |

### 9.10 修复任务接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/v1/defects/:id/fix-tasks` | fix_tasks:create | 创建修复任务 |
| GET | `/api/v1/defects/:id/fix-task-groups` | defects:read | 修复任务组列表 |
| GET | `/api/v1/defects/:id/fix-tasks` | defects:read | 修复任务列表 |
| GET | `/api/v1/fix-tasks/:taskId` | defects:read | 修复任务详情 |
| PUT | `/api/v1/fix-tasks/:taskId` | fix_tasks:update | 更新修复任务状态 |
| PATCH | `/api/v1/defects/:id/fix-tasks/:taskId/pr` | fix_tasks:update | 更新PR关联 |
| POST | `/api/v1/defects/:id/fix-tasks/:taskId/reject` | fix_tasks:update | 手动标记PR拒绝 |
| POST | `/api/v1/defects/:id/fix-tasks/:taskId/merge` | fix_tasks:update | 手动标记PR合并 |
| GET | `/api/v1/defects/:id/fix-tasks/:taskId/rejections` | defects:read | PR拒绝历史 |

### 9.11 工作流接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| PUT | `/api/v1/defects/:id/transition` | defects:update | 状态流转 |
| GET | `/api/v1/defects/:id/transitions` | defects:read | 可流转状态列表 |
| GET | `/api/v1/defects/:id/history` | defects:read | 状态变更历史 |
| POST | `/api/v1/workflow/batch` | defects:update | 批量状态流转 |

### 9.12 问题池接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/projects/:id/issue-clusters` | projects:read | 问题簇列表 |
| GET | `/api/v1/projects/:id/issue-clusters/:clusterId` | projects:read | 问题簇详情 |
| GET | `/api/v1/projects/:id/issue-clusters/:clusterId/signals` | projects:read | 簇内信号列表 |
| GET | `/api/v1/projects/:id/issue-clusters/release-summary` | projects:read | 版本摘要 |
| POST | `/api/v1/projects/:id/issue-clusters/:clusterId/assign` | projects:update | 分配负责人 |
| POST | `/api/v1/projects/:id/issue-clusters/:clusterId/ignore` | projects:update | 忽略 |
| POST | `/api/v1/projects/:id/issue-clusters/:clusterId/merge` | projects:update | 合并 |
| POST | `/api/v1/projects/:id/issue-clusters/:clusterId/convert` | projects:update | 转为缺陷 |
| POST | `/api/v1/projects/:id/issue-clusters/batch-assign` | projects:update | 批量分配 |
| POST | `/api/v1/projects/:id/issue-clusters/batch-ignore` | projects:update | 批量忽略 |
| POST | `/api/v1/projects/:id/issue-clusters/batch-convert` | projects:update | 批量转换 |
| POST | `/api/v1/projects/:id/issue-clusters/auto-triage` | projects:update | 自动分诊 |
| GET | `/api/v1/projects/:id/issue-clusters/suggestion-stats` | projects:read | 分诊建议统计 |

### 9.13 集成连接器接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/projects/:id/integrations` | projects:read | 连接器列表 |
| POST | `/api/v1/projects/:id/integrations` | projects:update | 创建连接器 |
| PUT | `/api/v1/projects/:id/integrations/:connectorId` | projects:update | 更新连接器 |
| DELETE | `/api/v1/projects/:id/integrations/:connectorId` | projects:update | 删除连接器 |
| POST | `/api/v1/projects/:id/integrations/:connectorId/test` | projects:update | 测试连接 |
| POST | `/api/v1/projects/:id/integrations/:connectorId/sync` | projects:update | 触发同步 |
| GET | `/api/v1/projects/:id/integrations/:connectorId/sync-records` | projects:read | 同步记录 |
| POST | `/api/v1/inbound/connectors/:token` | 公开 | 外部信号接入入口 |

### 9.14 权限与审计接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/rbac/roles` | rbac:manage | 角色列表 |
| GET | `/api/v1/rbac/permissions` | rbac:manage | 权限列表 |
| GET | `/api/v1/rbac/my-permissions` | — | 当前用户权限 |
| GET | `/api/v1/rbac/my-roles` | — | 当前用户角色 |
| POST | `/api/v1/rbac/assign` | rbac:manage | 分配用户角色 |
| GET | `/api/v1/rbac/check` | — | 权限校验 |
| GET | `/api/v1/audit-logs` | audit:read | 审计日志列表 |
| GET | `/api/v1/audit-logs/stats` | audit:read | 审计统计 |

### 9.15 通知接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/notifications` | — | 通知列表 |
| GET | `/api/v1/notifications/unread-count` | — | 未读计数 |
| PUT | `/api/v1/notifications/read` | — | 标记已读 |
| PUT | `/api/v1/notifications/read-all` | — | 标记全部已读 |
| POST | `/api/v1/notifications/send` | notifications:send | 发送通知 |
| GET | `/api/v1/notification-preferences` | — | 通知偏好 |
| PUT | `/api/v1/notification-preferences` | — | 更新通知偏好 |
| PUT | `/api/v1/projects/:id/notification-policies` | projects:update | 项目通知策略 |
| GET | `/api/v1/projects/:id/notification-webhooks` | projects:read | Webhook列表 |
| POST | `/api/v1/projects/:id/notification-webhooks` | projects:update | 创建Webhook |

### 9.16 Agent能力管理接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET/POST/PUT/DELETE | `/api/v1/projects/:id/memories` | projects:read/update | Agent记忆CRUD |
| PATCH | `/api/v1/projects/:id/memories/:memoryId/toggle` | projects:update | 启用/禁用记忆 |
| GET | `/api/v1/projects/:id/mcp-servers` | projects:read | MCP服务列表 |
| POST/PUT/DELETE | `/api/v1/projects/:id/mcp-servers` | projects:update | MCP服务CRUD |
| POST | `/api/v1/projects/:id/mcp-servers/:serverId/test` | projects:update | 测试MCP连接 |
| GET | `/api/v1/projects/:id/skills` | projects:read | 技能列表 |
| POST/PUT/DELETE | `/api/v1/projects/:id/skills` | projects:update | 技能CRUD |
| GET | `/api/v1/projects/:id/retriever-plugins` | projects:read | 检索器插件列表 |
| PUT | `/api/v1/projects/:id/retriever-plugins/:pluginId` | projects:update | 更新检索器插件 |
| POST | `/api/v1/projects/:id/retriever-plugins/:pluginId/test` | projects:update | 测试检索器 |

### 9.17 AI目录管理接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/ai/providers` | — | 获取AI厂商列表 |
| GET/POST/PUT/DELETE | `/api/v1/admin/ai/providers` | users:manage | AI厂商CRUD |
| GET/POST/PUT/DELETE | `/api/v1/admin/ai/models` | users:manage | AI模型CRUD |
| POST | `/api/v1/admin/ai/models/:id/test` | users:manage | 测试模型可用性 |

### 9.18 报表与统计接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/reports/dashboard` | — | 仪表盘数据 |
| GET | `/api/v1/reports/trend` | — | 趋势数据 |
| GET | `/api/v1/reports/status-distribution` | — | 状态分布 |
| GET | `/api/v1/reports/severity-distribution` | — | 严重级别分布 |
| GET | `/api/v1/reports/team-metrics` | — | 团队指标 |
| GET | `/api/v1/reports/export/csv` | reports:export | CSV导出 |
| GET | `/api/v1/reports/export/json` | reports:export | JSON导出 |

### 9.19 Token统计接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/projects/:id/token-usage` | projects:read | 项目Token汇总 |
| GET | `/api/v1/projects/:id/token-usage/by-iteration` | projects:read | 按迭代分组 |
| GET | `/api/v1/projects/:id/token-usage/by-defect` | projects:read | 按缺陷分组 |
| GET | `/api/v1/projects/:id/iterations/:iterationId/token-usage` | projects:read | 迭代Token |
| GET | `/api/v1/defects/:id/token-usage` | defects:read | 缺陷Token汇总 |
| GET | `/api/v1/defects/:id/token-usage/details` | defects:read | 缺陷Token明细 |
| GET | `/api/v1/iterations/:id/token-usage` | projects:read | 迭代Token |

### 9.20 协同与质量接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST/GET | `/api/v1/collaborations` | agents:analyze | 创建/列表协作任务 |
| GET | `/api/v1/collaborations/:taskId` | defects:read | 协作任务详情 |
| GET | `/api/v1/collaborations/:taskId/report` | defects:read | 协作汇总报告 |
| GET | `/api/v1/projects/:id/quality-insights/overview` | projects:read | 质量洞察概览 |
| GET/POST | `/api/v1/projects/:id/regression-items` | projects:read/update | 回归项管理 |

### 9.21 凭证与平台设置接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET/POST/PUT/DELETE | `/api/v1/credentials` | — | 个人凭证CRUD |
| POST | `/api/v1/credentials/test-connection` | — | 测试凭证连接 |
| GET/POST/PUT/DELETE | `/api/v1/admin/platform-credentials` | users:manage | 平台凭证CRUD |
| GET/PUT | `/api/v1/admin/platform-settings/email` | system:settings | 邮件设置 |
| POST | `/api/v1/admin/platform-settings/email/test` | system:settings | 测试邮件 |

### 9.22 协作与评论接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/v1/defects/:id/comments` | defects:update | 发布评论 |
| GET | `/api/v1/defects/:id/comments` | defects:read | 获取评论列表 |

---

## 十、非功能性需求

### 10.1 性能需求

| 指标 | 要求 |
|------|------|
| 页面加载时间 | < 2秒 |
| API响应时间 | < 500ms（不含AI调用） |
| Agent分析时间 | < 60秒（典型场景） |
| 流式分析首帧时间 | < 3秒 |
| 支持并发用户数 | > 1000 |
| 并发分析数 | 可配置（默认3） |

### 10.2 安全需求

- 用户认证：JWT Token（HS256签名）
- 权限控制：RBAC 双层次（平台 + 项目）
- 数据加密：敏感数据 AES-256-GCM 加密存储
- 操作审计：记录关键操作日志
- 密钥脱敏：API密钥在接口返回时脱敏显示
- 代码访问：按缺陷隔离工作目录，修复后自动删除
- Webhook签名：支持 `X-Hub-Signature-256` 校验
- Agent安全：SafetyGate 工具调用分级审批

### 10.3 可靠性需求

- AI 失败不阻断缺陷主流程
- 通知失败不阻断主流程
- 外部系统不可用时保留手动路径
- 修复目录按缺陷隔离
- 任务可取消，状态可恢复
- 推送失败不影响主流程状态写入

### 10.4 可观测性

- 连接器有健康状态
- AI 调用有 Token 和耗时记录
- 状态流转有历史记录
- PR 生命周期可追溯
- 页面错误可见且可重试
- 调度器指标可查询

---

## 十一、版本历史

| 版本 | 日期 | 核心变更 | 关联文档 |
|------|------|---------|---------|
| v1.0 | 2025-01 | 初稿：基础缺陷管理、Agent分析、自动修复 | — |
| v1.1 | 2026-03 | 用户管理、AGENT身份分配、项目仓库/迭代仓库分离、AI配置管理 | PRD-v1.1 |
| v2.0~v4.0 | 2026-03~04 | 平台凭证、邀请码、通知系统、SMTP、云效集成、强制改密 | PRD-v2.0 ~ v4.0 |
| v5.0 | 2026-04-12 | 信号接入 + 智能分诊 + 问题池 + 路由闭环 + 质量沉淀 | PRD-v5.0 |
| v5.1 | 2026-04-13 | 项目接入生产化 | PRD-v5.1 |
| v5.2 | 2026-04-13 | 对话式缺陷创建、缺陷详情重新设计 | PRD-v5.2 |
| v5.3 | 2026-04 | 智能运营与加固、Webhook签名校验 | PRD-v5.3 |
| v5.4 | 2026-04-25 | 人工修复路径、PR生命周期管理（拒绝/合并回退）、Agent记忆体系 | PRD-v5.4 |
| v5.5 | 2026-05-06 | 状态链路优化（驳回→待分析、重新分析）、WebSocket→SSE迁移、Token统计、仓库隔离、Agent能力管理（MCP/技能） | PRD-v5.5 |
| v5.6 | 2026-05-08 | Agent架构重设计：Planner+Executor、ToolRegistry动态注册、AgentScheduler优先级调度、SafetyGate、RolloutRecorder | PRD-v5.6 |
| v5.7 | 2026-05 | Function Calling模式支持 | PRD-v5.7 |
| v5.8 | 2026-06 | RepoWiki检索器插件 | PRD-v5.8 |

---

## 十二、附录

### 12.1 术语表

| 术语 | 说明 |
|------|------|
| Agent | 内置的AI智能体，具备特定领域的分析和修复能力 |
| ADK | Agent Development Kit，基于 Google ADK 构建的 Agent 框架 |
| FixTask | 修复任务单元，关联缺陷和仓库 |
| FixTaskGroup | 多仓库修复的聚合任务 |
| 分析报告 | Agent 对缺陷进行分析后生成的结构化报告 |
| 问题簇 | 外部信号聚类后的聚合单元 |
| 问题信号 | 外部平台上报的原始异常信号 |
| 连接器 | 从外部平台接入信号的通道配置 |
| SSE | Server-Sent Events，服务端到客户端的单向实时推送协议 |
| MCP | Model Context Protocol，模型上下文协议，扩展 AI 能力 |
| RBAC | 基于角色的访问控制（Role-Based Access Control） |
| Planner | 探索计划器，输出结构化代码探索步骤 |
| Executor | 计划执行器，按步骤调用工具收集证据 |
| SafetyGate | 安全门控，按操作风险级别自动审批或拒绝工具调用 |
| RolloutRecorder | Agent 会话事件记录器 |
| ToolRegistry | 工具注册中心，支持动态工具组装 |
| AgentScheduler | 优先级任务调度器 |
| AES-256-GCM | 高级加密标准，256位密钥，Galois/Counter模式 |

### 12.2 参考文档

- PRD-v2.0.md ~ PRD-v5.8.md：各版本详细需求文档
- DESIGN-v5.3.md ~ DESIGN-v5.6.md：各版本设计文档
- DEV_PLAN-v3.0.md ~ DEV_PLAN-v5.6.md：各版本开发计划
- CODE_WIKI.md：项目 Code Wiki（架构、模块、部署等）
- 测试计划与报告：TEST_PLAN、TEST_PROGRESS 系列文档

---

**文档变更记录**

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|---------|------|
| v1.0 | 2025-01 | 初稿 | WorkBuddy |
| v1.1 | 2026-03 | 新增用户管理、项目仓库、AI配置 | WorkBuddy |
| v5.8 | 2026-06-06 | 综合更新：集成 v1.1~v5.8 全部功能，新增问题池/信号接入/Agent记忆/PR生命周期/SSE/AI架构重设计等全部能力，更新状态机、数据模型和接口到最新版本 | WorkBuddy |
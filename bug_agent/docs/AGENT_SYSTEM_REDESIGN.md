# BugAgent Agent 系统重构设计文档

> 版本：v1.1  
> 日期：2026-05-03  
> 作者：BugAgent 架构组  
> 状态：设计评审中（v1.1 新增"自建 vs 集成"评估，修订推荐方案）

---

## 目录

1. [当前架构问题分析](#1-当前架构问题分析)
2. [主流开源 Agent 项目调研](#2-主流开源-agent-项目调研)
3. [自建 vs 集成评估](#3-自建-vs-集成评估) ← **v1.1 新增**
4. [新架构整体设计](#4-新架构整体设计)
5. [执行效率优化方案](#5-执行效率优化方案)
6. [工具扩展框架设计](#6-工具扩展框架设计)
7. [流式输出实现方案](#7-流式输出实现方案)
8. [MCP 协议集成方案](#8-mcp-协议集成方案)
9. [技能管理系统设计](#9-技能管理系统设计)
10. [新旧架构对比分析](#10-新旧架构对比分析)
11. [分阶段实施计划](#11-分阶段实施计划)
12. [性能测试指标及验收标准](#12-性能测试指标及验收标准)
13. [潜在风险评估及应对策略](#13-潜在风险评估及应对策略)

---

## 1. 当前架构问题分析

### 1.1 系统现状概览

当前 BugAgent 的 Agent 系统围绕缺陷生命周期构建，核心流程为：

```
缺陷创建 → 待分析 → [触发分析] → 分析中 → 待修复 → [触发修复] → 修复中 → 待验证 → 已修复
```

核心组件包括：
- **AnalysisService**：串行遍历 agentTypes 执行分析
- **FixEngine**：7 步修复工作流（克隆→分支→生成→应用→提交→推送→PR）
- **CodeExplorer**：自研多轮 Tool-Use Agent（4 种工具）
- **CollaborationService**：并行多 Agent 协作（独立于分析路径）
- **AgentMemoryService**：项目级知识积累（Jaccard 去重）

### 1.2 核心问题清单

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| P1 | **执行效率过低** | 多 Agent 类型串行执行（`for range agentTypes`）；每次分析克隆仓库；AI 配置重复查询+解密 | 3 种 Agent 分析耗时 = 单次 × 3，无并行加速 |
| P2 | **可用工具数量有限** | 仅 CodeExplorer 4 种工具（search_code/read_file/trace_call/find_api_handler）；自研协议非标准 | 无法执行测试、查询数据库、Web 搜索、文件系统操作 |
| P3 | **缺乏流式输出** | `ChatStream` 已实现但从未使用；前端只能轮询；WS 通知在 Analysis/Fix 路径断裂 | 用户等待黑盒，体验差；无法实时展示推理过程 |
| P4 | **缺少 MCP 集成** | CodeExplorer 使用自研 tool-use 协议（JSON 正则解析），不兼容 MCP 标准 | 无法接入 MCP 生态工具（已有数百个 MCP Server） |
| P5 | **缺少技能系统** | 无技能注册/组合/调度机制；Prompt 硬编码；Agent 类型名存实亡（client/product/test fallback 到 frontend） | 扩展新能力需改代码；无法动态组合能力 |
| P6 | **Prompt 管理落后** | 纯字符串拼接；版本号硬编码常量；无模板引擎 | 变更风险高，无法 A/B 测试 |
| P7 | **协作路径分裂** | 单 Agent 串行 vs 多 Agent 并行两套代码；WS 通知仅 CollaborationService 接入 | 维护成本高，行为不一致 |

### 1.3 性能基线数据

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| 单 Agent 分析延迟 | 15-30s（含 LLM 调用） | 15-30s（LLM 不可压缩） |
| 3 Agent 串行分析延迟 | 45-90s | 15-30s（并行） |
| 仓库克隆耗时 | 5-15s/次 | <1s（缓存命中） |
| AI 配置查询+解密 | 50-100ms/次 | <5ms（进程缓存） |
| 前端首字节等待 | 等待完整结果 | <200ms（流式首 token） |
| 工具种类 | 4 | 20+（含 MCP 生态） |

---

## 2. 主流开源 Agent 项目调研

### 2.1 LangChain v1.0 + LangGraph

**架构核心**：

LangChain v1.0 围绕 `create_agent` 统一入口重构，核心改进：

| 组件 | 设计 | 要点 |
|------|------|------|
| **Agent Loop** | ReAct 循环（Reason → Tool Call → Observe → Decide） | 标准化推理-行动循环，替代旧版 Chain |
| **Middleware** | 横切能力注入 | Human-in-the-loop、Summarization、PII 脱敏、日志审计 |
| **Structured Output** | 主循环内生成，无需额外 LLM 调用 | 降低成本和延迟 |
| **Tool Calling** | 模型原生 function calling | 并行 tool call 支持 |

**LangGraph**（独立图编排引擎）：

| 特性 | 实现 |
|------|------|
| **执行模型** | 基于 Google Pregel 的超步并行执行 |
| **状态管理** | 持久化状态图（支持中断/恢复/时间旅行调试） |
| **流式输出** | 多级流式：values（完整状态）、updates（增量）、messages（token 级） |
| **人工介入** | 内置 breakpoint + interrupt 机制 |
| **并行** | Send API 实现动态扇出/扇入 |

**关键洞察**：
- LangChain v1.0 将 Agent 从"Chain 组合"简化为"ReAct 循环 + Middleware"
- LangGraph 提供了图级别编排能力，支持循环、条件分支、持久化
- 流式输出是 first-class 支持，不是事后补丁

### 2.2 AutoGPT Platform

**架构核心**：Block → Graph → Agent 三层抽象

| 组件 | 设计 | 要点 |
|------|------|------|
| **Block** | 原子计算单元，async generator | 声明式 JSON Schema 输入输出；yield 支持流式中间结果 |
| **Graph** | Block 编排层（DAG） | 拓扑排序 → 分层并行执行；端口命名连接 |
| **Agent** | Agent 即 Graph | AgentBlock 支持嵌套组合，实现递归多 Agent |
| **Registry** | Block 自动发现注册 | 放入 blocks/ 目录即自动注册 |
| **Credentials** | 凭据与 Block 解耦 | Block 代码不接触原始密钥，运行时注入 |

**执行引擎**：
```
GraphExecutor → 拓扑排序 → 分层并行 → 数据传递 → 状态管理
```

**关键洞察**：
- Block 的 async generator 设计天然支持流式输出
- Agent 即 Graph 避免引入新抽象层
- 端口命名连接比整块连接更精细，支持多输出分别路由
- 凭据管理是安全基础

### 2.3 MetaGPT

**架构核心**：Action → Role → Environment → Message 四层抽象

| 组件 | 设计 | 要点 |
|------|------|------|
| **Action** | 无状态原子操作 | 通过 context 注入共享服务；async run |
| **Role** | 智能体本体 | observe → think → act 循环；3 种 react_mode |
| **Message** | 标准化通信载体 | cause_by 实现类型级路由；Pydantic 结构化输出 |
| **Environment** | 发布-订阅消息总线 | 基于 Action 类型的消息路由；解耦 Role 间依赖 |

**协作模式**：
- **SOP 驱动**：将软件工程最佳实践编码为消息流（PRD → Design → Code → Test）
- **类型级路由**：Role 订阅 Action 类型而非 Role 名称，实现松耦合
- **结构化消息**：Pydantic Model 约束 LLM 输出，减少信息损失

**关键洞察**：
- SOP 约束比自由对话更可靠，适合需要严格流程的场景
- 基于类型的消息路由解耦了发送者和接收者
- 结构化输出（Pydantic）比纯文本更可靠

### 2.4 MCP（Model Context Protocol）

**协议核心**：Client-Host-Server 架构

```
┌──────────────────────┐
│        Host          │  LLM 应用（如 Claude Desktop）
│  ┌────────────────┐  │
│  │    Client 1    │  │  1:1 连接 Server
│  └────────────────┘  │
│  ┌────────────────┐  │
│  │    Client 2    │  │  每个 Client 独立会话
│  └────────────────┘  │
└──────────────────────┘
         │
    JSON-RPC 2.0
         │
┌──────────────────────┐
│       Server         │  提供上下文和能力
│  ┌────────────────┐  │
│  │   Resources    │  │  应用控制的上下文数据
│  ├────────────────┤  │
│  │    Prompts     │  │  用户控制的模板消息
│  ├────────────────┤  │
│  │     Tools      │  │  模型控制的执行函数
│  └────────────────┘  │
└──────────────────────┘
```

**三种原语**：

| 原语 | 控制方 | 描述 | 示例 |
|------|--------|------|------|
| Resources | 应用 | 上下文数据，由客户端附加 | 文件内容、Git 历史 |
| Prompts | 用户 | 交互式模板，由用户选择触发 | 斜杠命令、菜单选项 |
| Tools | 模型 | AI 可调用的函数 | 代码搜索、文件读写 |

**Sampling（采样）**：Server 可请求 Client 的 LLM 生成能力，实现 Server 端的 Agent 循环（2025-11 规范新增）。

**关键洞察**：
- MCP 标准化了 AI 应用与外部工具/数据的集成方式
- 三种原语的控制模型不同，对应不同的安全边界
- Sampling 允许 MCP Server 实现自主推理循环

### 2.5 调研结论与选型依据

| 需求 | 参考项目 | 采用方案 |
|------|----------|----------|
| Agent 执行循环 | LangChain ReAct + Middleware | ReAct 循环 + Middleware 横切 |
| 图编排 | LangGraph Pregel + AutoGPT Graph | 有向图编排，分层并行 |
| 工具集成 | MCP 协议 + AutoGPT Block | MCP Server 标准接口 + Block 注册 |
| 多 Agent 协作 | MetaGPT Environment + AutoGPT AgentBlock | 发布-订阅消息总线 + 类型级路由 |
| 流式输出 | LangGraph 多级流式 + AutoGPT generator | SSE + WebSocket 双通道 |
| 技能管理 | AutoGPT Block 组合 + MetaGPT Action | 技能 = Action 组合，声明式注册 |
| 凭据管理 | AutoGPT Credentials | 凭据与工具解耦，运行时注入 |

---

## 3. 自建 vs 集成评估

> **v1.1 新增章节**：基于问题清单的严重程度，重新评估"自建 Agent 框架"与"集成开源 Agent 框架"的真实成本效益。

### 3.1 评估框架

决策的核心问题是：**BugAgent 的差异化价值在哪里？**

```
BugAgent 的价值 = 缺陷管理领域知识 + 代码分析能力 + 修复工作流
                ≠ Agent 框架本身
```

Agent 框架是**手段**而非**目的**。选择的标准应该是：哪种方式能以最低总成本（开发+运维+风险）交付所需的 Agent 能力。

### 3.2 四种候选方案

| 方案 | 描述 | 核心思路 |
|------|------|----------|
| **A. 全量自建** | 在 Go 中从零实现所有 Agent 能力 | 完全控制，无外部依赖 |
| **B. 集成 LangChain** | Python sidecar 运行 LangChain，Go 通过 gRPC/HTTP 调用 | 复用成熟框架 |
| **C. 集成 LangGraph** | Python sidecar 运行 LangGraph，Go 编排层调用 | 复用图编排引擎 |
| **D. Go 核心 + MCP 生态** | Agent 核心用 Go 自建，工具扩展通过 MCP 接入生态 | 最小化自建，最大化复用生态 |

### 3.3 语言栈冲突——决定性因素

**BugAgent 后端是 Go，主流 Agent 框架全是 Python。**

| 框架 | 语言 | Go SDK | 生产就绪 |
|------|------|--------|----------|
| LangChain v1.0 | Python | ❌ 无 | ✅ |
| LangGraph v1.0 | Python | ❌ 无 | ✅ |
| AutoGPT Platform | Python | ❌ 无 | ✅ |
| MetaGPT | Python | ❌ 无 | ⚠️ |
| CrewAI | Python | ❌ 无 | ✅ |
| Semantic Kernel | Python/C#/Java | ❌ 无 Go | ✅ |

Go 生态中**没有**成熟的 Agent 框架。这意味着方案 B/C 必然引入 Go↔Python 桥接层。

### 3.4 逐组件成本对比

| 组件 | 方案 A（Go 自建） | 方案 B/C（集成 Python） | 方案 D（Go+MCP） |
|------|-------------------|------------------------|-------------------|
| **ReAct 循环** | 3天 | 5天（含桥接层） | 3天 |
| **工具注册/调用** | 2天 | 4天（适配层） | 2天 |
| **流式输出** | 3天 | 7天（Python async→Go SSE 桥接极复杂） | 3天 |
| **MCP 协议** | 5天 | 5天（同样需要实现） | 5天 |
| **Prompt 管理** | 2天 | 3天（LangChain PromptTemplate→Go 适配） | 2天 |
| **并行编排** | 3天 | 6天（LangGraph→Go 调用编排） | 3天 |
| **记忆管理** | 2天（已有基础） | 4天（适配 LangChain Memory） | 2天 |
| **Go↔Python 桥接** | 0 | **8-10天**（gRPC/HTTP+序列化+错误处理+超时） | 0 |
| **Python 运维** | 0 | **持续**（依赖管理、版本升级、部署） | 0 |
| **小计** | **20天** | **42-48天** | **20天** |

**关键发现**：集成 Python 框架的开发成本是自建的 **2x+**，而非预期的更低。核心原因是语言栈不匹配导致的桥接成本。

### 3.5 Go vs Python 在 Agent 场景的天然适配度

| 能力 | Go | Python | 优势方 |
|------|-----|--------|--------|
| 并行执行 | goroutine + errgroup，天然并行 | asyncio，需显式 await | **Go** |
| 流式输出 | channel + SSE，零拷贝 | async generator，需适配 | **Go** |
| HTTP 服务 | net/http 标准库，高性能 | Flask/FastAPI，够用 | Go |
| 类型安全 | 编译时检查 | 运行时（Pydantic 弥补） | **Go** |
| 部署 | 单二进制 | 依赖环境 | **Go** |
| Agent 生态 | 几乎为零 | 极其丰富 | **Python** |
| LLM SDK | 需自建或用 REST | 官方 SDK 完善 | Python |

**结论**：Go 在 Agent **执行层**（并行、流式、服务）天然优于 Python；Python 在 Agent **生态层**（SDK、工具、框架）天然优于 Go。

### 3.6 推荐方案：D —— Go 核心 + MCP 生态集成

**核心思路**：执行层用 Go 自建（Go 天然适合），生态层通过 MCP 协议接入（不重复造轮子）。

```
┌──────────────────────────────────────────────────┐
│              BugAgent (Go)                        │
│                                                   │
│  自建（Go 天然适合）          集成（复用生态）       │
│  ┌─────────────────────┐    ┌──────────────────┐ │
│  │ ReAct 执行循环       │    │ MCP Client       │ │
│  │ 工具注册/调用        │    │ ├─ GitHub Server │ │
│  │ 流式输出 SSE/WS     │    │ ├─ DB Server     │ │
│  │ 并行编排 goroutine  │    │ ├─ Web Search    │ │
│  │ Prompt 模板引擎     │    │ ├─ File System   │ │
│  │ 缓存层             │    │ └─ ...任意 Server │ │
│  │ 优先级队列          │    │                  │ │
│  └─────────────────────┘    └──────────────────┘ │
│                                                   │
│  保留/增强（领域特定）                              │
│  ┌─────────────────────┐                          │
│  │ 缺陷分析 Prompt     │                          │
│  │ 修复工作流          │                          │
│  │ Evidence Repair     │                          │
│  │ 代码检索            │                          │
│  │ 记忆管理            │                          │
│  └─────────────────────┘                          │
└──────────────────────────────────────────────────┘
```

### 3.7 为什么不集成 LangChain/LangGraph

| 反对理由 | 详细说明 |
|----------|----------|
| **语言栈成本** | Go↔Python 桥接层开发 8-10 天 + 持续运维成本。每增加一个跨语言调用点就增加一个故障点 |
| **流式输出不可桥接** | LangGraph 的 token 级流式是 Python async generator，无法直接映射到 Go SSE。需要自建 Python→Go 的流式桥接，比直接在 Go 中实现流式更复杂 |
| **库依赖 vs 协议依赖** | LangChain API 是库级依赖（v1.0 刚发布，API 仍在演进）；MCP 是协议级依赖（JSON-RPC 2.0，向后兼容）。协议比库更稳定 |
| **工具生态对比** | LangChain Tools ≈ 200+；MCP Server 生态 ≈ 1000+（且增长更快）。MCP 生态更大且语言无关 |
| **部署复杂度** | LangChain sidecar 需要独立 Python 环境、依赖管理、进程监控；MCP Server 是独立进程，按需启停 |
| **团队技能** | BugAgent 团队以 Go 为主；引入 Python 框架需要团队同时掌握两套技术栈 |

### 3.8 方案 D 的唯一风险与应对

| 风险 | 应对 |
|------|------|
| Go 没有 MCP SDK，需自建 MCP Client | MCP 协议基于 JSON-RPC 2.0，规范清晰，实现一个 Client 约 3-5 天。社区已有 Go MCP 实现可参考（如 mark3labs/mcp-go） |
| 自建 ReAct 循环不如 LangChain 成熟 | BugAgent 的 ReAct 循环比通用场景简单（固定工具集、有限轮次），3 天实现足够。当前 CodeExplorer 已有类似实现可复用 |
| MCP Server 质量参差不齐 | 内置 14 种核心工具作为兜底；MCP Server 作为扩展而非依赖，单个 Server 故障不影响主流程 |

### 3.9 修订后的实施周期

| Phase | 内容 | 天数 | vs 原方案 |
|-------|------|------|-----------|
| Phase 1 | 并行执行 + 缓存 + Prompt 引擎 | 10天 | 不变 |
| Phase 2 | 流式输出 + 工具框架 + 内置工具 | 10天 | 不变 |
| Phase 3 | MCP Client + 技能系统 | 8天 | **减少 2 天**（MCP Client 比全量自建工具更轻） |
| Phase 4 | 优化 + 稳定化 | 5天 | 减少 2 天 |
| **总计** | | **33天** | **原方案 35天 → 33天** |

对比集成方案 B/C 的 42-48 天，方案 D 节省 **9-15 天** 开发 + 消除持续运维成本。

### 3.10 方案 E：基于 Google ADK-Go 开发（推荐）

> **v1.1 新增**：Google 于 2025 年 4 月发布了 ADK-Go（Agent Development Kit for Go），这是 Go 生态中第一个由大厂维护的生产级 Agent SDK。本节评估基于 ADK-Go 开发的可行性。

#### ADK-Go 核心能力与 BugAgent 需求匹配度

| BugAgent 需求 | ADK-Go 能力 | 匹配度 |
|---------------|-------------|--------|
| ReAct 执行循环 | 内置 Agent ReAct Loop | ✅ 完全匹配 |
| 工具注册/调用 | Function Tool + MCP Tool + Built-in Tool | ✅ 完全匹配 |
| 流式输出 | Event Channel（天生流式） | ✅ 完全匹配 |
| MCP 协议支持 | 原生 MCP Tool 集成 | ✅ 完全匹配 |
| 多 Agent 并行 | ParallelAgent | ✅ 完全匹配 |
| 多 Agent 串行 | SequentialAgent | ✅ 完全匹配 |
| 多 Agent 循环 | LoopAgent | ✅ 完全匹配 |
| Agent 间通信 | Transfer + 共享 State | ✅ 完全匹配 |
| 回调/中间件 | CallbackService（Before/After Model/Tool） | ✅ 完全匹配 |
| 会话/状态管理 | SessionService + State | ✅ 完全匹配 |
| 附件管理 | ArtifactService | ✅ 完全匹配 |
| LLM 多厂商 | ⚠️ 官方仅 Gemini | 需适配器 |
| Prompt 模板 | Instruction 字段 | ⚠️ 需增强 |
| 记忆/知识库 | ⚠️ 无内置向量检索 | 需自建或 MCP |

**匹配度：12/14 完全匹配，2/14 需适配**——远优于自建方案。

#### 逐组件工作量对比

| 组件 | 方案 D（Go 自建） | 方案 E（ADK-Go） | 节省 |
|------|-------------------|-------------------|------|
| ReAct 循环 | 3天 | 0天（内置） | **3天** |
| 工具注册/调用 | 2天 | 0天（内置） | **2天** |
| 流式输出 | 3天 | 1天（Event→SSE/WS 适配） | **2天** |
| MCP 支持 | 5天 | 0天（内置） | **5天** |
| Prompt 管理 | 2天 | 1天（Instruction + 模板） | **1天** |
| 并行编排 | 3天 | 0天（ParallelAgent） | **3天** |
| 多 Agent 协作 | 3天 | 0天（Transfer + SubAgent） | **3天** |
| 回调/中间件 | 2天 | 0天（CallbackService） | **2天** |
| 会话/状态 | 1天 | 1天（实现 SessionService） | 0天 |
| LLM 多厂商适配 | 0天 | 2-3天（实现 Model 接口） | **-3天** |
| 领域逻辑适配 | 7天 | 5天（ADK-Go 简化基础设施） | **2天** |
| 缓存/优先级队列 | 3天 | 3天（应用层，ADK-Go 不涉及） | 0天 |
| **总计** | **~34天** | **~13天** | **~21天（62%）** |

#### LLM 多厂商适配方案

ADK-Go 官方仅内置 Gemini，但 BugAgent 需要 OpenAI/Anthropic/智谱/DeepSeek/阿里云。适配方案：

```go
// OpenAI-compatible Model 适配器
type OpenAICompatibleModel struct {
    client *ai.OpenAICompatibleClient  // 复用现有 AIClient
    model  string
}

func (m *OpenAICompatibleModel) GenerateContent(ctx context.Context, req *adk.GenerateContentRequest) (*adk.GenerateContentResponse, error) {
    // 1. 转换 ADK-Go 请求 → OpenAI 请求
    openaiReq := m.convertRequest(req)
    // 2. 调用现有 AIClient
    resp, err := m.client.Chat(ctx, openaiReq)
    // 3. 转换 OpenAI 响应 → ADK-Go 响应
    return m.convertResponse(resp), err
}

func (m *OpenAICompatibleModel) GenerateContentStream(ctx context.Context, req *adk.GenerateContentRequest) (<-chan adk.GenerateContentResponse, error) {
    // 复用现有 ChatStream
    ch, err := m.client.ChatStream(ctx, m.convertRequest(req))
    // 适配 channel 类型
    return m.adaptStreamChannel(ch), err
}
```

**工作量**：约 2-3 天，因为现有 AIClient 已实现所有厂商的调用逻辑，只需做接口适配。

#### BugAgent 领域逻辑迁移映射

| 现有组件 | ADK-Go 映射 | 迁移方式 |
|----------|-------------|----------|
| AnalysisService | `ParallelAgent` + 多个分析 Agent | 每个 agentType 创建一个 Agent，并行执行 |
| FixEngine 7步流程 | `SequentialAgent` + 7个 Tool | clone→branch→generate→apply→test→commit→pr |
| CodeExplorer | Agent + 4个 Function Tool | search_code/read_file/trace_call/find_api_handler |
| CollaborationService | `ParallelAgent` + 聚合 Agent | 复用 ADK-Go 并行编排 |
| AgentMemoryService | Session State + 自定义 Tool | 记忆注入为 Instruction 上下文 |
| Evidence Repair | LoopAgent | 分析→校验→修正循环 |
| WS 通知 | CallbackService（AfterToolCall/AfterModelCall） | 回调中发布 WS 事件 |
| 审计日志 | CallbackService（BeforeToolCall） | 回调中记录审计 |

#### 实施周期（修订）

| Phase | 内容 | 天数 |
|-------|------|------|
| Phase 1 | LLM Model 适配器 + SessionService + ArtifactService | 3天 |
| Phase 2 | 分析流程迁移（ParallelAgent + 分析 Agent） | 3天 |
| Phase 3 | 修复流程迁移（SequentialAgent + Tool） | 2天 |
| Phase 4 | MCP 工具集成 + 流式输出适配 + WS 通知 | 2天 |
| Phase 5 | 记忆系统 + 技能系统 + 缓存 + 测试 | 3天 |
| **总计** | | **13天** |

对比方案 D 的 33 天，方案 E 节省 **20 天（62%）**。

#### 风险评估

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| ADK-Go API 变更 | 中 | 中 | go.mod 锁定版本；不跟最新版 |
| LLM 适配器 Function Calling 格式差异 | 中 | 中 | OpenAI function calling 格式与 Gemini 不同，需适配层；Anthropic 需独立适配 |
| ADK-Go 未发布 1.0 | 低 | 低 | Google 维护，质量有保障；核心 API 已稳定 |
| ADK-Go 社区不够活跃 | 低 | 低 | BugAgent 的核心逻辑是领域特定代码，不依赖社区 |
| Gemini 依赖 | 低 | 低 | Model 接口可扩展，BugAgent 主力不是 Gemini |

#### 最终推荐

| 方案 | 开发天数 | 运维成本 | 风险 | 推荐度 |
|------|----------|----------|------|--------|
| A. 全量自建 | 34天 | 低 | 低 | ⭐⭐ |
| B. 集成 LangChain | 42-48天 | 高 | 高 | ⭐ |
| D. Go 核心 + MCP | 33天 | 低 | 低 | ⭐⭐⭐ |
| **E. 基于 ADK-Go** | **13天** | **低** | **中** | **⭐⭐⭐⭐⭐** |

**方案 E（基于 ADK-Go）是当前最优解**：开发量最少（13天 vs 33天），Go 原生无语言栈冲突，内置 MCP 支持，Google 维护质量有保障。唯一额外成本是 LLM 多厂商适配器（2-3天），但复用现有 AIClient 代码后工作量可控。

---

## 4. 新架构整体设计

### 4.1 系统组件图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          API Gateway (Gin)                              │
│                    /api/v1/defects /projects /agents                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    Agent Orchestrator                            │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │    │
│  │  │ Workflow  │  │  Skill   │  │ Priority │  │  Middleware   │   │    │
│  │  │  Engine   │  │ Dispatch │  │  Queue   │  │   Pipeline   │   │    │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────────┘   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐      │
│  │   Agent Runtime  │  │   Tool Registry  │  │   MCP Client     │      │
│  │  ┌────────────┐  │  │  ┌────────────┐  │  │  ┌────────────┐  │      │
│  │  │ ReAct Loop │  │  │  │  Built-in  │  │  │  │  MCP       │  │      │
│  │  │ + Memory   │  │  │  │  Tools     │  │  │  │  Servers   │  │      │
│  │  │ + Prompt   │  │  │  │  (12+)     │  │  │  │  (N+)      │  │      │
│  │  └────────────┘  │  │  └────────────┘  │  │  └────────────┘  │      │
│  │  ┌────────────┐  │  │  ┌────────────┐  │  │  ┌────────────┐  │      │
│  │  │ Agent Pool │  │  │  │  Tool      │  │  │  │  Sampling  │  │      │
│  │  │ (parallel) │  │  │  │  Sandbox   │  │  │  │  Handler   │  │      │
│  │  └────────────┘  │  │  └────────────┘  │  │  └────────────┘  │      │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘      │
│                                                                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐      │
│  │  Stream Manager  │  │  Memory Service  │  │  Prompt Engine   │      │
│  │  ┌────────────┐  │  │  ┌────────────┐  │  │  ┌────────────┐  │      │
│  │  │  SSE Hub   │  │  │  │  Project   │  │  │  │  Template  │  │      │
│  │  │  WS Hub    │  │  │  │  Memory    │  │  │  │  Engine    │  │      │
│  │  │  Buffer    │  │  │  │  + Vector  │  │  │  │  + Version │  │      │
│  │  └────────────┘  │  │  └────────────┘  │  │  └────────────┘  │      │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘      │
│                                                                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐      │
│  │  Cache Layer     │  │  Credential Mgr  │  │  Event Bus       │      │
│  │  ┌────────────┐  │  │  ┌────────────┐  │  │  ┌────────────┐  │      │
│  │  │  AI Config │  │  │  │  Encrypt   │  │  │  │  Publish   │  │      │
│  │  │  Repo      │  │  │  │  Store     │  │  │  │  Subscribe │  │      │
│  │  │  LLM Resp  │  │  │  │  Inject    │  │  │  │  Route     │  │      │
│  │  └────────────┘  │  │  └────────────┘  │  │  └────────────┘  │      │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘      │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                        Infrastructure Layer                             │
│     PostgreSQL / Redis / Git / Vector DB / Object Storage               │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 核心模块交互流程

#### 4.2.1 分析流程（重构后）

```
HTTP POST /api/v1/defects/:id/analyze
  │
  ▼
Agent Orchestrator
  │
  ├─ 1. Middleware Pipeline（鉴权/限流/审计）
  │
  ├─ 2. Skill Dispatch → 选择 "defect-analysis" 技能
  │     └─ 技能定义：并行执行 [frontend, backend, ui, test] Agent
  │
  ├─ 3. Workflow Engine
  │     ├─ 构建并行执行图
  │     ├─ 每个 Agent 独立 ReAct Loop
  │     │   ├─ 加载 Prompt（模板引擎 + 记忆注入）
  │     │   ├─ 获取代码上下文（缓存层）
  │     │   ├─ LLM 调用（流式）
  │     │   ├─ Tool Call（MCP/Built-in）
  │     │   └─ 结构化输出解析
  │     └─ 聚合结果（投票/共识）
  │
  ├─ 4. Stream Manager → SSE/WS 推送进度
  │
  ├─ 5. Memory Service → 异步提取记忆
  │
  └─ 6. Event Bus → 通知下游（评论/状态变更/审计）
```

#### 4.2.2 修复流程（重构后）

```
HTTP POST /api/v1/defects/:id/fix-tasks
  │
  ▼
Agent Orchestrator
  │
  ├─ 1. Skill Dispatch → 选择 "defect-fix" 技能
  │     └─ 技能定义：顺序执行 [clone→analyze→generate→apply→test→commit→pr]
  │
  ├─ 2. Workflow Engine
  │     ├─ 构建 DAG 执行图
  │     ├─ 节点并行：analyze(多 Agent) + test(沙箱)
  │     ├─ 节点串行：clone → generate → apply → commit → pr
  │     └─ 每步实时推送进度
  │
  ├─ 3. Tool Registry
  │     ├─ git-clone（内置，带缓存）
  │     ├─ code-generate（LLM Tool）
  │     ├─ code-apply（内置）
  │     ├─ test-run（沙箱 Tool）
  │     └─ pr-create（VCS Tool）
  │
  └─ 4. Stream Manager → 逐步推送
```

### 4.3 核心抽象定义

```go
// Agent —— 智能体本体
type Agent interface {
    ID() string
    Type() AgentType
    Run(ctx context.Context, input AgentInput) (<-chan AgentEvent, error)
    Tools() []ToolRef
    Memory() MemoryProvider
}

// AgentType —— Agent 类型枚举（可扩展）
type AgentType string

const (
    AgentFrontend AgentType = "frontend"
    AgentBackend  AgentType = "backend"
    AgentUI       AgentType = "ui"
    AgentTest     AgentType = "test"
    AgentProduct  AgentType = "product"
    AgentClient   AgentType = "client"
    AgentCustom   AgentType = "custom"  // 新增：自定义 Agent
)

// AgentEvent —— Agent 输出事件（流式）
type AgentEvent struct {
    Type    EventType   // thinking / tool_call / tool_result / partial / completed / error
    Data    interface{}
    AgentID string
    Ts      time.Time
}

// Skill —— 技能定义
type Skill struct {
    ID          string
    Name        string
    Description string
    Agents      []AgentSpec     // 需要哪些 Agent
    Workflow    WorkflowDef     // 执行图定义
    Middleware  []MiddlewareDef // 横切配置
}

// AgentSpec —— Agent 规格
type AgentSpec struct {
    Type       AgentType
    PromptRef  string     // Prompt 模板引用
    Tools      []string   // 需要的工具列表
    MemoryScope string    // project / iteration
    Priority   int        // 执行优先级
}

// WorkflowDef —— 工作流定义
type WorkflowDef struct {
    Mode    string      // parallel / sequential / dag
    Timeout time.Duration
    Retry   RetryPolicy
}
```

---

## 5. 执行效率优化方案

### 4.1 并行 Agent 执行

**当前问题**：`PerformAnalysis` 中 `for range agentTypes` 串行执行

**优化方案**：统一使用 Workflow Engine 的并行模式

```go
// 优化前
for _, agentType := range req.AgentTypes {
    result, err := s.analyzeWithFallback(ctx, defect, agentType, ...)
}

// 优化后
results, err := s.workflowEngine.ExecuteParallel(ctx, agents, func(agent Agent) (*AnalysisResult, error) {
    return agent.Run(ctx, input)
})
// 3 Agent 并行 → 延迟从 3T 降到 T
```

**实现细节**：
- 使用 `errgroup.Group` 管理并行 goroutine
- 每个 Agent 独立 context，支持单独超时
- 结果通过 channel 收集，支持部分成功
- Fallback 在每个 Agent 内部独立处理

### 4.2 仓库缓存层

**当前问题**：每次分析/修复都完整克隆 Git 仓库

**优化方案**：LRU 缓存 + 增量更新

```go
type RepoCache struct {
    mu    sync.RWMutex
    items map[string]*cacheEntry  // key: repoURL
    lru   *list.List
    maxSize int
}

type cacheEntry struct {
    localPath   string
    lastFetch   time.Time
    defaultBranch string
}

// GetOrClone：缓存命中则 git fetch --rebase，未命中则 git clone
func (c *RepoCache) GetOrClone(ctx context.Context, repoURL, branch string) (string, error)
```

**缓存策略**：
- LRU 淘汰，最大 50 个仓库
- TTL 30 分钟，过期后 `git fetch --rebase` 增量更新
- 同一缺陷的分析+修复共享缓存条目
- 预估效果：仓库准备从 5-15s 降到 <1s（缓存命中）

### 4.3 AI 配置进程缓存

**当前问题**：每次分析/修复/记忆提取都查数据库 + 解密 API Key

**优化方案**：进程级缓存 + 解密结果缓存

```go
type AIConfigCache struct {
    mu      sync.RWMutex
    configs map[uint][]*CachedAIConfig  // key: projectID
    expiry  map[uint]time.Time
    ttl     time.Duration  // 默认 5 分钟
}

type CachedAIConfig struct {
    Provider    string
    ModelName   string
    APIKey      string  // 已解密
    APIEndpoint string
    IsDefault   bool
}
```

**失效策略**：
- TTL 5 分钟自动过期
- 配置变更时主动失效（通过 Event Bus 通知）
- 解密结果随缓存一起存储，避免重复解密

### 4.4 优先级任务队列

**当前问题**：所有 Agent 任务平等竞争，无优先级

**优化方案**：基于 Redis 的优先级队列

```go
type PriorityTaskQueue struct {
    redis  *redis.Client
    queues map[Priority]string  // high/medium/low → Redis List key
}

type Task struct {
    ID       string
    Priority Priority
    Type     string  // analysis / fix / memory_extraction
    Payload  json.RawMessage
}

// Worker 消费：优先处理 high 队列
func (q *PriorityTaskQueue) Consume(ctx context.Context) (*Task, error) {
    // BLPOP high → medium → low 依次检查
}
```

**优先级规则**：
- 用户手动触发 → high
- 自动触发分析 → medium
- 记忆提取/后台任务 → low
- 修复任务 → medium（人工修复后提升为 high）

### 4.5 LLM 响应缓存

**优化方案**：对相同 prompt + model + parameters 的 LLM 调用结果缓存

```go
type LLMResponseCache struct {
    store CacheStore  // Redis / InMemory
}

func (c *LLMResponseCache) GetOrCall(ctx context.Context, req *ChatRequest, fn func() (*ChatResponse, error)) (*ChatResponse, error) {
    key := c.computeKey(req)  // hash(prompt + model + temperature + maxTokens)
    if cached, ok := c.store.Get(key); ok {
        return cached, nil
    }
    resp, err := fn()
    if err == nil {
        c.store.Set(key, resp, 1*time.Hour)
    }
    return resp, err
}
```

**适用场景**：
- Evidence Repair 的二次调用（相同上下文）
- 测试环境重复分析
- 不适用于生产实时分析（默认关闭，可配置开启）

---

## 6. 工具扩展框架设计

### 5.1 工具注册体系

```go
// Tool —— 工具接口
type Tool interface {
    ID() string
    Name() string
    Description() string
    InputSchema() *jsonschema.Schema
    OutputSchema() *jsonschema.Schema
    Execute(ctx context.Context, input json.RawMessage) (json.RawMessage, error)
    Category() ToolCategory
    RequiredCredentials() []CredentialRef
}

// ToolCategory —— 工具分类
type ToolCategory string

const (
    ToolCodeSearch   ToolCategory = "code_search"
    ToolCodeRead     ToolCategory = "code_read"
    ToolCodeModify   ToolCategory = "code_modify"
    ToolTestRun      ToolCategory = "test_run"
    ToolDBQuery      ToolCategory = "db_query"
    ToolWebSearch    ToolCategory = "web_search"
    ToolGit          ToolCategory = "git"
    ToolVCS          ToolCategory = "vcs"
    ToolFileSystem   ToolCategory = "file_system"
    ToolMCP          ToolCategory = "mcp"
)

// ToolRegistry —— 工具注册表
type ToolRegistry struct {
    mu    sync.RWMutex
    tools map[string]Tool  // key: toolID
}

func (r *ToolRegistry) Register(tool Tool) error
func (r *ToolRegistry) Get(toolID string) (Tool, error)
func (r *ToolRegistry) ListByCategory(cat ToolCategory) []Tool
func (r *ToolRegistry) ListByIDs(ids []string) []Tool
```

### 5.2 内置工具清单

| ID | 名称 | 类别 | 描述 |
|----|------|------|------|
| `search_code` | 代码语义搜索 | code_search | 语义搜索代码符号（Kiwiskil/本地） |
| `read_file` | 读取文件 | code_read | 读取仓库文件内容 |
| `trace_call` | 调用链追踪 | code_search | 追踪函数上下游调用 |
| `find_api_handler` | API 路由映射 | code_search | 前端 API → 后端 Handler |
| `list_directory` | 目录浏览 | code_read | 浏览仓库目录结构 |
| `search_symbols` | 符号搜索 | code_search | 按名称/类型搜索代码符号 |
| `git_diff` | Git Diff | git | 查看文件变更差异 |
| `git_log` | Git Log | git | 查看提交历史 |
| `git_blame` | Git Blame | git | 查看行级变更归属 |
| `run_test` | 运行测试 | test_run | 在沙箱中运行测试用例 |
| `run_lint` | 运行 Lint | test_run | 在沙箱中运行代码检查 |
| `db_query` | 数据库查询 | db_query | 执行只读 SQL 查询（受限） |
| `web_search` | Web 搜索 | web_search | 搜索互联网信息 |
| `pr_create` | 创建 PR/MR | vcs | 创建 GitHub/GitLab PR |
| `pr_review` | 审查 PR | vcs | 获取 PR diff 和评论 |

### 5.3 工具调用规范

```go
// ToolCall —— LLM 输出的工具调用
type ToolCall struct {
    ID       string          `json:"id"`
    ToolID   string          `json:"tool_id"`
    Input    json.RawMessage `json:"input"`
}

// ToolResult —— 工具执行结果
type ToolResult struct {
    CallID   string          `json:"call_id"`
    Output   json.RawMessage `json:"output"`
    Error    string          `json:"error,omitempty"`
    Duration time.Duration   `json:"duration"`
}

// ToolExecutor —— 工具执行器（含权限控制）
type ToolExecutor struct {
    registry  *ToolRegistry
    credMgr   *CredentialManager
    sandbox   *SandboxManager
    auditLog  AuditLogger
}

func (e *ToolExecutor) Execute(ctx context.Context, call ToolCall) (*ToolResult, error) {
    // 1. 查找工具
    tool, err := e.registry.Get(call.ToolID)
    
    // 2. 权限检查（当前 Agent 是否有权使用此工具）
    if !e.hasPermission(ctx, call.ToolID) {
        return nil, ErrPermissionDenied
    }
    
    // 3. 凭据注入
    ctx = e.credMgr.InjectCredentials(ctx, tool.RequiredCredentials())
    
    // 4. 沙箱执行（高风险工具）
    if tool.Category() == ToolCodeModify || tool.Category() == ToolTestRun {
        return e.sandbox.Execute(ctx, tool, call.Input)
    }
    
    // 5. 审计记录
    defer e.auditLog.Log(ctx, call)
    
    // 6. 执行
    output, err := tool.Execute(ctx, call.Input)
    return &ToolResult{CallID: call.ID, Output: output, Error: errStr}, err
}
```

### 5.4 权限控制模型

```go
// ToolPermission —— 工具权限
type ToolPermission struct {
    AgentType  AgentType
    ToolID     string
    Allowed    bool
    MaxCalls   int     // 单次执行最大调用次数（0=无限）
    Sandbox    bool    // 是否在沙箱中执行
}

// 默认权限矩阵
var DefaultPermissions = []ToolPermission{
    {AgentFrontend, "search_code", true, 10, false},
    {AgentFrontend, "read_file", true, 20, false},
    {AgentFrontend, "trace_call", true, 5, false},
    {AgentFrontend, "find_api_handler", true, 5, false},
    {AgentBackend, "search_code", true, 10, false},
    {AgentBackend, "read_file", true, 20, false},
    {AgentBackend, "db_query", true, 3, true},    // 沙箱执行
    {AgentTest, "run_test", true, 5, true},        // 沙箱执行
    {AgentTest, "run_lint", true, 5, true},        // 沙箱执行
    // ... 可通过配置扩展
}
```

---

## 6. 流式输出实现方案

### 6.1 双通道流式架构

```
┌──────────────┐     SSE Channel      ┌──────────────┐
│              │ ───────────────────── │              │
│  Agent       │     (token 级)        │  Frontend    │
│  Runtime     │                       │              │
│              │ ───────────────────── │              │
└──────────────┘     WS Channel        └──────────────┘
                     (事件级)
```

**SSE 通道**：LLM token 级流式输出
- 每个 Agent 的推理过程逐 token 推送
- 前端实时渲染 Markdown
- 连接断开自动重连 + Last-Event-ID 续传

**WebSocket 通道**：结构化事件推送
- Agent 状态变更（started/completed/failed）
- Tool Call 执行进度
- 工作流节点状态
- 缺陷状态变更

### 6.2 数据分块策略

```go
// StreamChunk —— 流式数据块
type StreamChunk struct {
    ID        string      `json:"id"`
    Type      string      `json:"type"`       // token / thinking / tool_call / tool_result / completed
    AgentID   string      `json:"agent_id"`
    Data      interface{} `json:"data"`
    Timestamp int64       `json:"ts"`
}

// Token 级分块
type TokenChunk struct {
    Content string `json:"content"`  // 单个或多个 token
    Index   int    `json:"index"`    // 在完整输出中的位置
}

// Thinking 级分块
type ThinkingChunk struct {
    Content string `json:"content"`  // 推理过程
}

// Tool Call 级分块
type ToolCallChunk struct {
    CallID string          `json:"call_id"`
    ToolID string          `json:"tool_id"`
    Input  json.RawMessage `json:"input"`
    Status string          `json:"status"`  // started / completed / failed
    Result json.RawMessage `json:"result,omitempty"`
}
```

### 6.3 SSE 实现方案

```go
// SSEHandler —— SSE 端点
func (h *SSEHandler) StreamAnalysis(c *gin.Context) {
    defectID := c.Param("id")
    
    // 设置 SSE 头
    c.Header("Content-Type", "text/event-stream")
    c.Header("Cache-Control", "no-cache")
    c.Header("Connection", "keep-alive")
    c.Header("X-Accel-Buffering", "no")
    
    // 订阅事件流
    sub := h.streamManager.Subscribe(defectID)
    defer h.streamManager.Unsubscribe(defectID, sub.ID)
    
    // 推送事件
    for {
        select {
        case event := <-sub.Ch:
            data, _ := json.Marshal(event)
            fmt.Fprintf(c.Writer, "id: %s\nevent: %s\ndata: %s\n\n", event.ID, event.Type, data)
            c.Writer.(http.Flusher).Flush()
        case <-c.Request.Context().Done():
            return
        }
    }
}
```

### 6.4 StreamManager 实现

```go
type StreamManager struct {
    mu       sync.RWMutex
    streams  map[string]*Stream  // key: defectID
}

type Stream struct {
    DefectID string
    Subs     map[string]*Subscriber
    Buffer   *RingBuffer  // 环形缓冲，支持断线重连
}

type Subscriber struct {
    ID string
    Ch chan StreamChunk
}

func (m *StreamManager) Publish(defectID string, chunk StreamChunk) {
    m.mu.RLock()
    defer m.mu.RUnlock()
    
    stream, ok := m.streams[defectID]
    if !ok { return }
    
    stream.Buffer.Write(chunk)  // 写入缓冲
    
    for _, sub := range stream.Subs {
        select {
        case sub.Ch <- chunk:
        default:  // 慢消费者跳过，避免阻塞
        }
    }
}
```

### 6.5 LLM 流式接入

```go
// 将 ChatStream 接入 StreamManager
func (s *AnalysisService) runAgentStream(ctx context.Context, agent Agent, input AgentInput, streamMgr *StreamManager) {
    eventCh, err := agent.Run(ctx, input)
    if err != nil { return }
    
    for event := range eventCh {
        switch event.Type {
        case EventTypePartial:
            // token 级流式 → SSE
            streamMgr.Publish(input.DefectID, StreamChunk{
                Type:    "token",
                AgentID: agent.ID(),
                Data:    TokenChunk{Content: event.Data.(string)},
            })
        case EventTypeToolCall:
            streamMgr.Publish(input.DefectID, StreamChunk{
                Type:    "tool_call",
                AgentID: agent.ID(),
                Data:    event.Data,
            })
        case EventTypeCompleted:
            streamMgr.Publish(input.DefectID, StreamChunk{
                Type:    "completed",
                AgentID: agent.ID(),
                Data:    event.Data,
            })
        }
    }
}
```

---

## 8. MCP 协议集成方案

### 7.1 MCP Client 架构

```
┌──────────────────────────────────────────┐
│              BugAgent (Host)              │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │          MCP Client Manager        │  │
│  │  ┌──────────┐  ┌──────────┐       │  │
│  │  │ Client 1 │  │ Client 2 │  ...   │  │
│  │  │ (GitHub) │  │ (DB)     │       │  │
│  │  └────┬─────┘  └────┬─────┘       │  │
│  └───────┼──────────────┼─────────────┘  │
│          │              │                │
│     stdio/SSE      stdio/SSE             │
│          │              │                │
│  ┌───────▼──────┐ ┌─────▼──────┐        │
│  │  MCP Server  │ │  MCP Server│        │
│  │  (GitHub)    │ │  (Postgres)│        │
│  └──────────────┘ └────────────┘        │
└──────────────────────────────────────────┘
```

### 7.2 MCP Server 配置模型

```go
// MCPServerConfig —— MCP Server 配置
type MCPServerConfig struct {
    ID          string            `json:"id"`
    Name        string            `json:"name"`
    Command     string            `json:"command"`      // 启动命令（stdio 模式）
    Args        []string          `json:"args"`         // 命令参数
    Env         map[string]string `json:"env"`          // 环境变量
    URL         string            `json:"url"`          // SSE 模式 URL
    Transport   string            `json:"transport"`    // stdio / sse
    ProjectID   *uint             `json:"project_id"`   // 项目级（null=全局）
    Enabled     bool              `json:"enabled"`
    AutoStart   bool              `json:"auto_start"`
}
```

### 7.3 MCP Tool 桥接

```go
// MCPToolBridge —— 将 MCP Server 的 Tools 桥接为 BugAgent Tool
type MCPToolBridge struct {
    client *mcp.Client
}

func (b *MCPToolBridge) ListTools(ctx context.Context) ([]Tool, error) {
    mcpTools, err := b.client.ListTools(ctx)
    if err != nil { return nil, err }
    
    var tools []Tool
    for _, t := range mcpTools {
        tools = append(tools, &MCPToolAdapter{
            id:          fmt.Sprintf("mcp:%s:%s", b.client.ServerID(), t.Name),
            name:        t.Name,
            description: t.Description,
            inputSchema: t.InputSchema,
            client:      b.client,
        })
    }
    return tools, nil
}

// MCPToolAdapter —— 适配器，将 MCP Tool 转为 BugAgent Tool 接口
type MCPToolAdapter struct {
    id          string
    name        string
    description string
    inputSchema *jsonschema.Schema
    client      *mcp.Client
}

func (a *MCPToolAdapter) Execute(ctx context.Context, input json.RawMessage) (json.RawMessage, error) {
    return a.client.CallTool(ctx, a.name, input)
}
```

### 7.4 MCP 资源映射

```go
// MCP Resource → BugAgent Context Provider
type MCPResourceProvider struct {
    client *mcp.Client
}

func (p *MCPResourceProvider) GetResource(ctx context.Context, uri string) (string, error) {
    resp, err := p.client.ReadResource(ctx, uri)
    if err != nil { return "", err }
    return resp.Content, nil
}

// 在 ReAct Loop 中注入 MCP 资源作为上下文
func (r *ReActLoop) buildContext(ctx context.Context, input AgentInput) (string, error) {
    var contextParts []string
    
    // 1. 内置代码上下文
    codeCtx, err := r.codeProvider.GetContext(ctx, input)
    
    // 2. MCP 资源上下文
    for _, provider := range r.mcpProviders {
        for _, uri := range input.RequiredResources {
            res, err := provider.GetResource(ctx, uri)
            contextParts = append(contextParts, res)
        }
    }
    
    return strings.Join(contextParts, "\n"), nil
}
```

### 7.5 MCP Sampling 支持

```go
// MCPSamplingHandler —— 处理 MCP Server 的 Sampling 请求
type MCPSamplingHandler struct {
    agentPool *AgentPool
}

func (h *MCPSamplingHandler) HandleSampling(ctx context.Context, req *mcp.SamplingRequest) (*mcp.SamplingResult, error) {
    // 1. 权限检查：用户是否允许此 Server 使用 LLM
    if !h.isSamplingAllowed(ctx, req.ServerID) {
        return nil, ErrSamplingNotAllowed
    }
    
    // 2. 使用 Agent Pool 中的 LLM 执行
    agent := h.agentPool.GetAgent(ctx, req.ModelPreferences)
    result, err := agent.Chat(ctx, &ChatRequest{
        Messages:    req.Messages,
        Temperature: req.Temperature,
        MaxTokens:   req.MaxTokens,
    })
    
    return &mcp.SamplingResult{Content: result.Content}, err
}
```

### 7.6 多 Agent 协作机制

**协作模式设计**：

| 模式 | 描述 | 适用场景 |
|------|------|----------|
| **并行分析** | 多 Agent 独立分析同一缺陷，投票/共识 | 缺陷分析（当前核心场景） |
| **流水线** | Agent 串行处理，前一个输出是后一个输入 | PRD → 设计 → 编码 → 测试 |
| **主从** | Orchestrator 分配子任务给 Worker | 复杂修复任务拆分 |
| **协商** | 多 Agent 辩论后达成共识 | 争议性缺陷定级 |

**实现方案**：基于 Event Bus 的发布-订阅模型（参考 MetaGPT）

```go
// EventBus —— 事件总线
type EventBus struct {
    mu         sync.RWMutex
    subscribers map[string][]Subscriber  // key: eventType
}

type Subscriber struct {
    ID       string
    Handler  func(event Event)
    Filter   EventFilter
}

// Event —— 事件
type Event struct {
    Type      string          // action.completed / agent.started / workflow.progress
    Source    string          // Agent ID
    Data      interface{}
    Timestamp time.Time
}

// Agent 间协作示例
func (s *AnalysisService) ParallelAnalysis(ctx context.Context, defect *Defect, agents []Agent) (*AggregatedResult, error) {
    // 1. 每个 Agent 独立执行
    resultCh := make(chan *AnalysisResult, len(agents))
    
    for _, agent := range agents {
        go func(a Agent) {
            eventCh, _ := a.Run(ctx, input)
            result := collectResult(eventCh)
            resultCh <- result
            
            // 发布完成事件
            s.eventBus.Publish(Event{
                Type:   "agent.analysis.completed",
                Source: a.ID(),
                Data:   result,
            })
        }(agent)
    }
    
    // 2. 收集结果
    var results []*AnalysisResult
    for i := 0; i < len(agents); i++ {
        results = append(results, <-resultCh)
    }
    
    // 3. 聚合（投票/共识）
    return s.aggregateResults(results), nil
}
```

---

## 8. 技能管理系统设计

### 8.1 技能定义模型

```go
// Skill —— 技能
type Skill struct {
    ID          string         `json:"id"`
    Name        string         `json:"name"`
    Description string         `json:"description"`
    Version     string         `json:"version"`
    Category    SkillCategory  `json:"category"`
    
    // 技能组成
    Agents      []AgentSpec    `json:"agents"`       // 需要的 Agent
    Tools       []string       `json:"tools"`        // 需要的工具
    Workflow    WorkflowDef    `json:"workflow"`     // 执行图
    Middleware  []MiddlewareDef `json:"middleware"`   // 横切配置
    
    // 元数据
    IsBuiltIn   bool           `json:"is_built_in"`
    CreatedBy   uint           `json:"created_by"`
    CreatedAt   time.Time      `json:"created_at"`
}

// SkillCategory —— 技能分类
type SkillCategory string

const (
    SkillAnalysis      SkillCategory = "analysis"       // 缺陷分析
    SkillFix           SkillCategory = "fix"            // 缺陷修复
    SkillTest          SkillCategory = "test"           // 测试生成
    SkillReview        SkillCategory = "review"         // 代码审查
    SkillMemory        SkillCategory = "memory"         // 记忆提取
    SkillCollaborate   SkillCategory = "collaborate"    // 多 Agent 协作
    SkillCustom        SkillCategory = "custom"         // 自定义
)
```

### 8.2 内置技能定义

```yaml
# defect-analysis 技能
id: defect-analysis
name: 缺陷分析
category: analysis
agents:
  - type: frontend
    prompt_ref: analysis/frontend
    tools: [search_code, read_file, trace_call, find_api_handler]
    memory_scope: project
  - type: backend
    prompt_ref: analysis/backend
    tools: [search_code, read_file, trace_call, db_query]
    memory_scope: project
  - type: test
    prompt_ref: analysis/test
    tools: [search_code, read_file, run_test]
    memory_scope: project
workflow:
  mode: parallel
  timeout: 10m
  retry:
    max_attempts: 2
    backoff: exponential
middleware:
  - type: audit_log
  - type: stream_output
  - type: memory_extraction

---
# defect-fix 技能
id: defect-fix
name: 缺陷修复
category: fix
agents:
  - type: backend
    prompt_ref: fix/generate
    tools: [search_code, read_file, git_diff, run_test, run_lint]
    memory_scope: project
workflow:
  mode: dag
  nodes:
    - id: clone
      tool: git_clone
    - id: analyze
      skill: defect-analysis
      depends_on: [clone]
    - id: generate
      agent: backend
      depends_on: [analyze]
    - id: apply
      tool: code_apply
      depends_on: [generate]
    - id: test
      tool: run_test
      depends_on: [apply]
    - id: commit
      tool: git_commit
      depends_on: [test]
    - id: pr
      tool: pr_create
      depends_on: [commit]
  timeout: 30m
middleware:
  - type: audit_log
  - type: stream_output
  - type: memory_extraction
  - type: human_in_the_loop
    config:
      approve_nodes: [apply, pr]
```

### 8.3 技能注册与发现

```go
// SkillRegistry —— 技能注册表
type SkillRegistry struct {
    mu     sync.RWMutex
    skills map[string]*Skill  // key: skillID
}

func (r *SkillRegistry) Register(skill *Skill) error
func (r *SkillRegistry) Get(skillID string) (*Skill, error)
func (r *SkillRegistry) ListByCategory(cat SkillCategory) []*Skill
func (r *SkillRegistry) Match(defect *Defect) []*Skill  // 根据缺陷特征匹配技能

// 技能匹配逻辑
func (r *SkillRegistry) Match(defect *Defect) []*Skill {
    var matched []*Skill
    for _, skill := range r.skills {
        if skill.Matches(defect) {
            matched = append(matched, skill)
        }
    }
    // 按优先级排序
    sort.Slice(matched, func(i, j int) bool {
        return matched[i].Priority > matched[j].Priority
    })
    return matched
}
```

### 8.4 技能组合机制

```go
// SkillComposer —— 技能组合器
type SkillComposer struct {
    registry *SkillRegistry
}

// Compose —— 组合多个技能为新的复合技能
func (c *SkillComposer) Compose(skills []string, workflow WorkflowDef) (*Skill, error) {
    var agents []AgentSpec
    var tools []string
    var middleware []MiddlewareDef
    
    for _, skillID := range skills {
        skill, err := c.registry.Get(skillID)
        if err != nil { return nil, err }
        agents = append(agents, skill.Agents...)
        tools = append(tools, skill.Tools...)
        middleware = append(middleware, skill.Middleware...)
    }
    
    // 去重
    agents = dedupAgents(agents)
    tools = dedupStrings(tools)
    middleware = dedupMiddleware(middleware)
    
    return &Skill{
        ID:         uuid.New().String(),
        Agents:     agents,
        Tools:      tools,
        Workflow:   workflow,
        Middleware: middleware,
    }, nil
}
```

### 8.5 技能调度机制

```go
// SkillDispatcher —— 技能调度器
type SkillDispatcher struct {
    registry  *SkillRegistry
    workflow  *WorkflowEngine
    streamMgr *StreamManager
}

func (d *SkillDispatcher) Dispatch(ctx context.Context, skillID string, input SkillInput) (<-chan AgentEvent, error) {
    skill, err := d.registry.Get(skillID)
    if err != nil { return nil, err }
    
    // 1. 创建 Agent 实例
    agents := d.createAgents(skill.Agents)
    
    // 2. 构建工作流
    wf := d.workflow.Build(skill.Workflow, agents)
    
    // 3. 注入 Middleware
    wf = d.applyMiddleware(wf, skill.Middleware)
    
    // 4. 执行
    return wf.Run(ctx, input)
}
```

---

## 9. 新旧架构对比分析

### 9.1 核心差异点

| 维度 | 旧架构 | 新架构 | 差异说明 |
|------|--------|--------|----------|
| **执行模型** | 串行 for 循环 | 并行 DAG + 优先级队列 | 3 Agent 延迟从 3T 降到 T |
| **工具系统** | 4 种自研工具 | 14+ 内置 + N MCP 工具 | 工具数量 5x+，标准协议 |
| **流式输出** | 无（轮询） | SSE + WS 双通道 | 实时可见推理过程 |
| **MCP 集成** | 无 | 完整 Client + Sampling | 接入 MCP 生态 |
| **技能管理** | 无 | 声明式注册 + 组合 + 调度 | 新能力零代码扩展 |
| **Prompt 管理** | 字符串拼接 + 硬编码 | 模板引擎 + 版本管理 | A/B 测试、灰度发布 |
| **协作模式** | 两套代码（串行/并行分裂） | 统一 Workflow Engine | 一套代码，配置驱动 |
| **缓存** | 无 | AI 配置 + 仓库 + LLM 响应 | 重复操作 <5ms |
| **凭据管理** | 工具内直接使用 | 凭据管理器 + 运行时注入 | 安全隔离 |
| **权限控制** | 无 | 工具级权限矩阵 | 细粒度访问控制 |
| **审计** | 部分记录 | 全链路审计 + 事件溯源 | 可追溯、可回放 |

### 9.2 架构演进路线

```
旧架构：
  Handler → asyncx.Go() → Service(串行) → LLM(同步) → DB(轮询)

新架构：
  Handler → Orchestrator → SkillDispatch → WorkflowEngine(并行DAG)
    → Agent(ReAct+Memory) → Tool(MCP/Built-in) → LLM(流式)
    → StreamManager(SSE/WS) → EventBus(通知/审计)
```

---

## 10. 分阶段实施计划

### Phase 1：基础重构（2 周）

**目标**：解决最紧急的效率和安全问题

| 任务 | 交付物 | 验收标准 |
|------|--------|----------|
| 统一并行执行框架 | WorkflowEngine | 3 Agent 并行分析延迟 < 单 Agent × 1.2 |
| AI 配置缓存 | AIConfigCache | 配置查询 <5ms |
| 仓库缓存层 | RepoCache | 缓存命中时仓库准备 <1s |
| 系统角色权限保护 | RBAC IsSystem 检查 | 系统角色不可修改（已修复） |
| Prompt 模板引擎 | PromptEngine | 模板变量注入 + 版本号管理 |

### Phase 2：流式 + 工具扩展（2 周）

**目标**：实现流式输出和工具扩展框架

| 任务 | 交付物 | 验收标准 |
|------|--------|----------|
| SSE 流式端点 | StreamManager + SSE Handler | 前端首 token <200ms |
| WS 事件推送统一 | 全路径 WS 通知 | Analysis/Fix/Collaboration 统一推送 |
| Tool Registry | ToolRegistry + ToolExecutor | 工具注册/发现/执行/审计 |
| 内置工具扩展 | 6 种新工具 | list_directory/search_symbols/git_diff/git_log/git_blame/web_search |
| 工具权限矩阵 | PermissionManager | Agent 只能调用授权工具 |
| 凭据管理器 | CredentialManager | 工具不接触原始密钥 |

### Phase 3：MCP + 技能系统（2 周）

**目标**：接入 MCP 生态，建立技能管理

| 任务 | 交付物 | 验收标准 |
|------|--------|----------|
| MCP Client | MCPClientManager | 连接 stdio/SSE 模式 MCP Server |
| MCP Tool 桥接 | MCPToolBridge | MCP Tools 自动注册为 BugAgent Tools |
| MCP Resource 映射 | MCPResourceProvider | MCP Resources 注入 Agent 上下文 |
| MCP Sampling | MCPSamplingHandler | Server 可请求 LLM 生成（用户授权） |
| 技能注册表 | SkillRegistry | 内置 5 种技能（analysis/fix/test/review/memory） |
| 技能调度器 | SkillDispatcher | 根据缺陷特征自动匹配技能 |
| 技能组合器 | SkillComposer | 多技能组合为复合技能 |

### Phase 4：优化 + 稳定化（1 周）

**目标**：性能优化和稳定性加固

| 任务 | 交付物 | 验收标准 |
|------|--------|----------|
| LLM 响应缓存 | LLMResponseCache | 重复 prompt 缓存命中 |
| 优先级任务队列 | PriorityTaskQueue | 高优先级任务优先执行 |
| 沙箱执行环境 | SandboxManager | 代码修改/测试在沙箱中执行 |
| 全链路压测 | 性能报告 | 满足验收指标 |
| 文档更新 | API 文档 + 架构文档 | 与代码同步 |

### 里程碑时间线

```
Week 1-2: Phase 1 基础重构
  ├── Day 1-3:  并行执行框架 + AI 配置缓存
  ├── Day 4-6:  仓库缓存 + Prompt 模板引擎
  └── Day 7-10: 集成测试 + Bug 修复

Week 3-4: Phase 2 流式 + 工具扩展
  ├── Day 11-13: SSE 流式 + WS 统一
  ├── Day 14-17: Tool Registry + 内置工具
  └── Day 18-20: 权限矩阵 + 凭据管理

Week 5-6: Phase 3 MCP + 技能系统
  ├── Day 21-24: MCP Client + Tool 桥接
  ├── Day 25-27: MCP Resource + Sampling
  └── Day 28-30: 技能注册/调度/组合

Week 7: Phase 4 优化 + 稳定化
  ├── Day 31-32: LLM 缓存 + 优先级队列
  ├── Day 33-34: 沙箱 + 压测
  └── Day 35:    文档 + 验收
```

---

## 11. 性能测试指标及验收标准

### 11.1 执行效率指标

| 指标 | 当前值 | Phase 1 目标 | 最终目标 | 测试方法 |
|------|--------|-------------|----------|----------|
| 3 Agent 并行分析延迟 | 45-90s | 18-35s | 18-35s | 创建缺陷 + 触发 3 Agent 分析，计时 |
| 仓库准备耗时 | 5-15s | <1s（缓存命中） | <1s | 连续分析同一项目，第二次计时 |
| AI 配置查询 | 50-100ms | <5ms | <5ms | 压测 AI 配置查询接口 |
| 前端首字节等待 | 等完整结果 | <200ms | <200ms | SSE 连接后计时到首个 token |

### 11.2 工具能力指标

| 指标 | 当前值 | 目标值 | 测试方法 |
|------|--------|--------|----------|
| 内置工具种类 | 4 | 14+ | 列举 ToolRegistry 注册的工具 |
| MCP 工具接入 | 0 | 任意 MCP Server | 启动 3 个 MCP Server，验证工具发现和调用 |
| 工具权限控制 | 无 | Agent 粒度 | 验证无权限工具调用被拒绝 |

### 11.3 流式输出指标

| 指标 | 当前值 | 目标值 | 测试方法 |
|------|--------|--------|----------|
| 流式首 token 延迟 | N/A | <200ms | SSE 连接后计时 |
| Token 推送间隔 | N/A | <50ms | 测量连续 token 间隔 |
| WS 事件推送延迟 | N/A | <100ms | 状态变更到 WS 推送的时间 |
| 断线重连恢复 | N/A | 支持 Last-Event-ID | 断开 SSE 后重连，验证续传 |

### 11.4 稳定性指标

| 指标 | 目标值 | 测试方法 |
|------|--------|----------|
| 并发分析（10 缺陷同时） | 无 OOM/无 panic | 压测 10 并发分析 |
| 长时间运行（24h） | 无内存泄漏 | 监控内存使用 |
| MCP Server 断连 | 自动重连，不影响主流程 | 模拟 MCP Server 崩溃 |
| 缓存失效 | 配置变更后 5s 内生效 | 修改 AI 配置，验证缓存更新 |

---

## 12. 潜在风险评估及应对策略

### 12.1 技术风险

| 风险 | 概率 | 影响 | 应对策略 |
|------|------|------|----------|
| **并行执行引入竞态** | 中 | 高 | Workflow Engine 使用状态机严格管理状态转换；每个 Agent 独立 context；聚合阶段加锁 |
| **MCP Server 不稳定** | 高 | 中 | MCP Client 实现指数退避重连；MCP 工具调用超时独立于主流程；降级到内置工具 |
| **流式输出内存膨胀** | 中 | 中 | RingBuffer 限制大小（默认 1000 chunks）；慢消费者跳过策略；SSE 连接超时自动断开 |
| **仓库缓存一致性** | 低 | 高 | 缓存 TTL 30 分钟；强制刷新 API；git fetch --rebase 增量更新 |
| **Prompt 模板注入** | 中 | 高 | 模板变量转义；禁止模板内执行代码；沙箱内渲染 |

### 12.2 业务风险

| 风险 | 概率 | 影响 | 应对策略 |
|------|------|------|----------|
| **重构期间功能回归** | 中 | 高 | Phase 1 保持旧接口兼容；新架构通过 Feature Flag 切换；全量回归测试 |
| **MCP 工具安全** | 高 | 高 | MCP Server 白名单；工具调用审计；Sampling 需用户授权；沙箱执行高风险工具 |
| **技能组合爆炸** | 低 | 中 | 技能组合限制最大 Agent 数（5）；工具调用次数限制；超时兜底 |
| **流式输出增加 LLM 调用成本** | 低 | 低 | 流式不影响 token 用量（仅传输方式变化）；LLM 缓存减少重复调用 |

### 12.3 运维风险

| 风险 | 概率 | 影响 | 应对策略 |
|------|------|------|----------|
| **MCP Server 进程管理** | 中 | 中 | MCP Client Manager 管理 Server 生命周期；健康检查；自动重启 |
| **SSE 连接数过多** | 中 | 中 | 单用户最大 10 个 SSE 连接；连接超时 30 分钟；Nginx 配置优化 |
| **仓库缓存磁盘占用** | 低 | 中 | LRU 最大 50 个仓库；磁盘使用告警；定期清理 |
| **优先级队列饥饿** | 低 | 中 | 低优先级任务最长等待 30 分钟后自动提升优先级 |

### 12.4 回滚方案

每个 Phase 都保持旧接口可用，通过 Feature Flag 控制切换：

```go
// Feature Flags
var Features = struct {
    ParallelAnalysis  bool  // 并行分析（Phase 1）
    StreamOutput      bool  // 流式输出（Phase 2）
    MCPIntegration    bool  // MCP 集成（Phase 3）
    SkillSystem       bool  // 技能系统（Phase 3）
    LLMLCache         bool  // LLM 缓存（Phase 4）
}{
    ParallelAnalysis:  true,   // Phase 1 完成后开启
    StreamOutput:      false,  // Phase 2 完成后开启
    MCPIntegration:    false,  // Phase 3 完成后开启
    SkillSystem:       false,  // Phase 3 完成后开启
    LLMLCache:         false,  // Phase 4 完成后开启
}
```

**回滚触发条件**：
- 错误率 > 5%（5 分钟窗口）
- P99 延迟 > 旧架构 2 倍
- 内存使用 > 阈值

**回滚操作**：
1. 关闭对应 Feature Flag
2. 请求自动路由到旧代码路径
3. 无需重启服务

---

## 附录 A：术语表

| 术语 | 全称 | 含义 |
|------|------|------|
| MCP | Model Context Protocol | 模型上下文协议，标准化 AI 应用与外部工具/数据的集成 |
| ReAct | Reason + Act | 推理-行动循环，Agent 核心执行模式 |
| DAG | Directed Acyclic Graph | 有向无环图，工作流编排模型 |
| SSE | Server-Sent Events | 服务器推送事件，HTTP 流式传输协议 |
| SOP | Standard Operating Procedure | 标准操作流程 |
| LRU | Least Recently Used | 最近最少使用缓存淘汰策略 |
| TTL | Time To Live | 缓存过期时间 |

## 附录 B：参考项目版本

| 项目 | 版本 | 参考日期 |
|------|------|----------|
| LangChain | v1.0 | 2025-05 |
| LangGraph | v1.0 | 2025-05 |
| AutoGPT Platform | latest | 2025-05 |
| MetaGPT | v0.8+ | 2025-05 |
| MCP Specification | 2025-03-26 / 2025-11-25 | 2025-11 |

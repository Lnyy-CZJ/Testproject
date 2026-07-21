# BugAgent v5.0 Overall Design

> Date: 2026-04-12  
> Scope: v5.0 总体产品设计（问题信号接入、问题池、智能分诊、缺陷转化与质量闭环）

---

## 1. 设计结论

BugAgent v5.0 的核心设计结论如下：

1. 新增“问题信号域”，用于承接外部来源的问题，而不是直接把外部数据写成正式缺陷。
2. 建立统一接入内核，Bugly、钉钉、飞书、阿里云日志平台、Webhook 都作为连接器接入。
3. 通过问题池和问题簇承接“分诊前”的问题状态，避免缺陷域被低质量和重复信号污染。
4. 首期坚持单向接入，双向回写仅做模型与协议预留。
5. 正式处置流程继续复用现有 Defect、Analysis、Collaboration、FixTask 主链路。

---

## 2. 核心边界

### 2.1 问题池 vs 正式缺陷

1. 问题池承接外部信号、分诊、聚类、忽略、合并和转缺陷。
2. 正式缺陷承接研发协作、AI 分析、修复、验证和关闭。
3. 两者必须在模型、状态机、页面和接口层彻底分开。

### 2.2 连接器 vs 接入内核

1. 连接器只负责“拉进来/收进来”。
2. 标准化、幂等、聚类和路由逻辑都放平台内核。
3. 原始 payload 必须留存，可追溯，可复查。

---

## 3. 首期方案

### 3.1 首期重点

1. 通用 Webhook 接入
2. Bugly 接入
3. 钉钉和飞书接入
4. 问题池和问题簇
5. 智能分诊建议
6. 问题转缺陷联动

### 3.2 首期不做

1. 自研 App SDK
2. 外部系统强双向同步
3. 大而全工单平台
4. 复杂规则编排器
5. 一次性全渠道接入

---

## 4. 核心模型

建议新增：

1. `integration_connectors`
2. `issue_signals`
3. `issue_clusters`
4. `issue_triage_records`
5. `issue_routing_rules`
6. `project_modules`
7. `app_releases`
8. `external_sync_records`

其中前 4 个为首期必须落地的核心模型。

---

## 5. 路线图结论

### Phase 5A

做“接入内核 + Bugly + IM + 问题池 + 分诊闭环”。

### Phase 5B

做“日志上下文 + 模块路由 + 版本关联 + 修复闭环增强”。

### Phase 5C

做“回归预防 + 质量情报 + 渠道扩展 + 双向回写”。

---

## 6. 关键风险控制

1. 控制首期渠道数量，避免连接器泛滥。
2. 强制问题池与缺陷域分层，避免模型污染。
3. 智能分诊先做建议，不做强自动化。
4. 保留原始 payload 与失败记录，适应不同渠道数据质量差异。

---

## 7. 产出文件

1. [PRD-v5.0-overall-signal-intake-triage-platform.md](/Users/jame/Workspace/bug_agent/docs/PRD-v5.0-overall-signal-intake-triage-platform.md)
2. [ROADMAP-v5.0-overall-signal-intake-triage-platform.md](/Users/jame/Workspace/bug_agent/docs/ROADMAP-v5.0-overall-signal-intake-triage-platform.md)

该设计文档用于归档总体设计结论，正式产品需求与路线图以上述两份文档为准。

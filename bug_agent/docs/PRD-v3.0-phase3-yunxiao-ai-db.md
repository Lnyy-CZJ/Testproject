# BugAgent v3.0 (Phase 3) PRD

> Version: v3.0  
> Date: 2026-04-09  
> Status: Draft  
> Owner: Product + Engineering

---

## 1. Background

当前系统已具备项目、缺陷、迭代、仓库、AI 配置与协作闭环能力，但在外部平台接入和 AI 配置治理上存在两类缺口：

1. 缺少云效（Alibaba Cloud DevOps）一体化能力，仓库和成员仍依赖手工维护。
2. AI 厂商/模型可选项仍以静态清单为主，无法通过数据库统一管理、灰度与下线。

本期目标是在不改变核心缺陷流程的前提下，补齐云效接入和 AI 配置中心化能力。

---

## 2. Goals And Non-Goals

### 2.1 Goals

1. 支持新增云效凭证并安全存储。
2. 支持调用云效 API 拉取仓库并导入到项目仓库列表。
3. 支持从云效导入成员并映射为项目成员角色。
4. 将 AI 厂商与模型可选项改为数据库配置，可动态维护。
5. 保留手动填写厂商/模型能力，覆盖数据库未收录的厂商。

### 2.2 Non-Goals

1. 不做云效工作项/流水线全量同步。
2. 不做跨组织多租户权限隔离重构。
3. 不做兼容历史前端版本（项目未上线）。

---

## 3. Personas

1. 平台管理员：维护 AI 厂商模型目录、控制可用性。
2. 项目管理员：配置云效凭证、导入仓库和成员。
3. 开发/测试成员：消费导入后的仓库与成员信息执行缺陷协作。

---

## 4. User Stories

1. 作为项目管理员，我可以新增云效凭证并测试连通性，确保后续导入成功。
2. 作为项目管理员，我可以按空间/搜索条件从云效拉取仓库并一键导入项目。
3. 作为项目管理员，我可以从云效导入成员并映射到项目角色。
4. 作为平台管理员，我可以在后台维护厂商和模型清单，并立即对项目配置生效。
5. 作为项目管理员，我在模型清单不足时仍可手动填写厂商/模型完成配置。

---

## 5. Functional Requirements

### FR-1 云效凭证管理

1. 在现有凭证体系新增 `provider=yunxiao`。
2. 支持凭证类型：
   - `pat`（推荐）
   - `username_password`（兼容场景）
3. 支持保存扩展配置（JSON）：
   - `organizationId`
   - `workspaceId`（可选）
   - `endpoint`（默认云效开放 API 域名，可覆盖）
4. 凭证需支持：
   - 创建/更新/删除
   - 连通性测试
   - 最后使用时间回写
5. 安全要求：
   - 服务端加密存储
   - 返回脱敏值
   - 审计日志记录创建/更新/删除/测试动作

验收标准：
- 新建云效凭证后可通过“测试连接”。
- 无权限或凭证过期时返回明确错误码与中文提示。

### FR-2 云效仓库拉取与导入

1. 提供后端适配层（Yunxiao Adapter），支持：
   - 拉取仓库列表（分页、搜索）
   - 标准化输出：`name/repoUrl/defaultBranch/sourceType/externalRepoId`
2. 前端在仓库管理页新增“从云效导入”入口：
   - 选择凭证
   - 选择空间（可选）
   - 拉取并多选仓库
   - 批量导入
3. 导入规则：
   - `sourceType` 固定为 `yunxiao`
   - 同项目内按规范化 `repoUrl` 去重
   - 缺省分支为空时使用 `main`

验收标准：
- 单次导入 100 个仓库成功率 >= 99%。
- 重复导入不创建重复仓库，并返回跳过数量。

### FR-3 云效成员导入

1. 提供云效成员拉取接口，支持按关键字搜索。
2. 在项目成员页新增“从云效导入成员”。
3. 导入映射策略：
   - 云效管理员 -> `project_admin`
   - 开发者 -> `developer`
   - 测试 -> `tester`
   - 其他 -> `viewer`
4. 已存在成员按 `userId` 去重，支持“仅更新角色”模式。
5. 导入前提供预览与冲突提示（未匹配本地用户、角色冲突等）。

验收标准：
- 可一次导入 50 名成员，角色映射正确率 >= 95%。
- 导入结果明确区分：新增/更新/跳过/失败。

### FR-4 AI 厂商与模型数据库配置化

1. 新增平台级配置表：
   - `ai_provider_catalog`（厂商）
   - `ai_model_catalog`（模型）
2. 厂商字段：
   - `provider_key`（唯一，如 `openai`）
   - `display_name`
   - `default_endpoint`
   - `status`（active/inactive）
   - `sort_order`
3. 模型字段：
   - `model_name`
   - `provider_key`
   - `endpoint`（可覆盖厂商默认端点）
   - `capability_tags`（chat/reasoning/code）
   - `status`（active/deprecated）
   - `is_default`
4. `GET /api/v1/ai/providers` 改为优先读数据库，数据库为空时回退内置默认。
5. 项目 AI 配置表继续保留 `provider/modelName/apiEndpoint` 文本字段，确保向后兼容。

验收标准：
- 平台新增/下线模型后，项目配置页可在 1 次刷新内看到变化。
- 数据库目录为空时仍可使用系统默认模型清单。

### FR-5 手动填写兜底

1. 项目 AI 配置页保留“手动填写厂商”“手动填写模型”入口。
2. 手动填写不依赖目录表，可直接保存。
3. 若手动填写值与目录冲突，不阻断保存，仅提示“非目录模型”。

验收标准：
- 手动填写路径可完整创建、编辑、调用 AI。

---

## 6. API Design (Draft)

### 6.1 云效集成

1. `POST /api/v1/integrations/yunxiao/test-connection`
2. `GET /api/v1/integrations/yunxiao/repos`
3. `POST /api/v1/projects/:id/repos/import/yunxiao`
4. `GET /api/v1/integrations/yunxiao/members`
5. `POST /api/v1/projects/:id/members/import/yunxiao`

### 6.2 AI 目录管理

1. `GET /api/v1/ai/providers`（项目侧读取）
2. `GET /api/v1/admin/ai/providers`
3. `POST /api/v1/admin/ai/providers`
4. `PUT /api/v1/admin/ai/providers/:id`
5. `GET /api/v1/admin/ai/models`
6. `POST /api/v1/admin/ai/models`
7. `PUT /api/v1/admin/ai/models/:id`

---

## 7. Data Model Changes

1. `repo_credentials`：
   - 扩展 `provider` 枚举支持 `yunxiao`
   - 新增 `extra_config` (JSON/TEXT)
2. 新增 `ai_provider_catalog`
3. 新增 `ai_model_catalog`
4. `project_repos`：
   - `source_type` 枚举支持 `yunxiao`
   - 可选 `external_repo_id`（后续追踪同步）
5. `project_members` 保持不变，导入走现有成员写入流程。

---

## 8. Error Handling

1. 云效凭证失效：返回 `401` + `凭证无效或已过期`。
2. 云效 API 限流：返回 `429` + 重试建议。
3. 仓库重复：返回导入结果中的 `skipped` 列表，不报整体失败。
4. 成员未映射到本地用户：返回 `unmatched` 列表并支持导出。
5. AI 目录读失败：回退默认内置清单并上报告警日志。

---

## 9. Non-Functional Requirements

1. 性能：
   - 仓库拉取列表接口 P95 < 1200ms（100 条）
   - 成员拉取接口 P95 < 1200ms（100 条）
2. 稳定性：
   - 云效 API 瞬时失败支持 3 次指数退避重试
3. 安全：
   - 所有凭证服务端加密
   - 导入相关接口需项目管理员及以上权限
4. 可观测性：
   - 记录外部 API 耗时、失败码、重试次数

---

## 10. Rollout Plan

1. 阶段 1：先上线 AI 目录数据库化（低耦合、低风险）。
2. 阶段 2：灰度云效凭证与仓库导入（仅管理员可见）。
3. 阶段 3：开放成员导入并补齐审计看板。

回滚策略：
- 云效相关接口可通过开关关闭，保留现有手动仓库/成员管理路径。
- AI 目录查询失败自动回退内置清单，无需停机。

---

## 11. Acceptance Checklist

1. 云效凭证创建/更新/测试通过。
2. 可从云效拉取仓库并批量导入，重复导入不重复写入。
3. 可从云效拉取成员并完成角色映射导入。
4. AI 厂商模型目录可由数据库维护，项目页同步可见。
5. 目录外模型可手动填写并可正常调用。
6. 审计日志覆盖关键操作。


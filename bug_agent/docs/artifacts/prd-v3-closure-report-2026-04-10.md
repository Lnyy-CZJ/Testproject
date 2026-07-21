# BugAgent v3.0 (Phase 3) PRD 差异-修复-验证闭环清单

**日期**: 2026-04-10  
**分支**: `codex/phase3-prd-fixes-and-perf`  
**基线文档**: `docs/PRD-v3.0-phase3-yunxiao-ai-db.md`

---

## 1. 总览

本轮按 FR-1 ~ FR-5 与 NFR 逐项复核，已完成主要差异修复并通过后端全量测试与浏览器侧 E2E 回归。

## 2. 模块闭环清单

| 模块 | PRD关键要求 | 修复结果 | 验证证据 | 状态 |
|---|---|---|---|---|
| 云效凭证管理 (FR-1) | 支持 `yunxiao` 凭证、扩展配置、连接测试、错误码语义 | 支持 `pat/username_password`；`extraConfig` 支持 `organizationId/workspaceId/endpoint`；连接测试 `401/429` 映射完善；测试成功回写 `lastUsedAt` | `go test ./internal/handler -run TestYunxiaoIntegration_ -count=1` | ✅ |
| 云效仓库导入 (FR-2) | 标准化仓库字段、去重导入、默认分支兜底 | 列表返回包含 `name/repoUrl/defaultBranch/sourceType/externalRepoId`；按规范化 URL 去重；空分支兜底 `main` | `TestYunxiaoIntegration_ListReposAndImport` | ✅ |
| 云效成员导入 (FR-3) | 角色映射、仅更新模式、导入前预览冲突提示 | 增加前端预估结果（将新增/将更新/已存在/本地未匹配）；支持 `updateExisting`；导入结果新增/更新/跳过/未匹配/失败分组 | 浏览器 E2E（成员导入流程） | ✅ |
| 未匹配成员导出 (Error Handling #4) | `unmatched` 列表支持导出 | 导入后保留未匹配结果并支持导出 CSV（`yunxiao-unmatched-members-*.csv`） | 浏览器 E2E（下载断言） | ✅ |
| AI目录数据库化 (FR-4) | 厂商/模型目录数据库维护 + 项目侧可见 | 已有目录管理 CRUD，新增删除能力；项目配置页可读目录并手动补录 | 浏览器 E2E（AI目录页） | ✅ |
| 手动填写兜底 (FR-5) | 目录外模型可保存，仅提示不阻断 | 项目 AI 配置新增“非目录模型”提示，不阻断保存 | 浏览器 E2E（手动模型提示） | ✅ |
| 审计与可观测性 (NFR) | 关键操作审计、外部 API 重试/耗时观测 | 新增云效测试/导入与 AI 目录增删改业务审计；云效请求记录重试、失败码、耗时日志；AI目录回退记录告警日志 | `go test ./internal/handler ./internal/middleware -count=1` | ✅ |

---

## 3. 本轮关键提交

- `b77ad06` feat(audit): add business audit logs for yunxiao and ai catalog ops
- `eb7927b` chore(observability): log yunxiao latency/retries and ai catalog fallback
- `e9d3940` feat(yunxiao): export unmatched member import results
- `73d9d0d` feat(yunxiao): normalize repo payload with sourceType and externalRepoId
- `bd77a9b` feat(phase3): add yunxiao precheck preview and status-code mapping
- `245949b` feat(ai-catalog): add delete actions and store external repo id

---

## 4. 验证记录

### 后端
- `cd server && /opt/homebrew/bin/go test ./... -count=1` ✅

### 前端
- `cd web && /opt/homebrew/bin/npm run build` ✅
- `cd web && /opt/homebrew/bin/npm run test:e2e` ✅（9/9）

---

## 5. 剩余风险（按模块）

1. 云效真实环境兼容风险：当前以 mock/测试环境验证为主，真实租户字段变更与权限模型差异仍需灰度验证。
2. 凭证类型风险：`username_password` 在云效侧可用性依赖上游认证策略，建议以 `pat` 作为默认推荐路径。
3. 审计数据增长风险：新增业务审计后写入量上升，需上线后关注 `audit_logs` 表增长与归档策略。
4. 前端依赖告警风险：E2E 运行仍存在 Ant Design 废弃 API warning，不影响功能但建议后续清理。

---

## 6. 结论

v3.0 Phase 3 的核心需求已完成“差异识别 -> 修复 -> 自动化验证”闭环，当前剩余项均为上线期观测与运维侧风险，不阻塞继续迭代与联调验收。

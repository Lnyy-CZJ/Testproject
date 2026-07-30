# searchTool v1.3 MVP 阶段7集成验收记录

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 对应需求 | `searchTool_v1.3_PRD需求整理.md` |
| 对应设计 | `searchTool_v1.3_MVP_开发设计与开发计划.md` |
| 优化需求 | `searchTool_v1.3_MVP_优化需求.md` |
| 优化设计 | `searchTool_v1.3_MVP_优化开发设计与开发计划.md` |
| 验收范围 | 阶段0–6集成、固定夹具、容量、安全、备份恢复和文档 |
| 环境 | 本地/测试环境，单用户，`127.0.0.1:5002` |
| 数据原则 | 自动验收仅使用虚构人物和 `example.test`；真实数据结果单独记录 |

优化阶段6全量回归于2026-07-25执行：

```text
Ran 63 tests in 45.142s
OK
```

## 2. 自动化验收范围

固定夹具：`tests/fixtures/v1_3_e2e`。

夹具包含：

- 2名 Person；
- 每人 `FULL_NAME`、`FULL_NAME_SOCIAL`；
- baseline/candidate 两个 Run；
- `HIT`、`NOT_HIT`、`SUSPECTED`；
- 1名 Candidate Detail 失败；
- 1条 Query 失败；
- 未知 `future_module.data.label` 字段；
- `llm_cost`、`total_cost`、`pdl_called` 全部为空。

端到端测试执行以下闭环：

```text
历史 JSONL 导入
  → 统一 Run/Query/Candidate/Raw/Failure
  → 发布 FieldSchema
  → 处理 baseline/candidate
  → 人工 Candidate/字段复核
  → 单 Run 指标与同人同条件版本配对
  → ReportModel 快照
  → 静态 HTML
  → processed Excel
```

阶段7集成测试还验证：

- 失败 Query 从 metadata 继承 `person_id/query_stage`，可以继续版本配对；
- Candidate Detail 失败生成 `DETAIL_FAILED`，不伪装成正常空字段；
- 新字段不修改采集代码即可通过配置提取并进入 Excel；
- 成本字段为空时显示 `NOT_CONNECTED`，不按0统计；
- 100人 × 2条件 × 2版本的400条 Query 和400名候选人可完整导入；
- SQLite backup API 生成的快照可以重新初始化并读取业务记录。

## 3. PRD 第17章验收证据

### 3.1 执行与导入

| 验收项 | 状态 | 自动化证据 |
| --- | --- | --- |
| Web 启动 FULL_NAME/FULL_NAME_SOCIAL | 代码通过，真实接口待现场 | `test_web_app.py` Web执行测试；现场需真实配置 |
| Web 导入 JSONL/Excel 历史结果 | 通过 | Web导入测试、`test_analysis_service.py` 导入测试 |
| 统一展示 Run/Query/Candidate | 通过 | 历史导入页面与阶段7固定闭环 |
| 重复执行/导入不覆盖旧数据 | 通过 | SHA-256重复拒绝、唯一Run测试 |
| Candidate Detail 失败后继续 | 通过 | 采集回归测试和阶段7固定夹具 |

### 3.2 原始数据

| 验收项 | 状态 | 自动化证据 |
| --- | --- | --- |
| 100人 Query 列表 | 合成数据通过，真实数据待现场 | 101条分页测试、阶段7 400 Query容量测试 |
| 查看全部已返回候选人 | 通过 | 超过5名候选人采集及详情页测试 |
| 查看业务字段和完整 Raw | 通过 | Candidate详情、Raw API测试 |
| 未配置字段仍保留 Raw | 通过 | `future_module` 固定夹具 |
| 下载原始结果和失败记录 | 通过 | Web下载测试 |

### 3.3 字段处理

| 验收项 | 状态 | 自动化证据 |
| --- | --- | --- |
| 新增/修改字段配置 | 通过 | FieldSchema发布与Web测试 |
| 保存生成新版本且不审核 | 通过 | 不可变FieldSchema测试 |
| 新配置重新处理历史 Raw | 通过 | Process版本测试 |
| Web与Excel共用处理结果 | 通过 | processed Excel测试和阶段7固定闭环 |
| 配置错误不修改 Raw | 通过 | 字段错误隔离测试 |

### 3.4 复核与指标

| 验收项 | 状态 | 自动化证据 |
| --- | --- | --- |
| JSONL/Excel基准导入 | 通过 | 基准导入测试 |
| Candidate和字段复核 | 通过 | Review保存、并发保护、阶段7固定闭环 |
| Social来源未确认不自动正式命中 | 通过 | Social冲突/建议规则测试 |
| 核心指标符合公式 | 通过 | 手算指标与配对测试 |
| 缺少基准/复核时不生成虚假结论 | 通过 | 预览值和formal readiness测试 |
| 成本/PDL未接入显示缺失 | 通过 | `NOT_CONNECTED` 测试 |

### 3.5 报告

| 验收项 | 状态 | 自动化证据 |
| --- | --- | --- |
| 单 Run报告 | 通过 | ReportModel测试 |
| baseline/candidate报告 | 通过 | 阶段6及阶段7对比报告测试 |
| FULL_NAME/FULL_NAME_SOCIAL比较 | 通过 | Query阶段指标测试 |
| 指标下钻到人物/Query/Candidate/Raw | 通过 | Web报告下钻测试 |
| Excel和静态HTML | 通过 | 实际工作簿生成、独立HTML下载测试 |
| HTML人物案例和风险说明 | 通过 | HTML转义、无CDN、案例测试 |

## 4. 性能与磁盘验收

自动容量门槛：

| 项目 | 门槛 | 状态 |
| --- | ---: | --- |
| 合成人物数 | 100 | 通过 |
| Query数 | 400 | 通过 |
| Candidate数 | 400 | 通过 |
| 两版本导入耗时 | 小于30秒 | 通过 |
| 测试SQLite文件 | 小于25 MiB | 通过 |
| Run列表分页 | 每页50条 | 通过 |

这些数据是开发机脱敏合成预检，不等价于接口网络耗时、真实候选人数或真实 Raw
体积。真实100人验收必须填写第7节。

## 5. 安全检查

已检查：

- `.env`、`data/`、`output/` 受 `.gitignore` 保护；
- 自动夹具仅使用虚构标识和 `example.test`；
- Raw脱敏测试覆盖 Token、Cookie、Header、Device ID 和 User ID；
- Web默认监听 `127.0.0.1`；
- 下载和Raw接口包含路径越界保护；
- HTML输出执行文本转义且不依赖外部CDN；
- 错误页不展示配置和堆栈。

发布前仍需由提交者检查 Git 暂存区，确认没有真实 `.env`、人物Raw、报告或凭证：

```bash
git status --short
git diff --cached --name-only
git diff --cached | rg -n 'AUTH_TOKEN|Bearer|Cookie|DEVICE_ID|USER_ID'
```

## 6. 备份、恢复与迁移

SQLite一致性备份/恢复已由
`test_sqlite_online_backup_can_be_restored` 自动验证。完整备份必须同时包含数据库、
imports、raw 和 reports。详细命令、恢复校验与以下迁移策略见项目 `README.md`：

- v1.3 Schema v1 环境使用完整目录备份恢复；
- v1.2/旧JSONL和规范化Excel通过导入接口迁移；
- FieldSchema变更通过新版本重新处理；
- 未支持的数据库Schema拒绝启动，不允许手工修改版本号。

## 7. 真实环境现场验收

真实接口与真实人物数据不进入自动夹具，本轮不能替用户填写“通过”。请在受控测试
环境完成以下两批验收，并把证据写入本表。

### 7.1 小批真实数据

建议先使用2–5人，覆盖两种 Query 条件。

| 记录项 | 结果 |
| --- | --- |
| 验收日期 | 待填写 |
| Evaluation ID | 待填写 |
| Run ID | 待填写 |
| 人物数 / Query数 | 待填写 |
| 完成 / 部分失败 / 失败 Query | 待填写 |
| Candidate Detail失败数 | 待填写 |
| Process / Report ID | 待填写 |
| HTML / Excel检查 | 待填写 |
| 结论和问题单 | 待填写 |

### 7.2 100人真实数据

输入应包含100人 × `FULL_NAME/FULL_NAME_SOCIAL`，执行前先完成备份并确认磁盘空间。

| 记录项 | 结果 |
| --- | --- |
| 验收日期 | 待填写 |
| Evaluation ID | 待填写 |
| baseline / candidate Run ID | 待填写 |
| 实际 Query / Candidate 数 | 待填写 |
| 总耗时、平均 Query 耗时 | 待填写 |
| 数据库 / Raw / 报告磁盘增量 | 待填写 |
| Query失败 / Detail失败数 | 待填写 |
| 分页、Raw下钻抽查 | 待填写 |
| 备份恢复抽查 | 待填写 |
| 报告与Excel行数核对 | 待填写 |
| 最终结论和问题单 | 待填写 |

任何真实 Query 失败、Detail失败或人工复核未完成都应在报告中保留，不得通过删除
失败记录来获得“通过”结论。

## 8. 已知限制

1. 本地单用户、无登录权限，只允许受控 localhost 使用。
2. 同一时刻只有一个采集 Run；重启后当前 Query 不续跑。
3. 首版不支持照片输入及对应 PUT 请求。
4. List Candidates 暂不执行真实翻页。
5. `llm_cost`、`third_party_cost`、`total_cost`、`pdl_called` 和
   `search_duration_ms` 正式接口路径尚未接入；成本单位和包含关系待确认。
6. `provider_summary`、顶层 `evidence`、`social_accounts` 暂只保留 Raw。
7. 历史Excel缺失Raw时只能标记 `LEGACY_PARTIAL_RAW`。
8. 静态HTML包含人物案例时需要按受控测试数据保管。

## 9. 阶段7结论

代码级集成、脱敏固定夹具、100人合成容量、备份恢复、安全检查和交付文档已完成。
小批真实数据及100人真实数据仍属于现场验收项；在第7节填写并通过前，不将其表述
为“真实环境验收完成”。

## 10. v1.3 MVP 优化阶段6复验

### 10.1 Excel v2

| 验收项 | 结果 |
| --- | --- |
| 固定 Sheet | `说明`、`核心指标`、`Query明细`、`候选结果`、`同条件对比`、`新增线索`、`模块字段统计`、`失败记录` 均通过 |
| 兼容 Sheet | `人工复核` 保留；超长内容按需生成 `Raw数据` |
| ReportModel | Excel 只读取报告快照，不重新计算指标 |
| 空值 | 未接入/无数据/未就绪保持空单元格 |
| 类型 | 成本、耗时、比例保持数字；`pdl_called=false` 保持布尔值 |
| URL/长 JSON | URL 保留原文；超过单元格限制的 JSON 可按 Raw 引用和分块还原 |
| 旧报告 | 旧 ReportModel v1 processed 输入仍可导出，缺少的 v2 指标保持空表/空值 |

### 10.2 集成与运行环境

| 验收项 | 结果 |
| --- | --- |
| 全量自动化 | 63项通过 |
| 固定端到端 | Dataset/历史导入 → Process → 复核 → ReportModel → HTML/Excel 通过 |
| 容量 | 100人 × 2条件 × 2版本，共400条 Query 和400名候选人通过 |
| Schema升级 | SQLite v1→v2保留历史语义；迁移失败可完整回滚 |
| 备份恢复 | SQLite online backup恢复通过 |
| Docker | 镜像重建后 `127.0.0.1:5002` 健康，首页和已有报告均返回200 |
| 数据持久化 | 重启前后均为 Schema v2，1个 Evaluation、1个 Run、1份报告 |

### 10.3 本阶段仍未闭环

- Docker 镜像按既有策略未内置 Codex spreadsheet runtime，因此容器内
  `SEARCH_REPORT_EXCEL_ENABLED=false`；Web 和静态 HTML 不受影响，Excel 可在
  宿主机生成。
- 五个待确认公共字段没有正式接口路径时只展示空值，不生成假数据。
- 小批真实接口和100人真实数据仍需按第7节现场验收表填写。

## 11. 信息架构与使用体验优化阶段3复验

| 验收项 | 结果 |
| --- | --- |
| Schema升级 | SQLite v2→v3新增 `threshold_profiles` 和 `evaluations.threshold_profile_id`；历史 `thresholds_json` 原值保留 |
| 连续迁移 | v1数据库可在单事务中连续升级到v3；任一步失败完整回滚 |
| 方案版本 | 支持创建、复制新版本、查看和归档；不允许覆盖 `profile_id` 或相同名称版本 |
| Evaluation | 创建时可选方案或留空；详情只显示摘要和更换入口，不再内嵌10项编辑器 |
| 快照 | 选择方案时原子复制 `thresholds_json`；旧手工接口清空方案关联并保留兼容 |
| 报告 | 新ReportModel记录方案标识、名称和版本；继续保存 `threshold_snapshot` |
| 历史兼容 | 旧Evaluation显示历史自定义参考线；旧ReportModel无需方案字段仍可打开 |
| 不可变性 | 更换方案不修改、不重算、不标记既有报告 |
| Web入口 | 顶部“参考线”可进入方案列表、新建、详情、复制和归档流程 |
| 全量自动化 | 69项通过 |
| Docker | `127.0.0.1:5002` 健康；参考线中心、创建Evaluation和旧报告均返回200 |
| 数据持久化 | 正式库由Schema v2升级到v3后仍为1个Evaluation、1个Run、24条Raw、2个Process、1份Report |
| 迁移备份 | `data/backups/pre_schema_v3_20260727_1204.db` 保留升级前Schema v2快照 |

本节属于阶段7之后的信息架构增量复验；原第7节真实数据现场验收状态不变。

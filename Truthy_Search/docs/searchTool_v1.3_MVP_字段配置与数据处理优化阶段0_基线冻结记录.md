# searchTool v1.3 MVP 字段配置与数据处理优化：阶段 0 基线冻结记录

## 1. 目的与边界

本记录冻结字段配置与数据处理优化开始前的现行行为，作为后续 FieldSchema v3、字段目录、字段对比和新指标实现的回归基线。

本阶段不修改字段配置结构、不新增可提取字段、不改变重处理规则，也不重算或覆盖既有报告。

## 2. 冻结版本

| 项目 | 冻结值 | 兼容策略 |
|---|---|---|
| 默认字段配置 | `field-schema-default-v2` | 保持不可变、可读取、可用于历史 Process |
| 字段处理规则 | `field-processing-v4` | 新 Process 当前继续写入 v4；v1/v2/v3 仍按原路由计算 |
| 指标规则 | `metrics-v3` | v3 与 v4 Process 继续路由到 metrics-v3 |
| 报告模型 | `report-model-v3` | 旧报告快照不重算；新建报告继续使用 v3 模型 |

## 3. 默认 FieldSchema 验收快照

默认配置共有 **33** 个字段，模块分布如下：

| 模块 | 字段数 |
|---|---:|
| Task | 6 |
| Candidate | 3 |
| Insights | 4 |
| Photos | 3 |
| Profile | 3 |
| Social | 4 |
| Summary | 10 |

当前默认配置仅 `social_urls` 参与 `identity`、`completeness` 和 `accuracy` 三类评分职责；其余字段按现状用于提取、展示、模块统计或人工查看，不在本阶段擅自改变评分范围。

## 4. candidatetest2 脱敏验收快照

以下为已完成的 `candidatetest2` 处理结果的脱敏聚合记录，用于人工验收比对；不保存真实人物名称、任务 ID、候选人 ID、Social Link 或原始响应。

| 项目 | 冻结值 |
|---|---:|
| Query 数 | 10 |
| Candidate Detail 成功数 | 45 |
| Candidate Detail 失败数 | 0 |
| 自动完成身份归类的 Query 数 | 10 |
| 主命中 Query 数 | 8 |
| 无命中 Query 数 | 2 |
| 待身份归类 Candidate 数 | 0 |
| 检索成功率 | 8 / 10（80.00%） |
| 命中候选完整度 | 3.2667 / 8（40.83%） |
| 命中候选准确度 | 7.7500 / 8（96.88%） |
| 非命中候选完整度 | 4.6667 / 31（15.05%） |

五模块数据数（分母均为 45 名 Detail 成功候选人）：Insights 2、Photos 0、Profile 45、Social 34、Summary 45。

成本相关字段在当前接口未接通时仍应为 `NOT_CONNECTED` 或等价的缺失状态，不能填充为 0，也不能混入正式质量指标。

## 5. 自动化回归夹具

脱敏自动化夹具位于 [v1_3_field_configuration_phase0_contract.json](/Users/admin/Testproject/Truthy_Search/tests/fixtures/v1_3_field_configuration_phase0_contract.json)。它冻结：

- 默认配置的版本、字段总数、模块数量和评分职责；
- `field-processing-v4` 到 `metrics-v3`、`report-model-v3` 的路由；
- 独立测试数据中的 10 条 Query、45 名 Candidate 和五模块统计。

真实 `candidatetest2` 仅用于本记录的人工验收，不会被自动化测试读取，因此不会将本地历史业务数据或个人数据写入测试夹具。

## 6. 验收结果

- 默认 FieldSchema 可以创建、读取并通过现有定义校验；
- 既有脱敏回归场景在 `field-processing-v4` 下仍输出 `metrics-v3` 和 `report-model-v3`；
- 既有报告和导出不需要迁移或重算；
- 后续阶段只能创建新的 FieldSchema / Process / Report，不能覆盖本阶段冻结的历史快照。

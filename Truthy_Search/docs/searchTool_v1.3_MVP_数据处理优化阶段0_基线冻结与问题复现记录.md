# searchTool v1.3 MVP 数据处理优化阶段0：基线冻结与问题复现记录

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 执行日期 | 2026-07-28 |
| 阶段 | 阶段0：基线冻结与问题复现 |
| 数据库版本 | SQLite Schema v3 |
| 字段处理规则 | `field-processing-v2` |
| 指标规则 | `metrics-v2` |
| 报告模型 | `report-model-v2` |
| 阶段状态 | 已完成 |

## 2. 阶段目标

本阶段只冻结当前问题、输入输出和 v3 验收口径，不实现 Schema v4、
`field-processing-v3`、`metrics-v3` 或页面功能。

成功标准：

- 真实问题可以稳定复现；
- 当前 v2 行为有不可变快照；
- v3 目标行为有预期失败测试；
- 生产数据库没有被测试或修复代码修改；
- 后续开发前存在可恢复的 SQLite 一致性备份。

## 3. 冻结的真实数据

| 对象 | ID/版本 |
| --- | --- |
| Evaluation | `eval_20260728` |
| Run | `run_2be5fe30b86f49bcba447296205911bb` |
| Process | `process_9c490abfc00f47a1a2f06d594f8819a7` |
| Report | `report_5a680512bbbc4048ae860ca42330b162` |
| Baseline | `test20260728` |
| FieldSchema | `field-schema-default-v2` |

真实输入和报告产物校验值：

| 文件 | SHA-256 |
| --- | --- |
| `data/results.jsonl` | `397847d23aa40aea783060ba1fcb6669eaa2b96a62769afe9123cf7061d489de` |
| `processed_export.jsonl` | `263dfe30b73074c2e19b6215d8e5dd4909f87fdfe6d19141eb118e415755981b` |
| `report.html` | `444b1722c2d1ee44221230aa749609b1bfd478f39dcb801c4ff251d7f4d3b075` |
| `report_model.json` | `85ff134bed9197337dce7ea7b8cd09550b0775648823db7b50899c543029cb42` |

以上文件只用于校验历史快照。本阶段没有修改原始 JSONL、Raw Record、ProcessResult
或旧报告。

## 4. SQLite 备份

备份文件：

```text
data/backups/searchtool_v1_3_before_data_processing_v3_20260728_142706.db
```

SHA-256：

```text
82972b59ccac0fdb784453be99b65f2aa6d3bacf3bfbda81fdb43c123265b3c7
```

验证结果：

- 使用 SQLite Online Backup 创建；
- `PRAGMA integrity_check` 返回 `ok`；
- 备份包含2个 Run 和2个 Report；
- 备份目标为新文件，没有覆盖旧备份；
- 源数据库仍为 `data/searchtool_v1_3.db`。

## 5. 真实问题复现结果

### 5.1 Query 人物关联

| 项目 | 当前结果 |
| --- | ---: |
| Query 总数 | 10 |
| `person_id` 为空 | 10 |
| Baseline Person 数 | 10 |
| 能通过现有关联进入正式 Baseline 对比 | 0 |

结论：Baseline 数据存在，但 Run Query 没有 `person_id`，处理器无法找到人物基准。

### 5.2 身份归类

| 状态 | 数量 |
| --- | ---: |
| Candidate Detail 成功 | 45 |
| `PENDING_REVIEW` | 45 |
| `HIT` | 0 |
| `NOT_HIT` | 0 |
| `SUSPECTED` | 0 |

结论：当前没有正式身份分母，因此命中和非命中指标不能形成正式值。但全部候选人
字段返回率不应依赖身份归类。

### 5.3 Query/Candidate 作用域

数据库中10条 Query 均存在 `task_id`，`processed_queries` 也成功提取10个
`task_id`。当前报告却在候选人字段聚合中展示：

```text
Task ID: 0/45
```

结论：`Task ID` 被错误使用 Candidate 分母。v3 必须展示 `10/10`，并明确
`value_scope=QUERY`。

### 5.4 模块空容器

当前 v2 模块统计：

| 模块 | v2 当前返回率 | 真实语义 |
| --- | ---: | --- |
| Insights | 100% | 仅2/45有数据 |
| Photos | 100% | 0/45有数据 |
| Profile | 100% | 45/45有数据 |
| Social | 100% | 34/45有数据 |

原因：v2 使用“模块任一字段非空”，`status=empty` 和空 `data` 对象仍被当成有效
内容。v3 必须使用模块语义状态。

### 5.5 Baseline 与评分字段交集

每名 Baseline Person 均声明15个 `baseline_available_fields`，但
`field-schema-default-v2` 只有 `social_urls` 参与 completeness。

```text
Baseline 可用字段：15
Candidate completeness 字段：1
有效交集：1
Baseline 单侧冲突：14
```

结论：系统需要字段对比矩阵，在处理前明确显示这14个冲突，不能静默缩小评分范围。

### 5.6 指标状态

当前报告质量指标：

| 指标 | v2 状态 | v2 分母 |
| --- | --- | ---: |
| 检索成功率 | `NOT_READY` | 10 |
| 命中完整度 | `NOT_APPLICABLE` | 0 |
| 命中准确率 | `NOT_APPLICABLE` | 0 |
| 非命中完整度 | `NOT_APPLICABLE` | 0 |

v2 把“人物未关联”“身份待归类”“没有有效字段”和“业务上确实没有分母”混合成
相同展示。v3 必须返回 `status`、`reason_codes` 和可读 `reasons`。

## 6. 脱敏夹具

新增夹具：

```text
tests/fixtures/v1_3_data_processing_phase0/problem_contract.json
```

夹具保留：

- 10条 Query；
- 候选人数分布 `5/6/1/7/4/6/3/6/1/6`；
- 45名候选人；
- 10个 `task_id`；
- 2名候选人有 Insights；
- 0名候选人有 Photos；
- 45名候选人有 Profile；
- 34名候选人有 Social；
- 15个 Baseline 可用字段；
- v2 当前快照和 v3 目标值。

夹具不包含真实姓名、真实 Candidate Detail、Token、Header、Device ID 或 User ID。

## 7. 回归测试设计

测试入口：

```bash
python3 -m unittest discover -s tests \
  -p 'test_analysis_service.py' \
  -k data_processing_phase0 -v
```

### 7.1 v2 快照测试

`test_data_processing_phase0_v2_problem_snapshot_is_reproducible`

该测试必须通过，证明脱敏场景可以复现：

- Query `person_id` 全空；
- Baseline 无法关联；
- 45名候选人全部 PENDING；
- Query 中10个 `task_id` 被报告成0/45；
- Insights/Photos 空容器被判有数据；
- 15个 Baseline 字段只有1个 completeness 字段。

### 7.2 v3 预期失败测试

| 测试 | 目标 |
| --- | --- |
| `test_data_processing_phase0_v3_query_scope_contract` | Task ID 为10/10 |
| `test_data_processing_phase0_v3_module_empty_contract` | Insights 2/45、Photos 0/45 |
| `test_data_processing_phase0_v3_identity_pending_reason_contract` | 返回 `BASELINE_NOT_LINKED`、`IDENTITY_PENDING` |
| `test_data_processing_phase0_v3_candidate_return_rate_contract` | 全 PENDING 时字段返回率仍 READY |
| `test_data_processing_phase0_v3_field_matrix_conflict_contract` | 显示15/1/14字段冲突 |

这些测试在阶段0使用 `unittest.expectedFailure`。后续实现满足目标时会变成
`unexpected success` 并让测试套件失败，届时必须移除装饰器，使测试正式转绿。

## 8. v3 冻结验收值

固定场景：

```text
10 Query
45 Candidate Detail SUCCESS
10 task_id
45 Profile data
34 Social data
2 Insights data
0 Photos data
45 PENDING identity classifications
```

固定期望：

| 项目 | v3 期望 |
| --- | --- |
| Task ID | `10/10`、`QUERY`、`READY` |
| Profile | `45/45` |
| Social | `34/45` |
| Insights | `2/45` |
| Photos | `0/45` |
| 全部候选人字段返回率 | PENDING 时仍 `READY` |
| 身份相关指标 | `NOT_READY/IDENTITY_PENDING` |
| Baseline 未关联 | `NOT_READY/BASELINE_NOT_LINKED` |
| Baseline/评分字段冲突 | 15个可用、1个评分、14个冲突 |

## 9. 阶段0测试结果

阶段开始前全量基线：

```text
Ran 69 tests
OK
```

阶段0专项预期：

```text
1个 v2 快照测试通过
5个 v3 契约测试 expected failure
```

阶段完成后的全量回归：

```text
Ran 75 tests in 48.076s
OK (expected failures=5)
```

其中70项现有及 v2 快照测试通过，5项尚未实现的 v3 契约按计划标记为
expected failure。阶段0没有修改生产业务逻辑、数据库 Schema、Web 页面和报告
计算实现。

## 10. 下一阶段入口

阶段1只处理：

- SQLite Schema v4；
- `person_id_source`；
- 人物关联审计；
- 历史 Run Query 人物关联服务；
- 报告 `STALE`；
- Raw/Results 校验和不变。

阶段1不得提前修改 `metrics-v3`、模块判空或字段矩阵计算。

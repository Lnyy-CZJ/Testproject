# searchTool v1.3 MVP 数据处理优化阶段1：Schema v4与历史人物关联验收记录

## 1. 阶段结论

| 项目 | 结果 |
| --- | --- |
| 阶段 | 阶段1：Schema v4与历史人物关联 |
| 执行日期 | 2026-07-28 |
| 实现状态 | 已完成 |
| SQLite Schema | v4 |
| Docker 服务 | `127.0.0.1:5002`，healthy |
| 全量测试 | 81项，全部符合预期 |

本阶段只实现数据库结构、历史 Run Query 人物关联服务和 Web 工作区，没有提前实现
无成本重新处理、Query 身份归类、字段矩阵、`field-processing-v3` 或
`metrics-v3`。

## 2. Schema v4

### 2.1 新增结构

- `dataset_queries.person_id_source`；
- `run_queries.person_id_source`；
- `reviews.classification_source`；
- `reviews.is_primary_hit`；
- `run_query_person_history`；
- `idx_person_history_run_query`。

### 2.2 来源枚举

Run Query：

- `UNSPECIFIED`；
- `DATASET`；
- `IMPORT_METADATA`；
- `MANUAL_RUN`。

Dataset Query：

- `UNSPECIFIED`；
- `INPUT`；
- `IMPORT_METADATA`；
- `MANUAL_DATASET`。

Review：

- `SUGGESTED`；
- `MANUAL`；
- `RULE`。

### 2.3 迁移规则

- 新数据库直接创建v4；
- v1、v2、v3均可连续迁移到v4；
- v3有 `person_id` 的历史 Run Query 标记为 `DATASET`；
- 无 `person_id` 的历史 Query 标记为 `UNSPECIFIED`；
- 未复核 Review 标记为 `SUGGESTED`；
- 已复核 Review 标记为 `MANUAL`；
- 同一 Process/Query 有多个历史最终 HIT 时，选择 `candidate_rank` 最小者作为
  `is_primary_hit=1`，同时发出迁移告警；
- 任一步骤失败时，Schema版本、新列和新表全部回滚。

## 3. 历史人物关联服务

已实现：

```python
get_run_person_link_context(run_id, baseline_version)
update_run_query_person_links(
    run_id,
    baseline_version,
    changes,
    sync_dataset=False,
    note="",
)
```

支持：

- 从 Dataset `FULL_NAME` clue 提取目标姓名；
- 兼容正式结构 `full_name_query.full_name`；
- 兼容 `SOCIAL_LINK.social_link_query.url`；
- 无 Dataset 时尝试从受控归档 results.jsonl 读取 clues；
- 姓名去除首尾空格、合并连续空白并 `casefold()`；
- 唯一精确建议、同名多匹配和无匹配；
- 单条和批量保存；
- 清除关联；
- 可选同步 Dataset；
- `expected_person_id` 乐观锁；
- 整批事务回滚；
- 关联修改审计；
- 关联 Process 的 READY Report 标记为 `STALE`；
- Raw、Candidate、旧 Process 和结果文件保持不变。

姓名建议只填充页面选项，不会自动保存。

## 4. Web 工作区

新增入口：

```text
Run详情 → 管理人物关联
```

新增路由：

```text
GET  /runs/<run_id>/person-links
POST /runs/<run_id>/person-links
```

工作区支持：

- Baseline版本选择；
- Query/姓名/person_id搜索；
- 已关联、未关联、无效关联、唯一建议、同名多匹配筛选；
- 当前关联和来源展示；
- 唯一建议批量填充；
- 人工逐条选择；
- 清除关联；
- 同步 Dataset；
- 修改说明；
- 历史修改次数；
- Run处于 PENDING/RUNNING 时只读。

批量采用唯一建议只改变浏览器表单，必须再次点击“保存人物关联”才会写入数据库。

## 5. 真实数据验收

验收对象：

| 对象 | ID |
| --- | --- |
| Run | `run_2be5fe30b86f49bcba447296205911bb` |
| Baseline | `test20260728` |
| Report | `report_5a680512bbbc4048ae860ca42330b162` |

验收结果：

```text
Query总数：10
已关联：0
未关联：10
无效关联：0
唯一精确建议：10
```

10条 Query 均成功从正式 `full_name_query.full_name` 结构提取姓名，并各自匹配到
唯一 Baseline Person。Docker页面实际渲染10个“唯一精确建议”。

本阶段没有替用户自动保存，因此：

- 10条 Query 仍保持未关联；
- `run_query_person_history` 当前为0条；
- 原报告保持 `READY`；
- 只有用户保存关联后，审计才会写入，相关报告才会变为 `STALE`。

## 6. 数据安全验证

阶段0备份：

```text
data/backups/searchtool_v1_3_before_data_processing_v3_20260728_142706.db
SHA-256:
82972b59ccac0fdb784453be99b65f2aa6d3bacf3bfbda81fdb43c123265b3c7
```

迁移后数据库：

```text
data/searchtool_v1_3.db
SHA-256:
e5c1a59baf71b035208c71d87728cd403fa7e88825cfa6c15fa0fc56071ee583
```

数据库 `PRAGMA integrity_check` 返回 `ok`。

以下冻结文件校验值与阶段0完全一致：

| 文件 | SHA-256 |
| --- | --- |
| `data/results.jsonl` | `397847d23aa40aea783060ba1fcb6669eaa2b96a62769afe9123cf7061d489de` |
| 原报告 `report_model.json` | `85ff134bed9197337dce7ea7b8cd09550b0775648823db7b50899c543029cb42` |

## 7. 测试结果

专项覆盖：

- 新库直接创建v4；
- v1→v4；
- v2→v4；
- v3→v4；
- 重复初始化；
- 外键开启；
- 迁移失败回滚；
- 历史 Review来源迁移；
- 多个历史 HIT 的主要命中选择；
- 唯一姓名建议；
- 同名不自动选择；
- 无匹配；
- 单条/批量关联；
- Dataset同步；
- 清除关联；
- 乐观锁；
- 非法批次整批回滚；
- 审计记录；
- Report STALE；
- Raw不变；
- Web查看和保存。

最终全量回归：

```text
Ran 81 tests in 48.255s
OK (expected failures=5)
```

5项 expected failure 是阶段0为后续 `metrics-v3`、模块语义判空和字段矩阵保留的
契约测试，不属于阶段1失败。

## 8. Docker部署

已执行：

```bash
docker compose up -d --build
```

当前状态：

```text
truthy_search-searchtool-1
Up / healthy
127.0.0.1:5002->5002
```

访问入口：

```text
http://127.0.0.1:5002/runs/
run_2be5fe30b86f49bcba447296205911bb/person-links
?baseline_version=test20260728
```

## 9. 下一阶段边界

阶段2再实现：

- 使用已有数据生成新 Process；
- 明确保证外部 HTTP 调用次数为0；
- Query级候选人身份归类；
- 主要 HIT；
- 确认无 HIT；
- 批量 NOT_HIT；
- 身份归类后报告过期。

当前“保存人物关联”不会自动创建新 Process，也不会调用收费检索接口。

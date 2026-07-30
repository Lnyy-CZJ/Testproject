# searchTool v1.3 MVP 数据处理优化阶段5：Excel、集成验收与文档

> 验收日期：2026-07-28  
> 验收范围：Excel v3、历史 Run 无成本修复、metrics-v3、report-model-v3、静态 HTML、Docker 与操作文档  
> 验收原则：不修改真实业务数据库，不调用检索接口，不覆盖旧 Process 或报告

## v4 增补（2026-07-29）

本次增补将阶段 4 的 `field-processing-v5`、`metrics-v4` 和
`report-model-v4` 纳入同一条可导出链路。旧记录仍按下文的 v3 结构读取；新 v4
报告不会回写或重算任何历史 Process / Report。

新增的 v4 Excel 审计 Sheet 如下：

| Sheet | 快照来源 | 口径 |
| --- | --- | --- |
| `Core Metrics` | ReportModel v4 | 身份、资料质量、版本回归与参考线核心指标 |
| `Module Quality` | `baseline_quality_metrics`、`non_hit_data_return` | 五模块完整度、准确度、非命中资料返回率及分子分母 |
| `Field Comparison` | 主命中 Candidate 的 `field_scores_json` | Baseline 值、检索值、完整度、准确度、状态和原因 |
| `Field Returns` | `field_metrics` | 成功 Candidate 的字段返回率 |
| `Rule Snapshot` | ReportModel metadata | FieldSchema、处理、指标、报告和 Baseline 版本 |
| `Raw` | processed Export | 仅在超长 JSON 分块时生成 |

v4 验收约束：

- 只导出 `is_primary_hit=true` 候选人的 Baseline 字段比较，避免非命中资料被误解为准确度错误；
- `Task`、`Candidate` 字段不进入 `Module Quality`；
- 没有可评分字段时保留空值与 `NOT_APPLICABLE`，不填 0；
- Excel 只读取保存的 ReportModel / processed export，不重新调用检索接口；
- `report-model-v1/v2/v3` 保持既有 Sheet 结构，不能因为 v4 导出而改变。

### v4 历史副本无成本重处理结果

2026-07-29 使用 `data/searchtool_v1_3.db` 的 SQLite 临时副本进行验证；原始
数据库、Raw、Run、Process 和报告文件均未被写入。验证对象为
`run_2be5fe30b86f49bcba447296205911bb`：

| 校验项 | 结果 |
| --- | ---: |
| Query 数 | 10 |
| Candidate Detail 成功数 | 45 |
| 重处理前 / 后 Raw 数 | 86 / 86 |
| 新增 HTTP 请求 | 0 |
| 处理规则 | `field-processing-v5` |
| 指标规则 | `metrics-v4` |

该历史 Run 当前没有已关联 `person_id`，所以主命中 Baseline 资料质量保持
`NOT_APPLICABLE`；这属于数据关联状态，不是重处理或指标错误。字段返回、处理规则
路由和无成本约束均已验证。

## 1. 验收结论

阶段5功能已实现并通过代码、自动化和真实历史数据副本验收：

- report-model-v3 可导出静态 HTML 和 processed Excel；
- Excel 新增7个 v3 审计 Sheet，并保留 v1/v2 导出兼容；
- 历史 Run 可以先修正 Query 人物关联，再从已有 Raw 创建新 Process；
- 无成本重处理链路不会调用 `SearchToolClient` 或任何 HTTP 检索接口；
- metrics-v3 可区分“0”“空”“未知”和“不适用”，并提供原因码；
- 真实业务数据库未被验收脚本修改。

## 2. 本阶段实现

### 2.1 Excel v3

processed Excel 在 report-model-v3 下新增：

| Sheet | 用途 |
| --- | --- |
| `Report_Summary` | 执行、身份归类和质量摘要 |
| `Query_Person_Links` | Query 与 Baseline 人物关联及匹配状态 |
| `Identity_Classification` | 候选人身份归类、来源和主要命中 |
| `Field_Matrix` | 双侧字段开关、覆盖、规则和问题 |
| `Field_Metrics` | 字段返回率、完整度、准确率及原因 |
| `Module_Metrics` | 模块 data/empty/unknown 统计 |
| `Not_Ready_Reasons` | 未就绪原因独立明细 |

导出规则：

- 比率保持 Excel 数字并使用百分比格式；
- 布尔状态保持布尔值；
- 缺失、未接入和未就绪值保持空单元格，不补0；
- 完整 HTTP(S) URL 写为可点击链接；
- 超过单元格限制的 JSON 继续拆分到 `Raw数据`；
- `reason_codes` 在主表聚合，详细原因保留到原因 Sheet；
- v1/v2 ReportModel 继续按旧 Sheet 导出。

### 2.2 集成链路

验收链路如下：

```text
历史 Run
  → 修正 Query person_id
  → 选择 FieldSchema v2 与 Baseline
  → 无成本重处理（field-processing-v4）
  → Query 级身份归类
  → metrics-v3
  → report-model-v3
  → Web / 静态 HTML / processed Excel
```

## 3. 真实历史数据副本验收

验收使用真实数据库的 SQLite 只读备份，不直接操作
`data/searchtool_v1_3.db`。

### 3.1 数据范围

| 项目 | 结果 |
| --- | ---: |
| 历史 Run | `run_2be5fe30b86f49bcba447296205911bb` |
| Baseline | `test20260728` |
| Query 数 | 10 |
| 已关联 Query | 10 |
| Candidate Detail 成功数 | 45 |
| 验收前 Raw 记录数 | 86 |
| 验收后 Raw 记录数 | 86 |
| 新增 HTTP 请求 | 0 |

### 3.2 模块结果

| 模块 | data | empty | unknown | 总数 |
| --- | ---: | ---: | ---: | ---: |
| Insights | 2 | 43 | 0 | 45 |
| Photos | 0 | 45 | 0 | 45 |
| Profile | 45 | 0 | 0 | 45 |
| Social | 34 | 11 | 0 | 45 |
| Summary | 45 | 0 | 0 | 45 |

以上结果证明“没有返回业务数据”会计入 `empty`，不会错误计为
`unknown` 或无解释的“不适用”。

### 3.3 验收边界

为验证完整工作流，副本中临时将每条 Query 的 rank 1 成功候选人标记为 HIT，
其余成功候选人标记为 NOT_HIT。该动作仅验证身份归类、指标和导出机械链路，
不代表对真实候选人的业务判断，也没有回写真实数据库。

实际使用时，测试人员必须在“候选人身份归类”页面依据证据逐条确认，系统不会
自动把 rank 1 当作真实命中。

## 4. Excel 验收

- 工作簿包含全部7个 v3 Sheet；
- 所有必需 Sheet 均通过结构检查；
- 公式错误扫描未发现 `#REF!`、`#DIV/0!`、`#VALUE!`、`#NAME?` 或 `#N/A`；
- 16个必需 Sheet 均完成渲染；
- 宽表按每12列分块渲染，`Field_Matrix` 等 Sheet 的末尾列不再漏验；
- v3 Sheet 已检查表头、换行、百分比、布尔值、时间和原因明细；
- v1/v2 Excel 兼容用例通过。

验收产物位于系统临时目录，只用于本次检查，不作为业务报告交付，也不会写入
项目数据目录。

## 5. 自动化验收

执行命令：

```bash
python3 -m unittest discover -s tests -v
```

结果：共89项测试，全部通过。

覆盖范围：

- Schema v4 迁移和兼容；
- 历史人物关联与审计；
- 无 HTTP 重处理；
- Query 级身份归类；
- 字段对比矩阵与500字段基础性能；
- processing-v3 模块语义判空；
- metrics-v3 与 report-model-v3；
- 静态 HTML 与 Excel v1/v2/v3；
- Web 路由、报告下载与历史版本兼容；
- 采集核心和旧 JSONL 导出回归。

## 6. Docker 验收

使用现有 `Dockerfile` 与 `docker-compose.yml` 重建服务，并检查：

- `searchtool` 服务容器状态为 healthy；
- `http://127.0.0.1:5002/` 返回成功；
- 首页可访问；
- 容器继续只监听宿主机 `127.0.0.1:5002`；
- 容器默认关闭 processed Excel 自动生成，宿主机 artifact-tool 导出不受影响。

## 7. 用户操作说明

完整操作步骤已更新到项目 `README.md` 的“历史 Run 无成本修复、基准与报告”：

1. 导入 Baseline；
2. 在 Run 页面管理 Query 人物关联；
3. 检查字段对比矩阵；
4. 从已有 Raw 启动新 Process；
5. 完成候选人身份归类；
6. 查看 metrics-v3；
7. 生成报告并下载静态 HTML 或 processed Excel。

关键提醒：

- 人物关联不等于候选人命中；
- 身份归类不负责补字段；
- 字段原本为空时，系统自动统计为空，不要求人工“复核出一个值”；
- 重新处理不会重新检索，不产生接口费用；
- 新 Process 和新报告都是快照，旧记录不会覆盖。

## 8. 已知限制

- MVP 仍是本地单用户模式；
- Docker 默认不能生成 processed Excel，因为 artifact-tool 位于 Codex 宿主机运行时；
- 历史 Excel 如果缺少完整 Raw，只能按 `LEGACY_PARTIAL_RAW` 能力范围重处理；
- 成本、PDL 等正式接口路径未接入时保持空值和明确原因，不按0计算；
- 本次没有替用户修改真实历史 Run 的 `person_id` 或身份判断。

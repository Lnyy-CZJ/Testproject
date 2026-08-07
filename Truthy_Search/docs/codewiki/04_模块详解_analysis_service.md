# 04 · 模块详解：analysis_service.py（核心业务编排层）

文件：[analysis_service.py](../../analysis_service.py)（约 15216 行，项目最大模块）

## 1. 职责

v1.3 本地检索分析服务的**核心编排层**，覆盖从原始数据到评测报告的全链路：

1. **数据导入**：Query Dataset、Person Baseline、历史运行结果（v1.2 legacy / v1.3 JSONL / 规范化 Excel），SHA-256 去重、归档、单事务入库；
2. **Run 采集执行**：编排 `search_tool.process_one` 串行采集，持久化 Query/Candidate/Raw，支持单 Query 重试与中断恢复；
3. **字段处理**：按版本化、不可变的 FieldSchema，用受限路径 + 白名单转换器提取结构化字段；
4. **身份判定与复核**：Social Link/照片相似度自动规则（RULE）+ 人工覆写（MANUAL）；
5. **指标计算**：metrics-v1…v4 四代口径按 Process 的 `rule_version` 严格分派；
6. **报告生成**：report-model-v2…v6-compare 不可变快照、静态 HTML、processed Excel 导出。

仅依赖标准库 + openpyxl；全部状态经 `AnalysisStore` 持久化。

## 2. 异常与数据类（行 857–943）

| 类 | 用途 |
|---|---|
| `ImportValidationError` | 导入格式/业务校验错误，携带可预览 `errors` 列表 |
| `DuplicateImportError` | 相同 SHA-256 内容已导入，禁止静默复制 |
| `ActiveRunError` | 已有 PENDING/RUNNING 采集 Run，禁止并行启动 |
| `FieldSchemaValidationError` | 字段配置/路径/转换器输入不符合受限规则 |
| `ReviewValidationError` | 复核内容非法或页面版本过期 |
| `PersonLinkValidationError` | 人物关联输入非法或乐观锁冲突 |
| `ImportPreview` / `ImportResult` | 预览（checksum/valid_count/errors）与导入结果 |
| `ProcessResult` | process_id / candidate_count / error_count / status / warnings |
| `ReportResult` | report_id / model / html_file / excel_file |

## 3. 关键常量与版本号（行 36–213）

| 常量 | 值/说明 |
|---|---|
| `SUPPORTED_QUERY_STAGES` | `{"FULL_NAME", "FULL_NAME_SOCIAL"}` |
| `EVALUATION_THRESHOLD_FIELDS` | 5 项参考线字段及方向（minimum_ratio / maximum_number） |
| `EVALUATION_PHASES` | PHASE_1_BASELINE / PHASE_2_POST_OPTIMIZATION / PHASE_3_TARGETED_ITERATION / UNSPECIFIED |
| `RESULT_STATUSES` | HAS_CANDIDATES / NO_CANDIDATES / EXECUTION_FAILED |
| `TASK_FIELD_KEYS` | llm_cost / third_party_cost / total_cost / pdl_called / search_duration_ms |
| `FIELD_MODULES` | Task / Candidate / Insights / Photos / Profile / Social / Summary |
| `FIELD_PATH_PART_PATTERN` | 路径语法：点号 + `[数字]` / `[*]` |
| `FIELD_NORMALIZERS` | 白名单转换器（见 5.2） |
| `FIELD_COMPARE_MODES` | presence / exact / normalized_text / set / url_set / semantic_text_lite / manual |
| `FINAL_JUDGEMENTS` | HIT / NOT_HIT / SUSPECTED |
| `REVIEW_REASONS` | SOCIAL_MATCH / SOCIAL_CONFLICT / PHOTO_MATCH / PHOTO_BELOW_THRESHOLD / NO_STRONG_FIELD / MANUAL |
| 默认字段配置 | `field-schema-default-v2` / `field-schema-default-v3` |
| 处理规则 | `field-processing-v1` … `v5` |
| 指标规则 | `metrics-v2` / `metrics-v3` / `metrics-v4`（当前） |
| 报告模型 | `report-model-v2/v3/v4`、`report-model-v5`（metrics-v4 单 Run）、`report-model-v6-compare`（对比） |
| `REPORT_V5_CORE_METRIC_DEFINITIONS` | 7 项核心指标产品级定义，随报告快照冻结 |
| `NONMATCHED_SIMILARITY_EXCLUDED_FIELDS` | 非命中相似度排除 `profile_full_name`（避免 Query 回显误判） |

## 4. 模块级纯函数（行 215–2378）

### 4.1 字段目录（262–854）
- `DEFAULT_FIELD_DEFINITIONS`：v2 默认字段目录；
- `DEFAULT_FIELD_DEFINITIONS_V3`（704–854）：v3 目录，覆盖全部 `ui_sections.*` 原子字段；默认"可提取、可展示、可版本比较，但不自动进入身份/质量指标"。

### 4.2 字段提取与转换（945–1758）

| 函数 | 行号 | 说明 |
|---|---|---|
| `select_primary_hit_candidate` | 215–259 | 多条 RULE=HIT 中选唯一主命中：rank_score 降序 → candidate_rank 升序 → 主键升序（可复现） |
| `extract_source_path` | 945–1046 | 受限路径取值，支持 EMPTY/ERROR 缺失策略；拒绝表达式/过滤器/脚本 |
| `extract_profile_item` | 1049–1119 | PROFILE_ITEM 受控选择器：按 section + label 提取，NFKC + casefold 稳定匹配 |
| `_normalize_social_url` | 1122–1169 | URL 规范化：x.com→twitter.com、去 www、去 utm 跟踪参数、平台账号路径 casefold |
| `normalize_field_value` | 1215–1273 | **7 个白名单转换器分派**（见 5.2），不执行任何用户代码 |
| `_apply_module_empty_rules` | 1312–1353 | processing-v3 起的模块语义判空（status=empty/data 修正，忽略 count=0 容器） |
| `validate_field_definitions` | 1450–1758 | FieldSchema v3 全量校验；旧 v1/v2 定义内存补齐、绝不回写历史 |

### 4.3 比较与身份工具（1760–2377）

| 函数 | 行号 | 说明 |
|---|---|---|
| `file_checksum` | 1788–1799 | "文件角色 + 内容" SHA-256，支持多文件包去重 |
| `_semantic_text_lite_score` | 1985–2024 | 可解释轻量相似度：NFKC + 完全匹配 + 包含 + 词元/双字符 Jaccard |
| `_compare_field_values` | 2027–2088 | 按 compare_mode 产出建议完整度/准确率 |
| `_candidate_identity_rule` | 2111–2188 | **身份自动判定核心**（见 6.1） |
| `_field_comparison_scores_v3` | 2240–2377 | field-processing-v5 基准对比快照（完整度与覆盖度分离） |

## 5. AnalysisService 主类（行 2380–15216，129 个方法）

构造接收 `AnalysisStore` 与受控目录（`data_dir`、`import_dir`、`raw_dir`、`report_dir`，后三者必须位于 `data_dir` 内），持有 `threading.Lock` 做"检查活动 Run → 创建 Run"的串行保护。

### 5.1 Evaluation 与参考线方案（2433–2675）

`create_evaluation`（2613）、`update_evaluation_thresholds`（2433）、`create_threshold_profile`（2469）、`archive_threshold_profile`（2546）、`assign_evaluation_threshold_profile`（2562）。方案不可变版本；Evaluation 绑定时复制独立 `thresholds_json` 快照；更换方案只影响以后的新报告。

### 5.2 FieldSchema 字段配置域（2735–3611）

| 方法 | 行号 | 说明 |
|---|---|---|
| `ensure_default_field_schema` | 2735–2796 | 幂等创建 v2 默认配置；仅系统 v1 活跃时升级激活，用户配置永不覆盖 |
| `ensure_default_field_schema_v3` | 2798–2859 | 幂等创建 v3 字段目录快照 |
| `publish_field_schema` | 2861–2921 | 校验并发布不可变新版本（可 `activate`）；旧版本绝不更新 |
| `discover_field_candidates` | 2922–3155 | 从 Candidate Detail `ui_sections` 与 Baseline 发现未登记子字段建议（只读） |
| `build_field_comparison_matrix` | 3157–3550 | 字段 × 基准人物对比矩阵：覆盖、开关、样例、结构、冲突；未知 Baseline 字段也保留为行 |
| `validate_process_field_alignment` | 3551–3574 | 处理前字段对齐预检（ERROR 级问题可阻断重处理） |

**7 个白名单转换器**（`FIELD_NORMALIZERS`）：`identity`（= sanitize_raw）、`trim_text`（兼容 Unix 毫秒时间戳）、`number`、`percentage`（0–1 自动放大到 0–100，拒绝布尔/非有限值）、`social_url`、`string_list`（去重）、`profile_sections`。

### 5.3 Process 处理与无成本重处理域（3612–4530）

| 方法 | 行号 | 说明 |
|---|---|---|
| `process_run` | 3904–4313 | **核心处理入口**：校验 Run 已结束 → 按 Schema 路由处理规则（v3→field-processing-v5，否则 v4）→ 逐 Query/候选人提取字段 → 写 processed_queries/processed_candidates → 生成身份判定与字段得分写 reviews（RULE 终判立即 reviewed_at，否则 SUGGESTED）→ 每 Query 选主命中 `is_primary_hit` → 置 COMPLETED 并令同 Run 旧 READY 报告 STALE |
| `reprocess_existing_run` | 4315–4424 | **无成本重处理**：校验人物关联、提示未关联/缺 Raw 警告、先回填 Admin 字段再复用 `process_run`；不接收 HTTP Client，零接口费用 |
| `_backfill_admin_task_fields` | 4426–4530 | 从历史 Admin Raw（最后一条业务成功的 Debug/Cost）经 `search_tool.extract_admin_task_fields` 回填 5 个任务字段 |
| 字段处理内部件 | 3612–3903 | `_processing_source / _process_field_values / _process_query_fields / _process_candidate_fields`：提取→array_mode→normalizer→data_type→判空；错误记 FIELD_PROCESSING_ERROR / DUPLICATE_PROFILE_ITEM / DETAIL_FAILED / INVALID_DETAIL_DATA |
| `get_query_classification_context` / `save_query_classification` | 4532–4866 | Query 级身份归类页读写（乐观锁） |

### 5.4 身份判定规则与人工覆写

**自动规则**（`_candidate_identity_rule`，2111–2188），优先级固定：

```text
1. Social 同平台链接冲突      → NOT_HIT / SOCIAL_CONFLICT（最高优先，不可被覆盖）
2. Social URL 交集命中        → HIT / SOCIAL_MATCH
3. 照片相似度 ≥ 80           → HIT / PHOTO_MATCH
4. 无返回 URL 且无照片分数    → SUSPECTED / NO_STRONG_FIELD
5. 照片分数 < 80             → NOT_HIT / PHOTO_BELOW_THRESHOLD
6. 兜底                      → NOT_HIT / NO_STRONG_FIELD
```

URL 参与前经 `_normalize_social_url` 归一；格式非法视为不可比较、继续照片规则；证据以 JSON 写 `reviews.evidence`。Detail 失败或缺基准 → `PENDING_REVIEW`。

**人工覆写**：`get_review_context`（4909–5040）/ `save_review`（5042–5245）——judgement ∈ FINAL_JUDGEMENTS、reason ∈ REVIEW_REASONS、字段得分覆写校验、`expected_reviewed_at` 乐观锁、保存后令关联报告过期；复核后 `classification_source` 记 MANUAL。

### 5.5 指标计算域（5247–7718）

`calculate_process_metrics`（5247–5279）按 Process 固化的 `rule_version` 分派，未知规则直接拒绝：

| rule_version | 指标口径 | 实现 |
|---|---|---|
| field-processing-v1 | metrics-v1 | `_calculate_process_metrics_v1`（5281–5579） |
| field-processing-v2 | metrics-v2 | 5580–6284 |
| field-processing-v3/v4 | metrics-v3 | 6285–7405 |
| field-processing-v5 | **metrics-v4** | `_calculate_process_metrics_v4`（7406–7717） |

metrics-v4 在复用 v3 全部结果基础上新增四个分区：

- `identity_metrics`：含 has_candidates、retrieval_success、reason_counts；
- `baseline_quality_metrics`：主命中基准资料质量，五模块 × completeness/accuracy，Query 等权聚合，区分"有没有返回"与基准覆盖度；
- `non_hit_data_return`：非命中/疑似候选人资料返回率；
- `regression_metrics`：版本回归字段目录（选对比 Process 后由 build_report_model 填充）。

### 5.6 报告模型与快照域（7719–12132）

| 方法 | 行号 | 说明 |
|---|---|---|
| `compare_processes` | 7719–8228 | 同条件对比：要求 evaluation/baseline/rule_version 一致；按 (person_id, query_stage) 配对；输出持续命中/新增命中/退化未命中/持续未命中、新增线索、不可比三类 |
| `_build_report_v5_*` 构建器 | 8983–10678 | report-model-v5：候选人快照（含 Raw 引用 ID 不读内容）、Query 工作台、处理范围、模块返回概览（只统计业务原子字段）、核心指标下钻、首屏摘要、诊断 |
| `assess_evaluation_thresholds` | 10679–10797 | 参考线评估：5 项指标 PASS/FAIL/NOT_CONFIGURED/NOT_READY；总体建议 RECOMMEND_RELEASE / CONTINUE_OPTIMIZATION / NOT_READY |
| `_report_compare_*` 构建器 | 10798–11139 | 对比报告专用：成本快照缺失保持空值、工具调用统计等 |
| `build_report_model` | 11140–11725 | 构建 Web/静态 HTML/Excel 共用的不可变 ReportModel；版本选择：有对比→v6-compare；metrics-v4 单 Run→v5；metrics-v3→v3；更早→v2 |
| `create_report` | 11900–11992 | 写 `report_model.json` + `processed_export.jsonl`，登记 reports（READY） |
| `save_report_html` | 12015–12029 | 原子写入静态 HTML（tmp + replace） |
| `export_report_excel` | 12031–12097 | 子进程调 `result_to_excel.py processed`（超时 180s，失败降级为 warning） |
| `resolve_report_artifact` / `mark_report_failed` | 12099–12131 | 产物路径解析；HTML 渲染失败只标记 FAILED 不删模型 |

### 5.7 Run 采集执行域（12133–13526）

| 方法 | 行号 | 说明 |
|---|---|---|
| `create_execution_run` | 12133–12258 | 仅建库记录（不在 Web 线程调接口）；全局只允许一个 PENDING/RUNNING EXECUTION Run；按 Dataset 生成全部 PENDING Query；新执行禁止 UNSPECIFIED 阶段 |
| `execute_run` | 13301–13460 | 顺序执行：逐 Query 调 `search_tool.process_one`（回调接收进度/Raw/失败）→ `_persist_execution_success` 事务落库并追加 results.jsonl；`FlowError` 走 `_persist_execution_failure`；终态 COMPLETED / PARTIAL_FAILED / FAILED |
| `_persist_execution_success` | 12912–13053 | 单事务写 run_queries（含 5 成本字段 + public_fields）、candidates（三快照）、raw_records、failures；落库 JSON 再次经 `sanitize_raw` |
| `validate_query_retry` / `execute_query_retry` | 13142–13284 | 单 Query 重跑：仅允许失败/未执行 Query；在原 Run 内排队 |
| `mark_run_failed` | 13461–13484 | 后台异常收敛标记 |
| `recover_interrupted_runs` | 13486–13526 | 启动恢复：遗留 RUNNING 执行 Run → INTERRUPTED；其 RUNNING Query → FAILED/EXECUTION_FAILED |
| `update_run_evaluation_phase` | 12260–12299 | 补录评估阶段并令关联报告过期 |

### 5.8 人物关联域（12302–12872）

| 方法 | 说明 |
|---|---|
| `get_run_person_link_context`（12385–12569） | Run × Baseline 关联工作区：人物选项、逐 Query 建议（**仅规范化姓名精确匹配 NORMALIZED_NAME_EXACT，从不自动写入**）、各类计数、历史修改次数 |
| `update_run_query_person_links`（12570–12872） | 原子批量更新：校验 person_id 属于所选 Baseline、`expected_person_id` 乐观锁、可选 `sync_dataset`、写 `run_query_person_history` 审计、令受影响报告 STALE；任一项失败整批回滚 |

### 5.9 数据导入域（13527–15216）

| 方法 | 行号 | 说明 |
|---|---|---|
| `import_dataset_jsonl / import_dataset_excel` | 13648–13709 | Query Dataset（Excel 固定 `Queries` Sheet）；校验 input_id 唯一、阶段合法、FULL_NAME_SOCIAL 必须含 SOCIAL_LINK 线索 |
| `import_baseline_jsonl / import_baseline_excel` | 13855–13957 | 版本化基准（Excel 固定 `基准数据` Sheet）；checksum 与 baseline_version 双重去重 |
| `import_results_jsonl` | 14364–14420 | v1.2/v1.3 results + 可选 failures/metadata 三文件包 |
| `import_results_excel` | 14461–14731 | 规范化 Excel（`候选结果/Query对比/失败记录/Raw数据` 四 Sheet，Raw 分块重组） |
| `_normalize_result_records` | 14115–14287 | 旧版与 v1.3 统一中间结构；`raw_status` 标记 `COMPLETE_RAW` / `LEGACY_PARTIAL_RAW`（历史缺 Raw 不伪造） |
| `_insert_result_raw` | 14765–14862 | 把 v1.3 Raw 对象拆为可查询 raw_records（Create/GetTask 历史/List/Admin/Detail） |
| `_import_run` | 14864–15216 | 归档 + 规范化 JSONL 落盘（`data/raw/<evaluation>/<run>/`）+ 单事务写 runs/run_queries/candidates/raw_records/failures；多文件包 SHA-256 去重 |
| `update_baseline_available_fields` | 14032–14089 | 人工维护人物可评估字段（来源 MANUAL），令关联报告 STALE |

导入通用约束：格式校验 → SHA-256 查重 → 归档源文件到 `data/imports/<object_id>/` → 单事务入库 → 失败清理归档；Excel 以只读、缓存值模式打开（不执行宏/公式）。

## 6. 方法行号速查表

| 功能域 | 行号范围 |
|---|---|
| 初始化与目录约束 | 2383–2431 |
| Evaluation 与参考线方案 | 2433–2675 |
| 文件/JSONL 内部工具 | 2676–2733 |
| FieldSchema 管理 | 2735–3611 |
| 字段提取/处理内部件 | 3612–3903 |
| process_run / 无成本重处理 / Admin 回填 | 3904–4530 |
| 身份归类与人工复核 | 4532–5245 |
| metrics-v1…v4 | 5247–7718 |
| compare_processes | 7719–8330 |
| 报告基础件（v2–v4 口径） | 8331–8982 |
| report-model-v5 构建器 | 8983–10678 |
| 参考线评估 | 10679–10797 |
| 对比报告构建器 | 10798–11139 |
| build_report_model / create_report / HTML / Excel | 11140–12132 |
| Run 创建/执行/重试/恢复 | 12133–13526 |
| 人物关联 | 12302–12872 |
| Dataset/Baseline 导入 | 13527–14090 |
| Results 导入与 _import_run | 14091–15216 |

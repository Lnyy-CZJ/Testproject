# searchTool

`searchTool` 按输入顺序调用以下接口并提取候选人的完整 `ui_sections`：

```text
CreateIntentTask → GetTask（每 5 秒轮询）
→ ListTaskCandidates（一次获取当前全部候选人）→ GetTaskCandidateDetail
```

## 安装

建议使用 Python 3.10 或更高版本：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 配置

复制配置模板并填写真实值：

```bash
cp .env.example .env
```

必须配置 `SEARCH_API_URL`、`AUTH_TOKEN`、`DEVICE_ID`、`USER_ID`。固定 HTTP 请求头写入 `SEARCH_HTTP_HEADERS_JSON`，其值必须为 JSON 对象。

输入、输出与重复运行策略也可以在 `.env` 中配置：

```dotenv
SEARCH_INPUT_FILE=input/tasks_v01.jsonl
SEARCH_OUTPUT_DIR=output
ALLOW_DUPLICATE_RUN=false
```

- `SEARCH_INPUT_FILE` 支持 `tasks_v01.jsonl`、`tasks_v02.jsonl` 或其他合法文件名；
- 命令行 `--input/--output` 优先于 `.env`；
- `ALLOW_DUPLICATE_RUN=false` 时，同日同输入已有结果会在 HTTP 请求前停止；
- 只有设置为 `true` 才允许重复执行，并创建新的 run 文件，不覆盖旧结果。

## 准备输入

```bash
cp input/tasks.example.jsonl input/tasks_v01.jsonl
```

输入 JSONL 每行是一条搜索任务。`input_id` 和非空 `clues` 必填，`match_strategy` 默认 `UNION`，`additional_details` 默认空数组。复制后将 `SEARCH_INPUT_FILE` 改为对应路径。

## 运行

```bash
python search_tool.py
```

也可指定路径：

```bash
python search_tool.py --input input/tasks_v02.jsonl --output output --env-file .env
```

输出文件根据运行日期和输入文件名生成。例如在 2026-07-22 运行 `tasks_v01.jsonl`：

```text
output/20260722_tasks_v01_results.jsonl
output/20260722_tasks_v01_failures.jsonl
```

如果同日再次执行且 `ALLOW_DUPLICATE_RUN=true`，则递增生成：

```text
output/20260722_tasks_v01_run02_results.jsonl
output/20260722_tasks_v01_run02_failures.jsonl
output/20260722_tasks_v01_run03_results.jsonl
output/20260722_tasks_v01_run03_failures.jsonl
```

结果文件保存成功任务的候选人数，以及 List 实际返回的全部候选人的排名、`rank_score` 和完整 `ui_sections`；失败文件保存输入、接口、未知状态或轮询超时错误。

`results.jsonl` 每行结构：

```json
{
  "input_id": "case-001",
  "task_id": "task_xxx",
  "candidate_count_total": 8,
  "candidate_count_listed": 5,
  "results": [
    {
      "candidate_rank": 1,
      "candidate_id": "candidate_xxx",
      "rank_score": 0.91,
      "ui_sections": {}
    }
  ]
}
```

- `candidate_count_total` 来自成功状态的 `GetTask.data.candidate_count`；接口未返回时为 `null`；
- `candidate_count_listed` 是 `ListTaskCandidates.data.items` 实际返回数量；
- `rank_score` 来自对应 List item，缺失或不是数值时为 `null`；
- `ListTaskCandidates` 当前固定使用 `page_size=100`，并对实际返回的每名候选人依次请求 `GetTaskCandidateDetail`。

退出码：全部成功为 `0`，配置或输入文件无法启动为 `1`，批次中存在失败为 `2`。

## 测试

测试使用模拟响应，不会调用真实接口：

```bash
python -m unittest discover -s tests -v
```

## 第二阶段：将结果导出为 Excel

导出工具只读取 searchTool 已生成的 JSONL，以及可选 `.env` 中的 `EXCEL_*` 文件配置；它不会读取接口凭证、调用接口或修改原始结果。

### 单 Run 导出

推荐显式指定搜索结果文件：

```bash
python3 result_to_excel.py single \
  --results-file output/20260722_tasks_v01_results.jsonl \
  --failures-file output/20260722_tasks_v01_failures.jsonl \
  --run-label candidate \
  --system-version v1.2.0 \
  --evaluation-id eval_20260721 \
  --output output/results_comparison.xlsx
```

### baseline/candidate 对比

```bash
python3 result_to_excel.py compare \
  --baseline-results-file output/20260722_tasks_v01_results.jsonl \
  --baseline-failures-file output/20260722_tasks_v01_failures.jsonl \
  --baseline-version baseline_commit \
  --candidate-results-file output/20260722_tasks_v01_run02_results.jsonl \
  --candidate-failures-file output/20260722_tasks_v01_run02_failures.jsonl \
  --candidate-version candidate_commit \
  --evaluation-id eval_20260721 \
  --metadata input/query_metadata.jsonl \
  --output output/results_comparison.xlsx
```

原有 `--run-dir`、`--baseline-dir`、`--candidate-dir` 方式继续兼容目录中固定名为 `results.jsonl/failures.jsonl` 的历史结果。

### 通过 `.env` 导出

单 Run 配置：

```dotenv
EXCEL_RESULTS_FILE=output/20260722_tasks_v01_results.jsonl
EXCEL_FAILURES_FILE=output/20260722_tasks_v01_failures.jsonl
EXCEL_OUTPUT_FILE=output/20260722_tasks_v01_comparison.xlsx
EXCEL_RUN_LABEL=candidate
EXCEL_SYSTEM_VERSION=v1.2.0
EXCEL_EVALUATION_ID=eval_20260722
EXCEL_METADATA_FILE=
```

配置后可直接运行：

```bash
python3 result_to_excel.py single --env-file .env
```

双 Run 使用 `EXCEL_BASELINE_*` 和 `EXCEL_CANDIDATE_*` 配置。显式命令行参数始终优先于 `.env`。

`--metadata` 可省略。提供时使用 JSONL，一行一条 Query：

```json
{"query_id":"case-001","person_id":"person-001","query_type":"Q1","person_group":"C","difficulty":"medium","tags":["common_name","few_clues"]}
```

`query_id` 必须与当前所选输入 JSONL 的 `input_id` 一致。工作簿包含：

- `候选结果`：每名已返回候选人一行；表头按“字段整理表”的保留规则输出，`candidate_id` 紧跟 `task_id`；三类 links 按 `title：url` 逐行展示；
- `Query对比`：Query 状态、候选数、人工目标排名及 Hit@1/3/5、MRR@5 公式；
- `失败记录`：接口失败和导出输入异常；
- `说明`：左侧为运行版本、数据量和评测口径，右侧“字段整理表”说明候选结果表头、来源和格式；黄色列可维护是否保留、新表头及后续处理规则；
- `Raw数据`：仅在完整 JSON 超过 Excel 单元格限制时生成，可按引用和分块序号还原。

Excel 由 Codex 工作区捆绑的 spreadsheet runtime 生成。若自动定位失败，可通过 `SEARCHTOOL_NODE` 指定捆绑的 Node.js 可执行文件。

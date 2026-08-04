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

输入 JSONL 每行是一条搜索任务。`input_id` 和非空 `clues` 必填，`match_strategy` 默认 `UNION`，`additional_details` 默认空数组。v1.3 可显式填写 `query_stage=FULL_NAME/FULL_NAME_SOCIAL`；旧输入未填写时，包含 `SOCIAL_LINK` 线索会推断为 `FULL_NAME_SOCIAL`，否则为 `FULL_NAME`。复制后将 `SEARCH_INPUT_FILE` 改为对应路径。

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

结果文件保存候选人数、Query 状态，以及 List 实际返回的全部候选人的排名、`rank_score`、详情状态、完整业务响应和 `ui_sections`。单个候选人详情失败时仍保留该候选人并继续请求后续候选人；失败文件同时保存对应的候选级失败。Create/Get/List 等 Query 级失败仍只写失败文件并继续下一 Query。

`results.jsonl` v1.3 每行核心结构：

```json
{
  "result_schema_version": "1.3",
  "run_id": "run_xxx",
  "input_id": "case-001",
  "task_id": "task_xxx",
  "query_stage": "FULL_NAME",
  "query_status": "PARTIAL_DETAIL_FAILED",
  "candidate_count_total": 8,
  "candidate_count_listed": 8,
  "detail_success_count": 7,
  "detail_failure_count": 1,
  "task_fields": {
    "llm_cost": null,
    "total_cost": null,
    "pdl_called": null
  },
  "raw": {
    "create_intent_task": {},
    "get_task_history": [],
    "list_task_candidates": {}
  },
  "results": [
    {
      "candidate_rank": 1,
      "candidate_id": "candidate_xxx",
      "rank_score": 0.91,
      "detail_status": "SUCCESS",
      "detail_error": "",
      "list_item_raw": {},
      "detail_data_raw": {},
      "detail_response_raw": {},
      "ui_sections": {}
    },
    {
      "candidate_rank": 2,
      "candidate_id": "candidate_yyy",
      "rank_score": 0.72,
      "detail_status": "FAILED",
      "detail_error": "接口返回失败: code=7",
      "list_item_raw": {},
      "detail_data_raw": null,
      "detail_response_raw": {},
      "ui_sections": null
    }
  ]
}
```

- `query_status` 为 `SUCCESS`、`NO_CANDIDATE` 或 `PARTIAL_DETAIL_FAILED`；
- `candidate_count_total` 来自成功状态的 `GetTask.data.candidate_count`；接口未返回时为 `null`；
- `candidate_count_listed` 是 `ListTaskCandidates.data.items` 实际返回数量；
- `rank_score` 来自对应 List item，缺失或不是数值时为 `null`；
- `detail_status=FAILED` 的候选人不是正常空字段，`ui_sections` 固定为 `null`；
- `raw` 和候选人 Raw 保存脱敏后的业务请求与完整业务响应，不保存 Token、Cookie、HTTP Header、Device ID 或 User ID；
- `ListTaskCandidates` 当前固定使用 `page_size=100`，并对实际返回的每名候选人依次请求 `GetTaskCandidateDetail`。

`failures.jsonl` 每行包含 `failure_schema_version=1.3`、`run_id`、`input_id`、`task_id`、`candidate_id`、`scope`、`stage`、`error` 和失败时已经取得的脱敏 Raw。`scope` 为 `INPUT`、`QUERY` 或 `CANDIDATE`。

退出码：全部成功或无候选人为 `0`，配置或输入文件无法启动为 `1`，批次中存在 Query 失败或部分候选人详情失败为 `2`。

## 测试

测试使用模拟响应，不会调用真实接口：

```bash
python -m unittest discover -s tests -v
```

## v1.3 本地检索分析 Web

v1.3 MVP 数据处理优化已提供本地单用户 Web、原始数据中心、版本化字段处理、
历史 Run 无成本重处理、metrics-v4、report-model-v5 和报告导出。完成 `.env`
配置后启动：

```bash
python3 web_app.py --env-file .env
```

默认访问：

```text
http://127.0.0.1:5002
```

Web 当前支持：

- 创建 Evaluation；
- 导入 Query Dataset JSONL 或固定 `Queries` Sheet Excel；
- 选择 Dataset，后台顺序启动 `FULL_NAME` / `FULL_NAME_SOCIAL` 检索；
- 定时查看 Run 总数、当前 Query、接口阶段和失败信息；
- 导入 v1.2/v1.3 JSONL 或规范化 Excel 历史结果；
- 按50条分页、关键词、状态和检索条件查看 Query；
- 下钻全部候选人、排名、`rank_score`、详情状态和五个业务模块；
- 按需加载、搜索和复制 Raw JSON 字段路径/值；
- 发布不可变 FieldSchema 新版本并复制旧版本继续编辑；
- 使用指定字段配置处理或重新处理任意已结束 Run；
- 查看每名候选人的结构化字段、空值状态和字段级错误；
- 导入 JSONL/Excel 基准版本并关联 Process；
- 修正历史 Run 的 Query 人物关联，不重新请求检索接口；
- 查看 Baseline 与 Candidate 两侧字段开关、覆盖情况和对比规则；
- 按 Social Link 与照片相似度规则自动判定身份；必要时可按 Query 人工覆写；
- 查看单 Run 四项核心指标与 baseline/candidate 配对结果；
- 生成不可变单 Run/对比报告，并下钻到 Query、Candidate 和 Raw；
- 下载独立静态 HTML 和 processed Excel；
- 下载标准化 `results.jsonl` 和 `failures.jsonl`。

Web 默认只监听 `127.0.0.1`，没有登录和权限系统，不应暴露到公共网络。页面不会展示 `.env`、Token、Cookie、完整 Header、Device ID 或 User ID。同一时间只允许一个执行 Run；应用重启后，遗留的 `RUNNING` Run 会标记为 `INTERRUPTED`，已完成 Query 和 Raw 保留。

### Docker 本地运行

Docker Compose 只把端口发布到宿主机 `127.0.0.1:5002`，并将 `.env` 只读挂载
到容器。数据库、Raw、导入归档和报告继续保存在宿主机的 `data/`、`output/`，
重建容器不会删除。

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f searchtool
```

访问：

```text
http://127.0.0.1:5002
```

停止服务：

```bash
docker compose down
```

不要使用 `docker compose down -v` 清理业务数据。当前 processed Excel 依赖 Codex
宿主机的 `@oai/artifact-tool`，Docker 服务默认设置
`SEARCH_REPORT_EXCEL_ENABLED=false`；Web 报告和静态 HTML 不受影响，宿主机直接
运行时仍可开启 Excel。

可选 Web 配置：

```dotenv
SEARCH_WEB_HOST=127.0.0.1
SEARCH_WEB_PORT=5002
SEARCH_WEB_BASE_PATH=
PLATFORM_HOME_URL=
SEARCH_DISPLAY_TIMEZONE=Asia/Shanghai
SEARCH_WEB_MAX_UPLOAD_BYTES=52428800
SEARCH_WEB_SECRET_KEY=replace-with-a-local-random-value
SEARCH_DATA_DIR=data
SEARCH_DB_FILE=data/searchtool_v1_3.db
SEARCH_REPORT_DIR=output/reports
SEARCH_REPORT_EXCEL_ENABLED=true
```

`SEARCH_DISPLAY_TIMEZONE` 只控制 Web、静态 HTML 和 processed Excel 的可见
时间，默认使用 `Asia/Shanghai`，统一显示为 `YYYY-MM-DD HH:mm:ss`。SQLite、
JSONL、Raw、API 及复核并发控制仍保留原始 UTC ISO 8601 值；非法时区会回退到
`Asia/Shanghai`。

接口凭证只在真正启动执行 Run 时读取，因此即使暂未配置真实接口，也可以先启动 Web 查看和导入历史数据。

### 独立模式与测试平台模式

独立 Compose 保持根路径运行，对宿主机只开放 `127.0.0.1:5002`：

```dotenv
SEARCH_WEB_BASE_PATH=
PLATFORM_HOME_URL=
```

测试平台 Compose 以第三个独立服务启动本项目，并固定使用：

```dotenv
SEARCH_WEB_BASE_PATH=/truthy-search
PLATFORM_HOME_URL=/
```

平台入口为 `/truthy-search/`，健康接口为 `/truthy-search/health`；独立模式对应 `/` 和 `/health`。页面、静态资源、表单跳转、Raw API 与下载链接都会保留当前模式的基础路径。

两个模式挂载同一个 `data/searchtool_v1_3.db`，因此必须互斥运行。切换前先确认 `runs` 表没有 `RUNNING` 记录，再停止当前容器；不得让独立 `searchtool` 与平台 `truthy-search` 同时访问该 SQLite。出现异常时先检查：

```bash
docker compose ps
docker compose logs --tail=100 searchtool
curl -i http://127.0.0.1:5002/health
```

### 字段配置与重新处理

首次启动 Web 会幂等创建“默认字段配置”，覆盖当前确认的 Task、Candidate、Insights、Photos、Profile、Social 和 Summary 字段。字段配置入口位于顶部“字段配置”。

配置规则：

- 只支持点路径、固定数组索引和数组通配，例如 `ui_sections.summary.data.avatar_url`、`items[0].description` 和 `profiles[*].url`；
- 支持 `identity`、`trim_text`、`number`、`percentage`、`social_url`、`string_list` 和 `profile_sections` 内置转换器；
- 不支持 `eval`、函数、条件过滤或用户脚本；
- 每次发布生成新的 `schema_version`，旧版本不修改；
- 每次处理生成新的 `process_id`，旧处理结果和 Raw 不覆盖；
- 路径缺失、类型错误或转换失败会记录为字段级错误，其他字段和候选人继续处理；
- Candidate Detail 失败只记录 `DETAIL_FAILED`，不会被当作正常空字段。

在 Run 详情页选择字段配置并点击“启动处理”，完成后可查看处理记录；Candidate 页面默认展示最近一次处理结果，也可以从历史 Process 进入指定快照。

### 历史 Run 无成本修复、基准与报告

1. 在顶部“参考线”提前创建可复用的版本化参考线方案；
2. 创建 Evaluation 时选择方案，或暂不选择；
3. 在顶部“基准数据”导入版本化 JSONL 或 Excel；
4. 对已有 Run，在 Run 页面进入“管理人物关联”，选择 Baseline 后检查并保存每条
   Query 的 `person_id`；同名或没有唯一建议时必须人工选择；
5. 从 Run 页面打开“字段对比矩阵”，确认 Baseline 和 Candidate 两侧需要参与
   对比的字段开关与规则；
6. 回到 Run 页面选择字段配置和基准版本启动处理；该操作只读取已保存的 Raw，
   创建新 Process，不调用 CreateIntentTask 或任何检索接口；
7. Process 会按 Social Link 与照片相似度自动判定主要 HIT、NOT_HIT 或
   SUSPECTED；只有规则无法判定或需要纠正规则结论时，才进入“查看 / 覆写规则”进行
   人工处理。这里不会补写接口中原本不存在的字段；
8. 回到 Process 查看 metrics-v4 的身份结果、五模块基准资料质量、非命中资料返回率、正式值和不适用原因；
9. 点击“生成报告快照”，生成 Web、静态 HTML 和 processed Excel。

每次重新处理都会生成新的 `process_id`，旧 Process、人工判断和报告快照不会覆盖。
人物关联保存和重新处理都不会启动采集，因此不会产生新的接口费用。开始前应先
确认 Run 已结束、Baseline 版本正确；如果 Query 无法唯一匹配人物，应保留未关联，
不要仅凭姓名相似自动绑定。

参考线方案采用不可变版本：需要调整时从旧方案“复制为新版本”，不能覆盖原版本。
归档方案仍可供历史 Evaluation 和报告查看，但不能再用于新建或更换。Evaluation
选择方案时会复制独立的 `thresholds_json` 快照；更换方案只影响以后生成的新报告，
既有报告不会重算或标记过期。未选择方案不影响采集和处理，报告建议会显示
“暂不能判断”。历史 Evaluation 的手工参考线继续显示为“历史自定义参考线”。

报告保存生成时的指标、字段配置、基准和规则版本。复核或重新处理变化后，旧报告标记为 `STALE`，原文件不覆盖。未完成复核时只展示预览值；成本/PDL 缺失时显示“未接入”，不会按0计算。

新生成的 metrics-v4 Process 报告使用 `report-model-v5`：Web 首屏展示候选人返回率、目标人物命中率、有候选人条件下命中率、命中信息准确度、命中资料完整度，以及非命中资料完整度和非命中候选人资料相似度（排除 `profile_full_name`）。Processing Scope 后的“五大资料模块返回概览”按全部候选人、全部 HIT、非命中/疑似分别展示模块有数据率与业务原子字段完整度；状态字段、容器 JSON 和 Candidate Detail 失败不进入计算分母。下方 Query 工作台默认展示5条、每次加载10条，但搜索和筛选覆盖报告快照中的全部 Query 与候选人。单次报告展示本次候选人与基准字段比较；对比报告额外显示同条件人物配对与变化分类。未选择参考线、未接入成本或没有建议时，对应空章节不会出现。旧 `report-model-v1/v2/v3/v4` 快照继续按历史版式打开。

下载的静态 HTML 不依赖网络或 JavaScript：它直接预渲染核心指标、全部 Query 与全部候选人摘要；模块、字段比较和 Evidence 默认折叠。静态 HTML 只保留 Candidate、Process 与 Raw 的引用信息，绝不嵌入 Candidate Detail 完整 Raw 响应。

首页会展示最近10份报告，顶部“报告”入口可进入全局报告中心。报告中心支持按
Evaluation、系统版本、`SINGLE`/`COMPARE` 类型和 `READY`/`STALE`/`FAILED`
状态筛选，每页显示50份。报告列表只读取已保存的快照摘要；只有静态 HTML 或
Excel 文件真实存在时才提供下载链接，`FAILED` 报告不提供产物下载。

`SEARCH_REPORT_EXCEL_ENABLED=false` 可关闭 Web 自动 Excel 导出。Node/artifact-tool 不可用时，Web 报告和静态 HTML 仍会成功生成。

processed Excel 与 Web/静态 HTML 共用已保存的 ReportModel 快照，不在导出时重新计算
指标。工作簿固定包含：

- `说明`：评估阶段、系统版本、字段/指标规则、空值规则和风险；
- `核心指标`：结果状态、质量、成本、耗时、PDL、Confidence、参考线和建议；
- `Query明细`：`result_status`、候选人数、成本、耗时和 PDL；
- `候选结果`：Confidence、复核结果和当前 FieldSchema 的结构化字段；
- `同条件对比`：人物级同条件前后变化及不可比原因；
- `新增线索`：没有上一阶段同条件基线的实际结果；
- `模块字段统计`：模块/字段在全部、命中和非命中候选人中的统计；
- `失败记录`：执行、Candidate Detail 和字段结构错误；
- `人工复核`：可回查的候选人及字段得分快照；
- `Report_Summary`：report-model-v3/v4/v5 的执行、身份归类和质量摘要；
- `Query_Person_Links`：Query 与 Baseline 人物关联、来源和匹配状态；
- `Identity_Classification`：逐候选人的身份归类、来源和主要命中状态；
- `Field_Matrix`：Baseline/Candidate 字段开关、覆盖、样例、规则和问题；
- `Field_Metrics`：字段级返回率、完整度、准确率、值域和不适用原因；
- `Module_Metrics`：模块级 data/empty/unknown 计数和返回率；
- `Not_Ready_Reasons`：指标、质量与报告中未就绪原因的独立明细；
- `Raw数据`：仅在完整 JSON 超过 Excel 单元格限制时生成。

当报告为 `report-model-v4` 或 `report-model-v5` 时，工作簿还会增加以下固定英文 Sheet，供后续测试平台按稳定名称读取：

- `Core Metrics`：身份、基准资料质量、版本回归和参考线核心指标；
- `Module Quality`：五个资料模块的完整度、准确度及非命中资料返回率；
- `Field Comparison`：每个主命中候选人的 Baseline 值、检索值、评分和原因；
- `Field Returns`：所有成功 Candidate 的字段返回率；
- `Rule Snapshot`：FieldSchema、处理规则、指标规则、报告规则和 Baseline 快照；
- `Raw`：存在超长 JSON 时的分块引用。

缺失、未接入和未就绪值保持空单元格；不会补 `0`、字符串 `"null"` 或伪造
`False`。真实数字和布尔值仍保持 Excel 数字/布尔类型；比率保持数值并使用百分比
格式，完整 HTTP(S) URL 写为可点击链接。旧 report-model-v1/v2 仍按原有 Sheet
导出，不强行补造 v3 数据。

### SQLite 与内部导入接口

如需在脚本中直接使用阶段2存储与导入服务：

```python
from pathlib import Path

from analysis_service import AnalysisService
from analysis_store import AnalysisStore

store = AnalysisStore(Path("data/searchtool_v1_3.db"))
store.initialize()
store.create_evaluation("eval-001", "检索评测")
service = AnalysisService(store, Path("data"))
```

当前支持：

- Query Dataset JSONL 和固定 `Queries` Sheet Excel；
- v1.2/v1.3 `results.jsonl`，以及可选 failures、Query 元数据；
- 项目生成的规范化结果 Excel；
- 基准 JSONL 和固定 `基准数据` Sheet Excel。

导入前会完成格式校验和错误汇总；导入成功后原文件归档到 `data/imports`，规范化结果写入 `data/raw`。相同内容通过 SHA-256 明确拒绝，不覆盖旧 Run。Excel 使用只读、缓存值模式，不执行宏、外部链接或公式。

## v1.3 集成验收

阶段7提供固定脱敏夹具和自动化验收，覆盖2名人物、两种 Query 条件、
baseline/candidate 两个版本、三种人工判定、Candidate Detail 失败、Query
失败、未知新增字段、空成本、报告和 Excel。

运行全量自动测试：

```bash
python3 -m unittest discover -s tests -v
```

只运行阶段7固定闭环、100人合成容量和备份恢复测试：

```bash
python3 -m unittest discover -s tests -p 'test_analysis*.py' -k stage7 -v
python3 -m unittest discover -s tests -p 'test_analysis_store.py' -k backup -v
```

固定夹具位于 `tests/fixtures/v1_3_e2e`。容量测试会生成100人 ×
`FULL_NAME/FULL_NAME_SOCIAL` × baseline/candidate，共400条 Query 和400名
候选人，只写入测试临时目录，不调用真实接口。

自动测试只能证明代码和脱敏夹具行为。小批真实接口与100人真实数据必须在受控
测试环境另行执行，并记录 Evaluation、Run、耗时、磁盘增量和失败明细。验收状态
及现场检查表见
`docs/searchTool_v1.3_MVP_阶段7_集成验收记录.md`。数据处理优化阶段5的真实历史
Run 副本、无成本重处理、Excel v3 和 Docker 验收见
`docs/searchTool_v1.3_MVP_数据处理优化阶段5_Excel集成验收记录.md`。

### 备份与恢复

备份范围必须同时包含：

- `SEARCH_DB_FILE` 对应的 SQLite 数据库；
- `SEARCH_IMPORT_DIR` 和 `SEARCH_RAW_DIR`；
- `SEARCH_REPORT_DIR`；
- 当前 `.env` 的配置说明，但不要把含凭证的 `.env` 放入版本库或普通共享包。

推荐先停止 Web 和 CLI，确认没有执行中的 Run，再使用 SQLite backup API 创建一致
性数据库快照。下面示例默认使用项目配置路径，并拒绝覆盖已有备份目录：

```bash
python3 - <<'PY'
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3

project = Path.cwd()
backup = project.parent / (
    "searchtool_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S")
)
if backup.exists():
    raise FileExistsError(f"备份目录已存在: {backup}")
(backup / "data").mkdir(parents=True)

source_db = project / "data" / "searchtool_v1_3.db"
target_db = backup / "data" / "searchtool_v1_3.db"
with sqlite3.connect(f"file:{source_db}?mode=ro", uri=True) as source:
    with sqlite3.connect(target_db) as target:
        source.backup(target)

for source, target in (
    (project / "data" / "imports", backup / "data" / "imports"),
    (project / "data" / "raw", backup / "data" / "raw"),
    (project / "output" / "reports", backup / "reports"),
):
    if source.exists():
        shutil.copytree(source, target)

print(backup)
PY
```

恢复时不要直接覆盖正在使用的数据目录。先把备份复制到新的恢复目录，创建单独的
`.env.restore`，配置：

```dotenv
SEARCH_DATA_DIR=../searchtool_restore/data
SEARCH_DB_FILE=../searchtool_restore/data/searchtool_v1_3.db
SEARCH_IMPORT_DIR=../searchtool_restore/data/imports
SEARCH_RAW_DIR=../searchtool_restore/data/raw
SEARCH_REPORT_DIR=../searchtool_restore/reports
SEARCH_WEB_HOST=127.0.0.1
SEARCH_WEB_PORT=5002
```

然后运行：

```bash
python3 web_app.py --env-file .env.restore
```

确认首页的 Evaluation/Run 数量、随机 Candidate Raw、Process、Review 和报告文件
均可访问后，才将恢复目录切换为正式目录。`.env.restore` 同样不得提交。

### 数据迁移

- 同一 v1.3 Schema v1 环境迁移：使用上述完整备份恢复，不要只复制数据库或只
  复制 Raw。
- v1.2/旧 JSONL 或规范化 Excel：在 Web“导入数据”页重新导入，让系统生成统一
  Run/Query/Candidate 和 `LEGACY_PARTIAL_RAW` 标记，不要手工写数据库。
- 字段规则变更：发布新的 FieldSchema 后重新处理旧 Raw；旧 Process、Review 和
  Report 不覆盖。
- 数据库 `schema_info.schema_version` 不是1时，当前版本会拒绝启动。升级到未来
  Schema 时必须先完整备份并使用对应迁移程序，禁止手工修改版本号。

### 常见排障

- `5002` 被占用：运行 `lsof -nP -iTCP:5002 -sTCP:LISTEN` 找到占用程序，停止该
  程序或同时修改 `SEARCH_WEB_PORT` 和访问地址。
- `.env` 已填写但提示缺少配置：确认命令带
  `--env-file /实际路径/.env`，并检查变量名是 `SEARCH_API_URL`、`AUTH_TOKEN`、
  `DEVICE_ID`、`USER_ID`。
- `SEARCH_HTTP_HEADERS_JSON` 报错：值必须是一个完整 JSON 对象，键和值均使用
  双引号，不能保留尾逗号。
- Dataset 下拉框为空：先在“导入数据”页选择“Query Dataset”导入；历史结果导入
  只会创建 Run，不会创建可执行 Dataset。
- 报告显示 `STALE`：复核或重新处理发生在报告快照之后；旧报告不会改写，需要
  重新生成报告。
- Excel 未生成：检查 `SEARCH_REPORT_EXCEL_ENABLED=true` 以及 Node/artifact-tool
  运行环境；Web 报告和静态 HTML 不受影响。
- 相同文件无法再次导入：这是 SHA-256 防覆盖策略；如数据确有变化，应生成内容
  不同的新文件并作为新 Run 导入。

### 已知限制

- MVP 是 localhost 单用户系统，没有登录、角色和权限，不允许暴露到公共网络。
- 同一时刻只执行一个采集 Run；进程重启后当前 Query 不自动续跑，但已落库数据
  保留并标记 `INTERRUPTED`。
- 首版只支持 `FULL_NAME` 和 `FULL_NAME_SOCIAL`，照片输入及 PUT 流程未实现。
- List Candidates 的分页字段只是预留，当前按一次响应取得的全部候选人处理。
- `llm_cost`、`third_party_cost`、`total_cost`、`pdl_called`、
  `search_duration_ms` 正式路径未接入时保持空值；成本单位和
  `total_cost` 包含关系仍待后端确认；
  `provider_summary`、顶层 `evidence`、`social_accounts` 暂只保留在 Raw。
- 历史 Excel 缺少完整 Raw 时无法还原接口响应，系统会标记
  `LEGACY_PARTIAL_RAW`，不会伪造数据。
- 静态 HTML 可包含人物级案例，应视为受控测试数据文件单独保管。

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

# searchTool v1.2 开发设计与开发计划

## 1. 文档目的

本文是《searchTool 结果处理与常态化对比 PRD v1.2》的实现设计，用于指导第二阶段开发。

第二阶段增加一个独立的离线导出工具，将 searchTool 已生成的 `results.jsonl` 和 `failures.jsonl` 转换为 Excel。工具同时支持：

1. 单 Run 结果导出；
2. baseline/candidate 双 Run 对比；
3. 可选 Query 元数据 JSONL 对齐；
4. 人工复核字段直接填写在 Excel；
5. 超长 JSON 拆分到 Raw Sheet，并在主表保留引用。

本阶段不修改现有 HTTP 请求流程，不重新请求接口，也不自动判断候选人身份、照片真实性或 AI 总结准确性。

## 2. 成功标准

- 单 Run 与双 Run 使用同一套字段读取和扁平化逻辑；
- Excel 中每个候选人对应一行，候选排名与原始 `results[]` 顺序一致；
- baseline/candidate 使用 `input_id/query_id` 正确对齐；
- insights、photos、profile、social、summary 指定字段全部导出；
- Profile 动态字段使用两个 Run 的字段并集生成统一表头；
- Query 元数据可以按 `query_id` 合并到候选结果和 Query 对比表；
- 人工复核列为空白且可直接编辑；
- 超过 Excel 单元格限制的数据能在 Raw Sheet 中完整还原；
- 原始 JSONL 不被修改；
- 生成的 `.xlsx` 可被 Microsoft Excel 正常打开。

## 3. 已确认的产品决策

| 项目 | 已确认方案 |
| --- | --- |
| 运行模式 | 单 Run 和 baseline/candidate 双 Run 都支持 |
| 代码复用 | 两种模式共用同一套 Run 读取、字段提取和行生成函数 |
| Query 元数据 | 首版采用 JSONL，通过 `query_id = tasks.jsonl.input_id` 对齐 |
| 人工复核 | 直接填写在导出的 Excel 中 |
| 超长 JSON | 允许拆分到额外的 `Raw数据` Sheet，主表写入引用 |
| 数据处理方式 | 本地、离线、同步，不发起 HTTP 请求 |

## 4. 影响范围与文件计划

开发阶段只做以下必要改动：

| 文件 | 操作 | 原因 |
| --- | --- | --- |
| `result_to_excel.py` | 新增 | 独立处理 JSONL 和生成 Excel，不影响搜索链路 |
| `requirements.txt` | 修改 | 增加 `openpyxl` 依赖 |
| `README.md` | 修改 | 增加单 Run、双 Run 和 Query 元数据使用说明 |
| `tests/test_result_to_excel.py` | 新增 | 隔离验证导出逻辑，不混入现有 HTTP 流程测试 |

不修改：

- `search_tool.py`；
- `.env` 和接口配置；
- 第一阶段请求流程；
- 原始 `results.jsonl`、`failures.jsonl`；
- 已确认的 PRD 和测试方案。

## 5. 整体设计

```text
单 Run：
  current/results.jsonl + current/failures.jsonl
                     ↓
               load_run()

双 Run：
  baseline/results.jsonl + baseline/failures.jsonl
  candidate/results.jsonl + candidate/failures.jsonl
                     ↓
               load_run() × 2

可选 query_metadata.jsonl
                     ↓
              load_metadata()
                     ↓
        collect_profile_columns()
                     ↓
     flatten_candidate() / build_query_rows()
                     ↓
              write_workbook()
                     ↓
          results_comparison.xlsx
```

设计原则：

- `load_run()` 不区分单 Run 和双 Run，只接收 Run 的目录、标签和版本；
- 双 Run 只是调用两次 `load_run()`，再将结果一起交给同一导出流程；
- 字段路径只在 `flatten_candidate()` 中定义一次；
- Excel 写入与数据提取分离，便于测试字段正确性；
- 不引入数据库、异步框架或 Web 页面。

## 6. 命令行设计

### 6.1 单 Run 模式

```bash
python3 result_to_excel.py single \
  --run-dir output/eval_current \
  --run-label current \
  --system-version v1.2.0 \
  --evaluation-id eval_20260721 \
  --metadata input/query_metadata.jsonl \
  --output output/results_comparison.xlsx
```

`--metadata` 可省略。省略后仍能导出 `query_id`、`task_id` 和候选结果，但 Person、Query 类型和分组字段为空。

### 6.2 双 Run 模式

```bash
python3 result_to_excel.py compare \
  --baseline-dir output/eval_baseline_20260721 \
  --baseline-version baseline_commit \
  --candidate-dir output/eval_candidate_20260721 \
  --candidate-version candidate_commit \
  --evaluation-id eval_20260721 \
  --metadata input/query_metadata.jsonl \
  --output output/results_comparison.xlsx
```

双 Run 标签固定为：

- `baseline`；
- `candidate`。

### 6.3 参数校验

- `single` 模式必须提供 `--run-dir`、`--run-label`、`--system-version`；
- `compare` 模式必须同时提供 baseline 和 candidate 目录与版本；
- `--evaluation-id` 必填；
- `--output` 必须以 `.xlsx` 结尾；
- Run 目录必须存在且包含 `results.jsonl`；
- `failures.jsonl` 和 `--metadata` 可以不存在，但必须输出明确提示；
- 输入目录和输出文件不能指向同一文件。

## 7. Query 元数据设计

文件格式为 JSONL，一行一条 Query：

```json
{"query_id":"query-001","person_id":"person-001","query_type":"Q1","person_group":"C","difficulty":"medium","tags":["common_name","few_clues"]}
```

字段规则：

| 字段 | 是否必填 | 规则 |
| --- | --- | --- |
| `query_id` | 是 | 唯一；必须与 `tasks.jsonl.input_id` 一致 |
| `person_id` | 否 | 金标人物稳定 ID |
| `query_type` | 否 | Q1–Q15 |
| `person_group` | 否 | A/B/C/D |
| `difficulty` | 否 | low/medium/high |
| `tags` | 否 | 字符串数组；Excel 中换行连接 |

处理规则：

- 重复 `query_id` 视为元数据错误并停止导出；
- `tags` 不是数组时记录明确错误；
- 元数据存在但结果中没有该 Query 时，仍在 `Query对比` Sheet 生成一行，状态标记为 `MISSING`；
- 结果中存在但元数据缺失的 Query 仍正常导出，元数据列留空；
- metadata 文件仅用于对齐和分组，不改变原始候选结果。

## 8. 内部数据模型

实现采用简单 `dataclass`，不引入额外数据校验框架。

### 8.1 `RunSpec`

```python
@dataclass(frozen=True)
class RunSpec:
    run_dir: Path
    run_label: str
    system_version: str
```

表示一个需要导出的 Run。

### 8.2 `RunData`

```python
@dataclass
class RunData:
    spec: RunSpec
    results_by_query: dict[str, dict]
    failures_by_query: dict[str, list[dict]]
    input_errors: list[dict]
```

`results_by_query` 使用 `input_id/query_id` 建索引。同一 Run 出现重复 `input_id` 时记录输入错误，避免静默覆盖。

### 8.3 `QueryMetadata`

```python
@dataclass(frozen=True)
class QueryMetadata:
    query_id: str
    person_id: str = ""
    query_type: str = ""
    person_group: str = ""
    difficulty: str = ""
    tags: tuple[str, ...] = ()
```

### 8.4 候选人扁平行

候选结果内部使用普通 `dict[str, object]`，键名直接对应 Excel 列名。动态 Profile 列无需修改固定 dataclass。

## 9. 核心函数设计

所有新增函数必须包含功能说明、参数、返回值和异常策略的 docstring；仅对非直观逻辑增加行内注释。

### 9.1 输入读取

```python
def read_jsonl(path: Path) -> tuple[list[dict], list[dict]]:
    """读取 JSONL，返回合法记录和包含文件/行号的解析错误。"""
```

- 空行忽略；
- 单行坏 JSON 不终止其他行处理；
- 错误中只记录文件、行号和解析原因，不记录敏感完整内容。

```python
def load_run(spec: RunSpec) -> RunData:
    """加载一个 Run 的 results/failures，并按 query_id 建索引。"""
```

```python
def load_metadata(path: Path | None) -> dict[str, QueryMetadata]:
    """加载可选 Query 元数据并校验 query_id 唯一性。"""
```

### 9.2 Profile 字段收集

```python
def collect_profile_columns(runs: list[RunData]) -> list[str]:
    """扫描所有 Run 的 Profile section/label，返回稳定有序的字段并集。"""
```

列名格式：

```text
profile.<section.title>.<item.label>
```

排序规则：

1. 按首次出现的 Run 顺序；
2. 同一 Run 内按 Query 和候选人原始顺序；
3. section 与 item 保持接口返回顺序；
4. 已收集列不重复添加。

这样既保证 baseline/candidate 表头一致，也避免字母排序改变业务展示顺序。

### 9.3 候选字段扁平化

```python
def flatten_candidate(
    run: RunData,
    query_id: str,
    task_id: str,
    candidate: dict,
    candidate_rank: int,
    metadata: QueryMetadata | None,
) -> dict[str, object]:
    """将单个候选人的 ui_sections 转换为一行 Excel 数据。"""
```

该函数是单 Run 和双 Run 共用的唯一字段提取入口。

#### Insights

- `insights_status`：`insights.status`；
- `insights_description`：`insights.data.items[0].description`；
- `insights_links`：`insights.data.items[0].links` 转紧凑 JSON；
- `insights_data`：完整 `insights.data` 转紧凑 JSON。

`items` 缺失、不是数组或为空时，description 和 links 留空，不抛异常。

#### Photos

- `photos_status`；
- `photos_baseline_photo_url`；
- `photos_identity_match_rate`；
- `photos_authenticity_photos` JSON；
- `photos_match_photos` JSON；
- `photos_data` 完整 JSON。

#### Profile

- `profile_status`；
- `profile_data` 完整 JSON；
- 动态 `profile.<title>.<label>` 列。

同一个动态字段存在多个值时，转换为字符串后使用 `\n` 连接。空值不写字符串 `None`。

#### Social

- `social_status`；
- `social_display_handles`；
- `social_platforms`；
- `social_urls`；
- `social_profiles` 完整 JSON。

三个多值列都遍历同一 `profiles[]`，保持索引顺序一致；不得分别排序或去重。

#### Summary

- `summary_avatar_url`；
- `summary_confidence_level`；
- `summary_primary_image_url`；
- `summary_social_links` JSON；
- `summary_web_links` JSON；
- `summary_display_name`；
- `summary_location`；
- `summary_match_score`；
- `summary_is_top_result`；
- `summary_is_best_match`。

### 9.4 Query 对齐

```python
def build_query_rows(
    runs: list[RunData],
    metadata: dict[str, QueryMetadata],
) -> list[dict[str, object]]:
    """生成单 Run 或 baseline/candidate 的 Query 汇总行。"""
```

Query 集合取以下并集：

- 所有 Run 的 results query_id；
- 所有 Run 的 failures query_id；
- metadata 中的 query_id。

单个 Run 的状态判定：

| 条件 | 状态 |
| --- | --- |
| results 存在且 `results` 非空 | `SUCCESS` |
| results 存在且 `results` 为空 | `NO_CANDIDATE` |
| failures 存在 | `FAILED` |
| 仅 metadata 存在 | `MISSING` |
| 同时存在 results 和 failures | `DATA_CONFLICT`，必须人工检查 |

双 Run 模式生成 baseline/candidate 两组状态和候选数；单 Run 模式只填 current 对应列，另一组列不生成，避免无意义空列。

### 9.5 Excel 写入

```python
def write_workbook(
    output_path: Path,
    candidate_rows: list[dict[str, object]],
    query_rows: list[dict[str, object]],
    failure_rows: list[dict[str, object]],
    profile_columns: list[str],
    context: dict[str, object],
) -> None:
    """生成候选结果、Query对比、失败记录、说明和可选 Raw Sheet。"""
```

写入顺序：

1. 先构造所有候选行和最终表头；
2. 处理超长值并生成 Raw 引用；
3. 写入四个固定 Sheet；
4. 有超长字段时额外创建 `Raw数据` Sheet；
5. 应用筛选、冻结、换行和列宽；
6. 保存到临时文件；
7. 使用 `openpyxl.load_workbook()` 回读验证；
8. 验证成功后替换目标输出文件。

## 10. 超长 JSON 与 Raw Sheet 设计

### 10.1 Excel 限制

Excel 单元格最多保存 32,767 个字符。为给引用文本和兼容处理留出余量，单个 Raw 数据块最大使用 30,000 个字符。

### 10.2 触发范围

任何导出字段的字符串长度超过 32,000 字符时触发拆分，重点包括：

- `profile_data`；
- `photos_data`；
- `insights_data`；
- `social_profiles`；
- `insights_links`；
- `summary_social_links`；
- `summary_web_links`。

### 10.3 主表引用

为超长值生成稳定引用：

```text
RAW:<run_label>:<query_id>:<candidate_id>:<field_name>
```

主表原单元格写入：

```text
[超长内容见 Raw数据] RAW:baseline:query-001:candidate-001:photos_data
```

### 10.4 `Raw数据` Sheet

| 列 | 说明 |
| --- | --- |
| `raw_ref` | 主表引用 ID |
| `run_label` | Run 标签 |
| `query_id` | Query ID |
| `candidate_id` | 候选人 ID |
| `field_name` | 原字段名 |
| `chunk_index` | 当前块序号，从 1 开始 |
| `chunk_total` | 总块数 |
| `content` | 不超过 30,000 字符的数据块 |

同一 `raw_ref` 按 `chunk_index` 顺序拼接后，必须与原字符串逐字符一致。没有超长字段时不创建 `Raw数据` Sheet。

## 11. Excel 工作簿实现细节

### 11.1 `候选结果`

- 固定列按 PRD 顺序排列；
- Profile 动态列放在 `profile_status/profile_data` 后；
- 人工复核列放在最后；
- 人工复核列初始为空，不设置自动推断值；
- 每行唯一键为 `run_label + query_id + candidate_rank`；
- 候选结果按 `query_id、run_label、candidate_rank` 排序。

### 11.2 `Query对比`

- 单 Run 生成 current 状态、候选数和人工排名列；
- 双 Run 生成 baseline/candidate 两组列；
- 人工填写 `baseline_target_rank`、`candidate_target_rank`；
- Hit@1/3/5 与 MRR@5 使用 Excel 公式；
- `rank_change = baseline_target_rank - candidate_target_rank`，正数表示排名改善；
- 任一排名为空时，rank_change 留空；
- `change_type`、`regression_flag` 和失败归因由人工填写，不自动判断身份。

公式规则示例：

```text
Hit@1 = IF(ISNUMBER(target_rank), --(target_rank<=1), "")
Hit@3 = IF(ISNUMBER(target_rank), --(target_rank<=3), "")
Hit@5 = IF(ISNUMBER(target_rank), --(target_rank<=5), "")
MRR@5 = IF(ISNUMBER(target_rank), IF(AND(target_rank>=1,target_rank<=5),1/target_rank,0), "")
```

### 11.3 `失败记录`

- 包含 API 失败和导出输入错误；
- API 失败保留原始 `stage/error`；
- JSON 解析、重复 query_id 等导出错误使用 `stage=EXPORT_INPUT`；
- 不写入原始敏感请求或凭证。

### 11.4 `说明`

至少包含：

- 生成时间；
- evaluation_id；
- 运行模式；
- Run 路径、标签、版本；
- metadata 路径和记录数；
- 每个 Run 的成功 Query、空结果、失败和候选人数；
- 输入解析错误数；
- Raw 引用数量；
- Top 5、Profile 动态列和人工复核口径。

### 11.5 通用格式

- 冻结首行；
- 开启自动筛选；
- 首行加粗并使用统一底色；
- URL、JSON、多值和人工备注列自动换行、顶部对齐；
- 列宽最大不超过合理显示宽度；
- 布尔值和数值保持原始类型；
- `None` 写为空单元格；
- 外部文本以 `=、+、-、@` 开头时前置单引号，防止公式注入；
- 仅工具生成的 Hit/MRR 公式允许以 `=` 开头。

## 12. 异常处理策略

| 异常 | 处理方式 |
| --- | --- |
| Run 目录不存在 | 启动失败，退出码 1 |
| `results.jsonl` 不存在 | 启动失败，退出码 1 |
| `failures.jsonl` 不存在 | 警告并按无失败继续 |
| metadata 文件路径已提供但不存在 | 启动失败，避免误以为已完成分组对齐 |
| JSONL 单行解析失败 | 写入失败记录，继续读取其他行 |
| 同一 Run 重复 query_id | 标记 `DATA_CONFLICT`，不静默覆盖 |
| metadata 重复 query_id | 启动失败，要求先修复元数据 |
| 候选人不是对象 | 写入导出输入错误，跳过该候选人 |
| `ui_sections` 缺失 | 保留追溯字段，其余提取列为空 |
| 模块缺失或 status=empty | 对应值为空，不计为 Pipeline failure |
| 输出文件正在被 Excel 占用 | 明确提示关闭文件后重试，不覆盖旧文件 |
| 临时工作簿验证失败 | 删除临时文件，保留已有目标文件 |

退出码：

- `0`：工作簿生成成功；可以包含已记录的单行输入错误；
- `1`：参数、目录、metadata、工作簿保存或回读验证失败。

## 13. 安全设计

- 工具只读取显式指定的 Run 目录和 metadata 文件；
- 不读取 `.env`；
- 不访问网络；
- 不输出 token、Cookie 或 HTTP headers；
- 错误消息不打印完整 JSONL 原文；
- 输出中的 URL 和公开资料按测试数据权限管理；
- 公式注入防护应用于所有来自 JSONL 的字符串；
- 写入采用临时文件验证后替换，避免失败时破坏已有 Excel。

## 14. 测试设计

测试使用临时目录和脱敏的最小 JSON，不读取真实 `output/`，也不访问网络。

### 14.1 单元测试

| 测试 | 验证内容 |
| --- | --- |
| 单 Run 基本导出 | 一条 Query、一个候选人生成正确字段 |
| 双 Run 共用逻辑 | baseline/candidate 使用同一 flatten 函数且字段一致 |
| Query 元数据对齐 | input_id 正确合并 person/query 分组字段 |
| Profile 动态列 | 两个 Run 的不同 section/label 生成字段并集 |
| Profile 重复字段 | 相同 title/label 多值按顺序换行连接 |
| Insights 空数组 | items 为空时 description/links 留空 |
| Social 多账号 | handle/platform/url 顺序完全一致 |
| Summary 嵌套缺失 | primary_image 缺失时不报错 |
| 空候选人 | Query 状态为 NO_CANDIDATE |
| 失败任务 | failures 进入失败记录 Sheet |
| 坏 JSON | 记录文件和行号，其他行继续处理 |
| 重复 query_id | 不静默覆盖，状态可见 |
| 公式注入 | 外部字符串不会作为 Excel 公式执行 |

### 14.2 超长数据测试

构造大于 70,000 字符的 `photos_data`：

1. 主表应写入 Raw 引用；
2. Raw Sheet 应生成 3 个数据块；
3. 每块不超过 30,000 字符；
4. 按 chunk_index 拼接后与原数据完全一致；
5. 其他正常字段不受影响。

### 14.3 工作簿验证

- 使用 `openpyxl.load_workbook()` 成功回读；
- Sheet 名称和数量符合预期；
- 表头唯一且顺序正确；
- 候选行数等于输入候选总数；
- 公式单元格存在且引用正确；
- 冻结窗格和自动筛选已设置；
- 原始输入文件修改时间和校验值不变。

### 14.4 回归测试

运行现有测试，确认第二阶段没有影响第一阶段：

```bash
python3 -m unittest discover -s tests -v
python3 -m ruff check search_tool.py result_to_excel.py tests/
```

## 15. 开发计划

### P0：确认与准备

修改内容：

- 确认 v1.2 PRD 和本设计通过；
- 确认 `openpyxl` 版本范围；
- 准备脱敏的单 Run、双 Run、metadata 测试样本。

完成标准：输入、输出、字段和超长数据规则无未决项。

### P1：输入读取与数据模型

修改内容：

- 新增 `result_to_excel.py`；
- 实现 CLI 子命令和参数校验；
- 实现 `read_jsonl()`、`load_run()`、`load_metadata()`；
- 建立 RunSpec、RunData、QueryMetadata。

完成标准：单 Run、双 Run 和 metadata 可以加载；坏 JSON 和重复 ID 有明确结果。

### P2：共用字段提取

修改内容：

- 实现 `collect_profile_columns()`；
- 实现唯一的 `flatten_candidate()`；
- 提取五个 ui_sections 模块；
- 实现 Query 状态对齐。

完成标准：单/双 Run 字段结果一致，Profile 动态列和空模块场景测试通过。

### P3：Excel 与 Raw Sheet

修改内容：

- 生成候选结果、Query对比、失败记录和说明 Sheet；
- 增加人工复核列和 Hit/MRR 公式；
- 实现超长 JSON 拆分与引用；
- 增加格式化、公式注入防护和临时文件回读验证。

完成标准：工作簿可正常打开，超长数据可完整还原，原始输入不被修改。

### P4：文档与完整验证

修改内容：

- 更新 `requirements.txt`；
- 更新 README 的安装和运行示例；
- 完成全部单元测试；
- 使用当前真实 `output/results.jsonl` 做脱敏验证；
- 构造 baseline/candidate 两目录做配对验证。

完成标准：自动化测试、静态检查和工作簿回读全部通过；验收结果记录清楚。

## 16. 风险与控制

| 风险 | 影响 | 控制措施 |
| --- | --- | --- |
| Profile 字段持续变化 | 表头变化影响历史比较 | 每次取双 Run 字段并集，并保留 profile_data 原始 JSON |
| baseline/candidate Query 不一致 | 对比结论失真 | Query Sheet 显示 MISSING/FAILED/NO_CANDIDATE，不自动剔除 |
| 人工复核列被重新导出覆盖 | 标注丢失 | 每次导出生成新文件；不支持覆盖并合并旧人工标注 |
| 超长 JSON 超出单元格限制 | 数据丢失或 Excel 损坏 | 30,000 字符分块写 Raw Sheet，主表保留引用 |
| 多账号列错位 | 人工误判 | 三个字段从同一 profiles 数组一次遍历生成 |
| 系统 confidence 被当作身份结论 | 评分偏差 | 表头和说明中明确仅为系统原始字段 |
| 坏 JSON 被静默忽略 | 行数和指标失真 | 记录文件、行号、错误数并放入失败记录/说明 |
| Excel 公式注入 | 打开文件时执行外部文本 | 所有外部字符串做前缀检查，只有工具公式例外 |

## 17. 交付物

开发完成后应交付：

- `result_to_excel.py`；
- 更新后的 `requirements.txt`；
- 更新后的 `README.md`；
- `tests/test_result_to_excel.py`；
- 单 Run 示例工作簿；
- 双 Run 对比示例工作簿；
- 测试与静态检查结果。

示例工作簿仅使用脱敏测试数据，不包含真实 token、私人信息或未授权数据。

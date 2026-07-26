# searchTool v1.3 阶段0：基线冻结记录

> 记录日期：2026-07-23  
> 对应 PRD：`docs/searchTool_v1.3_PRD需求整理.md`  
> 对应开发设计：`docs/searchTool_v1.3_MVP_开发设计与开发计划.md`  
> 阶段范围：仅完成基线冻结与开发准备，不实现 v1.3 采集、SQLite、Web、字段处理和报告功能。

## 1. 阶段目标与验收结果

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| 现有测试全部通过 | 通过 | `python3 -m unittest discover -s tests -v`：16/16 通过 |
| CLI 仍可运行 | 通过 | `search_tool.py --help`、`result_to_excel.py --help` 均正常 |
| 当前 JSONL 结构已冻结 | 通过 | `tests/fixtures/v1_3_baseline/` 脱敏夹具及 SHA-256 |
| Excel 导出可回归 | 通过 | 3 个 Query、2 个候选人、1 条失败记录成功导出 |
| Flask/openpyxl 依赖已声明 | 通过 | `requirements.txt` 已更新，`pip --dry-run` 解析成功 |
| 数据库 Schema 版本已定义 | 通过 | 首版固定为 `1`，阶段2实现时必须沿用 |
| 人物数据和数据库不会误提交 | 通过 | `.gitignore` 已加入 `/data/`，`.env` 保持忽略 |

## 2. 测试基线

### 2.1 初始检查

阶段0开始时运行原有 14 项测试，结果为 13 项通过、1 项失败：

- 失败用例：`test_long_json_is_split_and_reconstructable`
- 直接现象：预期生成 3 条 Raw 数据，实际为 0 条。
- 根因：`.env` 中的 `EXCEL_RESULTS_FILE` 被注入命令行，覆盖了测试显式传入的 `--run-dir` 数据源，违反“命令行显式参数优先于 `.env`”的约定。

处理方式：

1. 先增加 `test_explicit_run_directory_prevents_env_result_file_injection` 稳定复现；
2. 仅调整 `result_to_excel.py` 的参数准备逻辑；
3. 显式提供 Run 目录时，不再注入同一侧的 results/failures 文件配置；
4. 保留原有显式文件参数和纯 `.env` 模式，不改变其他导出流程。

### 2.2 冻结后的自动测试

冻结后共有 16 项测试：

- searchTool 采集与配置测试：10 项；
- Excel 模型与导出测试：6 项；
- 结果：16 项全部通过；
- 执行时长：11.619 秒；
- 测试过程不调用真实搜索接口。

新增的两项阶段0回归测试：

- 显式 Run 目录不会被 `.env` 结果文件覆盖；
- 阶段0 JSONL 夹具可稳定生成 2 条候选结果、3 条 Query 结果和 1 条失败记录。

### 2.3 静态检查

以下检查全部通过：

```bash
python3 -m py_compile search_tool.py result_to_excel.py tests/test_search_tool.py tests/test_result_to_excel.py
node --check result_to_excel_builder.mjs
python3 -m ruff check search_tool.py result_to_excel.py tests/test_search_tool.py tests/test_result_to_excel.py
```

验证环境：

- Python：3.12.10
- Node.js：24.14.0

## 3. JSONL 基线夹具

夹具目录：

```text
tests/fixtures/v1_3_baseline/
  README.md
  tasks.jsonl
  query_metadata.jsonl
  results.jsonl
  failures.jsonl
```

夹具覆盖：

- `FULL_NAME`；
- `FULL_NAME_SOCIAL`；
- 有候选人、无候选人和 Query 失败三类结果；
- 候选人总数、`candidate_rank` 和 `rank_score`；
- `insights`、`photos`、`profile`、`social`、`summary` 五个 `ui_sections`；
- Query 元数据通过 `query_id = input_id` 对齐；
- 失败阶段和错误信息。

所有人物、链接和标识均为虚构数据，只使用 `example.test` 域名，不包含真实 Token、请求头或个人数据。

### 3.1 夹具校验值

| 文件 | SHA-256 |
| --- | --- |
| `failures.jsonl` | `c449b42bf94ad852a2702527e96393c5e0839ebf7198a25076e70f563b7fd4c7` |
| `query_metadata.jsonl` | `a0fb184bbdfeba3166be9d4e7aeeda710a3ecff70a253e6a949291f0e5304565` |
| `results.jsonl` | `24ae71138379ae566c575961a58b3f6927a14fc2b6fc3363957b90f9316f89ad` |
| `tasks.jsonl` | `b600b6443753e5756e6cfa7f092f8e74776b19122c66feded6ab46fd03feb01c` |

修改夹具结构或内容时，必须同步更新：

1. 夹具 README；
2. SHA-256；
3. Excel 基线验证；
4. 对应自动测试；
5. 本冻结记录或后续版本记录。

## 4. Excel 导出基线

验证输入：

- `tests/fixtures/v1_3_baseline/results.jsonl`
- `tests/fixtures/v1_3_baseline/failures.jsonl`
- `tests/fixtures/v1_3_baseline/query_metadata.jsonl`

验证输出：

- `outputs/v1_3_phase0/baseline_results.xlsx`

导出结果：

| Sheet | 冻结结果 |
| --- | --- |
| 候选结果 | 2 行候选人，31 列 |
| Query对比 | 3 行 Query，17 列 |
| 失败记录 | 1 行失败，10 列 |
| 说明 | 运行信息和字段目录 |

结构、公式错误和视觉检查均通过：

- 未发现 `#REF!`、`#DIV/0!`、`#VALUE!`、`#NAME?` 或 `#N/A`；
- 候选人数、排名、分数、Query 状态和失败阶段与夹具一致；
- 4 个 Sheet 均已渲染检查，未发现表头错位、数据遮挡或不可读问题；
- 当前夹具未触发 Excel 单元格超长拆分，因此未生成 `Raw数据` Sheet；超长拆分能力由既有自动测试继续覆盖。

复现命令：

```bash
SEARCHTOOL_VERIFY_DIR=outputs/v1_3_phase0/verification \
python3 result_to_excel.py single \
  --results-file tests/fixtures/v1_3_baseline/results.jsonl \
  --failures-file tests/fixtures/v1_3_baseline/failures.jsonl \
  --run-label baseline \
  --system-version phase0 \
  --evaluation-id eval-v1.3-phase0 \
  --metadata tests/fixtures/v1_3_baseline/query_metadata.jsonl \
  --output outputs/v1_3_phase0/baseline_results.xlsx
```

## 5. 依赖基线

`requirements.txt` 当前依赖：

```text
requests>=2.31,<3
python-dotenv>=1.0,<2
Flask>=3.0,<4
openpyxl>=3.1,<4
```

`python3 -m pip install --dry-run -r requirements.txt` 已通过：

- 当前环境已有 `requests 2.34.2`；
- 当前环境已有 `python-dotenv 1.2.2`；
- 当前环境已有 `openpyxl 3.1.5`；
- Flask 可解析为 `3.1.3`，本阶段只声明依赖，不启动 Web。

进入后续开发阶段前，开发环境应执行：

```bash
python3 -m pip install -r requirements.txt
```

## 6. 数据目录与安全约定

冻结的数据目录如下：

```text
data/
  searchtool_v1_3.db
  imports/
    <run_id>/
      source.jsonl 或 source.xlsx
  raw/
    <evaluation_id>/
      <run_id>/
        results.jsonl
        failures.jsonl
output/
  reports/
    <evaluation_id>/
      <report_id>/
        report.html
        report.xlsx
```

约束：

- `data/` 为运行数据目录，已整体加入 `.gitignore`；
- `.env` 继续忽略，不提交 URL、Headers、Token、Device ID 和 User ID；
- 测试夹具只能使用脱敏或虚构数据；
- 报告产物位于 `output/reports/`，是否提交由具体交付场景决定；
- 相对路径在后续实现中统一按项目目录解析。

## 7. 数据库 Schema 版本冻结

数据库首个 Schema 版本定义为：

```text
DB_SCHEMA_VERSION = 1
```

阶段0只冻结版本号，不提前创建空数据库模块或表结构。阶段2实现 `analysis_store.py` 时必须：

1. 以 Schema 版本 `1` 初始化设计文档中已定义的基础表和索引；
2. 在数据库内持久化当前 Schema 版本；
3. 初始化操作保持幂等；
4. 遇到高于程序支持范围的 Schema 版本时停止写入并明确报错；
5. 后续结构变更通过新增版本迁移，不静默修改版本 `1` 的含义。

## 8. 已知基线问题

以下问题本阶段只记录，不扩大范围修改：

1. Excel“说明”中的部分旧文案仍描述“当前通常为 1–5”或 Top 5，而当前采集工具已经按 List 返回数量请求全部候选人详情。该文案应在阶段6更新 Excel 导出时统一修正。
2. 历史 JSONL 只包含当时保存的结构，不能恢复未落盘的完整 API Raw；后续导入时必须标记为 legacy/raw 缺失，不得伪造。
3. Flask 已声明但尚未安装到当前解释器；进入 Web 阶段前需安装完整依赖。

## 9. 回滚与阶段边界

本阶段没有修改搜索接口调用顺序、候选人请求规则、输出命名或现有 Excel 表结构。

如需回滚阶段0改动：

- 移除 Flask/openpyxl 依赖声明；
- 移除 `/data/` 忽略规则；
- 回退 Excel 参数优先级修复及其测试；
- 删除脱敏夹具、冻结记录和阶段0验证产物。

回滚不会影响既有 CLI 的 JSONL 采集结果。进入阶段1前，以本记录中的 16 项测试、JSONL 校验值和 Excel 验证结果作为回归基线。

# searchTool v1.3 MVP 信息架构与使用体验优化开发设计与计划

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | searchTool v1.3 MVP 信息架构与使用体验优化开发设计与计划 |
| 文档版本 | v1.0 |
| 编写日期 | 2026-07-27 |
| 需求来源 | Evaluation 参考线入口、全局时间格式、报告快捷入口优化讨论 |
| 当前基线 | searchTool v1.3 MVP 优化阶段0～阶段6 |
| 适用环境 | 本地或测试环境，单用户，`127.0.0.1:5002` |
| 实施原则 | 三阶段完成、最小增量、历史兼容、报告快照不重算 |

## 2. 结论与阶段划分

本次优化可以在3个阶段内完成：

1. **阶段1：统一时间展示**；
2. **阶段2：全局报告中心与首页快捷入口**；
3. **阶段3：参考线方案管理与 Evaluation 简化**。

三阶段顺序如下：

```text
阶段1：统一展示基础
  ↓
阶段2：调整报告信息架构
  ↓
阶段3：解耦参考线配置与 Evaluation
```

阶段1和阶段2不需要修改核心业务 Schema；阶段3增加参考线方案表，并执行一次
SQLite Schema v2→v3 迁移。

## 3. 优化目标

### 3.1 任务目标

1. 创建 Evaluation 时不再要求填写整套参考线；
2. 支持提前维护多套可复用、可选择的参考线方案；
3. 将“参考线配置”和“系统建议”分成两个职责；
4. 全站时间统一展示为北京时间的秒级格式；
5. 首页可以直接查看最近的报告快照；
6. 增加独立报告中心，避免必须进入 Evaluation 才能查找报告；
7. 保持现有检索、处理、指标和 ReportModel 主流程不变；
8. 保持历史 Evaluation、旧参考线和旧报告可访问。

### 3.2 成功标准

- 创建 Evaluation 页面只包含基本信息和可选的参考线方案；
- 未选择参考线也可以创建、执行、处理和生成报告；
- 可以在独立入口创建和查看多套参考线方案；
- 一个 Evaluation 同一时间关联一个明确版本的参考线方案；
- 切换参考线方案只影响以后生成的报告；
- 历史报告继续使用生成时的参考线快照；
- 页面、静态 HTML 和 Excel 的可见时间统一为
  `2026-07-24 12:35:20`；
- 数据库、Raw、API 和并发控制字段仍保留 ISO 8601 原值；
- 首页展示最近报告，主导航可以进入全部报告；
- Docker 5002重启后页面、时间和历史数据正常。

### 3.3 本次不实现

- 登录、角色和权限；
- 参考线审批流；
- 同一报告同时套用多套参考线并产生多个结论；
- 自动根据历史指标推荐参考线；
- 自动替代业务负责人决定是否上线；
- 前后端分离或引入 React/Vue；
- 修改检索接口调用顺序、字段处理和指标计算公式。

## 4. 当前问题分析

### 4.1 Evaluation 页面职责过多

当前创建 Evaluation 页面同时承担：

- 创建评测容器；
- 填写测试说明；
- 配置 `FULL_NAME` 参考线；
- 配置 `FULL_NAME_SOCIAL` 参考线。

Evaluation 详情页又同时展示：

- 参考线编辑；
- 启动 Run；
- Run 列表；
- 报告列表。

参考线表单占据较大页面空间，且同一套参考线无法直接复用到其他 Evaluation。

### 4.2 “参考线与建议”概念混合

参考线是人工配置的验收标准：

```text
最低检索成功率
最低命中完整度
最低命中准确率
最高平均总成本
最高平均检索耗时
```

建议是系统计算结果：

```text
实际指标 + 参考线
  → PASS / FAIL / NOT_READY
  → 建议上线 / 继续优化 / 暂不能判断
```

在 Evaluation 尚未产生指标时，不存在可计算的“建议”。因此：

- 参考线管理页面只展示和维护参考线；
- Evaluation 页面只选择参考线方案；
- 报告页面才展示“参考线与建议”。

### 4.3 时间直接展示存储格式

当前 SQLite 保存 UTC ISO 8601，例如：

```text
2026-07-24T06:08:31.593258+00:00
```

该格式适合存储、排序和接口传递，但不适合业务页面阅读。当前多个模板直接输出
数据库原值，造成：

- 存在 `T`、微秒和时区偏移；
- 用户需要自行换算北京时间；
- 不同页面的空值文案不一致；
- Excel 和 HTML 的显示格式不统一。

### 4.4 报告入口层级过深

当前报告入口主要为：

```text
评测列表
  → Evaluation 详情
    → 报告快照
      → 报告详情
```

首页不能快速看到最近报告，也没有全局报告列表。

## 5. 优化后信息架构

### 5.1 主导航

```text
检索分析系统
├── 评测
├── 数据导入
├── 基准数据
├── 字段配置
├── 参考线
├── 报告
└── 新建评测
```

### 5.2 首页

首页保持 Evaluation 为主，同时增加“最近报告”：

```text
首页
├── 快捷操作
│   ├── 创建评测
│   ├── 导入数据
│   ├── 查看报告
│   └── 管理参考线
├── 评测列表
└── 最近报告（默认最近10份）
```

### 5.3 Evaluation 详情

```text
Evaluation 详情
├── 基本信息
├── 参考线方案摘要
│   ├── 当前方案
│   ├── 方案版本
│   └── 更换方案
├── 启动 searchTool
├── Run 列表
└── 本 Evaluation 报告
```

详情页不再直接展开完整参考线编辑表单。

### 5.4 参考线管理

```text
参考线管理
├── 方案列表
│   ├── 名称
│   ├── 版本
│   ├── 状态
│   ├── FULL_NAME 摘要
│   └── FULL_NAME_SOCIAL 摘要
├── 新建方案
├── 查看方案
├── 基于现有方案创建新版本
└── 归档方案
```

首版不允许原地修改已经被 Evaluation 使用的参考线内容。调整配置时创建新版本，
保证历史可追溯。

### 5.5 报告中心

```text
报告中心
├── 全部报告
├── Evaluation 筛选
├── 系统版本筛选
├── SINGLE / COMPARE 筛选
├── READY / STALE / FAILED 筛选
├── 查看 Web 报告
├── 下载静态 HTML
└── 下载 Excel
```

报告仍从 Process 页面创建。报告中心只负责集中查看、筛选和下载，不在首页复制
报告创建表单。

## 6. 统一时间展示设计

### 6.1 格式标准

所有用户可见时间统一为：

```text
2026-07-24 12:35:20
```

使用半角冒号 `:`。半角格式便于复制、排序、Excel 处理和日志检索。

### 6.2 时区标准

新增可选环境配置：

```dotenv
SEARCH_DISPLAY_TIMEZONE=Asia/Shanghai
```

默认值为 `Asia/Shanghai`。

处理规则：

1. 数据库存储继续使用 UTC ISO 8601；
2. Web 页面读取时转换到配置时区；
3. 静态 HTML 生成时使用相同配置；
4. Excel 写入转换后的本地时间，并设置
   `yyyy-mm-dd hh:mm:ss` 显示格式；
5. JSON API、Raw 下载和原始结果文件不修改时间原值。

### 6.3 Jinja 过滤器

在 Flask 应用增加统一过滤器，例如：

```python
format_datetime(value, empty_text="—")
```

功能要求：

- 支持带时区 ISO 8601；
- 支持结尾 `Z`；
- 对历史无时区值按 UTC 兼容；
- 转换到 `SEARCH_DISPLAY_TIMEZONE`；
- 去除微秒；
- 无值返回调用方指定的空值文案；
- 非法值不导致页面500，保留原文并记录测试覆盖。

模板统一使用：

```jinja2
{{ value|format_datetime }}
```

### 6.4 不参与格式转换的字段

以下字段必须继续使用数据库原值：

- `expected_reviewed_at` 隐藏字段；
- API 并发控制时间；
- SQLite 写入值；
- Raw JSON；
- JSONL 结果；
- 报告 `metrics_json` 中的原始时间快照。

例如 Candidate 复核页面：

```text
隐藏提交值：2026-07-24T06:08:31.593258+00:00
页面显示值：2026-07-24 14:08:31
```

这样不会破坏当前乐观并发控制。

### 6.5 页面覆盖范围

- 首页最近运行；
- Evaluation 的 Run 和报告时间；
- Run、Query、Candidate、Process 详情；
- Raw 和失败记录；
- Baseline 和 FieldSchema；
- 人工复核时间；
- 报告 Web 页面；
- 静态 HTML；
- processed Excel。

## 7. 报告中心设计

### 7.1 首页最近报告

首页查询最近10份报告，建议展示：

| 字段 | 说明 |
| --- | --- |
| `report_id` | 可点击进入报告 |
| Evaluation | 名称和标识 |
| `system_version` | Candidate 系统版本 |
| `evaluation_phase` | 评估阶段 |
| `report_type` | `SINGLE` 或 `COMPARE` |
| `status` | `READY`、`STALE` 或 `FAILED` |
| `created_at` | 统一格式后的生成时间 |

首页只展示摘要，不加载完整 `metrics_json`。

### 7.2 全部报告页面

新增路由：

```text
GET /reports
```

首版支持：

- 每页50条；
- 按创建时间倒序；
- Evaluation 筛选；
- 系统版本关键词；
- 报告类型筛选；
- 报告状态筛选；
- 直接进入报告；
- 已生成时下载 HTML/Excel。

查询只读取 `reports`、`process_runs`、`runs` 和 `evaluations`，不重新计算指标。

### 7.3 页面状态

| 状态 | 页面表现 |
| --- | --- |
| `READY` | 正常查看和下载 |
| `STALE` | 显示“数据或复核已变化，历史快照仍可查看” |
| `FAILED` | 显示失败状态，不伪造下载链接 |
| Excel 为空 | 显示“Excel 暂不可用”，HTML 不受影响 |

### 7.4 导航与返回路径

- 主导航增加“报告”；
- 首页增加“查看全部报告”；
- 报告详情保留返回所属 Evaluation；
- 报告详情增加返回“报告中心”；
- Evaluation 详情继续保留自身报告列表。

## 8. 参考线方案设计

### 8.1 业务规则

1. 参考线方案是可复用配置，不是报告结论；
2. 每个方案同时支持 `FULL_NAME` 和 `FULL_NAME_SOCIAL`；
3. Evaluation 可以不选择方案；
4. Evaluation 同一时间关联一个方案版本；
5. 选择方案时复制一份 `thresholds_json` 到 Evaluation；
6. 方案调整必须产生新版本，不覆盖旧版本；
7. 已归档方案不可用于新 Evaluation，但历史关联仍可查看；
8. 建议只在报告中计算；
9. 切换方案不修改旧报告，不自动把旧报告标记为 `STALE`；
10. 需要按新方案判断时，基于当前 Process 生成一份新报告。

### 8.2 SQLite Schema v3

新增表：

```sql
CREATE TABLE threshold_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL,
    thresholds_json TEXT NOT NULL,
    based_on_profile_id TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(name, version),
    FOREIGN KEY (based_on_profile_id)
        REFERENCES threshold_profiles(profile_id)
);
```

`status` 首版只支持：

```text
ACTIVE
ARCHIVED
```

扩展 `evaluations`：

```sql
ALTER TABLE evaluations
ADD COLUMN threshold_profile_id TEXT;
```

现有字段继续保留：

```text
evaluations.thresholds_json
```

其语义调整为“Evaluation 当前参考线快照”，而不是参考线方案的唯一维护位置。

### 8.3 版本策略

首版采用不可变版本：

```text
release-standard v1
  ↓ 基于此版本创建
release-standard v2
```

- `profile_id` 标识具体版本；
- `name + version` 用于页面展示；
- `based_on_profile_id` 记录来源；
- 归档只改变是否可供新 Evaluation 选择；
- 不允许删除已经被 Evaluation 引用的方案。

### 8.4 创建 Evaluation

创建页面保留：

- `evaluation_id`；
- 评测名称；
- 说明；
- 参考线方案，可选。

移除：

- `FULL_NAME` 的5个展开输入；
- `FULL_NAME_SOCIAL` 的5个展开输入；
- “参考线与建议”标题。

选择方案后：

```text
threshold_profile_id = 所选 profile_id
thresholds_json = 所选方案 thresholds_json 的快照
```

未选择时：

```text
threshold_profile_id = null
thresholds_json = 标准空参考线对象
```

### 8.5 Evaluation 详情

页面只展示方案摘要：

```text
参考线方案：发布验收参考线 v2
状态：ACTIVE
FULL_NAME：配置3项
FULL_NAME_SOCIAL：配置5项
[查看方案] [更换方案]
```

未配置时显示：

```text
尚未选择参考线方案。
不影响执行和生成报告；报告建议将显示“暂不能判断”。
```

### 8.6 更换方案

更换前页面明确提示：

```text
更换只影响以后生成的新报告。
既有报告继续保留原参考线和建议，不会重新计算。
```

提交时在同一事务中更新：

- `threshold_profile_id`；
- `thresholds_json`；
- `updated_at`。

### 8.7 ReportModel 扩展

新报告的 `metadata` 增加：

```json
{
  "threshold_profile_id": "threshold_release_v2",
  "threshold_profile_name": "发布验收参考线",
  "threshold_profile_version": 2
}
```

继续保留：

```text
threshold_assessment.threshold_snapshot
```

打开旧报告时：

- 无方案标识不报错；
- 页面显示“历史自定义参考线”；
- 继续读取报告中的 `threshold_snapshot`；
- 不回查当前 Evaluation 的方案。

## 9. 兼容与迁移

### 9.1 数据库迁移

Schema v2→v3：

1. 开启单个事务；
2. 创建 `threshold_profiles`；
3. 为 `evaluations` 增加 `threshold_profile_id`；
4. 保持所有现有 `thresholds_json` 原值；
5. 将现有 Evaluation 的 `threshold_profile_id` 设为 `null`；
6. 更新 `schema_info` 为3；
7. 任一步失败时完整回滚。

### 9.2 历史 Evaluation

历史 Evaluation 显示：

```text
参考线来源：历史自定义配置
```

不自动为每个旧 Evaluation 创建一套新方案，避免生成大量重复记录。

需要复用时，用户可以从历史快照创建一套新的参考线方案。

### 9.3 历史报告

- `reports.metrics_json` 不修改；
- HTML/Excel 文件不覆盖；
- 旧 ReportModel v1/v2 继续打开；
- 新时间格式只改变页面渲染，不改变报告快照内容；
- 已导出的旧静态文件不自动重写。

## 10. 路由与页面设计

### 10.1 新增路由

```text
GET  /reports
GET  /threshold-profiles
GET  /threshold-profiles/new
POST /threshold-profiles
GET  /threshold-profiles/<profile_id>
GET  /threshold-profiles/<profile_id>/copy
POST /threshold-profiles/<profile_id>/archive
POST /evaluations/<evaluation_id>/threshold-profile
```

### 10.2 保持兼容的路由

```text
GET  /
GET  /evaluations/new
POST /evaluations/new
GET  /evaluations/<evaluation_id>
POST /reports
GET  /reports/<report_id>
```

现有：

```text
POST /evaluations/<evaluation_id>/thresholds
```

迁移后不再由普通页面使用。为兼容已有调用，首版可以保留服务端路由，但必须：

- 继续校验参数；
- 将来源标记为历史自定义；
- 清空 `threshold_profile_id`；
- 不修改旧报告。

后续确认没有调用方后再移除。

## 11. 安全与校验

### 11.1 参考线

- `profile_id` 使用现有存储标识校验；
- 比率限制在0～1；
- 成本和耗时必须为非负数；
- 未知 Query Stage 或字段拒绝保存；
- 新版本必须有唯一 `name + version`；
- 已归档方案不能被新 Evaluation 选择；
- 不允许覆盖已有版本。

### 11.2 报告中心

- 下载继续使用现有受控路径解析；
- 页面不展示完整 `metrics_json`；
- 不展示 `.env`、Token、Header 或 Raw 凭证；
- 筛选参数使用固定枚举和参数化 SQL；
- 分页设置最大页大小。

### 11.3 时间

- 时区名称通过 `zoneinfo.ZoneInfo` 校验；
- 非法 `SEARCH_DISPLAY_TIMEZONE` 启动时回退
  `Asia/Shanghai` 并记录可读警告；
- 不使用浏览器本地时区隐式转换；
- 不修改并发控制和数据签名使用的原始时间。

## 12. 测试设计

### 12.1 时间测试

- UTC 转换为 `Asia/Shanghai`；
- 微秒被移除；
- `Z` 和 `+00:00` 均支持；
- 空值使用页面指定文案；
- 非法历史值不导致500；
- Candidate 隐藏并发字段仍提交原 ISO 值；
- 静态 HTML 与 Web 时间一致；
- Excel 时间显示为 `yyyy-mm-dd hh:mm:ss`。

### 12.2 报告中心测试

- 首页最多展示最近10份报告；
- 全部报告按时间倒序；
- Evaluation、版本、类型和状态筛选；
- 50条分页；
- READY/STALE/FAILED 状态正确；
- HTML/Excel 缺失时不生成错误下载链接；
- 报告详情可以返回报告中心和所属 Evaluation；
- 旧报告可以从全局入口打开。

### 12.3 参考线方案测试

- 新建方案和版本；
- 重复 `name + version` 拒绝；
- 非法参考线整次回滚；
- 创建 Evaluation 时选择方案；
- 未选择方案仍可创建；
- Evaluation 保存方案快照；
- 更换方案只影响新报告；
- 旧报告参考线和建议不变；
- 归档方案历史可见、新建不可选；
- Schema v2→v3 迁移保留 Evaluation、Run、Raw、Process 和 Report；
- 迁移失败完整回滚。

### 12.4 回归测试

- 顺序检索流程不变；
- 历史 JSONL/Excel 导入不变；
- Process 和复核不变；
- 指标 v2 公式不变；
- ReportModel v1/v2 兼容；
- 单次和对比报告正常；
- Excel v2 Sheet 不回归；
- Docker 5002启动和重启通过。

## 13. 三阶段开发计划

### 阶段1：统一时间展示

#### 目标

建立全系统唯一的时间展示规则，不修改存储值和业务逻辑。

#### 工作项

1. 增加 `SEARCH_DISPLAY_TIMEZONE` 配置；
2. 增加统一时间解析和格式化函数；
3. 注册 Jinja 时间过滤器；
4. 替换所有页面直接输出的时间；
5. 保留 Candidate 并发隐藏字段的原始 ISO 值；
6. 静态 HTML 使用同一过滤器；
7. processed Excel 时间列使用日期时间类型和统一格式；
8. 增加时间单元测试、Web 测试和 Excel 测试；
9. 更新 `.env.example` 和 README。

#### 主要文件

- `web_app.py`
- `templates/index.html`
- `templates/evaluation_detail.html`
- `templates/run_detail.html`
- `templates/query_detail.html`
- `templates/candidate_detail.html`
- `templates/process_detail.html`
- `templates/baselines.html`
- `templates/field_schemas.html`
- `templates/imports.html`
- `templates/_report_content.html`
- `result_to_excel_builder.mjs`
- `tests/test_web_app.py`
- `tests/test_result_to_excel.py`
- `.env.example`
- `README.md`

#### 完成标准

- 所有用户可见时间均为 `yyyy-mm-dd hh:mm:ss`；
- 北京时间转换正确；
- 页面不显示 `T`、微秒或 `+00:00`；
- API、Raw、数据库和并发控制不受影响；
- Web、静态 HTML 和 Excel 时间一致；
- 阶段1相关测试和全量回归通过。

### 阶段2：报告中心与首页快捷入口

#### 目标

让用户从首页和主导航直接查找全部报告快照。

#### 工作项

1. 首页查询并展示最近10份报告；
2. 新增报告中心路由；
3. 增加 Evaluation、版本、类型和状态筛选；
4. 增加50条服务端分页；
5. 增加报告状态和下载可用性展示；
6. 主导航增加“报告”；
7. 报告详情增加返回报告中心；
8. 保留 Evaluation 和 Process 内已有报告入口；
9. 增加查询、筛选、分页和下载测试；
10. 更新 README。

#### 主要文件

- `web_app.py`
- `templates/base.html`
- `templates/index.html`
- `templates/report_detail.html`
- `templates/reports.html`（新增）
- `static/app.css`
- `tests/test_web_app.py`
- `README.md`

#### 完成标准

- 首页可以直接进入最近报告；
- 主导航可以进入全部报告；
- 报告中心筛选和分页正确；
- 报告列表不重新计算 `metrics_json`；
- READY/STALE/FAILED 状态清晰；
- HTML/Excel 下载入口只在文件可用时展示；
- 阶段2相关测试和全量回归通过。

### 阶段3：参考线方案与 Evaluation 简化

#### 目标

将参考线从 Evaluation 表单中解耦，形成可复用、版本化的参考线方案。

#### 工作项

1. SQLite Schema v2→v3 迁移；
2. 新增 `threshold_profiles` 表；
3. Evaluation 增加 `threshold_profile_id`；
4. 实现参考线方案查询、创建、复制版本和归档服务；
5. 新增参考线管理和详情页面；
6. 主导航增加“参考线”；
7. 创建 Evaluation 改为可选方案下拉框；
8. Evaluation 详情改为方案摘要和更换入口；
9. 保留 `thresholds_json` 作为 Evaluation 快照；
10. ReportModel 增加方案标识，继续保存参考线内容快照；
11. 兼容历史自定义参考线和旧报告；
12. 保留旧参考线更新路由的兼容行为；
13. 增加 Schema、服务、Web、报告兼容测试；
14. 更新 README 和验收记录。

#### 主要文件

- `analysis_store.py`
- `analysis_service.py`
- `web_app.py`
- `templates/base.html`
- `templates/evaluation_new.html`
- `templates/evaluation_detail.html`
- `templates/threshold_profiles.html`（新增）
- `templates/threshold_profile_new.html`（新增）
- `templates/threshold_profile_detail.html`（新增）
- `templates/_report_content.html`
- `tests/test_analysis_store.py`
- `tests/test_analysis_service.py`
- `tests/test_web_app.py`
- `README.md`
- 现有集成验收记录

#### 完成标准

- 可以提前建立多套参考线方案；
- 创建 Evaluation 时可以选择或不选择方案；
- 创建页不再展开完整参考线表单；
- Evaluation 详情不再承担参考线编辑器职责；
- 同一方案可以复用到多个 Evaluation；
- 新版本不覆盖旧方案；
- 更换方案只影响新报告；
- 历史 Evaluation 和报告不丢失、不重算；
- Schema v2→v3迁移和失败回滚测试通过；
- 阶段3相关测试和全量回归通过。

## 14. 阶段依赖与交付节奏

```text
阶段1
统一时间过滤器和导出格式
  ↓
阶段2
首页最近报告 + 全局报告中心
  ↓
阶段3
参考线方案 + Evaluation 简化 + Schema v3
```

每个阶段都必须独立满足：

1. 相关自动化测试通过；
2. 全量回归通过；
3. Docker 镜像重新构建；
4. `127.0.0.1:5002` 健康；
5. 重启前后数据量不变；
6. README 更新；
7. 不夹带下一阶段功能。

## 15. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 展示时间误改为存储时间 | 并发判断或排序异常 | 只在模板/Excel展示层转换 |
| 浏览器和服务端时区不一致 | 页面时间不一致 | 服务端统一使用 `ZoneInfo` |
| 旧无时区时间语义不清 | 历史时间偏移 | 按UTC兼容并增加测试说明 |
| 首页查询完整报告 JSON | 首页变慢 | 只查询摘要列和最近10条 |
| 报告中心筛选参数失控 | SQL或性能问题 | 固定枚举、参数化SQL、分页上限 |
| 参考线方案被直接覆盖 | 历史标准不可追溯 | 方案版本不可变，修改即新版本 |
| 切换方案影响旧报告 | 历史结论变化 | 报告只读自身快照 |
| 自动迁移生成大量重复方案 | 数据混乱 | 历史 Evaluation 保持自定义来源 |
| 归档导致历史页面失效 | 旧关联不可查看 | 归档不删除记录 |
| 概念仍然混淆 | 用户误以为方案直接给出建议 | 方案页只叫“参考线”，建议只在报告出现 |

## 16. 最终验收清单

- [ ] 创建 Evaluation 页面已移除展开参考线表单；
- [ ] 创建 Evaluation 可以选择已有参考线方案；
- [ ] 不选择方案仍可完成全部流程；
- [ ] 独立参考线入口可以维护多个不可变版本；
- [ ] Evaluation 详情只显示参考线方案摘要；
- [ ] 建议只在报告中根据实际指标生成；
- [ ] 切换方案不修改旧报告；
- [ ] 全站可见时间统一到秒；
- [ ] 页面时间正确转换为 `Asia/Shanghai`；
- [ ] ISO 原值、Raw、API 和并发控制不变；
- [ ] 首页展示最近报告；
- [ ] 主导航包含报告中心；
- [ ] 报告中心筛选和分页正确；
- [ ] READY/STALE/FAILED 状态正确；
- [ ] 旧 Evaluation、旧报告和旧导出可访问；
- [ ] SQLite v2→v3 无数据丢失；
- [ ] 迁移失败完整回滚；
- [ ] Web、静态 HTML 和 Excel 展示一致；
- [ ] 全量自动化测试通过；
- [ ] Docker 5002重启和数据持久化验证通过。

## 17. 最终建议

三阶段足以完成本次优化，不需要再拆成更多阶段：

- 阶段1解决全局一致性；
- 阶段2解决报告入口层级；
- 阶段3解决参考线复用和 Evaluation 职责混乱。

阶段3虽然涉及 Schema v3，但只新增一张表和一个可空关联字段，现有
`evaluations.thresholds_json`、指标计算和报告快照逻辑可以继续复用，不需要重写
核心架构。

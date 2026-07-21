# 性能基准与优化报告（2026-04-09）

## 1. 目标

针对大数据量场景，对以下三条链路进行基准与优化：
- 缺陷列表：`GET /defects`
- 项目列表：`GET /user/projects`
- 协作轮询：`GET /collaborations/:taskId`

## 2. 基准方法

基准文件：
- `server/internal/handler/perf_benchmark_test.go`

执行命令（统一口径）：

```bash
cd server
go test ./internal/handler -run '^$' \
  -bench 'Benchmark(DefectHandler_ListDefects_LargeDataset|UserProjectsHandler_ListUserProjects_LargeDataset|CollaborationHandler_GetCollaborationTask_Polling)$' \
  -benchmem -benchtime=3x -count=1
```

数据规模（benchmark seed）：
- 缺陷列表：1 项目 / 20 迭代 / 20,000 缺陷
- 项目列表：400 项目 / 每项目 6 成员 / 每项目 3 迭代 / 每迭代 20 缺陷
- 协作轮询：1 协作任务 / 600 协作报告

## 3. 优化内容

### 3.1 缺陷列表
- 文件：`server/internal/handler/defect.go`
- 优化点：
  - `count` 与 `order by` 解耦，避免 count 查询执行无意义排序。
  - 预加载用户改为最小字段集（`id/username/nickname/avatar`），减少关联查询 I/O。

### 3.2 项目列表（用户可见项目）
- 文件：`server/internal/handler/user_projects.go`
- 优化点：
  - 将原先按项目循环的 N+1 查询改为聚合查询：
    - 缺陷统计：单次 `iterations + defects` 聚合
    - 成员总数：单次 `project_members` 聚合
    - 成员预览：窗口函数 `row_number` 一次取每项目前 5 个成员
  - `GetProjectStats` 从多次 count 改为单次聚合查询。

### 3.3 协作轮询
- 文件：`server/internal/service/collaboration.go`
- 优化点：
  - `GetCollaborationTask` 改为轻量查询，不再默认 `Preload(Reports/Defect)`。
  - `GetAggregatedReport` 将 AnalysisReport 查询由 N+1 改为批量 `IN` 查询。

### 3.4 索引增强
- 模型索引标签：
  - `server/internal/model/models.go`
  - `server/internal/model/collaboration.go`
- 启动期索引创建：
  - `server/cmd/server/main.go`
- SQL 迁移：
  - `server/migrations/v2.1_perf_indexes.sql`
- 新增关键索引：
  - `defects(iteration_id, status, created_at DESC)`
  - `project_members(user_id, project_id)`
  - `project_members(project_id, user_id)`
  - `collaboration_tasks(status, updated_at DESC)`
  - `collaboration_tasks(defect_id, created_at DESC)`
  - `collaboration_reports(task_id, status)`
  - `collaboration_reports(report_id)`

## 4. 结果对比（优化前 vs 优化后）

| Benchmark | 优化前 ns/op | 优化后 ns/op | 改善 |
|---|---:|---:|---:|
| DefectHandler_ListDefects_LargeDataset | 35,781,319 | 31,611,681 | **-11.7%** |
| UserProjectsHandler_ListUserProjects_LargeDataset | 40,942,792 | 24,297,903 | **-40.7%** |
| CollaborationHandler_GetCollaborationTask_Polling | 122,291,389 | 22,496,472 | **-81.6%** |

补充（内存）：
- 协作轮询 `B/op` 从 `994,277` 降至 `15,240`，显著降低轮询开销。

## 5. 回归验证

```bash
cd server && go test ./... -count=1
```

结果：PASS

## 6. 结论

本轮已完成“基准 -> 优化 -> 复测 -> 索引落地”闭环，三条目标链路在大数据量下均实现耗时下降，其中协作轮询链路提升最明显。

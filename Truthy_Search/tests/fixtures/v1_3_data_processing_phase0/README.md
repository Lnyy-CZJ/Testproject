# v1.3 MVP 数据处理优化阶段0夹具

该目录冻结数据处理优化阶段0的问题契约。夹具由真实评测的统计特征脱敏得到，
不包含真实人物姓名、候选人详情、接口凭证或完整原始响应。

## 来源

- Run：`run_2be5fe30b86f49bcba447296205911bb`
- Process：`process_9c490abfc00f47a1a2f06d594f8819a7`
- Report：`report_5a680512bbbc4048ae860ca42330b162`
- Baseline：`test20260728`

## 冻结场景

- 10条 Query，全部缺少 `person_id`；
- 45名成功返回详情的候选人，全部为 `PENDING_REVIEW`；
- 10个 Query 均存在 `task_id`；
- v2 报告错误展示 `Task ID 0/45`；
- v2 把 Insights、Photos 的空容器计为模块有数据；
- 每名 Baseline Person 声明15个可用字段，但默认配置仅
  `social_urls` 参与 completeness。

`problem_contract.json` 同时保存 v2 当前快照和 v3 目标契约。测试数据由契约动态
生成并写入临时 SQLite，不访问真实接口，也不修改生产数据库。

## 预期失败测试

阶段0中的 v3 契约测试使用 `unittest.expectedFailure`：

- 当前未实现时，测试套件正常通过并明确报告 expected failure；
- 后续实现满足契约时会变成 unexpected success，测试套件会失败；
- 对应阶段完成后应移除装饰器，使其成为正式回归测试。

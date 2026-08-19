# Functional Test Agent

功能测试智能体的独立源码项目，可单独开发、测试、构建、运行和回滚，不依赖相邻的 API 项目。

## 本机开发

```bash
python3 -m pip install -r requirements.lock
python3 -m pytest -q
node --test tests/ui/*.test.mjs
```

保留的命令行入口不依赖旧仓路径：

```bash
python3 -m agents.functional_test.case_generator_agent --document /absolute/path/requirement.md
# 或从已评审测试点生成用例
python3 -m agents.functional_test.case_generator_agent --reviewed-test-points /absolute/path/points.json
```

直接启动：

```bash
export PLATFORM_RUNTIME_ENV=dev
export AGENT_DATA_DIR="$PWD/runtime/dev/functional"
python3 -m services.functional_agent.app
```

容器启动：

```bash
docker compose -f compose.local.yml build
docker compose -f compose.local.yml up -d
curl http://127.0.0.1:5004/health
```

平台配置和 LLM Secret 通过功能项目专属 Platform Client Token 获取。不得把 API 数据库、Controller 或执行目标凭据放入本项目。

## 自由脑图 Review

在线测试点和测试用例 Review 使用 schema version 2 草稿：`rows` 继续作为 Runner、JSON 和 XLSX 的标准输入，`mindmap` 保存用户可自由调整的树结构。两部分由同一个 revision 与 SHA 做 CAS 保护，必须显式保存。

- 测试点的格式、层级和质量问题允许保存；“确认并继续”会列出问题，并要求用户明确确认风险。
- 测试用例只要是可安全序列化的对象数组即可发布；质量问题不会阻断，非对象数组元素和技术安全边界仍会拒绝。
- 已发布用例可以继续编辑并产生新的不可变版本；各版本 JSON/XLSX 同源并保留下载。
- 用例脑图的前置条件、全部步骤、预期结果和测试数据各占一个直属内容节点；测试数据不是 JSON 时按文本保留。
- 旧 schema version 1 草稿按需投影，不批量改写；旧 CLI 和 Runner 仍只读取标准数组 JSON。

本期没有新增配置开关或数据库迁移。若需回滚镜像，应先保留任务卷；旧镜像无法读取 version 2 信封时，可从信封的 `rows` 字段导出标准数组后使用旧 JSON 导入流程恢复。

## 发布与回滚

镜像使用不可变版本，例如 `functional-test-agent:0.1.0-local.20260817.f1a6260`，禁止使用 `latest`。回滚只需把平台的 `FUNCTIONAL_AGENT_IMAGE` 切回上一版本；API 镜像和 runtime 不应变化。

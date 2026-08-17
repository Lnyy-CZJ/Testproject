# Functional Test Agent

功能测试智能体的独立源码项目，可单独开发、测试、构建、运行和回滚。它不依赖旧 `AItestcase_Agents` 或相邻的 API 项目。

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

## 发布与回滚

镜像使用不可变版本，例如 `functional-test-agent:0.1.0-local.20260817.f1a6260`，禁止使用 `latest`。回滚只需把平台的 `FUNCTIONAL_AGENT_IMAGE` 切回上一版本；API 镜像和 runtime 不应变化。

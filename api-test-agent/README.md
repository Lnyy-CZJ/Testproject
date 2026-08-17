# API Test Agent

API 测试智能体的独立源码项目，可单独开发、测试、构建、运行和整体回滚四个同版本镜像，不依赖相邻的功能项目。

## 安全默认值

```text
API_EXECUTION_ENABLED=false
DATABASE_PERSIST_ENABLED=false
ALLOWED_TARGETS=[]
```

首次发布只提供可信生成和 Review。生产环境中真实执行由代码级门禁固定禁止；无数据库配置时仍可生成并下载文件。

## 本机开发

```bash
python3 -m pip install -r requirements-agent.lock
python3 -m pytest -q
```

旧命令行模块仍可由 `python3 -m agents.api_test.api_testcase_agent` 启动；首次独立发布的受支持交付路径是 Web 可信生成/Review，命令行真实执行不得用于 prod。

构建四个同版本镜像：

```bash
export API_RELEASE=0.1.0-local.20260817.f1a6260
docker compose -f compose.local.yml build
```

默认启动仅包含可信生成服务：

```bash
docker compose -f compose.local.yml up -d api-test-agent
curl http://127.0.0.1:5005/health
```

回滚时四个 API 镜像必须整体切回相同 Release；功能项目镜像和 runtime 不应变化。

# 云效 Codeup、Flow、ACR 迁移与首次生产发布 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 GitHub、GitHub Actions、GHCR 发布链路安全迁移到云效顶层 `Testproject` Codeup 仓库、Flow 和 ACR，并以 `dev → main → Release Tag → 不可变镜像 digest → Prod` 完成首次正式发布和回滚演练。

**Architecture:** `Testproject` 继续采用单仓库多组件结构，只保留 `dev` 和 `main` 两个长期分支；Release 是 `main` 提交上的不可变 Git Tag，不创建 Release 分支。迁移期间 GitHub 是唯一写入源、Codeup 只运行影子流水线；最终冻结后把 Codeup 切换为唯一写入源，生产服务器只从 ACR 拉取 Flow 生成并登记到 BOM 的 digest 镜像，不执行 `git pull` 或现场构建。

**Tech Stack:** Git、云效 Codeup、云效 Flow、阿里云 ACR、Docker Buildx、Docker Compose、Python 3.12、Node.js 24、PostgreSQL 17、Alembic、Ubuntu 主机组 Runner。

**Spec:** `test-platform/docs/测试开发团队代码协作与上线发布规范.md`

## Global Constraints

- Codeup 目标固定为用户已创建的云效顶层 `Testproject` 仓库；禁止创建或使用 `ai/Testproject`、`ai/bug_agent` 作为本项目目标。
- 项目只保留 `dev` 和 `main` 两个长期分支；不创建 Release 分支。
- Prod 只能发布 `main` 上符合 `release-YYYY.MM.DD.N` 的 Tag。
- 普通组件合并与生产发布不设置固定平台维护者或人工审批人；自动门禁通过后，由轮值发布协调人在约定窗口启动。
- Flow Prod 流水线并发数固定为 `1`；同一时间不得运行两个生产部署实例。
- 生产镜像必须为 `linux/amd64`，必须使用完整 `@sha256:` digest，禁止 `latest`。
- 生产服务器禁止 `git pull` 驱动上线，禁止 `docker compose build` 现场构建。
- Prod 继续使用 HTTP `http://170.106.159.147:41873`；本次迁移不引入 HTTPS、域名或端口变更。
- Dev 与 Prod 只对齐数据库 Schema、Alembic revision 和兼容契约，不同步本机与生产业务数据。
- 不提交 `.env`、Secret、Token、KEK、SSH 私钥、云效服务连接凭证和真实数据库凭证。
- GitHub 与 Codeup 不能双向开发；影子阶段只允许 GitHub 写入，由迁移执行者单向更新 Codeup。
- 当前工作区存在大量未提交变更，未完成分类、测试、提交和推送前不得执行最终仓库切换。
- `platform-tool.yaml` Schema、生成器和接入门禁属于独立后续开发计划，不阻塞代码托管迁移；未落地前继续按公共文件同行复核规则接入工具。

## Execution-time Inputs

以下值来自已经存在的云效或 ACR 页面，执行时读取并立即校验，不写死到仓库：

- `CODEUP_REPO_URL`：从顶层 `Testproject` 的 Clone 对话框复制；必须以 `/Testproject.git` 结尾，且不能包含 `/ai/bug_agent`。
- `ACR_IMAGE_PREFIX`：从公司批准的 ACR 实例、地域和命名空间组合得到；必须是不带协议且以 `/` 结尾的完整命名空间前缀。
- `CHANGE_BASE_SHA`：Flow 根据 Push 的 before SHA 或 MR base SHA 映射的流水线变量。
- `CURRENT_COMMIT_SHA`：Flow 当前检出提交的完整 40 位 SHA。
- `FLOW_TAG_NAME`、`FLOW_TAG_COMMIT_SHA`：由 Codeup Tag 创建事件注入。
- `RELEASE_NAME`：正式运行时等于 `FLOW_TAG_NAME`；影子运行时由 main SHA 自动生成。
- `DEPLOYMENT_ID`：由 `deploy-prod.sh` 根据 Release 和部署时间生成，不由人工填写。

## Target State

```text
本机功能分支
  → Codeup Testproject/dev
  → Flow CI
  → Codeup Testproject/main
  → release-YYYY.MM.DD.N Tag
  → Flow Release
  → ACR 11 个 linux/amd64 镜像及 digest
  → Release BOM
  → test-platform-prod 主机组
  → /srv/test-platform/releases/$RELEASE_NAME/deploy-prod.sh
  → HTTP 170.106.159.147:41873
```

## Success Criteria

- Codeup `Testproject` 的 `dev`、`main` 和全部 Release Tag 与切换时 Git 基线 SHA 完全一致。
- 所有开发者从 Codeup 创建功能分支、提交 MR，并在门禁通过后合并自己的普通组件改动。
- Flow CI 在 `dev` Push 和目标为 `main` 的 MR 上自动运行并阻止失败合并。
- Flow Release 只响应 `release-*` Tag 或受控手工演练，生产并发数为 `1`。
- ACR 保存 11 个自有镜像，每个镜像 OCI version/revision 与 `versions.json` 和 Tag commit 一致。
- Release BOM 包含 Release、commit、11 个镜像 digest、组件版本、PostgreSQL digest 和 Alembic revision。
- Prod 实际容器镜像、版本、SHA、源码哈希和 BOM 一致。
- 平台首页、API、六个默认工具和两个智能体 Smoke Test 全部通过。
- Functional Agent 完成独立升级与回滚，其他组件不重启。
- API Agent Suite 四镜像完成原子升级与回滚，其他组件不重启。
- GitHub 停止写入和生产发布，仅保留为只读历史归档。

---

### Task 1: 固化迁移前 Git 基线并保护当前工作

**Files:**
- Include after verification: `test-platform/docs/测试开发团队代码协作与上线发布规范.md`
- Include after verification: `test-platform/docs/superpowers/plans/2026-09-01-yunxiao-codeup-flow-acr-migration.md`
- Inspect only: all currently modified, deleted and untracked workspace paths

**Interfaces:**
- Consumes: 当前本机 `dev`、GitHub `origin/dev`、`origin/main` 和现有 Release Tag。
- Produces: 工作区干净、已推送的 `dev` 基线和两条迁移前归档 Tag。

- [ ] **Step 1: 更新只读远端引用并记录当前状态**

```bash
git fetch --prune --tags origin
git status --porcelain=v1
git rev-list --left-right --count origin/main...dev
git log --oneline dev..origin/main
git tag --list 'release-*' --sort=-creatordate | head -n 10
```

Expected: 明确列出每个未提交文件；不得通过 `git reset --hard`、`git checkout --` 或删除目录清理用户改动。

- [ ] **Step 2: 核对大批删除是否属于已完成的目录迁移**

```bash
git diff --summary
git status --short -- Truthy_ApiAutoTest2 api-autotest test-platform log_filter_tool dating_tool
```

Expected: 每个删除文件都能归类为明确的目录迁移、产品改动或不应提交的临时产物；无法解释的删除必须保留并停止提交该路径。

- [ ] **Step 3: 将临时产物排除在提交之外**

检查并确保以下内容不进入暂存区：

```text
.codex-audit-*
.playwright-cli/
设计截图
临时 QA 输出
本地数据库
任务、日志、报告和导出产物
真实 .env 与 Secret
```

- [ ] **Step 4: 运行当前 `dev` 的完整基线测试**

```bash
python test-platform/scripts/version_tool.py validate
python -m pip install -r test-platform/backend/requirements.txt
(cd test-platform/backend && python -m pytest)
python -m pip install -r functional-test-agent/requirements.lock
(cd functional-test-agent && python -m pytest && node --test tests/ui/*.test.mjs)
python -m pip install -r api-test-agent/requirements-agent.lock
python -m pip install "$(grep '^docker==' api-test-agent/requirements-controller.lock)"
(cd api-test-agent && python -m pytest)
(cd test-platform/frontend && npm ci && npm test && npm run build)
(cd test-platform && docker compose --env-file .env.prod.example -f docker-compose.yml -f docker-compose.prod.yml config --quiet)
```

Expected: 全部命令返回 0；失败项先定位和修复，不得带失败基线迁移。

- [ ] **Step 5: 分目的提交有效改动**

至少将规范和迁移计划独立提交：

```bash
git add test-platform/docs/测试开发团队代码协作与上线发布规范.md \
  test-platform/docs/superpowers/plans/2026-09-01-yunxiao-codeup-flow-acr-migration.md
git commit -m "docs: define Codeup collaboration and migration workflow"
```

其他产品代码按组件分别暂存、测试和提交；禁止使用无范围的 `git add .` 混入临时文件。

- [ ] **Step 6: 推送基线并创建迁移前归档 Tag**

```bash
git push origin dev
git tag archive/pre-codeup-dev-2026.09.01 dev
git tag archive/pre-codeup-main-2026.09.01 origin/main
git push origin archive/pre-codeup-dev-2026.09.01 archive/pre-codeup-main-2026.09.01
```

Expected: 两条归档 Tag 不匹配 `release-*`，因此不会触发生产发布。

---

### Task 2: 统一 `dev` 与 `main` 历史并固定发布合并策略

**Files:**
- Modify: `test-platform/docs/测试开发团队代码协作与上线发布规范.md`

**Interfaces:**
- Consumes: Task 1 的干净 `dev` 和最新 `origin/main`。
- Produces: `origin/main` 成为 `dev` 祖先；文档明确 Release Tag 和 release MR 合并策略。

- [ ] **Step 1: 把生产主线历史同步回 `dev`**

```bash
git switch dev
git merge --no-ff origin/main -m "chore: sync production history before Codeup migration"
```

Expected: 保留双方历史；如果出现冲突，只解决当前变更涉及的文件并重新运行相关测试。

- [ ] **Step 2: 验证历史关系**

```bash
git merge-base --is-ancestor origin/main dev
git rev-list --left-right --count origin/main...dev
```

Expected: 第一条返回 0；第二条左侧为 `0`，右侧为 Dev 尚未发布的提交数。

- [ ] **Step 3: 在规范中增加两个明确规则**

在分支模型和 Prod 发布章节加入：

```text
项目不设置 Release 分支；正式 Release 是创建在 main 已验证提交上的不可变 Git Tag。

feature/fix → dev 可以使用 squash；dev → main 的发布合并请求必须保留 merge commit。
如果平台设置导致 dev → main 被 squash 或 rebase，发布完成后必须立即将 main 合并回 dev。
```

- [ ] **Step 4: 验证并提交**

```bash
python - <<'PY'
from pathlib import Path
text = Path("test-platform/docs/测试开发团队代码协作与上线发布规范.md").read_text()
assert "不设置 Release 分支" in text
assert "dev → main" in text
PY
git add test-platform/docs/测试开发团队代码协作与上线发布规范.md
git commit -m "docs: clarify release tag and merge strategy"
git push origin dev
```

---

### Task 3: 将生产镜像校验从 GHCR 参数化为受信任仓库前缀

**Files:**
- Modify: `test-platform/tests/test_agent_split.py`
- Modify: `test-platform/scripts/deploy-prod.sh`
- Modify: `test-platform/.env.prod.example`
- Runtime-only modify: `/srv/test-platform/env/.env.prod`

**Interfaces:**
- Consumes: `PROD_IMAGE_REPOSITORY_PREFIX`，格式为无协议、以 `/` 结尾的仓库命名空间前缀。
- Produces: 部署脚本接受受信任 ACR 前缀并继续拒绝错误仓库、可变 Tag 和非 digest 镜像。

- [ ] **Step 1: 写失败测试**

在 `test-platform/tests/test_agent_split.py` 增加断言：

```python
def test_prod_deploy_uses_configured_immutable_registry_prefix(self) -> None:
    script = (ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.prod.example").read_text(encoding="utf-8")
    self.assertIn("PROD_IMAGE_REPOSITORY_PREFIX", script)
    self.assertIn("PROD_IMAGE_REPOSITORY_PREFIX=", env_example)
    self.assertNotIn("ghcr.io/lnyy-czj", script)

def test_prod_deploy_rejects_images_outside_configured_registry(self) -> None:
    script = (ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
    self.assertIn("must use the approved image repository", script)
    self.assertIn("@sha256:[0-9a-f]{64}", script)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m unittest test-platform.tests.test_agent_split.AgentSplitContractTests.test_prod_deploy_uses_configured_immutable_registry_prefix -v
```

Expected: 因脚本仍硬编码 `ghcr.io/lnyy-czj` 而失败。

- [ ] **Step 3: 修改生产环境示例结构**

在 `test-platform/.env.prod.example` 增加：

```dotenv
PROD_IMAGE_REPOSITORY_PREFIX=registry.cn-shanghai.aliyuncs.com/testproject/
```

将 11 个镜像示例改为同一受信任前缀下的完整 digest；真实地域和命名空间在 ACR Task 完成后写入服务器真实 `.env.prod`，示例值不作为线上凭证。

- [ ] **Step 4: 修改部署脚本验证逻辑**

`deploy-prod.sh` 必须从 `base_env` 安全读取 `PROD_IMAGE_REPOSITORY_PREFIX`，禁止 `source .env`；传给 Python 校验器后检查：

```python
expected = approved_prefix + repository_name + "@sha256:"
if not value.startswith(expected):
    raise SystemExit(f"{key} must use the approved image repository")
if not re.fullmatch(re.escape(approved_prefix + repository_name) + r"@sha256:[0-9a-f]{64}", value):
    raise SystemExit(f"{key} must use an immutable sha256 digest")
```

组件与仓库名映射覆盖全部 11 个镜像变量；API Agent Suite 的四个镜像仍作为同一组件原子校验。

- [ ] **Step 5: 运行回归测试和 Compose 检查**

```bash
python -m unittest test-platform.tests.test_agent_split -v
(cd test-platform && docker compose --env-file .env.prod.example -f docker-compose.yml -f docker-compose.prod.yml config --quiet)
```

Expected: 测试和 Compose 检查通过，仓库中运行时代码不再硬编码个人 GHCR 命名空间。

- [ ] **Step 6: 提交参数化改动**

```bash
git add test-platform/tests/test_agent_split.py \
  test-platform/scripts/deploy-prod.sh \
  test-platform/.env.prod.example
git commit -m "chore: parameterize production image registry"
git push origin dev
```

---

### Task 4: 将现有云效顶层 `Testproject` 初始化为完整镜像仓库

**Files:**
- No repository file changes
- External resource: 云效 Codeup 顶层 `Testproject`

**Interfaces:**
- Consumes: Task 1-3 已推送的 GitHub 基线和 Codeup 页面提供的准确 Clone URL。
- Produces: 名为 `codeup` 的本地远端，以及包含完整分支和 Tag 的 Codeup 仓库。

- [ ] **Step 1: 在 Codeup 页面确认仓库为空且目标正确**

确认页面路径最终仓库名为 `Testproject`，提交数和分支数为 `0`。如果仓库已经出现其他提交，停止推送并先核对来源；不得使用 `--force` 覆盖不明内容。

- [ ] **Step 2: 复制 Codeup 提供的 SSH 或 HTTPS Clone URL并添加远端**

```bash
read -r CODEUP_REPO_URL
case "$CODEUP_REPO_URL" in
  */Testproject.git) ;;
  *) echo "Codeup URL 必须指向顶层 Testproject" >&2; exit 1 ;;
esac
case "$CODEUP_REPO_URL" in
  */ai/bug_agent.git) echo "禁止使用 ai/bug_agent" >&2; exit 1 ;;
esac
git remote add codeup "$CODEUP_REPO_URL"
git remote -v
```

Expected: `origin` 仍是 GitHub，`codeup` 只指向顶层 `Testproject`，URL 中不包含 `/ai/bug_agent`。

- [ ] **Step 3: 首次推送全部本地分支和 Tag**

```bash
git push codeup --all
git push codeup --tags
```

禁止使用会覆盖 Codeup 未知引用的长期 `git push --mirror`。首次推送后影子阶段也只能由迁移执行者执行 GitHub → Codeup 单向更新。

- [ ] **Step 4: 比较关键引用 SHA**

```bash
git ls-remote origin refs/heads/dev refs/heads/main 'refs/tags/release-*' > /tmp/github-refs.txt
git ls-remote codeup refs/heads/dev refs/heads/main 'refs/tags/release-*' > /tmp/codeup-refs.txt
python - <<'PY'
from pathlib import Path

def refs(path: str) -> dict[str, str]:
    result = {}
    for line in Path(path).read_text().splitlines():
        sha, ref = line.split()
        result[ref] = sha
    return result

github = refs("/tmp/github-refs.txt")
codeup = refs("/tmp/codeup-refs.txt")
assert github == codeup, {"github_only": github.keys() - codeup.keys(), "codeup_only": codeup.keys() - github.keys()}
print(f"verified {len(github)} refs")
PY
```

Expected: `dev`、`main` 和所有 Release Tag SHA 完全一致。

---

### Task 5: 配置 Codeup 分支、Tag 和团队权限

**Files:**
- External resource: Codeup `Testproject` 仓库设置

**Interfaces:**
- Consumes: 完整 Codeup Git 历史。
- Produces: 与 V1.1 团队规范一致的自助合并规则。

- [ ] **Step 1: 配置 `dev` 保护规则**

```text
禁止直接 Push：开启
禁止强制 Push：开启
必须通过合并请求：开启
必须通过 Flow CI 状态检查：在影子 CI 连续成功后开启
普通组件最少人工审批数：0
允许 MR 发起人在检查通过后合并：开启
新提交使旧检查结果失效：开启
```

- [ ] **Step 2: 配置 `main` 保护规则**

```text
禁止直接 Push：开启
禁止强制 Push：开启
必须通过合并请求：开启
必须通过 Flow CI 状态检查：开启
发布 MR 来源：dev
普通发布最少人工审批数：0
合并方式：merge commit
```

- [ ] **Step 3: 配置 Release Tag 规则**

将 `release-*` Tag 创建权限授予团队发布成员；Tag 一经创建不得移动或复用。创建错误时废弃该 Tag 并使用递增的下一发布号，不能把同名 Tag 指向新提交。

- [ ] **Step 4: 配置成员权限**

```text
测试开发成员：Codeup 开发者
Flow CI：运行权限
Flow Release：运行权限
流水线配置和服务连接：仅少量管理员拥有所有权限
主机组：团队流水线可使用，管理员可编辑
```

轮值发布协调人是当次执行角色，不是长期管理角色，也不获得 Secret 明文权限。

---

### Task 6: 创建 ACR 命名空间、11 个仓库和服务连接

**Files:**
- External resource: 公司 ACR 实例
- External resource: Flow ACR 服务连接
- Runtime-only modify: `/srv/test-platform/env/.env.prod`

**Interfaces:**
- Consumes: 公司已授权的 ACR 实例、地域和命名空间策略。
- Produces: 11 个私有镜像仓库和一个仅供 Flow 构建/部署使用的服务连接。

- [ ] **Step 1: 选择 ACR 实例与地域**

优先使用公司现有 ACR 企业版实例；构建集群选择与 ACR 相同或网络最稳定的地域。生产服务器不在同一 VPC 时，使用 ACR 公网地址并配置最小白名单；不得假定 `170.106.159.147` 是阿里云 ECS。

- [ ] **Step 2: 创建命名空间**

命名空间使用公司批准的名称，并把页面显示的无协议前缀保存为 Flow 变量 `ACR_IMAGE_PREFIX`：

```text
ACR_IMAGE_PREFIX
```

变量值必须匹配 `^[a-z0-9][a-z0-9.-]+(?::[0-9]+)?/[a-z0-9][a-z0-9._/-]*/$`。

- [ ] **Step 3: 创建 11 个私有仓库**

```text
testproject-platform-gateway
testproject-platform-backend
testproject-trackevents-web
testproject-log-filter-tool
testproject-truthy-search
testproject-api-autotest
testproject-functional-test-agent
testproject-api-test-agent
testproject-api-execution-controller
testproject-api-egress-proxy
testproject-api-test-executor
```

- [ ] **Step 4: 创建 Flow 服务连接**

服务连接只授予以上命名空间所需的镜像 Push/Pull 权限；团队成员获得“使用服务连接”能力，不获得 RAM 密钥明文。

- [ ] **Step 5: 更新服务器受信任镜像前缀**

在服务器执行前先备份：

```bash
sudo install -m 600 /srv/test-platform/env/.env.prod \
  /srv/test-platform/backups/.env.prod.pre-acr-20260901
```

然后把真实 `PROD_IMAGE_REPOSITORY_PREFIX` 写入 `/srv/test-platform/env/.env.prod`，权限保持 `600`。此时不修改 `.env.images.current`，因此不会提前切换运行镜像。

---

### Task 7: 建立 Flow CI 影子流水线

**Files:**
- Read as source of truth: `.github/workflows/ci.yml`
- External resource: Flow pipeline `Testproject CI`

**Interfaces:**
- Consumes: Codeup `Testproject` 源码和现有测试命令。
- Produces: 与 GitHub CI 等价的 Codeup 状态检查，不部署 Prod。

- [ ] **Step 1: 创建流水线和代码源**

```text
流水线名称：Testproject CI
代码源：Codeup 顶层 Testproject
触发事件：dev Push；目标为 main 的 MR 新建/更新
下载深度：0，版本门禁需要完整 Git 历史
部署阶段：不存在
```

- [ ] **Step 2: 配置版本门禁 Job**

```bash
python test-platform/scripts/version_tool.py validate
python test-platform/scripts/version_tool.py check-bump --base "$CHANGE_BASE_SHA"
```

Flow 必须使用本次事件提供的 base/before SHA，不能固定写死 GitHub 环境变量。

- [ ] **Step 3: 配置 Python 和 Node 测试 Job**

复用 Task 1 Step 4 的平台后端、两个智能体和平台前端命令，Python 固定 `3.12`，Node 固定 `24`。

- [ ] **Step 4: 配置生产 Compose 静态检查 Job**

```bash
cd test-platform
docker compose --env-file .env.prod.example -f docker-compose.yml -f docker-compose.prod.yml config --quiet
! docker compose --env-file .env.prod.example -f docker-compose.yml -f docker-compose.prod.yml config | grep -qE '^[[:space:]]+build:'
```

同时复用现有 `jq` 检查，确保所有 Prod 服务只使用镜像、关键数据卷和 KEK 挂载存在。

- [ ] **Step 5: 配置 11 镜像 Build-only Job**

按照 `.github/workflows/ci.yml` 当前矩阵构建 11 个 `linux/amd64` 镜像，传入：

```text
APP_VERSION=$COMPONENT_VERSION
APP_REVISION=$CURRENT_COMMIT_SHA
APP_BUILD_DIRTY=false
```

CI 阶段只构建验证，不 Push ACR。

- [ ] **Step 6: 连续运行三次影子 CI**

分别覆盖：

```text
dev 普通 Push
普通组件 MR 更新
仅文档变化的 MR 更新
```

Expected: Flow 与 GitHub CI 结论一致；失败必须定位差异，不能直接关闭检查。

- [ ] **Step 7: 将 Flow CI 设为 Codeup 必需状态检查**

只有三次影子运行稳定后，才在 `dev` 和 `main` 保护规则中启用必需状态检查。

---

### Task 8: 建立 Flow Release 构建、BOM 和制品流水线

**Files:**
- Read as source of truth: `.github/workflows/release.yml`
- Reuse: `test-platform/scripts/version_tool.py`
- Reuse: `test-platform/scripts/deploy-prod.sh`
- External resource: Flow pipeline `Testproject Release`

**Interfaces:**
- Consumes: `release-*` Tag、Codeup commit、ACR 服务连接。
- Produces: 11 个 ACR digest 镜像和与当前 GitHub Release 同结构的部署包。

- [ ] **Step 1: 创建 Tag 触发器**

```text
代码源：Codeup Testproject
触发事件：Tag 创建
Tag 过滤：^release-[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]+$
流水线并发数：1
人工审批卡点：不配置
```

- [ ] **Step 2: 增加发布来源校验**

```bash
git merge-base --is-ancestor "$FLOW_TAG_COMMIT_SHA" origin/main
test "$(git rev-parse "$FLOW_TAG_NAME^{commit}")" = "$FLOW_TAG_COMMIT_SHA"
python test-platform/scripts/version_tool.py validate
```

Expected: Tag 不在 `main` 上或 Tag SHA 不一致时立即失败。

- [ ] **Step 3: 运行与 CI 相同的测试和生产 Compose 门禁**

所有测试通过后才能登录 ACR 和 Push 镜像。

- [ ] **Step 4: 配置 11 镜像 Push 矩阵**

构建矩阵逐项复制 `.github/workflows/release.yml:61-115` 的 `component_id`、context 和 Dockerfile；镜像名使用 Task 6 的 ACR 仓库。所有镜像使用 Release Tag 作为可读 Tag，同时记录 Push 返回的 digest；Prod 只消费 digest。

- [ ] **Step 5: 写入 OCI 与运行元数据**

每个镜像必须包含：

```text
org.opencontainers.image.version=$COMPONENT_VERSION
org.opencontainers.image.revision=$FLOW_TAG_COMMIT_SHA
APP_VERSION=$COMPONENT_VERSION
APP_REVISION=$FLOW_TAG_COMMIT_SHA
APP_BUILD_DIRTY=false
APP_CONTENT_SHA256=$COMPONENT_CONTENT_SHA256
```

- [ ] **Step 6: 生成 `.env.images` 和 `image-map.json`**

每个值必须形如：

```text
PLATFORM_GATEWAY_IMAGE=${ACR_IMAGE_PREFIX}testproject-platform-gateway@${PLATFORM_GATEWAY_DIGEST}
```

其中 `PLATFORM_GATEWAY_DIGEST` 必须匹配 `^sha256:[0-9a-f]{64}$`，其他十个 digest 使用相同规则。

11 个变量齐全后才能生成 BOM。

- [ ] **Step 7: 生成部署包**

```bash
mkdir -p deploy-bundle
cp test-platform/docker-compose.yml deploy-bundle/
cp test-platform/docker-compose.prod.yml deploy-bundle/
cp test-platform/versions.json deploy-bundle/
cp test-platform/scripts/deploy-prod.sh deploy-bundle/
cp test-platform/scripts/version_tool.py deploy-bundle/
python test-platform/scripts/version_tool.py bom \
  --release "$FLOW_TAG_NAME" \
  --commit "$FLOW_TAG_COMMIT_SHA" \
  --images deploy-bundle/image-map.json \
  --output deploy-bundle/release-manifest.json
```

- [ ] **Step 8: 上传 Flow 制品**

部署包至少包含：

```text
.env.images
image-map.json
release-manifest.json
versions.json
docker-compose.yml
docker-compose.prod.yml
deploy-prod.sh
version_tool.py
```

---

### Task 9: 接入 `170.106.159.147` 到自建生产主机组

**Files:**
- External resource: Flow 主机组 `test-platform-prod`
- Runtime paths: `/srv/test-platform/**`

**Interfaces:**
- Consumes: Flow 部署制品和 ACR Pull 凭证。
- Produces: Runner 在线、可下载制品并调用现有生产部署脚本的主机组。

- [ ] **Step 1: 创建自建主机组**

```text
名称：test-platform-prod
环境：production
主机：170.106.159.147
接入方式：自建/公网主机或混合云托管；只有确认属于阿里云 ECS 时才选择 ECS
```

- [ ] **Step 2: 安装并验证 Runner**

使用云效页面为该主机生成的安装命令，在服务器执行。Runner 必须使用出站连接访问云效；不新增对公网开放的管理端口。

- [ ] **Step 3: 验证部署用户权限**

部署用户必须能够：

```bash
docker version
docker compose version
test -d /srv/test-platform
test -w /srv/test-platform/releases
test -w /srv/test-platform/state
```

需要提权时只授予 Docker 和 `/srv/test-platform` 所需权限，不授予读取其他系统 Secret 的权限。

- [ ] **Step 4: 备份当前生产状态**

```bash
sudo install -m 600 /srv/test-platform/state/current.json \
  /srv/test-platform/backups/current.pre-codeup-20260901.json
sudo install -m 600 /srv/test-platform/env/.env.images.current \
  /srv/test-platform/backups/.env.images.pre-codeup-20260901
docker ps --format '{{.Names}} {{.Image}}' | sudo tee /srv/test-platform/backups/containers.pre-codeup-20260901.txt >/dev/null
```

数据库、生产 `.env`、KEK 和 Secret 文件继续保留在服务器，不上传 Flow 制品。

- [ ] **Step 5: 配置部署任务但保持禁用**

部署任务下载 Flow 制品到独立临时目录，再安装到：

```text
/srv/test-platform/releases/$RELEASE_NAME
```

部署阶段在影子验证完成前通过 Flow 条件关闭，防止首次测试误触发 Prod。

---

### Task 10: 完成不部署 Prod 的影子 Release 验证

**Files:**
- No repository file changes
- External resources: Flow Release、ACR、Flow artifacts

**Interfaces:**
- Consumes: Codeup `main` 当前提交。
- Produces: 与 GitHub Release 等价的 ACR 镜像、digest 和 BOM，不改变生产容器。

- [ ] **Step 1: 手工运行 Release 流水线的 Build-only 模式**

运行参数：

```text
source_ref=main 当前 SHA
MAIN_SHA=$(git rev-parse origin/main)
RELEASE_NAME=shadow-codeup-${MAIN_SHA:0:12}
deploy_enabled=false
```

该名称不匹配 `release-*`，不能被当成正式生产发布。

- [ ] **Step 2: 验证 ACR 镜像平台与标签**

对全部 11 个镜像执行等价检查：

```bash
docker buildx imagetools inspect "$IMAGE_REF"
```

Expected: 存在 `linux/amd64`；OCI version/revision 正确；没有依赖 `latest`。

- [ ] **Step 3: 验证 BOM**

```bash
python - <<'PY'
import json
from pathlib import Path
bom = json.loads(Path("deploy-bundle/release-manifest.json").read_text())
assert bom["schema_version"] == 2
assert len([image for component in bom["components"].values() for image in component["images"].values()]) == 11
assert all("@sha256:" in image for component in bom["components"].values() for image in component["images"].values())
print("BOM verified")
PY
```

- [ ] **Step 4: 比较 GitHub 与 Flow 构建元数据**

相同 commit 下比较组件 version、revision、内容哈希、Dockerfile/context 和 BOM 字段；跨架构或不同 registry 的 digest 不要求相同。

- [ ] **Step 5: 确认 Prod 未变化**

```bash
ssh ubuntu@170.106.159.147 'docker ps --format "{{.Names}} {{.Image}}"'
```

Expected: 容器镜像和启动时间与影子构建前一致。

---

### Task 11: 执行 GitHub → Codeup 最终切换

**Files:**
- Runtime Git remote configuration only
- External resources: GitHub、Codeup、团队通知

**Interfaces:**
- Consumes: 稳定的 Flow CI 和影子 Release。
- Produces: Codeup 成为唯一写入源，GitHub 只读归档。

- [ ] **Step 1: 宣布短暂停写窗口**

通知团队从该时间点停止 GitHub 和 Codeup 的 Push/MR；正在进行的功能分支先保留在开发者本地，不在窗口中合并。

- [ ] **Step 2: 执行最后一次 GitHub → Codeup 单向推送**

```bash
git fetch --prune --tags origin
git switch dev
git pull --ff-only origin dev
git push codeup dev main
git push codeup --tags
```

- [ ] **Step 3: 再次比较全部关键引用**

重复 Task 4 Step 4；任何 SHA 不一致都必须停止切换。

- [ ] **Step 4: 切换本机默认远端**

```bash
git remote rename origin github-archive
git remote rename codeup origin
git remote -v
git fetch --prune --tags origin
```

Expected: 新 `origin` 指向 Codeup 顶层 `Testproject`，`github-archive` 只保留核对用途。

- [ ] **Step 5: 停止 GitHub 写入和发布**

```text
GitHub 仓库设置为只读/归档或收紧 Push 权限
GitHub Actions Production Release 停用
禁止创建新的 GitHub release-* Tag
保留历史 Workflow、Release、GHCR 镜像和审计记录至少一个发布周期
```

- [ ] **Step 6: 恢复团队开发**

所有开发者从 Codeup 重新 Clone，或按 Task 11 Step 4 切换远端；新 MR 只能创建在 Codeup。

---

### Task 12: 创建首个 Codeup Release 并部署 Prod

**Files:**
- External resources: Codeup MR、Flow Release、ACR、Prod 主机组
- Runtime records: `/srv/test-platform/releases/$RELEASE_NAME`、`/srv/test-platform/state/**`

**Interfaces:**
- Consumes: 已验证的 `dev`、Flow CI 和可用主机组。
- Produces: 首个云效管理的正式生产 Release。

- [ ] **Step 1: 创建 `dev → main` 发布 MR**

要求：

```text
Flow CI 全部通过
使用 merge commit
发布范围和组件版本明确
数据库 migration revision 明确
回滚目标为切换前 current.json
```

- [ ] **Step 2: 合并并验证 main SHA**

```bash
git fetch origin
git rev-parse origin/main
git merge-base --is-ancestor origin/dev origin/main
```

Expected: 发布 MR 使用 merge commit，`dev` 已包含在 `main` 历史中。

- [ ] **Step 3: 创建新 Release Tag**

如果实际执行日期仍为 2026-09-01，首个候选为：

```bash
git tag -a release-2026.09.01.1 origin/main -m "release: first Codeup Flow production deployment"
git push origin release-2026.09.01.1
```

如果执行日期或当日序号已经变化，按 `release-YYYY.MM.DD.N` 选择未使用的新编号；不得复用已有 Tag。

- [ ] **Step 4: Flow 自动构建并由轮值协调人启动部署**

流程：

```text
Tag 校验
→ 测试
→ 构建并推送 11 个 ACR 镜像
→ 生成 BOM
→ 下载制品到 test-platform-prod
→ ACR docker login
→ 安装 Release 包
→ 调用 deploy-prod.sh
→ docker logout
```

- [ ] **Step 5: 验证数据库仅迁移 Schema**

确认部署脚本执行目标 Alembic revision，但不导入本机任务、用户、日志、报告或其他业务数据。迁移前备份必须存在，失败时停止后续服务启动。

- [ ] **Step 6: 运行生产验收**

```text
平台首页：http://170.106.159.147:41873/
平台 API 健康检查
TrackEvents
Log Filter
Truthy Search
API Autotest
Functional Test Agent
API Test Agent
```

同时检查版本矩阵：Prod 实际版本、SHA、内容哈希、digest、数据库 revision 和 Release BOM 一致。

- [ ] **Step 7: 保存首次发布记录**

检查以下文件已经生成且不包含 Secret：

```text
/srv/test-platform/state/current.json
/srv/test-platform/state/deployments/$DEPLOYMENT_ID.json
/srv/test-platform/state/deployments/$DEPLOYMENT_ID.md
/srv/test-platform/releases/$RELEASE_NAME/release-manifest.json
```

---

### Task 13: 完成单组件升级和回滚演练

**Files:**
- Reuse: `test-platform/scripts/deploy-prod.sh`
- Runtime records: `/srv/test-platform/state/deployments/**`

**Interfaces:**
- Consumes: 首个 Codeup Release 的 ACR digest 和切换前 digest。
- Produces: 两个智能体独立发布/回滚的可验证证据。

- [ ] **Step 1: 记录演练前容器 ID 和启动时间**

```bash
docker ps --format '{{.Names}} {{.ID}} {{.RunningFor}} {{.Image}}' > /tmp/containers-before-component-drill.txt
```

- [ ] **Step 2: Functional Agent 执行旧 → 新 → 旧 → 新**

每次调用 `deploy-prod.sh "$RELEASE_DIR" functional-test-agent` 的等价组件模式，并验证：

```text
functional-test-agent 版本、SHA、digest 正确
平台和 API Agent 容器 ID 不变
任务列表和历史产物仍可读取
每次操作生成 Deployment Record
```

- [ ] **Step 3: API Agent Suite 四镜像原子演练**

组件参数使用 `api-test-agent`，四个镜像同时切换：

```text
API_AGENT_IMAGE
API_EXECUTION_CONTROLLER_IMAGE
API_EGRESS_PROXY_IMAGE
API_EXECUTOR_IMAGE
```

默认未启用的执行链不需要启动，但四个期望 digest 必须作为同一版本组合记录和回滚。

- [ ] **Step 4: 比较其他组件是否重启**

```bash
docker ps --format '{{.Names}} {{.ID}} {{.RunningFor}} {{.Image}}' > /tmp/containers-after-component-drill.txt
diff -u /tmp/containers-before-component-drill.txt /tmp/containers-after-component-drill.txt
```

Expected: 除被演练组件外，其他默认服务容器 ID 不变。

- [ ] **Step 5: 将两个组件恢复到新版本并再次 Smoke Test**

演练结束时 Prod 必须回到首个 Codeup Release 的期望 ACR digest，不得停留在旧版本。

---

### Task 14: 更新运行文档并关闭迁移状态

**Files:**
- Modify: `test-platform/docs/测试开发团队代码协作与上线发布规范.md`
- Modify locally, do not commit while it contains credentials: `环境信息.md`
- Generate from deployment state: Dev/Prod 发布记录 Markdown

**Interfaces:**
- Consumes: 实际 Codeup、Flow、ACR、主机组和首发结果。
- Produces: 与真实运行方式一致的团队文档和发布记录。

- [ ] **Step 1: 将团队规范状态改为正式生效**

只有 Codeup、Flow、ACR 和回滚演练全部通过后，才将文档状态从“团队试行”改为“生效中”。`platform-tool.yaml` 自动化尚未完成时，保留其过渡期说明，不宣布自助接入自动化已完成。

- [ ] **Step 2: 更新《环境信息.md》的部署方式**

将旧流程：

```text
git push dev → 服务器 git pull → docker compose up --build
```

替换为：

```text
Codeup main Release Tag → Flow → ACR digest → test-platform-prod 主机组 → deploy-prod.sh
```

该文件含真实凭证，继续保存在本机受控位置，不提交 Codeup。

- [ ] **Step 3: 生成 Dev 和 Prod 发布记录**

使用 `version_tool.py report` 和生产 `current.json` 生成报告，至少包含：

```text
产品版本
Release Tag
Git SHA
各组件 SemVer
各镜像 digest
数据库 Alembic revision
Config Release ID
部署时间
验收结果
前一部署记录
```

- [ ] **Step 4: 提交非敏感文档**

```bash
git add test-platform/docs/测试开发团队代码协作与上线发布规范.md
git commit -m "docs: record Codeup Flow production cutover"
git push origin dev
```

---

## Rollback Strategy

### Codeup 切换失败

- 在首次 Codeup Prod 发布前，GitHub、GitHub Actions、GHCR 和旧生产 `current.json` 全部保留。
- 恢复开发时，把本机 `github-archive` 重新命名为 `origin`，暂停 Codeup 写入。
- 禁止两个仓库同时恢复写入；必须发布一次明确的事实源切换通知。

### Flow/ACR 构建失败

- 不执行部署阶段，Prod 保持现有 GHCR digest。
- 修复 Flow 或 ACR 服务连接后重新使用新的影子运行，不移动已有 Release Tag。

### 首次生产部署失败

- `deploy-prod.sh` 使用 `/srv/test-platform/state/current.json` 和上一 `.env.images.current` 恢复旧镜像组合。
- 数据库迁移不自动 downgrade；只有存在不兼容迁移且应用无法使用旧版本时，才按迁移前备份整体恢复数据库。
- 回滚后仍保留失败 Deployment Record 和 Flow 日志。

### 主机 Runner 不可用

- 不改生产容器。
- 继续保留原 SSH 部署通道作为一个发布周期内的应急回退，但应执行同一 Release 包和 `deploy-prod.sh`，不能回退为服务器 `git pull` 和现场构建。

---

## Explicitly Deferred Follow-up

以下内容单独制定开发计划，不与本次 Codeup/Flow/ACR 迁移混在同一实施批次：

```text
platform-tool.yaml JSON/YAML Schema
工具清单生成器
Compose/Nginx/菜单/构建矩阵自动生成
所有现有工具接入清单补录
接入冲突 CI 门禁
```

在该后续计划完成前，V1.1 规范中的工具自助接入章节按“目标规范 + 过渡期同行复核”执行。

---

## Final Verification Checklist

- [ ] Codeup 目标为顶层 `Testproject`，没有使用 `ai/` 路径。
- [ ] `dev`、`main` 和全部 Tag SHA 已核对。
- [ ] 没有 Release 分支。
- [ ] GitHub 和 Codeup 没有双向写入。
- [ ] Flow CI 与旧 CI 结果一致。
- [ ] Flow Release 无固定人工审批，Prod 并发数为 `1`。
- [ ] 11 个 ACR 镜像全部使用 digest。
- [ ] `deploy-prod.sh` 不再硬编码个人 GHCR 前缀。
- [ ] Prod 不执行 Git Pull 或 Docker Build。
- [ ] 数据库只迁移 Schema，没有同步本机业务数据。
- [ ] HTTP `41873` 保持可用。
- [ ] 八项生产 Smoke Test 通过。
- [ ] 两个智能体独立升级和回滚演练通过。
- [ ] Dev/Prod 发布记录已生成。
- [ ] GitHub 已转为只读历史归档。

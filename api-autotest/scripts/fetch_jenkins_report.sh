#!/usr/bin/env bash
#
# 从 Jenkins 拉取 Allure HTML 报告并发布（设计 12.2 的远程实现）。
#
# 功能说明:
#   Phase 0 实测确认 Jenkins 为远程服务器（本机无 JENKINS_HOME），
#   因此本脚本不走本地文件系统读取，而是通过 Jenkins HTTP JSON API
#   定位最近一次已完成且包含 HTML 归档的构建，下载归档产物后调用
#   publish_allure_report.sh 完成原子发布。凭证只从环境变量读取，
#   不落盘、不入库。
#
# 用法:
#   fetch_jenkins_report.sh [报告根目录]
#
# 参数说明:
#   报告根目录  可选，透传给发布脚本，默认 <项目根>/reports。
#
# 环境变量:
#   JENKINS_URL    Jenkins 根地址，默认 http://10.0.30.33:8081
#   JENKINS_USER   认证用户名，必填
#   JENKINS_TOKEN  认证密码或 API Token，必填（与 JENKINS_USER 配对）
#   JOB_NAME       任务名，默认 truthy-api-autotest（Phase 0 实测值）
#   BUILD_NUMBER   可选，显式指定构建号；缺省从新到旧扫描已完成构建，
#                  选择第一个包含 allure-report-publish/index.html 的
#                  构建，不按 SUCCESS/FAILURE/UNSTABLE 过滤。
#   PUBLISH_TASK_ID 必填的平台根任务 ID；拉取与发布全链路显式透传。
#   PUBLISH_PROJECT_ID 工具项目 ID；旧 Jenkins 任务缺省为 truthy 并输出提示。
#
# 返回值（退出码）:
#   0  拉取并发布成功；
#   2  缺少必需环境变量或参数错误；
#   5  未找到包含 HTML 归档的已完成构建；
#   6  API 请求、下载或解压失败；
#   其余 透传发布脚本退出码（3=锁冲突，4=发布失败）。

set -euo pipefail

log() { echo "[fetch_jenkins_report] $*" >&2; }
die() { local code="$1"; shift; log "错误: $*"; exit "$code"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPORT_ROOT="${1:-$PROJECT_ROOT/reports}"

JENKINS_URL="${JENKINS_URL:-http://10.0.30.33:8081}"
JOB_NAME="${JOB_NAME:-truthy-api-autotest}"
# 归档产物相对路径依赖 Jenkinsfile 12.1 的统一 dir(PROJECT_DIR) 作用域。
ARTIFACT_DIR="allure-report-publish"
ARTIFACT_ENTRY="$ARTIFACT_DIR/index.html"

[ -n "${JENKINS_USER:-}" ] || die 2 "缺少环境变量 JENKINS_USER"
[ -n "${JENKINS_TOKEN:-}" ] || die 2 "缺少环境变量 JENKINS_TOKEN"
[ -n "${PUBLISH_TASK_ID:-}" ] || die 2 "缺少环境变量 PUBLISH_TASK_ID"
printf '%s' "$PUBLISH_TASK_ID" | LC_ALL=C grep -Eq '^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$' \
    || die 2 "PUBLISH_TASK_ID 格式非法: $PUBLISH_TASK_ID"
if [ -z "${PUBLISH_PROJECT_ID:-}" ]; then
    log "弃用提示：旧任务未提供 PUBLISH_PROJECT_ID，兼容期默认使用 truthy"
fi
PUBLISH_PROJECT_ID="${PUBLISH_PROJECT_ID:-truthy}"
printf '%s' "$PUBLISH_PROJECT_ID" | LC_ALL=C grep -Eq '^[a-z][a-z0-9-]{1,31}$' \
    || die 2 "PUBLISH_PROJECT_ID 格式非法: $PUBLISH_PROJECT_ID"

# curl 统一参数：-s 静默、-g 关闭 URL 通配（Jenkins zip 路径含 *）、
# -f HTTP 错误即失败、--retry 抗瞬时网络抖动。
jenkins_curl() {
    curl -sgf --retry 3 --retry-delay 2 \
        -u "$JENKINS_USER:$JENKINS_TOKEN" "$@"
}

# 查询构建的归档清单与参数，只有 HTML 入口和 PLATFORM_TASK_ID 同时匹配
# 才允许被选中。调用者环境变量不能覆盖 Jenkins 已固化的构建归属。
build_has_report_artifact() {
    local build_number="$1"
    local body
    body="$(jenkins_curl \
        "$JENKINS_URL/job/$JOB_NAME/$build_number/api/json?tree=artifacts[relativePath],actions[parameters[name,value]]" \
        2>/dev/null)" || return 1
    printf '%s' "$body" | ARTIFACT_ENTRY="$ARTIFACT_ENTRY" \
        EXPECTED_TASK_ID="$PUBLISH_TASK_ID" EXPECTED_PROJECT_ID="$PUBLISH_PROJECT_ID" python3 -c '
import json, os, sys
data = json.load(sys.stdin)
paths = [a.get("relativePath", "") for a in data.get("artifacts", [])]
parameters = [
    parameter
    for action in data.get("actions", []) if isinstance(action, dict)
    for parameter in (action.get("parameters") or []) if isinstance(parameter, dict)
]
task_ids = [p.get("value") for p in parameters if p.get("name") == "PLATFORM_TASK_ID"]
project_ids = [p.get("value") for p in parameters if p.get("name") == "PROJECT_ID"]
project_matches = project_ids == [os.environ["EXPECTED_PROJECT_ID"]]
# 兼容项目参数上线前的 Truthy 构建；其他项目绝不允许缺省归属。
if not project_ids and os.environ["EXPECTED_PROJECT_ID"] == "truthy":
    project_matches = True
valid = (
    os.environ["ARTIFACT_ENTRY"] in paths
    and task_ids == [os.environ["EXPECTED_TASK_ID"]]
    and project_matches
)
sys.exit(0 if valid else 1)
'
}

# ---------------- 选择目标构建 ----------------

SELECTED_BUILD=""
BUILD_RESULT=""
BUILD_URL=""

if [ -n "${BUILD_NUMBER:-}" ]; then
    # 显式构建号：直接校验该构建存在且包含归档。
    log "校验指定构建 #$BUILD_NUMBER"
    build_has_report_artifact "$BUILD_NUMBER" \
        || die 5 "构建 #$BUILD_NUMBER 不存在或缺少 $ARTIFACT_ENTRY"
    SELECTED_BUILD="$BUILD_NUMBER"
else
    # 从新到旧扫描已完成构建（result 非 null），选择第一个含归档的，
    # 不按结果过滤：失败构建的报告同样有排查价值（设计 12.2）。
    log "扫描 $JOB_NAME 的已完成构建……"
    BUILDS_JSON="$(jenkins_curl \
        "$JENKINS_URL/job/$JOB_NAME/api/json?tree=builds[number,result,url]")" \
        || die 6 "无法获取构建列表: $JENKINS_URL/job/$JOB_NAME"
    SELECTED_BUILD="$(printf '%s' "$BUILDS_JSON" | python3 -c '
import json, sys
data = json.load(sys.stdin)
# result 为 null 表示构建仍在进行，跳过；其余结果（含 FAILURE）均可选。
numbers = [b["number"] for b in data.get("builds", []) if b.get("result")]
print("\n".join(str(n) for n in sorted(numbers, reverse=True)))
')" || die 6 "解析构建列表失败"
    for candidate in $SELECTED_BUILD; do
        if build_has_report_artifact "$candidate"; then
            SELECTED_BUILD="$candidate"
            break
        fi
        SELECTED_BUILD=""
    done
    [ -n "$SELECTED_BUILD" ] || die 5 "未找到包含 $ARTIFACT_ENTRY 的已完成构建"
fi

# 读取选中构建的 result 与 URL 元信息。
BUILD_JSON="$(jenkins_curl \
    "$JENKINS_URL/job/$JOB_NAME/$SELECTED_BUILD/api/json?tree=result,url")" \
    || die 6 "无法获取构建 #$SELECTED_BUILD 详情"
BUILD_RESULT="$(printf '%s' "$BUILD_JSON" | python3 -c \
    'import json,sys; print(json.load(sys.stdin).get("result") or "UNKNOWN")')"
BUILD_URL="$(printf '%s' "$BUILD_JSON" | python3 -c \
    'import json,sys; print(json.load(sys.stdin).get("url") or "")')"
log "选中构建 #${SELECTED_BUILD}（result=${BUILD_RESULT}）"

# ---------------- 下载与解压归档 ----------------

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/fetch_jenkins_report.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

ZIP_PATH="$WORK_DIR/$ARTIFACT_DIR.zip"
log "下载归档: $ARTIFACT_DIR/**"
jenkins_curl --output "$ZIP_PATH" \
    "$JENKINS_URL/job/$JOB_NAME/$SELECTED_BUILD/artifact/$ARTIFACT_DIR/*zip*/$ARTIFACT_DIR.zip" \
    || die 6 "下载归档失败（构建 #${SELECTED_BUILD}）"

unzip -q "$ZIP_PATH" -d "$WORK_DIR" || die 6 "解压归档失败: $ZIP_PATH"
HTML_DIR="$WORK_DIR/$ARTIFACT_DIR"
[ -f "$HTML_DIR/index.html" ] || die 6 "归档中缺少 index.html: $HTML_DIR"
TASK_META="$HTML_DIR/platform-task-meta.json"
[ -f "$TASK_META" ] || die 6 "归档中缺少受控任务元数据: platform-task-meta.json"
EXPECTED_TASK_ID="$PUBLISH_TASK_ID" \
EXPECTED_PROJECT_ID="$PUBLISH_PROJECT_ID" \
EXPECTED_BUILD_NUMBER="$SELECTED_BUILD" \
EXPECTED_JOB_NAME="$JOB_NAME" \
python3 - "$TASK_META" <<'PYEOF' \
    || die 6 "归档任务元数据与 Jenkins 构建参数不一致"
import json
import os
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as file:
        metadata = json.load(file)
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)

expected = {
    "task_id": os.environ["EXPECTED_TASK_ID"],
    "build_number": int(os.environ["EXPECTED_BUILD_NUMBER"]),
    "job_name": os.environ["EXPECTED_JOB_NAME"],
}
project_id = metadata.pop("project_id", None)
project_matches = project_id == os.environ["EXPECTED_PROJECT_ID"]
if project_id is None and os.environ["EXPECTED_PROJECT_ID"] == "truthy":
    project_matches = True
raise SystemExit(0 if project_matches and metadata == expected else 1)
PYEOF

# ---------------- 调用发布脚本 ----------------

log "调用发布脚本（source=jenkins）"
PUBLISH_JOB_NAME="$JOB_NAME" \
PUBLISH_BUILD_NUMBER="$SELECTED_BUILD" \
PUBLISH_BUILD_RESULT="$BUILD_RESULT" \
PUBLISH_BUILD_URL="$BUILD_URL" \
PUBLISH_TASK_ID="$PUBLISH_TASK_ID" \
PUBLISH_PROJECT_ID="$PUBLISH_PROJECT_ID" \
    "$SCRIPT_DIR/publish_allure_report.sh" "$HTML_DIR" "$REPORT_ROOT" jenkins

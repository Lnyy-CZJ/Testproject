#!/usr/bin/env bash
#
# Allure HTML 报告原子发布脚本（设计 11.3）。
#
# 功能说明:
#   把一份生成好的 Allure HTML 报告完整复制到版本目录
#   reports/task-reports/<project_id>/<task_id>/versions/<version>/，写入报告元信息，
#   然后通过临时相对软链接 + rename(2) 原子切换该任务自己的 current。
#   不同任务目录互不覆盖，切换完成前旧报告始终可用。
#
# 用法:
#   publish_allure_report.sh <源HTML目录> [报告根目录] [来源]
#
# 参数说明:
#   源HTML目录   必填，必须包含 index.html（Allure 报告入口）；
#   报告根目录   可选，默认 <项目根>/reports（项目根 = 本脚本上级目录）；
#   来源         可选，jenkins|manual，默认 manual；决定版本目录命名与
#                元信息字段。
#
# 元信息环境变量（可选，来源为 jenkins 时建议全部提供）:
#   PUBLISH_JOB_NAME       Jenkins 任务名
#   PUBLISH_BUILD_NUMBER   Jenkins 构建号（整数）
#   PUBLISH_BUILD_RESULT   Jenkins 构建结果（SUCCESS/FAILURE/UNSTABLE 等）
#   PUBLISH_BUILD_URL      Jenkins 构建页面 URL
#   PUBLISH_ALLURE_VERSION Allure 版本号，默认 unknown
#   PUBLISH_TASK_ID        必填的平台根任务 ID；用于物理目录和元数据绑定。
#   PUBLISH_PROJECT_ID     新版任务的工具项目 ID；缺省时仅兼容发布旧版报告路径。
#
# 返回值（退出码）:
#   0  发布成功；
#   2  源目录无效（不存在或缺 index.html）；
#   3  已有发布正在进行（获取锁失败）；
#   4  发布过程中失败（旧 current 保持不变，本次临时目录已清理）。

set -euo pipefail

log() { echo "[publish_allure_report] $*" >&2; }
die() { local code="$1"; shift; log "错误: $*"; exit "$code"; }

# ---------------- 参数解析 ----------------

SOURCE_DIR="${1:-}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPORT_ROOT="${2:-$PROJECT_ROOT/reports}"
SOURCE="${3:-manual}"

[ -n "$SOURCE_DIR" ] || die 2 "用法: publish_allure_report.sh <源HTML目录> [报告根目录] [来源]"
[ -d "$SOURCE_DIR" ] || die 2 "源目录不存在: $SOURCE_DIR"
[ -f "$SOURCE_DIR/index.html" ] || die 2 "源目录缺少 index.html: $SOURCE_DIR"
case "$SOURCE" in
    jenkins|manual) ;;
    *) die 2 "来源必须是 jenkins 或 manual，实际: $SOURCE" ;;
esac
[ -n "${PUBLISH_TASK_ID:-}" ] || die 2 "缺少环境变量 PUBLISH_TASK_ID"
printf '%s' "$PUBLISH_TASK_ID" | LC_ALL=C grep -Eq '^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$' \
    || die 2 "PUBLISH_TASK_ID 格式非法: $PUBLISH_TASK_ID"
if [ -n "${PUBLISH_PROJECT_ID:-}" ]; then
    printf '%s' "$PUBLISH_PROJECT_ID" | LC_ALL=C grep -Eq '^[a-z][a-z0-9-]{1,31}$' \
        || die 2 "PUBLISH_PROJECT_ID 格式非法: $PUBLISH_PROJECT_ID"
fi

if [ -n "${PUBLISH_PROJECT_ID:-}" ]; then
    TASK_REPORT_ROOT="$REPORT_ROOT/task-reports/$PUBLISH_PROJECT_ID/$PUBLISH_TASK_ID"
else
    # 仅供历史单项目调用方读取；平台/Jenkins 新任务必须显式传项目。
    log "弃用提示：未提供 PUBLISH_PROJECT_ID，沿用历史单项目报告路径"
    TASK_REPORT_ROOT="$REPORT_ROOT/task-reports/$PUBLISH_TASK_ID"
fi
ALLURE_REPORTS_DIR="$TASK_REPORT_ROOT/versions"
CURRENT_LINK="$TASK_REPORT_ROOT/current"
LOCK_DIR="$REPORT_ROOT/.publish.lock"
LOCK_MAX_AGE_SECONDS=600   # 锁超过该时间视为残留，强制回收
TMP_MAX_AGE_SECONDS=3600   # 无引用临时目录超过该时间才允许清理

# ---------------- 版本标识 ----------------

# 生成不可冲突的版本目录名:
#   jenkins → jenkins-<任务安全名>-<构建号>
#   manual  → manual-<UTC时间戳>-<随机后缀>
make_version() {
    if [ "$SOURCE" = "jenkins" ]; then
        local job="${PUBLISH_JOB_NAME:-unknown-job}"
        local number="${PUBLISH_BUILD_NUMBER:-0}"
        # 任务名只保留字母数字与连字符，保证可作目录名。
        local safe_job
        safe_job="$(printf '%s' "$job" | LC_ALL=C tr -c 'A-Za-z0-9-' '-' | LC_ALL=C sed 's/--*/-/g; s/^-//; s/-$//')"
        echo "jenkins-${safe_job}-${number}"
    else
        echo "manual-$(date -u +%Y%m%dT%H%M%SZ)-$$-${RANDOM}"
    fi
}

VERSION="$(make_version)"
VERSION_DIR="$ALLURE_REPORTS_DIR/$VERSION"
STAGING_DIR="$ALLURE_REPORTS_DIR/.$VERSION.tmp"
TMP_LINK="$TASK_REPORT_ROOT/.current.tmp"

# ---------------- 发布锁 ----------------

acquire_lock() {
    # mkdir 是原子操作，用作跨进程互斥锁。
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        return 0
    fi
    # 已存在：判断是否为超龄残留锁（发布进程异常退出未清理）。
    local now lock_time
    now="$(date +%s)"
    lock_time="$(stat -f %m "$LOCK_DIR" 2>/dev/null || stat -c %Y "$LOCK_DIR" 2>/dev/null || echo "$now")"
    if [ $((now - lock_time)) -gt "$LOCK_MAX_AGE_SECONDS" ]; then
        log "回收超龄发布锁: $LOCK_DIR"
        rm -rf "$LOCK_DIR"
        mkdir "$LOCK_DIR" || die 3 "已有发布正在进行（回收锁后仍无法获取）: $LOCK_DIR"
        return 0
    fi
    die 3 "已有发布正在进行: $LOCK_DIR"
}

# 发布结束时统一清理：释放锁；失败时删除本次暂存目录与临时软链接，
# 保证旧 current 不受影响（trap 在 exit 前执行）。
cleanup() {
    local exit_code=$?
    if [ "$exit_code" -ne 0 ]; then
        rm -rf "$STAGING_DIR" "$TMP_LINK" 2>/dev/null || true
    fi
    rmdir "$LOCK_DIR" 2>/dev/null || rm -rf "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

# 清理无引用且超过安全时间的暂存目录（.*.tmp），避免中断残留累积。
# 只清理本次进程之外、修改时间足够旧的目录，绝不清理正在使用的版本。
cleanup_stale_tmp() {
    local now mtime
    now="$(date +%s)"
    for tmp in "$ALLURE_REPORTS_DIR"/.*.tmp; do
        [ -d "$tmp" ] || continue
        mtime="$(stat -f %m "$tmp" 2>/dev/null || stat -c %Y "$tmp" 2>/dev/null || echo "$now")"
        if [ $((now - mtime)) -gt "$TMP_MAX_AGE_SECONDS" ]; then
            log "清理残留暂存目录: $tmp"
            rm -rf "$tmp"
        fi
    done
}

# ---------------- 写入 report-meta.json ----------------

# 元信息至少包含 generated_at/source/allure_version；
# jenkins 来源额外包含 job_name/build_number/build_result/build_url。
write_meta() {
    local target_dir="$1"
    SOURCE="$SOURCE" \
    VERSION="$VERSION" \
    GENERATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    PUBLISH_JOB_NAME="${PUBLISH_JOB_NAME:-}" \
    PUBLISH_BUILD_NUMBER="${PUBLISH_BUILD_NUMBER:-}" \
    PUBLISH_BUILD_RESULT="${PUBLISH_BUILD_RESULT:-}" \
    PUBLISH_BUILD_URL="${PUBLISH_BUILD_URL:-}" \
    PUBLISH_ALLURE_VERSION="${PUBLISH_ALLURE_VERSION:-unknown}" \
    PUBLISH_TASK_ID="${PUBLISH_TASK_ID:-}" \
    PUBLISH_PROJECT_ID="${PUBLISH_PROJECT_ID:-}" \
    python3 - "$target_dir" <<'PYEOF'
import json
import os
import sys

target_dir = sys.argv[1]
meta = {
    "generated_at": os.environ["GENERATED_AT"],
    "source": os.environ["SOURCE"],
    "allure_version": os.environ["PUBLISH_ALLURE_VERSION"],
    "version": os.environ["VERSION"],
}
if os.environ["PUBLISH_TASK_ID"]:
    meta["task_id"] = os.environ["PUBLISH_TASK_ID"]
if os.environ["PUBLISH_PROJECT_ID"]:
    meta["project_id"] = os.environ["PUBLISH_PROJECT_ID"]
if os.environ["SOURCE"] == "jenkins":
    meta["job_name"] = os.environ["PUBLISH_JOB_NAME"]
    build_number = os.environ["PUBLISH_BUILD_NUMBER"]
    meta["build_number"] = int(build_number) if build_number.isdigit() else build_number
    meta["build_result"] = os.environ["PUBLISH_BUILD_RESULT"]
    meta["build_url"] = os.environ["PUBLISH_BUILD_URL"]
with open(os.path.join(target_dir, "report-meta.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
    f.write("\n")
PYEOF
}

# ---------------- 主流程 ----------------

# 报告根与版本目录必须先存在，否则 mkdir 锁目录会因缺少父目录失败，
# 并被误判为锁冲突。
mkdir -p "$REPORT_ROOT" "$ALLURE_REPORTS_DIR"
acquire_lock
cleanup_stale_tmp

# 1. 完整复制到暂存目录（先落盘完整报告，再谈切换）。
log "复制报告到暂存目录: $STAGING_DIR"
rm -rf "$STAGING_DIR"
cp -R "$SOURCE_DIR" "$STAGING_DIR"
write_meta "$STAGING_DIR"

# 2. 再次校验暂存目录完整性，防止复制过程中断产生半份报告。
[ -f "$STAGING_DIR/index.html" ] || die 4 "暂存目录缺少 index.html，复制可能中断: $STAGING_DIR"
[ -f "$STAGING_DIR/report-meta.json" ] || die 4 "暂存目录缺少 report-meta.json"
python3 -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' \
    "$STAGING_DIR/report-meta.json" || die 4 "report-meta.json 不是合法 JSON"

# 3. 暂存目录改名为正式版本目录；同名版本（重复发布同一构建）先挪开，
#    切换成功后再删除，保证切换前旧版本始终可读。
OBSOLETE_DIR=""
if [ -e "$VERSION_DIR" ]; then
    OBSOLETE_DIR="$ALLURE_REPORTS_DIR/.$VERSION.old.tmp"
    rm -rf "$OBSOLETE_DIR"
    mv "$VERSION_DIR" "$OBSOLETE_DIR"
fi
mv "$STAGING_DIR" "$VERSION_DIR"

# 4. 创建指向任务新版本的临时相对软链接，再用 rename(2) 原子替换
#    该任务的 current。其他任务的目录与 current 不参与本次切换。
#    注意: macOS 的 mv 遇到"符号链接指向目录"会把源移入目录内而非替换，
#    因此必须用 python3 os.replace（直接调用 rename(2)，不跟随符号链接）。
LEGACY_DIR=""
if [ -e "$CURRENT_LINK" ] && [ ! -L "$CURRENT_LINK" ]; then
    # 历史遗留的实体目录 current：挪开后再建软链接体系。
    LEGACY_DIR="$TASK_REPORT_ROOT/.legacy-current.$(date +%s).tmp"
    mv "$CURRENT_LINK" "$LEGACY_DIR"
fi
ln -s "versions/$VERSION" "$TMP_LINK"
python3 -c 'import os,sys; os.replace(sys.argv[1], sys.argv[2])' "$TMP_LINK" "$CURRENT_LINK"
log "任务 $PUBLISH_TASK_ID 的 current 已切换到 $VERSION"

# 5. 切换成功后清理：同名旧版本、历史遗留实体目录、其余过期版本目录
#    （只保留 current 指向的一份，【确认项 6】对外只展示一份）。
[ -z "$OBSOLETE_DIR" ] || rm -rf "$OBSOLETE_DIR"
[ -z "$LEGACY_DIR" ] || rm -rf "$LEGACY_DIR"
for old in "$ALLURE_REPORTS_DIR"/*/; do
    [ -d "$old" ] || continue
    case "${old%/}" in
        "$VERSION_DIR") continue ;;
        *) log "删除旧版本: ${old%/}"; rm -rf "${old%/}" ;;
    esac
done

log "发布成功: source=$SOURCE version=$VERSION"
echo "$VERSION"

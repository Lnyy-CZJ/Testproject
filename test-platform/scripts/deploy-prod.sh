#!/usr/bin/env bash
set -euo pipefail

release_dir=${1:?usage: deploy-prod.sh RELEASE_DIR [COMPONENT] [IMAGE_OR_ENV_FILE]}
component=${2:-}
override=${3:-}
base_env=/srv/test-platform/env/.env.prod
release_images="$release_dir/.env.images"
current_images=/srv/test-platform/env/.env.images.current
state_dir=/srv/test-platform/state
deployments_dir="$state_dir/deployments"
backup_root=/srv/test-platform/backups
previous_release=$(readlink -f /srv/test-platform/current 2>/dev/null || true)
deployment_id="$(date -u +%Y%m%dT%H%M%SZ)-${component:-full}"

test -f "$base_env"
test -f "$release_images"
test -f "$release_dir/versions.json"
test -f "$release_dir/release-manifest.json"
mkdir -p "$backup_root" "$deployments_dir"
[[ -f "$state_dir/current.json" ]] || printf '{}\n' > "$state_dir/current.json"

# 两个智能体以固定非 root UID 运行；环境互查 Token 只允许平台读取。
sudo chown 10001:10001 /srv/test-platform/secrets/prod/functional-test-agent-client-token
sudo chown 10002:10002 \
  /srv/test-platform/secrets/prod/api-test-agent-client-token \
  /srv/test-platform/secrets/prod/api-execution-controller-token
sudo chmod 600 \
  /srv/test-platform/secrets/prod/functional-test-agent-client-token \
  /srv/test-platform/secrets/prod/api-test-agent-client-token \
  /srv/test-platform/secrets/prod/api-execution-controller-token \
  /srv/test-platform/secrets/prod/version-peer-token

candidate_images=$(mktemp)
previous_images=$(mktemp)
trap 'rm -f "$candidate_images" "$previous_images"' EXIT
if [[ -f "$current_images" ]]; then cp "$current_images" "$previous_images"; else cp "$release_images" "$previous_images"; fi

merge_images() {
  python3 - "$1" "$2" "$3" <<'PY'
import sys
from pathlib import Path

base, changes, output = map(Path, sys.argv[1:])
values = {}
for path in (base, changes):
    for line in path.read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
output.write_text("".join(f"{key}={values[key]}\n" for key in sorted(values)))
PY
}

verify_component_images() {
  local env_file=$1 target=$2
  python3 - "$env_file" "$target" <<'PY'
import re, sys
from pathlib import Path

values = dict(line.split("=", 1) for line in Path(sys.argv[1]).read_text().splitlines() if line)
expected = {
    "functional-test-agent": {
        "FUNCTIONAL_AGENT_IMAGE": "ghcr.io/lnyy-czj/testproject-functional-test-agent",
    },
    "api-test-agent": {
        "API_AGENT_IMAGE": "ghcr.io/lnyy-czj/testproject-api-test-agent",
        "API_EXECUTION_CONTROLLER_IMAGE": "ghcr.io/lnyy-czj/testproject-api-execution-controller",
        "API_EGRESS_PROXY_IMAGE": "ghcr.io/lnyy-czj/testproject-api-egress-proxy",
        "API_EXECUTOR_IMAGE": "ghcr.io/lnyy-czj/testproject-api-test-executor",
    },
}[sys.argv[2]]
for key, prefix in expected.items():
    value = values.get(key, "")
    if not re.fullmatch(re.escape(prefix) + r"@sha256:[0-9a-f]{64}", value):
        raise SystemExit(f"{key} must use the expected immutable digest")
PY
}

verify_runtime() {
  local target=${1:-} expected_version=${2:-} expected_revision=${3:-} expected_content=${4:-} snapshot
  snapshot=$(mktemp)
  if ! curl --fail --silent --show-error --retry 12 --retry-delay 5 --retry-all-errors \
    -H "Authorization: Bearer $(</srv/test-platform/secrets/prod/version-peer-token)" \
    "http://127.0.0.1:41873/api/v1/internal/version-snapshot" > "$snapshot"; then
    rm -f "$snapshot"
    return 1
  fi
  python3 - "$snapshot" "$target" "$expected_version" "$expected_revision" "$expected_content" "$release_dir/release-manifest.json" <<'PY'
import json, sys
from pathlib import Path

snapshot = json.loads(Path(sys.argv[1]).read_text())
target = sys.argv[2]
expected_version, expected_revision = sys.argv[3:5]
expected_content = sys.argv[5]
manifest = json.loads(Path(sys.argv[6]).read_text())
components = snapshot.get("components", {})
selected = {target: components.get(target)} if target else components
if not selected:
    raise SystemExit("runtime version verification returned no components")
for component_id, item in selected.items():
    expected_component = manifest.get("components", {}).get(component_id, {})
    version = expected_version or expected_component.get("version")
    revision = expected_revision or manifest.get("commit")
    content_sha256 = expected_content or expected_component.get("content_sha256")
    if not item or item.get("health") != "healthy" or item.get("version") != version or item.get("revision") != revision or item.get("content_sha256") != content_sha256 or item.get("dirty"):
        raise SystemExit(f"{component_id} runtime identity does not match release metadata")
print(f"verified {len(selected)} production component identities")
PY
  local result=$?
  rm -f "$snapshot"
  return "$result"
}

verify_deployed_service_images() {
  # 组件健康接口只能证明主进程身份；API Suite 的可选 Controller/Egress
  # 还必须核对容器实际 Image ID，避免“环境文件已更新、运行容器仍为旧镜像”。
  local service container_id actual_id expected_ref expected_id
  for service in "$@"; do
    container_id=$("${compose[@]}" ps -q "$service")
    [[ -n "$container_id" ]] || return 1
    actual_id=$(docker inspect --format '{{.Image}}' "$container_id")
    expected_ref=$("${compose[@]}" config --format json | python3 -c \
      'import json,sys; print(json.load(sys.stdin)["services"][sys.argv[1]]["image"])' "$service")
    expected_id=$(docker image inspect --format '{{.Id}}' "$expected_ref")
    [[ "$actual_id" == "$expected_id" ]] || return 1
  done
}

write_record() {
  local operation=$1 target=${2:-} image_env=$3 config_releases=${4:-} snapshot
  snapshot=$(mktemp)
  curl --fail --silent --show-error \
    -H "Authorization: Bearer $(</srv/test-platform/secrets/prod/version-peer-token)" \
    "http://127.0.0.1:41873/api/v1/internal/version-snapshot" > "$snapshot"
  DEPLOYED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  OPERATION="$operation" TARGET_COMPONENT="$target" CONFIG_RELEASES="$config_releases" \
  TARGET_VERSION="${expected_version:-}" TARGET_REVISION="${expected_revision:-}" \
  TARGET_CONTENT="${expected_content:-}" \
  PREVIOUS_RELEASE="$previous_release" \
  python3 - "$release_dir/release-manifest.json" "$state_dir/current.json" "$image_env" "$release_dir/versions.json" "$deployments_dir/$deployment_id.json" "$deployments_dir/$deployment_id.md" "$snapshot" <<'PY'
import json, os, sys
from pathlib import Path

manifest_path, current_path, images_path, versions_path, json_path, markdown_path, snapshot_path = map(Path, sys.argv[1:])
manifest = json.loads(manifest_path.read_text())
current = json.loads(current_path.read_text()) if current_path.stat().st_size else {}
versions = json.loads(versions_path.read_text())
snapshot = json.loads(snapshot_path.read_text())
images = dict(line.split("=", 1) for line in images_path.read_text().splitlines() if line)
target = os.environ["TARGET_COMPONENT"]
if os.environ["OPERATION"] == "full" or not current.get("components"):
    record = manifest
else:
    record = current
    source = manifest["components"][target]
    record["components"][target] = {
        "version": os.environ["TARGET_VERSION"] or versions["components"][target]["version"],
        "revision": os.environ["TARGET_REVISION"] or manifest.get("commit"),
        "content_sha256": os.environ["TARGET_CONTENT"] or source.get("content_sha256", "unknown"),
        "images": {key: images[key] for key in source["images"]},
    }
record["images"] = images
record.update({
    "deployment_id": json_path.stem,
    "operation": os.environ["OPERATION"],
    "target_component": target or None,
    "deployed_at": os.environ["DEPLOYED_AT"],
    "previous_release": Path(os.environ["PREVIOUS_RELEASE"]).name if os.environ["PREVIOUS_RELEASE"] else None,
    "config_releases": [
        {"owner_type": a, "owner_id": b, "release_id": c}
        for a, b, c in (line.split("|", 2) for line in os.environ["CONFIG_RELEASES"].splitlines() if line)
    ],
    "database": snapshot.get("database", {}),
    "config_fingerprints": snapshot.get("config_fingerprints", {}),
    "acceptance": {"result": "passed", "smoke_tests": 8 if os.environ["OPERATION"] == "full" else 1},
})
temp = current_path.with_suffix(".tmp")
temp.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
temp.replace(current_path)
json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
rows = [
    "# Production Deployment Record",
    "",
    f"- Deployment: `{record['deployment_id']}`",
    f"- Release: `{record.get('release', 'unknown')}`",
    f"- Commit: `{record.get('commit', 'unknown')}`",
    f"- Operation: `{record['operation']}`",
    f"- Deployed at: `{record['deployed_at']}`",
    "",
    "| Component | Version | Images |",
    "| --- | --- | --- |",
]
for component_id, component in sorted(record.get("components", {}).items()):
    image_list = "<br>".join(f"`{key}={value}`" for key, value in component.get("images", {}).items())
    rows.append(f"| {component_id} | `{component.get('version', 'unknown')}` | {image_list} |")
database = record.get("database", {})
rows.extend([
    "", "## Database structure", "",
    f"- Alembic revision: `{database.get('alembic_revision', 'unknown')}`",
    f"- Schema SHA-256: `{database.get('schema_sha256', 'unknown')}`",
    "- Business data: not compared",
    f"- Config fingerprints: `{len(record.get('config_fingerprints', {}))}` scopes",
])
markdown_path.write_text("\n".join(rows) + "\n")
PY
  rm -f "$snapshot"
  chmod 600 "$state_dir/current.json" "$deployments_dir/$deployment_id.json" "$deployments_dir/$deployment_id.md"
}

if [[ -n "$component" ]]; then
  changes=$(mktemp)
  trap 'rm -f "$candidate_images" "$previous_images" "$changes"' EXIT
  case "$component" in
    functional-test-agent)
      if [[ -n "$override" ]]; then printf 'FUNCTIONAL_AGENT_IMAGE=%s\n' "$override" > "$changes"; else grep '^FUNCTIONAL_AGENT_IMAGE=' "$release_images" > "$changes"; fi
      services=(functional-test-agent)
      deployment_services=(functional-test-agent)
      ;;
    api-test-agent)
      if [[ -n "$override" ]]; then
        test -f "$override"
        grep -E '^(API_AGENT_IMAGE|API_EXECUTION_CONTROLLER_IMAGE|API_EGRESS_PROXY_IMAGE|API_EXECUTOR_IMAGE)=' "$override" > "$changes"
      else
        grep -E '^(API_AGENT_IMAGE|API_EXECUTION_CONTROLLER_IMAGE|API_EGRESS_PROXY_IMAGE|API_EXECUTOR_IMAGE)=' "$release_images" > "$changes"
      fi
      [[ $(wc -l < "$changes" | tr -d ' ') == 4 ]]
      services=(api-test-agent api-execution-controller api-egress-proxy api-test-executor-image)
      deployment_services=(api-test-agent)
      ;;
    *) echo "不支持独立部署组件: $component" >&2; exit 1 ;;
  esac
  merge_images "$previous_images" "$changes" "$candidate_images"
  verify_component_images "$candidate_images" "$component"
  compose=(docker compose --env-file "$base_env" --env-file "$candidate_images" -p test-platform-prod -f "$release_dir/docker-compose.yml" -f "$release_dir/docker-compose.prod.yml")
  if ! "${compose[@]}" pull "${services[@]}"; then
    exit 1
  fi
  if [[ "$component" == "api-test-agent" ]]; then
    # 默认生产环境不启用真实执行链；若 Controller/Egress 已由 profile 启动，
    # 独立升级必须把这些正在运行的服务纳入同一次原子切换，但绝不能主动启用它们。
    running_services=$("${compose[@]}" ps --services --status running)
    for service in api-execution-controller api-egress-proxy; do
      if grep -qx "$service" <<<"$running_services"; then
        deployment_services+=("$service")
      fi
    done
  fi
  primary_key=FUNCTIONAL_AGENT_IMAGE
  [[ "$component" == "api-test-agent" ]] && primary_key=API_AGENT_IMAGE
  primary_image=$(grep "^${primary_key}=" "$candidate_images" | cut -d= -f2-)
  expected_version=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' "$primary_image")
  expected_revision=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$primary_image")
  expected_content=$(docker image inspect --format '{{ index .Config.Labels "io.testplatform.source-content-sha256" }}' "$primary_image")
  if [[ "$component" == "api-test-agent" ]]; then
    for key in API_EXECUTION_CONTROLLER_IMAGE API_EGRESS_PROXY_IMAGE API_EXECUTOR_IMAGE; do
      image=$(grep "^${key}=" "$candidate_images" | cut -d= -f2-)
      [[ $(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' "$image") == "$expected_version" ]]
      [[ $(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image") == "$expected_revision" ]]
      [[ $(docker image inspect --format '{{ index .Config.Labels "io.testplatform.source-content-sha256" }}' "$image") == "$expected_content" ]]
    done
  fi
  if ! "${compose[@]}" up -d --no-deps "${deployment_services[@]}" \
    || ! verify_deployed_service_images "${deployment_services[@]}" \
    || ! verify_runtime "$component" "$expected_version" "$expected_revision" "$expected_content"; then
    rollback=(docker compose --env-file "$base_env" --env-file "$previous_images" -p test-platform-prod -f "$release_dir/docker-compose.yml" -f "$release_dir/docker-compose.prod.yml")
    "${rollback[@]}" up -d --no-deps "${deployment_services[@]}"
    echo "$component 部署失败，已恢复前一镜像组合" >&2
    exit 1
  fi
  install -m 600 "$candidate_images" "$current_images.tmp"
  mv "$current_images.tmp" "$current_images"
  write_record "component-update" "$component" "$current_images"
  echo "$component active; deployment record: $deployment_id"
  exit 0
fi

compose=(docker compose --env-file "$base_env" --env-file "$release_images" -p test-platform-prod -f "$release_dir/docker-compose.yml" -f "$release_dir/docker-compose.prod.yml")
if docker ps --format '{{.Names}}' | grep -qx 'test-platform-prod-platform-db-1'; then
  backup="$backup_root/platform-$(date -u +%Y%m%dT%H%M%SZ).dump"
  "${compose[@]}" exec -T platform-db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' >"$backup"
  chmod 600 "$backup"
fi

"${compose[@]}" config --quiet
if "${compose[@]}" config | grep -qE '^[[:space:]]+build:'; then
  echo '生产 Compose 仍包含 build，拒绝部署' >&2
  exit 1
fi
"${compose[@]}" pull
alembic_target="$("${compose[@]}" config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["platform-migrate"]["command"][-1])')"
if [[ "$alembic_target" != "20260824_0019" ]]; then
  project_access_manifest="${PROJECT_ACCESS_MANIFEST:-}"
  if [[ -z "$project_access_manifest" || ! -f "$project_access_manifest" ]]; then
    echo 'Contract 发布必须通过 PROJECT_ACCESS_MANIFEST 提供完整角色、工具、成员、源端计数和资源清单' >&2
    exit 1
  fi
  manifest_path="$(cd "$(dirname "$project_access_manifest")" && pwd)/$(basename "$project_access_manifest")"
  # 生产发布的目标环境由部署脚本固定传入，禁止 manifest 用自报 bogus 环境绕过
  # 五个第一方工具的 prod 源清单核对。
  manifest_command=(python -m app.migrate_project_access --manifest /run/project-access-manifest.json --required-environment prod)
  "${compose[@]}" run --rm --no-deps -v "$manifest_path:/run/project-access-manifest.json:ro" platform-migrate "${manifest_command[@]}"
  "${compose[@]}" run --rm --no-deps -v "$manifest_path:/run/project-access-manifest.json:ro" platform-migrate "${manifest_command[@]}" --apply
fi
"${compose[@]}" run --rm platform-migrate

read -r prod_objects prod_activations < <("${compose[@]}" exec -T platform-db sh -c \
  'psql -At -F " " -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select (select count(*) from config_releases where environment_id='"'"'prod'"'"') + (select count(*) from secrets where environment_id='"'"'prod'"'"') + (select count(*) from credentials where environment_id='"'"'prod'"'"') + (select count(*) from tool_clients where environment_id='"'"'prod'"'"'), (select count(*) from config_activations where environment_id='"'"'prod'"'"');"')
if [[ "$prod_objects" == "0" && "$prod_activations" == "0" ]]; then
  promotion=(python -m app.promote_environment --source dev --target prod --require-empty-target --copy-secrets --seed-credentials)
  "${compose[@]}" run --rm --no-deps platform-migrate "${promotion[@]}" --dry-run
  "${compose[@]}" run --rm --no-deps platform-migrate "${promotion[@]}"
elif [[ "$prod_activations" == "0" ]]; then
  echo 'prod 已部分初始化但没有激活配置，拒绝继续部署' >&2
  exit 1
fi

"${compose[@]}" up -d --remove-orphans
for path in / /api/v1/health/live; do
  curl --fail --silent --show-error --retry 12 --retry-delay 5 --retry-all-errors "http://127.0.0.1:41873$path" >/dev/null
done
# V3 是功能智能体的生产界面契约。发布验收使用工具自己的最小权限
# Client Token 读取普通配置，并核对当前镜像模板；不能伪造用户 Header 绕过可信身份层。
"${compose[@]}" exec -T functional-test-agent python -c '
from pathlib import Path
from services.common.config import load_service_settings
from services.common.platform_client import PlatformClient
settings = load_service_settings("functional-test-agent", "functional", "/functional-test-agent", 5004)
snapshot = PlatformClient(
    settings.platform_api_url,
    settings.tool_id,
    settings.runtime_environment,
    settings.platform_client_token_file,
).runtime_config(include_secrets=False, llm_capability=None)
assert snapshot.get("normal", {}).get("FUNCTIONAL_WORKBENCH_V3_ENABLED") is True
template = Path("services/common/templates/index.html").read_text(encoding="utf-8")
assert "functional_workbench_v3" in template and "测试用例生成" in template
print("functional V3 config and image template verified")
'
verify_runtime
config_releases=$("${compose[@]}" exec -T platform-db sh -c \
  'psql -At -F "|" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select owner_type, owner_id, active_release_id from config_activations where environment_id='"'"'prod'"'"' order by owner_type, owner_id;"')
install -m 600 "$release_images" "$current_images.tmp"
mv "$current_images.tmp" "$current_images"
write_record "full" "" "$current_images" "$config_releases"
ln -sfn "$release_dir" /srv/test-platform/current
echo "production release active: $(basename "$release_dir"); deployment record: $deployment_id"

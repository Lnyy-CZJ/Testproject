#!/usr/bin/env bash
set -euo pipefail

platform_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_dir="$(cd "$platform_dir/.." && pwd)"
runtime_dir="$platform_dir/.runtime/dev"
secret_dir="$platform_dir/.runtime-secrets/dev"
metadata_file="$(mktemp)"
trap 'rm -f "$metadata_file"' EXIT

python3 "$platform_dir/scripts/version_tool.py" validate
python3 "$platform_dir/scripts/version_tool.py" export > "$metadata_file"
mkdir -p "$runtime_dir" "$secret_dir"
if [[ ! -s "$secret_dir/version-peer-token" ]]; then
  python3 -c 'import secrets,sys; print(secrets.token_urlsafe(48))' > "$secret_dir/version-peer-token"
  chmod 600 "$secret_dir/version-peer-token"
fi

python3 - "$metadata_file" "$runtime_dir/build.env" "$runtime_dir/current.json" <<'PY'
import json
import sys
from pathlib import Path

metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
env_names = {
    "platform-gateway": "PLATFORM_GATEWAY",
    "platform-backend": "PLATFORM_BACKEND",
    "trackevents-web": "TRACKEVENTS",
    "log-filter-tool": "LOG_FILTER",
    "truthy-search": "TRUTHY_SEARCH",
    "api-autotest": "API_AUTOTEST",
    "functional-test-agent": "FUNCTIONAL_AGENT",
    "api-test-agent": "API_AGENT",
}
short_sha = metadata["revision"][:12]
lines = [f"APP_REVISION={metadata['revision']}", "PLATFORM_RUNTIME_ENV=dev"]
images = {}
components = {}
for component_id, component in metadata["components"].items():
    prefix = env_names[component_id]
    lines.extend([
        f"{prefix}_VERSION={component['version']}",
        f"{prefix}_DIRTY={str(component['dirty']).lower()}",
    ])
    for image_env in component["image_envs"]:
        image_name = image_env.removesuffix("_IMAGE").lower().replace("_", "-")
        image = f"{image_name}:{component['version']}-dev.{short_sha}"
        lines.append(f"{image_env}={image}")
        images[image_env] = image
    components[component_id] = {
        "version": component["version"],
        "revision": metadata["revision"],
        "dirty": component["dirty"],
        "images": {key: images[key] for key in component["image_envs"]},
    }
Path(sys.argv[2]).write_text("\n".join(lines) + "\n", encoding="utf-8")
current_path = Path(sys.argv[3])
current = json.loads(current_path.read_text()) if current_path.exists() else {}
current.update({
    "schema_version": 2,
    "release": f"dev-{short_sha}",
    "commit": metadata["revision"],
})
current.setdefault("components", {}).update(components)
current.setdefault("images", {}).update(images)
current_path.write_text(
    json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

set -a
source "$runtime_dir/build.env"
set +a

selected=("$@")
if [[ ${#selected[@]} -eq 0 ]]; then
  selected=(platform-gateway platform-backend trackevents-web log-filter-tool truthy-search api-autotest functional-test-agent api-test-agent)
fi

compose_services=()
for component in "${selected[@]}"; do
  case "$component" in
    platform-gateway) compose_services+=(platform-gateway) ;;
    platform-backend) compose_services+=(platform-migrate platform-bootstrap platform-api platform-credential-agent) ;;
    trackevents-web|log-filter-tool|truthy-search|api-autotest) compose_services+=("$component") ;;
    functional-test-agent)
      docker build --build-arg APP_VERSION="$FUNCTIONAL_AGENT_VERSION" --build-arg APP_REVISION="$APP_REVISION" --build-arg APP_BUILD_DIRTY="$FUNCTIONAL_AGENT_DIRTY" -t "$FUNCTIONAL_AGENT_IMAGE" "$repo_dir/functional-test-agent"
      compose_services+=(functional-test-agent)
      ;;
    api-test-agent)
      docker build -f "$repo_dir/api-test-agent/Dockerfile.agent" --build-arg APP_VERSION="$API_AGENT_VERSION" --build-arg APP_REVISION="$APP_REVISION" --build-arg APP_BUILD_DIRTY="$API_AGENT_DIRTY" -t "$API_AGENT_IMAGE" "$repo_dir/api-test-agent"
      docker build -f "$repo_dir/api-test-agent/Dockerfile.controller" --build-arg APP_VERSION="$API_AGENT_VERSION" --build-arg APP_REVISION="$APP_REVISION" --build-arg APP_BUILD_DIRTY="$API_AGENT_DIRTY" -t "$API_EXECUTION_CONTROLLER_IMAGE" "$repo_dir/api-test-agent"
      docker build -f "$repo_dir/api-test-agent/Dockerfile.egress" --build-arg APP_VERSION="$API_AGENT_VERSION" --build-arg APP_REVISION="$APP_REVISION" --build-arg APP_BUILD_DIRTY="$API_AGENT_DIRTY" -t "$API_EGRESS_PROXY_IMAGE" "$repo_dir/api-test-agent"
      docker build -f "$repo_dir/api-test-agent/Dockerfile.executor" --build-arg APP_VERSION="$API_AGENT_VERSION" --build-arg APP_REVISION="$APP_REVISION" --build-arg APP_BUILD_DIRTY="$API_AGENT_DIRTY" -t "$API_EXECUTOR_IMAGE" "$repo_dir/api-test-agent"
      compose_services+=(api-test-agent)
      ;;
    *) echo "unknown component: $component" >&2; exit 2 ;;
  esac
done

compose=(docker compose --env-file "$runtime_dir/build.env" -f "$platform_dir/docker-compose.yml")
buildable=()
for service in "${compose_services[@]}"; do
  case "$service" in
    functional-test-agent|api-test-agent) ;;
    *) buildable+=("$service") ;;
  esac
done
if [[ ${#buildable[@]} -gt 0 ]]; then
  "${compose[@]}" build "${buildable[@]}"
fi
"${compose[@]}" up -d "${compose_services[@]}"

snapshot_file="$runtime_dir/snapshot.json"
peer_token=$(<"$secret_dir/version-peer-token")
snapshot_temp="$snapshot_file.tmp"
for attempt in {1..12}; do
  if curl --fail --silent --show-error --retry 2 --retry-delay 1 --retry-all-errors \
    -H "Authorization: Bearer $peer_token" \
    "http://127.0.0.1:${PLATFORM_PORT:-8080}/api/v1/internal/version-snapshot" > "$snapshot_temp" \
    && python3 - "$snapshot_temp" <<'PY'
import json, sys
from pathlib import Path

components = json.loads(Path(sys.argv[1]).read_text()).get("components", {})
raise SystemExit(0 if components and all(
    item.get("health") == "healthy" and item.get("version") not in {None, "unknown"}
    for item in components.values()
) else 1)
PY
  then
    mv "$snapshot_temp" "$snapshot_file"
    break
  fi
  [[ "$attempt" == 12 ]] && { echo "Dev components did not become version-ready" >&2; exit 1; }
  sleep 3
done
python3 - "$metadata_file" "$snapshot_file" <<'PY'
import json, sys
from pathlib import Path

expected = json.loads(Path(sys.argv[1]).read_text())["components"]
actual = json.loads(Path(sys.argv[2]).read_text())["components"]
failures = []
for component_id, component in expected.items():
    identity = actual.get(component_id, {})
    if identity.get("version") != component["version"]:
        failures.append(f"{component_id}: expected {component['version']}, got {identity.get('version', 'missing')}")
if failures:
    raise SystemExit("Dev version verification failed:\n" + "\n".join(failures))
print(f"verified {len(expected)} component versions")
PY
python3 "$platform_dir/scripts/version_tool.py" report --dev "$snapshot_file" --output "$runtime_dir/dev-version-report.md"

echo "Dev 运行清单：$runtime_dir/current.json"
echo "Dev 版本报告：$runtime_dir/dev-version-report.md"
echo "版本页面：http://127.0.0.1:${PLATFORM_PORT:-8080}/system/versions"

#!/usr/bin/env bash
set -euo pipefail

release_dir=${1:?usage: deploy-prod.sh RELEASE_DIR}
base_env=/srv/test-platform/env/.env.prod
image_env="$release_dir/.env.images"
backup_root=/srv/test-platform/backups
compose=(docker compose --env-file "$base_env" --env-file "$image_env" -p test-platform-prod -f "$release_dir/docker-compose.yml" -f "$release_dir/docker-compose.prod.yml")

test -f "$base_env"
test -f "$image_env"
test -f "$release_dir/VERSION"
mkdir -p "$backup_root"

# 两个智能体以固定非 root UID 运行；令牌保持 600，并仅授权给对应容器用户。
sudo chown 10001:10001 /srv/test-platform/secrets/prod/functional-test-agent-client-token
sudo chown 10002:10002 \
  /srv/test-platform/secrets/prod/api-test-agent-client-token \
  /srv/test-platform/secrets/prod/api-execution-controller-token
sudo chmod 600 \
  /srv/test-platform/secrets/prod/functional-test-agent-client-token \
  /srv/test-platform/secrets/prod/api-test-agent-client-token \
  /srv/test-platform/secrets/prod/api-execution-controller-token

# 在替换应用前保留可恢复的数据库快照；首次切换由迁移流程单独恢复 dev 快照。
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
"${compose[@]}" run --rm platform-migrate

# 只在首次恢复出的空 prod 上复制 dev 当前激活配置；部分初始化必须人工处理。
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
"${compose[@]}" ps

for path in / /api/v1/health/live /trackevents/health /log-filter/health /truthy-search/health /api-autotest/health /functional-test-agent/health /api-test-agent/health; do
  curl --fail --silent --show-error --retry 12 --retry-delay 5 "http://127.0.0.1:41873$path" >/dev/null
done

ln -sfn "$release_dir" /srv/test-platform/current
echo "production release active: $(basename "$release_dir")"

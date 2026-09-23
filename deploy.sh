#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

for command_name in docker curl; do
    command -v "$command_name" >/dev/null || { echo "缺少命令：$command_name" >&2; exit 1; }
done
docker compose version >/dev/null

if [[ ! -f .env ]]; then
    cp deploy/.env.production.example .env
    chmod 600 .env
    echo "已创建 .env。请填写模型密钥和两个 MySQL 密码，然后重新运行 ./deploy.sh。" >&2
    exit 1
fi

for key in TIDEBOUND_LLM_API_KEY TIDEBOUND_MYSQL_PASSWORD TIDEBOUND_MYSQL_ROOT_PASSWORD; do
    if ! awk -F= -v key="$key" '$1 == key && length($0) > length(key) + 1 { found=1 } END { exit !found }' .env; then
        echo ".env 中缺少 $key 的值。" >&2
        exit 1
    fi
done

public_port=$(awk -F= '$1 == "TIDEBOUND_PUBLIC_PORT" { print $2; exit }' .env)
public_port=${public_port:-8080}
if [[ ! "$public_port" =~ ^[0-9]+$ ]] || (( public_port < 1 || public_port > 65535 )); then
    echo "TIDEBOUND_PUBLIC_PORT 必须是 1 到 65535 的端口。" >&2
    exit 1
fi

compose_project=${TIDEBOUND_COMPOSE_PROJECT:-tidebound-prod}
if [[ ! "$compose_project" =~ ^[a-z][a-z0-9_-]*$ ]]; then
    echo "TIDEBOUND_COMPOSE_PROJECT 不是合法的 Compose 项目名。" >&2
    exit 1
fi

docker compose --env-file .env -p "$compose_project" -f deploy/compose.prod.yaml up -d --build --wait
for attempt in {1..30}; do
    if curl --fail --silent --output /dev/null "http://127.0.0.1:${public_port}/api/health" && \
       curl --fail --silent --output /dev/null "http://127.0.0.1:${public_port}/app/"; then
        public_host=${TIDEBOUND_PUBLIC_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}' || true)}
        public_host=${public_host:-服务器IP}
        echo "部署完成：http://${public_host}:${public_port}/app/"
        exit 0
    fi
    sleep 2
done
echo "服务未通过 HTTP 验证；运行 docker compose --env-file .env -p $compose_project -f deploy/compose.prod.yaml logs 查看原因。" >&2
exit 1

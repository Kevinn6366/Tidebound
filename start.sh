#!/usr/bin/env bash
# Linux/macOS 开发启动；--skip-db 使用已有 MySQL。
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--skip-db" ) ]]; then
    echo "Usage: ./start.sh [--skip-db]" >&2
    exit 1
fi
for tool in uv node npm; do
    command -v "$tool" >/dev/null || { echo "Missing command: $tool" >&2; exit 1; }
done
if [[ ! -f .env ]]; then
    echo "Copy .env.example to .env and configure MySQL and model credentials first." >&2
    exit 1
fi
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 12)) { console.error("Node.js >=22.12 required"); process.exit(1); }'
uv sync --locked
# 提前拒绝重复启动，不停止其他终端或任务已运行的服务。
.venv/bin/python -c 'import socket; sockets = [socket.socket() for _ in range(2)]; [s.bind(("127.0.0.1", p)) for s, p in zip(sockets, (5201, 5173))]'
if [[ "${1:-}" != "--skip-db" ]]; then
    docker info >/dev/null
    docker compose --env-file .env -p tidebound -f deploy/compose.mysql.yaml up -d --wait
fi
npm --prefix webfrontend ci
mkdir -p data

backend_pid=""
frontend_pid=""
# 只回收本脚本启动的子进程，数据库容器保留以供下次使用。
cleanup() {
    local pid
    for pid in "$backend_pid" "$frontend_pid"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    wait || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
.venv/bin/python -u -m uvicorn webapp.main:app --host 127.0.0.1 --port 5201 --no-access-log --no-proxy-headers >> data/agent-debug.log 2>&1 &
backend_pid=$!
(
    cd webfrontend
    exec node node_modules/vite/bin/vite.js --host 127.0.0.1
) &
frontend_pid=$!
echo "Starting Tidebound: http://127.0.0.1:5173/app/"
echo "Backend log: data/agent-debug.log. Press Ctrl+C to stop both services."
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
    sleep 1
done
echo "A service stopped. Check the terminal and data/agent-debug.log." >&2
exit 1

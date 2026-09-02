#!/usr/bin/env bash
set -euo pipefail

# 开发机 Vue 实时预览：后端 API 在 8087，Vite 热更新界面在 5173。
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BACKEND_LOG="/tmp/ry-aletheia-dev-backend.log"
cd "$ROOT"

# 开发预览必须使用项目锁定的 Python 3.10：系统 Python 3.13 已移除
# stdlib cgi，而控制台的流式 multipart 上传仍依赖它。Pixi 同时锁定
# web_console.py 所需的 PyYAML，避免开发机全局解释器的依赖差异。
if command -v pixi >/dev/null 2>&1; then
  PYTHON_COMMAND=(pixi run python)
else
  PYTHON_COMMAND=(python3)
fi
if ! "${PYTHON_COMMAND[@]}" -c 'import cgi, yaml' >/dev/null 2>&1; then
  echo "后端需要项目的 Python 环境。请安装 Pixi 后重试：pixi install && pixi run vue-preview" >&2
  exit 1
fi

port_is_listening() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" | awk 'NR > 1 { found = 1 } END { exit(found ? 0 : 1) }'
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

show_port_owner() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp "sport = :$port" >&2 || true
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2 || true
  fi
}

start_detached_backend() {
  echo "正在恢复本地开发后端：http://127.0.0.1:8087"
  nohup "${PYTHON_COMMAND[@]}" "$ROOT/web_console.py" >"$BACKEND_LOG" 2>&1 &
  for _ in {1..20}; do
    curl -fsS --max-time 1 http://127.0.0.1:8087/api/settings >/dev/null 2>&1 && return 0
    sleep 0.25
  done
  echo "本地开发后端启动失败，请查看 $BACKEND_LOG" >&2
  return 1
}
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "未找到前端依赖。首次执行：cd frontend && npm install" >&2
  exit 1
fi

# 避免重复启动 Vite。已运行时不触碰它管理的进程，只返回可访问地址。
PREVIEW_RESPONSE="$(curl -fsS --max-time 1 http://127.0.0.1:5173/ 2>/dev/null || true)"
if [[ "$PREVIEW_RESPONSE" == *"/@vite/client"* && "$PREVIEW_RESPONSE" == *"id=\"app\""* ]]; then
  echo "Vue 实时预览已在运行：http://127.0.0.1:5173"
  if curl -fsS --max-time 1 http://127.0.0.1:8087/api/settings >/dev/null 2>&1; then
    echo "本地开发后端已就绪：http://127.0.0.1:8087"
  else
    start_detached_backend
  fi
  exit 0
fi
if port_is_listening 5173; then
  echo "端口 5173 已被其它程序占用，未启动新的 Vue 预览。" >&2
  show_port_owner 5173
  exit 1
fi
if ! curl -fsS --max-time 1 http://127.0.0.1:8087/api/settings >/dev/null 2>&1; then
  echo "正在启动本地开发后端：http://127.0.0.1:8087"
  "${PYTHON_COMMAND[@]}" "$ROOT/web_console.py" >"$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!
  cleanup() { kill "$BACKEND_PID" 2>/dev/null || true; }
  trap cleanup EXIT INT TERM
  for _ in {1..20}; do
    curl -fsS --max-time 1 http://127.0.0.1:8087/api/settings >/dev/null 2>&1 && break
    sleep 0.25
  done
  if ! curl -fsS --max-time 1 http://127.0.0.1:8087/api/settings >/dev/null 2>&1; then
    echo "本地开发后端启动失败，请查看 $BACKEND_LOG" >&2
    exit 1
  fi
fi
echo "Vue 实时预览：http://127.0.0.1:5173"
echo "同网段访问：http://<开发机IP>:5173"
echo "按 Ctrl+C 结束预览；若脚本启动了后端，也会一并停止。"
cd "$ROOT/frontend"
npm run dev

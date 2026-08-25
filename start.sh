#!/usr/bin/env bash
# =============================================================================
# 一键启动 Agent 评测平台
#
# 启动两个服务：
#   1. PikoCI 编排引擎   http://localhost:8080  （后台执行评测流水线）
#   2. Flask 平台        http://localhost:8000  （浏览器日常使用这个）
#
# 用法：
#   ./start.sh           # 启动两个服务
#   ./start.sh status    # 查看运行状态
#
# 日志：
#   /tmp/pikoci.log   /tmp/flask.log
# PID：
#   /tmp/pikoci.pid   /tmp/flask.pid
#
# 停止：./stop.sh
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

PIKOCI_PORT="${PIKOCI_PORT:-8080}"
FLASK_PORT="${FLASK_PORT:-8000}"
JWT_SECRET="${JWT_SECRET:-dev-secret}"

PIKOCI_PID_FILE="/tmp/pikoci.pid"
FLASK_PID_FILE="/tmp/flask.pid"
PIKOCI_LOG="/tmp/pikoci.log"
FLASK_LOG="/tmp/flask.log"

# 加载 .env（含 ARK_API_KEY 等），让子进程继承
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="$(command -v python3)"

is_running() {
  local pid_file="$1"
  [ -f "$pid_file" ] || return 1
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

wait_for_port() {
  local port="$1" name="$2"
  for _ in $(seq 1 30); do
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "  ✓ $name 已就绪 (端口 $port)"
      return 0
    fi
    sleep 0.5
  done
  echo "  ⚠ $name 在端口 $port 未就绪，请查看日志"
  return 1
}

cmd_status() {
  echo "== 服务状态 =="
  if is_running "$PIKOCI_PID_FILE"; then
    echo "  PikoCI  运行中  PID=$(cat "$PIKOCI_PID_FILE")  http://localhost:$PIKOCI_PORT"
  else
    echo "  PikoCI  未运行"
  fi
  if is_running "$FLASK_PID_FILE"; then
    echo "  Flask   运行中  PID=$(cat "$FLASK_PID_FILE")  http://localhost:$FLASK_PORT"
  else
    echo "  Flask   未运行"
  fi
}

cmd_start() {
  mkdir -p eval_output

  if [ "$(uname -s 2>/dev/null)" = "Linux" ]; then
    echo "注意：当前为 Linux 环境，请确认 pikoci 二进制为对应平台版本。"
  fi

  # ---- 1. PikoCI ----
  if is_running "$PIKOCI_PID_FILE"; then
    echo "PikoCI 已在运行 (PID=$(cat "$PIKOCI_PID_FILE"))，跳过。"
  else
    if [ ! -x ./pikoci ]; then
      echo "错误：找不到可执行的 ./pikoci，请先下载（见 README_PIPELINE.md）。" >&2
      exit 1
    fi
    echo "启动 PikoCI 编排引擎 ..."
    nohup ./pikoci server \
      --db-system mem \
      --jwt-secret "$JWT_SECRET" \
      --pipeline-name agent-eval \
      --pipeline-config pipeline.hcl \
      > "$PIKOCI_LOG" 2>&1 &
    echo $! > "$PIKOCI_PID_FILE"
    wait_for_port "$PIKOCI_PORT" "PikoCI" || true
  fi

  # ---- 2. Flask 平台 ----
  if is_running "$FLASK_PID_FILE"; then
    echo "Flask 平台已在运行 (PID=$(cat "$FLASK_PID_FILE"))，跳过。"
  else
    echo "启动 Flask 平台 ..."
    nohup "$PYTHON_BIN" run.py > "$FLASK_LOG" 2>&1 &
    echo $! > "$FLASK_PID_FILE"
    wait_for_port "$FLASK_PORT" "Flask" || true
  fi

  echo ""
  cmd_status
  echo ""
  echo "浏览器打开：  http://localhost:$FLASK_PORT   （账号 admin / admin123）"
  echo "查看日志：    tail -f $FLASK_LOG   |   tail -f $PIKOCI_LOG"
  echo "停止：        ./stop.sh"
}

case "${1:-start}" in
  start)  cmd_start ;;
  status) cmd_status ;;
  *) echo "用法: $0 [start|status]"; exit 1 ;;
esac

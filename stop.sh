#!/usr/bin/env bash
# =============================================================================
# 停止 Agent 评测平台的两个服务（PikoCI + Flask）
#
# 用法：./stop.sh
# =============================================================================
set -uo pipefail

PIKOCI_PID_FILE="/tmp/pikoci.pid"
FLASK_PID_FILE="/tmp/flask.pid"

stop_by_pid() {
  local name="$1" pid_file="$2"
  if [ ! -f "$pid_file" ]; then
    echo "$name: 未找到 PID 文件，已停止。"
    return 0
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    echo "$name: 进程 $pid 未在运行。"
    rm -f "$pid_file"
    return 0
  fi
  echo "$name: 停止 PID $pid ..."
  # Flask debug 模式会 fork 出子进程；用进程组收尾，避免残留
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.3
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "$name: 强制结束 ..."
    kill -9 "$pid" 2>/dev/null || true
  fi
  # 兜底：清理同命令的残留子进程（Flask reloader）
  pkill -f "run.py" 2>/dev/null || true
  rm -f "$pid_file"
  echo "  ✓ $name 已停止"
}

stop_by_pid "Flask"  "$FLASK_PID_FILE"
stop_by_pid "PikoCI" "$PIKOCI_PID_FILE"

echo ""
echo "完成。"

#!/usr/bin/env bash
# =============================================================
#  玫瑰小镇 本地私服 —— 一键启动（服务端 + 游戏客户端）
# -------------------------------------------------------------
#  用法：
#    ./start_rose.sh                 # 启动服务端并自动打开游戏
#    ./start_rose.sh --server-only   # 只起服务端，不打开浏览器
#    ./start_rose.sh --no-wait       # 前端不阻塞（后台跑，脚本立即退出）
#    ROSE_PORT=9090 ./start_rose.sh  # 换端口
#    Ctrl-C 结束（若服务端是本脚本启动的，会一并关掉）
# =============================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PORT="${ROSE_PORT:-8088}"
BIND_HOST="${ROSE_HOST:-127.0.0.1}"
CONNECT_HOST="$BIND_HOST"
if [ "$CONNECT_HOST" = "0.0.0.0" ]; then CONNECT_HOST="127.0.0.1"; fi
SERVER_PY="$HERE/private_server.py"
STDOUT_LOG="${ROSE_STDOUT_LOG:-$HERE/server_stdout.log}"

# ---- 伪登录参数（还原自客户端 HttpSettings 的登录态注入，见 README_private_server.md）----
OPENID="AADAD8430DD37E40107C2D2D944712AF"
PINGPONG="448984620"
APPID="102072120"
SERVER_ONLY=0
NO_WAIT=0
for a in "$@"; do
  case "$a" in
    --server-only) SERVER_ONLY=1 ;;
    --no-wait)     NO_WAIT=1 ;;
    -h|--help)     sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "未知参数: $a" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "[!] 找不到 python3" >&2; exit 1; }
if ! [[ "$PORT" =~ ^[0-9]{1,5}$ ]] || (( 10#$PORT < 1 || 10#$PORT > 65535 )); then
  echo "[!] ROSE_PORT 必须是1到65535之间的端口号" >&2
  exit 2
fi
PORT=$((10#$PORT))
GAME_URL="http://${CONNECT_HOST}:${PORT}/index.html?open=portal&PingPong=${PINGPONG}&openid=${OPENID}&token=localtoken&openkey=localtoken&appid=${APPID}&session_type=openkey"

SERVER_PID=""
STARTED_BY_US=0

port_in_use() { (exec 3<>"/dev/tcp/${CONNECT_HOST}/${PORT}") 2>/dev/null; }

server_ready() {
  python3 - "$CONNECT_HOST" "$PORT" <<'PY'
import json
import sys
import urllib.request

try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://%s:%s/healthz" % tuple(sys.argv[1:]), timeout=0.5) as response:
        data = json.loads(response.read(4096))
        ready = response.status == 200 and data.get("service") == "rose-town-local" and data.get("status") == "ok"
except (OSError, ValueError, AttributeError):
    ready = False
sys.exit(0 if ready else 1)
PY
}

cleanup() {
  if [ "$STARTED_BY_US" = "1" ] && [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "[*] 关闭服务端 (pid ${SERVER_PID}) ..."
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ---------- 1. 启动服务端，只复用通过健康检查的游戏服务 ----------
if server_ready; then
  echo "[=] 端口 ${PORT} 已有玫瑰小镇服务，直接复用。"
elif port_in_use; then
  echo "[!] 端口 ${PORT} 被其他程序或旧版服务占用，请更换 ROSE_PORT 或先停止该程序。" >&2
  exit 1
else
  [ -f "$SERVER_PY" ] || { echo "[!] 缺少 $SERVER_PY" >&2; exit 1; }
  echo "[*] 启动私服: python3 private_server.py  (端口 ${PORT})"
  ROSE_PORT="$PORT" ROSE_HOST="$BIND_HOST" nohup python3 -u "$SERVER_PY" < /dev/null >"$STDOUT_LOG" 2>&1 &
  SERVER_PID=$!
  STARTED_BY_US=1

  # 等待游戏健康检查通过，不能只凭端口已监听判断启动成功。
  for _ in {1..50}; do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      echo "[!] 服务端启动失败，日志尾部：" >&2
      tail -n 20 "$STDOUT_LOG" >&2 || true
      exit 1
    fi
    if server_ready; then break; fi
    sleep 0.2
  done
  server_ready || { echo "[!] 服务端未在 ${PORT} 就绪" >&2; exit 1; }
fi

echo "[+] 服务端就绪: http://${CONNECT_HOST}:${PORT}/"
echo "[+] 游戏地址  : ${GAME_URL}"

# ---------- 2. 打开游戏（优先 chromium，其次系统默认浏览器） ----------
open_browser() {
  local url="$1"
  if command -v chromium >/dev/null 2>&1; then chromium "$url" >/dev/null 2>&1 &
  elif command -v google-chrome >/dev/null 2>&1; then google-chrome "$url" >/dev/null 2>&1 &
  elif command -v chromium-browser >/dev/null 2>&1; then chromium-browser "$url" >/dev/null 2>&1 &
  elif command -v firefox >/dev/null 2>&1; then firefox "$url" >/dev/null 2>&1 &
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$url" >/dev/null 2>&1 &
  else echo "[!] 未找到可用浏览器，请手动打开：${url}"; return 1; fi
}
if [ "$SERVER_ONLY" != "1" ]; then
  echo "[*] 打开游戏 ..."
  open_browser "$GAME_URL" || true
fi

if [ "$STARTED_BY_US" != "1" ]; then
  echo "[*] 使用已有服务，脚本退出；已有服务继续运行。"
  exit 0
fi

if [ "$NO_WAIT" = "1" ]; then
  disown "$SERVER_PID" 2>/dev/null || true
  echo "[*] 服务端后台运行中（pid ${SERVER_PID}），脚本退出，游戏不受影响。"
  trap - EXIT INT TERM
  exit 0
fi

echo "[*] 服务端运行中，Ctrl-C 结束游戏服务。"
wait "$SERVER_PID"

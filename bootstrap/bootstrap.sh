#!/usr/bin/env bash
# HR 子仓独立测试床一键自举（批 C）
#
# 面向子仓-only 检出（本仓同级独立 clone），一键完成：
#   隔离基础设施栈（compose tmpfs）→ 浅克隆主仓 + 子仓内容锁版本覆盖装配 →
#   后端 venv + 临时库迁移/seed + uvicorn 拉起 → 前端依赖 + vite dev 拉起
#
# 用法：
#   bootstrap/bootstrap.sh                 # 全量自举并拉起服务（前台驻留日志后退出）
#   bootstrap/bootstrap.sh --down          # 停止并清理全部自举产物
#
# 自举产物统一落在 bootstrap/.work/（已 .gitignore），不污染子仓与主仓。
# 服务起来后按提示运行集成测试与 e2e（见 bootstrap/README.md）。

set -euo pipefail

SUBREPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${SUBREPO_ROOT}/bootstrap/.work"
MAIN_DIR="${WORK_DIR}/kcloudy.ai-platform"
COMPOSE_FILE="${SUBREPO_ROOT}/bootstrap/docker-compose.infra.yml"

SUBREPO_REV="$(git -C "${SUBREPO_ROOT}" rev-parse HEAD)"
# 主仓克隆引用：子模块挂载 + gitlink 现居 feature/hr-system（合并 main 后可 HR_MAIN_REF=main 覆盖）
MAIN_REF="${HR_MAIN_REF:-feature/hr-system}"
BACKEND_PORT="${HR_TESTBED_BACKEND_PORT:-18080}"
FRONTEND_PORT="${HR_TESTBED_FRONTEND_PORT:-15173}"
PG_PORT="${HR_TESTBED_PG_PORT:-15432}"
TESTDB_NAME="hr_testbed"

log() { echo "[hr-testbed] $*"; }

backend_env() {
  cat <<EOF
PYTHON_SERVICE_ENV=local
TZ=Asia/Shanghai
PYTHONPATH=${MAIN_DIR}/server/python/src
APP_CONFIG_DIR=${MAIN_DIR}/server/config
SQLALCHEMY_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:${PG_PORT}/${TESTDB_NAME}
SQLALCHEMY_AUTO_MIGRATE=true
SQLALCHEMY_ECHO=false
REDIS_SINGLE_HOST=127.0.0.1
REDIS_SINGLE_PORT=16379
REDIS_SINGLE_PASSWORD=redis123
REDIS_SINGLE_DB=0
OSS_MINIO_ENDPOINT=127.0.0.1:19000
VITE_API_TARGET=http://127.0.0.1:${BACKEND_PORT}
EOF
}

wait_http() {
  # wait_http <名称> <url> <最大次数>
  local name="$1" url="$2" max="$3" i=1
  until curl -sf -o /dev/null "${url}"; do
    if [ "${i}" -ge "${max}" ]; then
      log "错误：${name} 就绪轮询 ${max} 次未通过（${url}）"
      return 1
    fi
    i=$((i + 1))
    sleep 3
  done
  log "${name} 就绪"
}

down() {
  log "清理自举产物…"
  if [ -f "${WORK_DIR}/backend.pid" ]; then
    kill "$(cat "${WORK_DIR}/backend.pid")" 2>/dev/null || true
    rm -f "${WORK_DIR}/backend.pid"
  fi
  if [ -f "${WORK_DIR}/frontend.pid" ]; then
    kill "$(cat "${WORK_DIR}/frontend.pid")" 2>/dev/null || true
    rm -f "${WORK_DIR}/frontend.pid"
  fi
  if docker compose -f "${COMPOSE_FILE}" ps -q 2>/dev/null | grep -q .; then
    docker compose -f "${COMPOSE_FILE}" down -v --remove-orphans || true
  fi
  rm -rf "${WORK_DIR}"
  log "清理完成"
}

if [ "${1:-}" = "--down" ]; then
  down
  exit 0
fi

# ---------- 0. 前置检查 ----------
for tool in docker uv node pnpm; do
  command -v "${tool}" >/dev/null 2>&1 || { log "错误：缺少依赖 ${tool}"; exit 1; }
done
docker compose version >/dev/null 2>&1 || { log "错误：docker compose 不可用"; exit 1; }

# ---------- 1. 隔离基础设施栈 ----------
log "拉起隔离基础设施栈（tmpfs，无持久化）…"
# 不用 --wait：minio-init 为 one-shot 容器，跑完即 exited，部分 compose 版本
# 将其判为非 running 使 --wait 返回非 0（docker/compose#10596）；就绪由下方
# pg_isready 轮询与 minio-init 的 depends_on: service_healthy 兜底
docker compose -f "${COMPOSE_FILE}" up -d
for i in $(seq 1 10); do
  docker compose -f "${COMPOSE_FILE}" exec -T postgres pg_isready -U postgres -d hr_testbed >/dev/null 2>&1 && break
  sleep 2
done
log "建临时库 ${TESTDB_NAME}（幂等）"
docker compose -f "${COMPOSE_FILE}" exec -T postgres psql -U postgres -d postgres -c \
  "SELECT 1 FROM pg_database WHERE datname='${TESTDB_NAME}'" | grep -q 1 ||
  docker compose -f "${COMPOSE_FILE}" exec -T postgres psql -U postgres -d postgres -c \
    "CREATE DATABASE ${TESTDB_NAME}"

# ---------- 2. 浅克隆主仓 + 子仓内容锁版本覆盖装配 ----------
if [ ! -d "${MAIN_DIR}/.git" ]; then
  log "浅克隆主仓（--depth 1）…"
  git clone --depth 1 --branch "${MAIN_REF}" git@gitee.com:kenttian/kcloudy.ai-platform.git "${MAIN_DIR}"
  git -C "${MAIN_DIR}" submodule update --init --depth 1
fi
# Windows 修复：git 检出的目录 symlink 在本机原生进程不可穿透（真 symlink 被 Node/Python
# EPERM；无权限 clone 时退化为纯文本文件），统一换 junction（mklink /J 无需特权，幂等）。
# 清单以 git ls-files 的 120000 模式为权威，兼容「真 symlink / 文本回退」两种工作树形态
if command -v cmd.exe >/dev/null 2>&1 && command -v cygpath >/dev/null 2>&1; then
  log "Windows 修复：主仓 clone 内 git symlink 换 junction…"
  git -C "${MAIN_DIR}" ls-files -s | awk '$1=="120000"{print $4}' | sed 's/"//g' |
  while IFS= read -r rel; do
    link="${MAIN_DIR}/${rel}"
    # 已是目录（junction/真实落位）则跳过——MSYS 对 junction 报 -L 与 -d 均真，-d 优先判
    if [ -d "$link" ]; then continue; fi
    if [ ! -f "$link" ]; then continue; fi
    target="$(dirname "$link")/$(cat "$link")"
    rm -f "$link"
    cmd //c mklink //J "$(cygpath -w "$link")" "$(cygpath -w "${target%/}")" >/dev/null
  done
fi
log "子仓内容锁版本覆盖装配（${SUBREPO_REV:0:7}）…"
# rsync 缺席时（Windows git-bash 不自带）用 robocopy /MIR 等价镜像；
# /XD、/XF 用绝对路径精确限定，避免同名误伤；robocopy rc<8 均为成功
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.git' --exclude '.gitignore' --exclude 'bootstrap/' \
    "${SUBREPO_ROOT}/" "${MAIN_DIR}/server/python/src/modules/hr/"
else
  wsrc="$(cygpath -w "${SUBREPO_ROOT}")"; wdst="$(cygpath -w "${MAIN_DIR}/server/python/src/modules/hr")"
  rc=0
  robocopy "${wsrc}" "${wdst}" //MIR //XD "${wsrc}\.git" "${wsrc}\bootstrap" //XF "${wsrc}\.gitignore" \
    //NFL //NDL //NJH //NJS //NP || rc=$?
  [ "${rc}" -lt 8 ] || { log "错误：robocopy 装配失败（rc=${rc}）"; exit 1; }
fi
# 前端测试面特殊处理：playwright/vitest 经 junction 的 realpath 会逃出 cwd 变换钩子与
# node_modules 解析域（配置能找到但加载必炸）——web/vue/tests/hr 直接以真实文件落位，
# 内容仍为子仓 web/tests/hr（被测代码同一份）；src/hr 后端链接保持 junction（Python 可穿透）
web_tests_link="${MAIN_DIR}/web/vue/tests/hr"
web_tests_src="${SUBREPO_ROOT}/web/tests/hr"
if [ -e "$web_tests_link" ] || [ -L "$web_tests_link" ]; then
  if [ -L "$web_tests_link" ]; then
    rm -f "$web_tests_link"
  elif [ -d "$web_tests_link" ]; then
    cmd //c rmdir "$(cygpath -w "$web_tests_link")" >/dev/null 2>&1 || rm -rf "$web_tests_link"
  else
    rm -f "$web_tests_link"
  fi
fi
rc=0
robocopy "$(cygpath -w "$web_tests_src")" "$(cygpath -w "$web_tests_link")" //MIR //E //NFL //NDL //NJH //NJS //NP || rc=$?
[ "${rc}" -lt 8 ] || { log "错误：web 测试面落位失败（rc=${rc}）"; exit 1; }
mkdir -p "${WORK_DIR}"

# ---------- 3. 后端 venv + 迁移/seed 由启动期 auto_migrate 完成 ----------
# --all-groups：应用动态加载全部启用模块，模块专属依赖组（ontology 的 rdflib 等）必须就位，
# 仅装公共段会在首个跨模块 import 处崩溃（与主仓开发 venv 同口径）
log "后端依赖安装（uv sync --frozen --all-groups）…"
( cd "${MAIN_DIR}/server/python" && uv sync --frozen --all-groups >/dev/null )

backend_env > "${WORK_DIR}/testbed.env"
log "拉起 uvicorn :${BACKEND_PORT}（auto_migrate 建表 + 各模块 seed + 菜单/权限码同步）…"
# venv 布局自适应：Windows 为 Scripts/uvicorn.exe，POSIX 为 bin/uvicorn
if [ -f "${MAIN_DIR}/server/python/.venv/Scripts/uvicorn.exe" ]; then
  UVICORN=".venv/Scripts/uvicorn.exe"
else
  UVICORN=".venv/bin/uvicorn"
fi
(
  cd "${MAIN_DIR}/server/python"
  set -a; source "${WORK_DIR}/testbed.env"; set +a
  nohup "${UVICORN}" application_web:app \
    --host 127.0.0.1 --port "${BACKEND_PORT}" \
    > "${WORK_DIR}/backend.log" 2>&1 &
  echo $! > "${WORK_DIR}/backend.pid"
)
wait_http "后端" "http://127.0.0.1:${BACKEND_PORT}/health" 40

# ---------- 4. 前端依赖 + vite dev ----------
log "前端依赖安装（pnpm install --frozen-lockfile）…"
( cd "${MAIN_DIR}/web/vue" && pnpm install --frozen-lockfile --ignore-scripts >/dev/null )
log "拉起 vite dev :${FRONTEND_PORT}…"
(
  cd "${MAIN_DIR}/web/vue"
  set -a; source "${WORK_DIR}/testbed.env"; set +a
  nohup pnpm dev --port "${FRONTEND_PORT}" --strictPort \
    > "${WORK_DIR}/frontend.log" 2>&1 &
  echo $! > "${WORK_DIR}/frontend.pid"
)
wait_http "前端" "http://127.0.0.1:${FRONTEND_PORT}/" 40

# ---------- 5. 就绪提示 ----------
log "自举完成 ✅"
log "  后端 API   http://127.0.0.1:${BACKEND_PORT}  （日志 ${WORK_DIR}/backend.log）"
log "  前端 dev   http://127.0.0.1:${FRONTEND_PORT}  （日志 ${WORK_DIR}/frontend.log）"
log "  集成测试：HR_TEST_BASE_URL=http://127.0.0.1:${BACKEND_PORT} \\"
log "            python -m pytest ${SUBREPO_ROOT}/server/tests/hr/integration -q"
log "  e2e：      cd ${MAIN_DIR}/web/vue && E2E_BASE_URL=http://127.0.0.1:${FRONTEND_PORT} \\"
log "            pnpm exec playwright test --config tests/hr/e2e/playwright.config.ts"
log "  清理：     bootstrap/bootstrap.sh --down"

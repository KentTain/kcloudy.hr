#!/usr/bin/env bash
# HR 子仓独立测试床一键自举（批 C）
#
# 面向子仓-only 检出（本仓同级独立 clone），一键完成：
#   隔离基础设施栈（compose tmpfs）→ 浅克隆主仓 + 子仓内容锁版本覆盖装配 →
#   后端 venv + 临时库迁移/seed + uvicorn 拉起 → 前端依赖 + vite dev 拉起
#
# 用法：
#   testbed/bootstrap.sh                 # 全量自举并拉起服务（前台驻留日志后退出）
#   testbed/bootstrap.sh --down          # 停止并清理全部自举产物
#
# 自举产物统一落在 testbed/.work/（已 .gitignore），不污染子仓与主仓。
# 服务起来后按提示运行集成测试与 e2e（见 testbed/README.md）。

set -euo pipefail

SUBREPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${SUBREPO_ROOT}/testbed/.work"
MAIN_DIR="${WORK_DIR}/kcloudy.ai-platform"
COMPOSE_FILE="${SUBREPO_ROOT}/testbed/docker-compose.infra.yml"

SUBREPO_REV="$(git -C "${SUBREPO_ROOT}" rev-parse HEAD)"
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
docker compose -f "${COMPOSE_FILE}" up -d --wait
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
  git clone --depth 1 git@gitee.com:kenttian/kcloudy.ai-platform.git "${MAIN_DIR}"
  git -C "${MAIN_DIR}" submodule update --init --depth 1
fi
log "子仓内容锁版本覆盖装配（${SUBREPO_REV:0:7}）…"
rsync -a --delete \
  --exclude '.git' --exclude '.gitignore' --exclude 'testbed/' \
  "${SUBREPO_ROOT}/" "${MAIN_DIR}/server/python/src/modules/hr/"
mkdir -p "${WORK_DIR}"

# ---------- 3. 后端 venv + 迁移/seed 由启动期 auto_migrate 完成 ----------
log "后端依赖安装（uv sync --frozen）…"
( cd "${MAIN_DIR}/server/python" && uv sync --frozen --no-dev >/dev/null )

backend_env > "${WORK_DIR}/testbed.env"
log "拉起 uvicorn :${BACKEND_PORT}（auto_migrate 建表 + 各模块 seed + 菜单/权限码同步）…"
(
  cd "${MAIN_DIR}/server/python"
  set -a; source "${WORK_DIR}/testbed.env"; set +a
  nohup .venv/bin/uvicorn application_web:app \
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
log "  e2e：      cd ${MAIN_DIR}/web/vue && HR_TEST_BASE_URL=http://127.0.0.1:${FRONTEND_PORT} \\"
log "            pnpm exec playwright test --config playwright.config.ts tests/hr/e2e"
log "  清理：     testbed/bootstrap.sh --down"

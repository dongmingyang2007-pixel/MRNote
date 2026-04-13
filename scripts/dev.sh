#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"
SERVICES=(postgres redis minio minio-init api worker web)
INFRA_SERVICES=(postgres redis minio)
INIT_SERVICES=(minio-init)
APP_SERVICES=(api worker web)
STATE_DIR="$ROOT_DIR/tmp/dev-stack-state"
STATE_FILE="$STATE_DIR/service-fingerprints.txt"
LOCAL_STATE_DIR="$ROOT_DIR/tmp/dev-local"
LOCAL_PID_DIR="$LOCAL_STATE_DIR/pids"
LOCAL_LOG_DIR="$LOCAL_STATE_DIR/logs"
LOCAL_API_DEPS_STAMP="$LOCAL_STATE_DIR/api-deps.stamp"
LOCAL_WEB_DEPS_STAMP="$LOCAL_STATE_DIR/web-deps.stamp"

MODE="local"
REBUILD=0
CLEAN=0
CLEAN_ARTIFACTS=0

usage() {
  cat <<'EOF'
Usage: ./scripts/dev.sh [--local|--docker] [--rebuild] [--clean] [--clean-artifacts]

Default behavior:
  Start the local development stack in fast mode:
  - postgres / redis / minio via docker compose
  - api / worker / web as local processes

Modes:
  --local            Fast local mode (default).
  --docker           Full docker-compose mode with image builds.

Options:
  --rebuild          Local mode: reinstall app dependencies before startup.
                     Docker mode: rebuild changed images before startup.
  --clean            Stop the old stack first, then start again.
  --clean-artifacts  Delete local Playwright output directories before starting.
  -h, --help         Show this help message.
EOF
}

join_by() {
  local delimiter="$1"
  shift
  local first=1
  local item
  for item in "$@"; do
    if [ "$first" -eq 1 ]; then
      printf '%s' "$item"
      first=0
    else
      printf '%s%s' "$delimiter" "$item"
    fi
  done
}

fingerprint_paths() {
  local tmp_file
  tmp_file="$(mktemp)"

  while [ $# -gt 0 ]; do
    local path="$1"
    shift

    if [ -d "$path" ]; then
      find "$path" \
        \( \
          -name .git -o \
          -name .venv -o \
          -name node_modules -o \
          -name .next -o \
          -name test-results -o \
          -name playwright-report -o \
          -name __pycache__ -o \
          -name .pytest_cache -o \
          -name .ruff_cache -o \
          -name output \
        \) -prune -o \
        -type f \
        ! -name '.DS_Store' \
        ! -name '*.pyc' \
        ! -name '*.pyo' \
        ! -name '*.pyd' \
        ! -name '*.tsbuildinfo' \
        ! -name '*.db' \
        ! -name '*.sqlite' \
        ! -name '*.sqlite3' \
        ! -name '*.log' \
        ! -name '*.pid' \
        -print >>"$tmp_file"
    elif [ -f "$path" ]; then
      printf '%s\n' "$path" >>"$tmp_file"
    fi
  done

  if [ ! -s "$tmp_file" ]; then
    rm -f "$tmp_file"
    echo "missing"
    return 0
  fi

  LC_ALL=C sort -u "$tmp_file" | while IFS= read -r file; do
    if [ -f "$file" ]; then
      shasum "$file"
    fi
  done | shasum | awk '{print $1}'

  rm -f "$tmp_file"
}

load_saved_fingerprint() {
  local service="$1"
  if [ ! -f "$STATE_FILE" ]; then
    return 1
  fi
  awk -v target="$service" '$1 == target { print $2 }' "$STATE_FILE" | tail -n 1
}

save_fingerprints() {
  mkdir -p "$STATE_DIR"
  cat >"$STATE_FILE" <<EOF
web $WEB_FINGERPRINT
api $API_FINGERPRINT
worker $WORKER_FINGERPRINT
EOF
}

cleanup_docker_build_space() {
  echo "Docker build ran out of disk space. Cleaning unused Docker images and stopped containers..."
  docker builder prune -af >/dev/null 2>&1 || true
  docker image prune -af >/dev/null 2>&1 || true
  docker container prune -f >/dev/null 2>&1 || true
}

cleanup_docker_unused_artifacts() {
  echo "Cleaning lightweight Docker leftovers before startup..."
  docker builder prune -f >/dev/null 2>&1 || true
  docker image prune -f >/dev/null 2>&1 || true
  docker container prune -f >/dev/null 2>&1 || true
}

log_contains() {
  local pattern="$1"
  local file="$2"
  grep -Eiq "$pattern" "$file"
}

show_registry_timeout_hint() {
  local file="$1"
  if log_contains 'registry-1\.docker\.io|failed to resolve reference "docker\.io/|docker\.io/' "$file"; then
    cat >&2 <<'EOF'
Docker could not reach Docker Hub.
If Docker Hub is slow or blocked on this network, set reachable images in .env, for example:
  PYTHON_BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
  NODE_BASE_IMAGE=docker.m.daocloud.io/library/node:22-bookworm-slim
  POSTGRES_IMAGE=docker.m.daocloud.io/pgvector/pgvector:pg15
  REDIS_IMAGE=docker.m.daocloud.io/library/redis:7
  MINIO_IMAGE=docker.m.daocloud.io/minio/minio:latest
  MINIO_MC_IMAGE=docker.m.daocloud.io/minio/mc:latest
EOF
  fi
}

build_services_with_retry() {
  if [ $# -eq 0 ]; then
    return 0
  fi

  local log_file
  local attempt
  local build_status
  local cleaned_space=0
  log_file="$(mktemp)"

  for attempt in 1 2 3; do
    : >"$log_file"
    set +e
    compose_cmd build "$@" 2>&1 | tee "$log_file"
    build_status=${PIPESTATUS[0]}
    set -e

    if [ "$build_status" -eq 0 ]; then
      rm -f "$log_file"
      return 0
    fi

    if [ "$cleaned_space" -eq 0 ] && log_contains 'ENOSPC|no space left on device|nospc' "$log_file"; then
      cleaned_space=1
      cleanup_docker_build_space
      echo "Retrying docker compose build after Docker cleanup..."
      continue
    fi

    if log_contains 'i/o timeout|tls handshake timeout|client\.timeout|econnreset|network timed out|temporary failure|unexpected eof|connection reset by peer' "$log_file"; then
      if [ "$attempt" -lt 3 ]; then
        echo "Docker build hit a transient network error. Retrying in 5s..."
        sleep 5
        continue
      fi
    fi

    show_registry_timeout_hint "$log_file"
    rm -f "$log_file"
    return "$build_status"
  done

  show_registry_timeout_hint "$log_file"
  rm -f "$log_file"
  return "$build_status"
}

run_compose_with_retry() {
  local log_file
  local attempt
  local command_status
  log_file="$(mktemp)"

  for attempt in 1 2 3; do
    : >"$log_file"
    set +e
    compose_cmd "$@" 2>&1 | tee "$log_file"
    command_status=${PIPESTATUS[0]}
    set -e

    if [ "$command_status" -eq 0 ]; then
      rm -f "$log_file"
      return 0
    fi

    if log_contains 'i/o timeout|tls handshake timeout|client\.timeout|econnreset|network timed out|temporary failure|unexpected eof|connection reset by peer' "$log_file"; then
      if [ "$attempt" -lt 3 ]; then
        echo "Docker compose command hit a transient network error. Retrying in 5s..."
        sleep 5
        continue
      fi
    fi

    rm -f "$log_file"
    return "$command_status"
  done

  rm -f "$log_file"
  return "$command_status"
}

compose_cmd() {
  if [ -f "$ENV_FILE" ]; then
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  else
    docker compose -f "$COMPOSE_FILE" "$@"
  fi
}

PLAYWRIGHT_OUTPUT_DIRS=(
  "$ROOT_DIR/output/playwright"
  "$ROOT_DIR/apps/web/output/playwright"
  "$ROOT_DIR/apps/web/test-results"
)

wait_for_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-60}"
  local delay="${4:-2}"

  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name is ready at $url"
      return 0
    fi
    sleep "$delay"
  done

  echo "Timed out waiting for $name at $url" >&2
  return 1
}

wait_for_service_health() {
  local service="$1"
  local attempts="${2:-60}"
  local delay="${3:-2}"
  local container_id=""
  local status=""

  for ((i = 1; i <= attempts; i++)); do
    container_id="$(compose_cmd ps -q "$service" 2>/dev/null | tr -d '\n')"
    if [ -n "$container_id" ]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id" 2>/dev/null || true)"
      if [ "$status" = "healthy" ] || [ "$status" = "none" ]; then
        echo "$service healthcheck is $status"
        return 0
      fi
    fi
    sleep "$delay"
  done

  echo "Timed out waiting for $service healthcheck (last status: ${status:-unknown})" >&2
  return 1
}

show_service_logs() {
  local service="$1"
  echo
  echo "Recent logs for $service:"
  compose_cmd logs --tail=80 "$service" || true
}

cleanup_playwright_outputs() {
  local dir
  for dir in "${PLAYWRIGHT_OUTPUT_DIRS[@]}"; do
    mkdir -p "$dir"
    find "$dir" -mindepth 1 -delete
  done
}

reset_local_web_cache() {
  echo "Resetting local Next.js dev cache..."
  rm -rf "$ROOT_DIR/apps/web/.next"
}

ensure_directory_layout() {
  mkdir -p "$STATE_DIR" "$LOCAL_STATE_DIR" "$LOCAL_PID_DIR" "$LOCAL_LOG_DIR"
}

ensure_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "$command_name is required but not found" >&2
    exit 1
  fi
}

show_local_service_log() {
  local service="$1"
  local log_file="$LOCAL_LOG_DIR/$service.log"
  echo
  echo "Recent logs for local $service:"
  if [ -f "$log_file" ]; then
    tail -n 80 "$log_file"
  else
    echo "No log file found for $service"
  fi
}

is_pid_running() {
  local pid="$1"
  kill -0 "$pid" >/dev/null 2>&1
}

kill_pid_list() {
  local service="$1"
  shift
  local pids=("$@")
  local pid

  if [ "${#pids[@]}" -eq 0 ]; then
    return 0
  fi

  for pid in "${pids[@]}"; do
    if [ -n "$pid" ] && is_pid_running "$pid"; then
      echo "Stopping local $service process ($pid)..."
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done

  for _ in $(seq 1 20); do
    local still_running=0
    for pid in "${pids[@]}"; do
      if [ -n "$pid" ] && is_pid_running "$pid"; then
        still_running=1
        break
      fi
    done
    if [ "$still_running" -eq 0 ]; then
      return 0
    fi
    sleep 0.5
  done

  for pid in "${pids[@]}"; do
    if [ -n "$pid" ] && is_pid_running "$pid"; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  done
}

stop_pid_file_process() {
  local service="$1"
  local pid_file="$LOCAL_PID_DIR/$service.pid"

  if [ ! -f "$pid_file" ]; then
    return 0
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  rm -f "$pid_file"

  if [ -z "$pid" ] || ! is_pid_running "$pid"; then
    return 0
  fi

  kill_pid_list "$service" "$pid"
}

stop_processes_on_port() {
  local service="$1"
  local port="$2"
  local raw_pids=""
  local pids=()
  local pid

  raw_pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -z "$raw_pids" ]; then
    return 0
  fi

  while IFS= read -r pid; do
    if [ -n "$pid" ]; then
      pids+=("$pid")
    fi
  done <<<"$raw_pids"

  kill_pid_list "$service" "${pids[@]}"
}

stop_processes_by_pattern() {
  local service="$1"
  local pattern="$2"
  local raw_pids=""
  local pids=()
  local pid

  raw_pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
  if [ -z "$raw_pids" ]; then
    return 0
  fi

  while IFS= read -r pid; do
    if [ -n "$pid" ]; then
      pids+=("$pid")
    fi
  done <<<"$raw_pids"

  kill_pid_list "$service" "${pids[@]}"
}

stop_local_processes() {
  stop_pid_file_process api
  stop_pid_file_process worker
  stop_pid_file_process beat
  stop_pid_file_process web
  stop_processes_by_pattern api "uvicorn app.main:app"
  stop_processes_by_pattern worker "celery -A app.tasks.celery_app:celery_app worker"
  stop_processes_by_pattern beat "celery -A app.tasks.celery_app:celery_app beat"
  stop_processes_on_port api 8000
  stop_processes_on_port web 3000
}

load_env_file_exports() {
  if [ ! -f "$ENV_FILE" ]; then
    return 0
  fi

  set +u
  set -a
  # shellcheck source=/dev/null
  . "$ENV_FILE"
  set +a
  set -u
}

normalize_local_url() {
  local current="${1:-}"
  local docker_value="$2"
  local local_value="$3"

  if [ -z "$current" ] || [ "$current" = "$docker_value" ]; then
    printf '%s\n' "$local_value"
    return 0
  fi

  printf '%s\n' "${current//$docker_value/$local_value}"
}

normalize_local_database_url() {
  local current="${DATABASE_URL:-}"

  if [ -z "$current" ]; then
    printf '%s\n' "postgresql+psycopg://postgres:postgres@localhost:5432/qihang"
    return 0
  fi

  printf '%s\n' "${current//@postgres:/@localhost:}"
}

apply_local_env_defaults() {
  ENV="${ENV:-local}"
  DATABASE_URL="$(normalize_local_database_url)"
  JWT_SECRET="${JWT_SECRET:-local-development-only-jwt-secret-20260307}"
  JWT_EXPIRE_MINUTES="${JWT_EXPIRE_MINUTES:-60}"
  JWT_REFRESH_EXPIRE_DAYS="${JWT_REFRESH_EXPIRE_DAYS:-14}"
  COOKIE_DOMAIN="${COOKIE_DOMAIN:-}"
  COOKIE_SECURE="${COOKIE_SECURE:-false}"
  COOKIE_SAMESITE="${COOKIE_SAMESITE:-lax}"
  CSRF_TTL_SECONDS="${CSRF_TTL_SECONDS:-3600}"
  REDIS_URL="$(normalize_local_url "${REDIS_URL:-}" "redis://redis:6379/0" "redis://localhost:6379/0")"
  REDIS_NAMESPACE="${REDIS_NAMESPACE:-qihang}"
  S3_ENDPOINT="$(normalize_local_url "${S3_ENDPOINT:-}" "http://minio:9000" "http://localhost:9000")"
  S3_PRESIGN_ENDPOINT="$(normalize_local_url "${S3_PRESIGN_ENDPOINT:-}" "http://minio:9000" "http://localhost:9000")"
  S3_ACCESS_KEY="${S3_ACCESS_KEY:-minioadmin}"
  S3_SECRET_KEY="${S3_SECRET_KEY:-minioadmin}"
  S3_PRIVATE_BUCKET="${S3_PRIVATE_BUCKET:-qihang-private}"
  S3_DEMO_BUCKET="${S3_DEMO_BUCKET:-qihang-demo}"
  S3_REGION="${S3_REGION:-us-east-1}"
  ALLOWED_HOSTS="${ALLOWED_HOSTS:-localhost,127.0.0.1,testserver,api}"
  CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:3000,http://127.0.0.1:3000}"
  DEMO_MODE="${DEMO_MODE:-true}"
  DEMO_INFER_ENABLED="${DEMO_INFER_ENABLED:-false}"
  UPLOAD_MAX_MB="${UPLOAD_MAX_MB:-50}"
  UPLOAD_PUT_PROXY="${UPLOAD_PUT_PROXY:-false}"

  INTERNAL_API_BASE_URL="$(normalize_local_url "${INTERNAL_API_BASE_URL:-}" "http://api:8000" "http://localhost:8000")"
  NEXT_PUBLIC_API_BASE_URL="$(normalize_local_url "${NEXT_PUBLIC_API_BASE_URL:-}" "http://api:8000" "http://localhost:8000")"
  NEXT_PUBLIC_ASSET_ORIGIN="$(normalize_local_url "${NEXT_PUBLIC_ASSET_ORIGIN:-}" "http://minio:9000" "http://localhost:9000")"
  NEXT_PUBLIC_APP_NAME="${NEXT_PUBLIC_APP_NAME:-QIHANG}"
  NEXT_PUBLIC_DEMO_MAX_IMAGE_MB="${NEXT_PUBLIC_DEMO_MAX_IMAGE_MB:-10}"
  QIHANG_LOCAL_STACK="true"
  NEXT_TELEMETRY_DISABLED=1

  export ENV
  export DATABASE_URL
  export JWT_SECRET
  export JWT_EXPIRE_MINUTES
  export JWT_REFRESH_EXPIRE_DAYS
  export COOKIE_DOMAIN
  export COOKIE_SECURE
  export COOKIE_SAMESITE
  export CSRF_TTL_SECONDS
  export REDIS_URL
  export REDIS_NAMESPACE
  export S3_ENDPOINT
  export S3_PRESIGN_ENDPOINT
  export S3_ACCESS_KEY
  export S3_SECRET_KEY
  export S3_PRIVATE_BUCKET
  export S3_DEMO_BUCKET
  export S3_REGION
  export ALLOWED_HOSTS
  export CORS_ORIGINS
  export DEMO_MODE
  export DEMO_INFER_ENABLED
  export UPLOAD_MAX_MB
  export UPLOAD_PUT_PROXY
  export INTERNAL_API_BASE_URL
  export NEXT_PUBLIC_API_BASE_URL
  export NEXT_PUBLIC_ASSET_ORIGIN
  export NEXT_PUBLIC_APP_NAME
  export NEXT_PUBLIC_DEMO_MAX_IMAGE_MB
  export QIHANG_LOCAL_STACK
  export NEXT_TELEMETRY_DISABLED
}

ensure_api_dependencies() {
  local should_install=0

  if [ "$REBUILD" -eq 1 ] || [ ! -x "$ROOT_DIR/apps/api/.venv/bin/uvicorn" ]; then
    should_install=1
  elif [ ! -f "$LOCAL_API_DEPS_STAMP" ] || [ "$ROOT_DIR/apps/api/pyproject.toml" -nt "$LOCAL_API_DEPS_STAMP" ]; then
    should_install=1
  fi

  if [ "$should_install" -eq 0 ]; then
    return 0
  fi

  echo "Ensuring local API dependencies are installed..."
  if command -v uv >/dev/null 2>&1; then
    (
      cd "$ROOT_DIR/apps/api"
      if [ ! -d .venv ]; then
        uv venv .venv
      fi
      uv pip install --python .venv/bin/python -e '.[dev]'
    )
  else
    (
      cd "$ROOT_DIR/apps/api"
      if [ ! -d .venv ]; then
        python3 -m venv .venv
      fi
      .venv/bin/pip install --upgrade pip
      .venv/bin/pip install -e '.[dev]'
    )
  fi

  touch "$LOCAL_API_DEPS_STAMP"
}

ensure_web_dependencies() {
  local should_install=0

  if [ "$REBUILD" -eq 1 ] || [ ! -d "$ROOT_DIR/apps/web/node_modules" ]; then
    should_install=1
  elif [ ! -f "$LOCAL_WEB_DEPS_STAMP" ]; then
    should_install=1
  elif [ -f "$ROOT_DIR/apps/web/pnpm-lock.yaml" ] && [ "$ROOT_DIR/apps/web/pnpm-lock.yaml" -nt "$LOCAL_WEB_DEPS_STAMP" ]; then
    should_install=1
  elif [ -f "$ROOT_DIR/apps/web/package-lock.json" ] && [ "$ROOT_DIR/apps/web/package-lock.json" -nt "$LOCAL_WEB_DEPS_STAMP" ]; then
    should_install=1
  elif [ "$ROOT_DIR/apps/web/package.json" -nt "$LOCAL_WEB_DEPS_STAMP" ]; then
    should_install=1
  fi

  if [ "$should_install" -eq 0 ]; then
    return 0
  fi

  echo "Ensuring local web dependencies are installed..."

  # Prefer pnpm when a pnpm lockfile exists, fall back to npm
  if [ -f "$ROOT_DIR/apps/web/pnpm-lock.yaml" ]; then
    local pnpm_bin=""
    if command -v pnpm >/dev/null 2>&1; then
      pnpm_bin="pnpm"
    elif command -v npx >/dev/null 2>&1; then
      pnpm_bin="npx pnpm"
    fi

    if [ -n "$pnpm_bin" ]; then
      (cd "$ROOT_DIR/apps/web" && $pnpm_bin install --frozen-lockfile 2>/dev/null || $pnpm_bin install)
    else
      echo "Warning: pnpm-lock.yaml found but pnpm is not installed. Falling back to npm..." >&2
      (cd "$ROOT_DIR/apps/web" && npm install)
    fi
  elif [ ! -d "$ROOT_DIR/apps/web/node_modules" ]; then
    (cd "$ROOT_DIR/apps/web" && npm ci)
  else
    (cd "$ROOT_DIR/apps/web" && npm install)
  fi

  touch "$LOCAL_WEB_DEPS_STAMP"
}

start_local_process() {
  local service="$1"
  local workdir="$2"
  shift 2

  local log_file="$LOCAL_LOG_DIR/$service.log"
  local pid_file="$LOCAL_PID_DIR/$service.pid"
  local original_dir="$PWD"
  local pid

  : >"$log_file"
  cd "$workdir"
  nohup "$@" >>"$log_file" 2>&1 &
  pid=$!
  cd "$original_dir"
  echo "$pid" >"$pid_file"

  sleep 1
  if ! is_pid_running "$pid"; then
    echo "Local $service process exited immediately." >&2
    show_local_service_log "$service"
    return 1
  fi
}

start_local_api() {
  echo "Starting local API..."
  start_local_process \
    api \
    "$ROOT_DIR" \
    env PYTHONPATH="$ROOT_DIR/apps/api" \
    "$ROOT_DIR/apps/api/.venv/bin/uvicorn" \
    app.main:app \
    --reload \
    --reload-dir "$ROOT_DIR/apps/api" \
    --host 127.0.0.1 \
    --port 8000
}

start_local_worker() {
  echo "Starting local worker..."
  start_local_process \
    worker \
    "$ROOT_DIR" \
    env PYTHONPATH="$ROOT_DIR/apps/api" \
    "$ROOT_DIR/apps/api/.venv/bin/celery" \
    -A app.tasks.celery_app:celery_app \
    worker \
    -l INFO \
    -Q celery,data,cleanup,inference

  echo "Starting local beat scheduler..."
  start_local_process \
    beat \
    "$ROOT_DIR" \
    env PYTHONPATH="$ROOT_DIR/apps/api" \
    "$ROOT_DIR/apps/api/.venv/bin/celery" \
    -A app.tasks.celery_app:celery_app \
    beat \
    -l INFO \
    -s "$LOCAL_STATE_DIR/celerybeat-schedule"
}

start_local_web() {
  echo "Starting local web..."
  start_local_process \
    web \
    "$ROOT_DIR/apps/web" \
    "$ROOT_DIR/apps/web/node_modules/.bin/next" \
    dev \
    --webpack \
    -H 127.0.0.1 \
    -p 3000
}

wait_for_local_worker() {
  local attempts="${1:-60}"
  local delay="${2:-2}"
  local pid_file="$LOCAL_PID_DIR/worker.pid"
  local pid=""

  for ((i = 1; i <= attempts; i++)); do
    if [ -f "$pid_file" ]; then
      pid="$(cat "$pid_file" 2>/dev/null || true)"
      if [ -n "$pid" ] && ! is_pid_running "$pid"; then
        echo "Local worker exited before becoming ready." >&2
        show_local_service_log worker
        return 1
      fi
    fi

    if env PYTHONPATH="$ROOT_DIR/apps/api" "$ROOT_DIR/apps/api/.venv/bin/celery" -A app.tasks.celery_app:celery_app inspect ping -t 5 >/dev/null 2>&1; then
      echo "worker is ready"
      return 0
    fi

    sleep "$delay"
  done

  echo "Timed out waiting for local worker." >&2
  show_local_service_log worker
  return 1
}

ensure_minio_buckets() {
  echo "Ensuring MinIO buckets exist..."
  if ! run_compose_with_retry run --rm "${INIT_SERVICES[0]}"; then
    echo "Warning: failed to run minio-init. Existing buckets may still be usable." >&2
  fi
}

start_local_mode() {
  ensure_command docker
  ensure_command curl
  ensure_command node
  ensure_command npm
  ensure_command python3

  ensure_directory_layout
  load_env_file_exports
  apply_local_env_defaults

  cleanup_docker_unused_artifacts

  if [ "$CLEAN" -eq 1 ]; then
    echo "Stopping old docker compose stack..."
    compose_cmd down --remove-orphans || true
  else
    echo "Stopping compose-managed app services to free local ports..."
    compose_cmd stop "${APP_SERVICES[@]}" >/dev/null 2>&1 || true
    compose_cmd rm -fs "${APP_SERVICES[@]}" >/dev/null 2>&1 || true
  fi

  if [ "$CLEAN_ARTIFACTS" -eq 1 ]; then
    echo "Cleaning local Playwright artifacts..."
    cleanup_playwright_outputs
  fi

  stop_local_processes

  echo "Ensuring local infra is running via docker compose..."
  run_compose_with_retry up -d --remove-orphans "${INFRA_SERVICES[@]}"
  wait_for_service_health postgres
  wait_for_service_health redis
  wait_for_service_health minio
  ensure_minio_buckets

  ensure_api_dependencies
  ensure_web_dependencies
  reset_local_web_cache

  start_local_api
  if ! wait_for_http "API" "http://localhost:8000/health"; then
    show_local_service_log api
    exit 1
  fi

  start_local_worker
  if ! wait_for_local_worker; then
    exit 1
  fi

  start_local_web
  if ! wait_for_http "Web" "http://localhost:3000"; then
    show_local_service_log web
    exit 1
  fi

  echo
  echo "QIHANG local fast stack is ready:"
  echo "  Web:    http://localhost:3000"
  echo "  API:    http://localhost:8000/health"
  echo "  MinIO:  http://localhost:9001"
  echo "  Logs:   $LOCAL_LOG_DIR"
  echo
  compose_cmd ps
}

start_docker_mode() {
  ensure_command docker

  cleanup_docker_unused_artifacts

  if [ "$CLEAN" -eq 1 ]; then
    echo "Stopping old compose containers..."
    compose_cmd down --remove-orphans
  fi

  if [ "$CLEAN_ARTIFACTS" -eq 1 ]; then
    echo "Cleaning local Playwright artifacts..."
    cleanup_playwright_outputs
  fi

  WEB_FINGERPRINT="$(fingerprint_paths \
    "$ROOT_DIR/apps/web" \
    "$ROOT_DIR/docker/Dockerfile.web" \
    "$ROOT_DIR/docker/docker-compose.yml" \
    "$ROOT_DIR/.dockerignore" \
    "$ENV_FILE")"
  API_FINGERPRINT="$(fingerprint_paths \
    "$ROOT_DIR/apps/api" \
    "$ROOT_DIR/docker/Dockerfile.api" \
    "$ROOT_DIR/docker/docker-compose.yml" \
    "$ROOT_DIR/.dockerignore" \
    "$ENV_FILE")"
  WORKER_FINGERPRINT="$(fingerprint_paths \
    "$ROOT_DIR/apps/api" \
    "$ROOT_DIR/docker/Dockerfile.worker" \
    "$ROOT_DIR/docker/docker-compose.yml" \
    "$ROOT_DIR/.dockerignore" \
    "$ENV_FILE")"

  BUILD_SERVICES=()

  if [ "$REBUILD" -eq 1 ]; then
    BUILD_SERVICES=(api worker web)
  else
    SAVED_WEB_FINGERPRINT="$(load_saved_fingerprint web || true)"
    SAVED_API_FINGERPRINT="$(load_saved_fingerprint api || true)"
    SAVED_WORKER_FINGERPRINT="$(load_saved_fingerprint worker || true)"

    if [ -z "${SAVED_WEB_FINGERPRINT:-}" ] || [ "$WEB_FINGERPRINT" != "$SAVED_WEB_FINGERPRINT" ]; then
      BUILD_SERVICES+=(web)
    fi
    if [ -z "${SAVED_API_FINGERPRINT:-}" ] || [ "$API_FINGERPRINT" != "$SAVED_API_FINGERPRINT" ]; then
      BUILD_SERVICES+=(api)
    fi
    if [ -z "${SAVED_WORKER_FINGERPRINT:-}" ] || [ "$WORKER_FINGERPRINT" != "$SAVED_WORKER_FINGERPRINT" ]; then
      BUILD_SERVICES+=(worker)
    fi
  fi

  if [ "${#BUILD_SERVICES[@]}" -gt 0 ]; then
    echo "Detected app changes for: $(join_by ', ' "${BUILD_SERVICES[@]}")"
    echo "Rebuilding affected images..."
    build_services_with_retry "${BUILD_SERVICES[@]}"
  else
    echo "No app source changes detected; reusing existing images."
  fi

  echo "Ensuring local stack is running via docker compose..."
  run_compose_with_retry up -d --remove-orphans "${INFRA_SERVICES[@]}"
  wait_for_service_health postgres
  wait_for_service_health redis
  wait_for_service_health minio
  ensure_minio_buckets

  if [ "${#BUILD_SERVICES[@]}" -gt 0 ]; then
    run_compose_with_retry up -d --remove-orphans --force-recreate "${BUILD_SERVICES[@]}"
  fi

  run_compose_with_retry up -d --remove-orphans "${APP_SERVICES[@]}"

  wait_for_http "API" "http://localhost:8000/health"
  wait_for_http "Web" "http://localhost:3000"
  wait_for_service_health api
  wait_for_service_health web
  if ! wait_for_service_health worker; then
    show_service_logs worker
    exit 1
  fi

  save_fingerprints

  echo
  echo "QIHANG docker stack is ready:"
  echo "  Web:    http://localhost:3000"
  echo "  API:    http://localhost:8000/health"
  echo "  MinIO:  http://localhost:9001"
  echo "  Worker: celery queues ready"
  echo
  compose_cmd ps
}

cd "$ROOT_DIR"
ensure_directory_layout

while [ $# -gt 0 ]; do
  case "$1" in
    --local)
      MODE="local"
      ;;
    --docker|--compose)
      MODE="docker"
      ;;
    --rebuild|--build)
      REBUILD=1
      ;;
    --clean)
      CLEAN=1
      REBUILD=1
      CLEAN_ARTIFACTS=1
      ;;
    --clean-artifacts)
      CLEAN_ARTIFACTS=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [ "$MODE" = "local" ]; then
  start_local_mode
else
  start_docker_mode
fi

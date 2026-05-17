#!/usr/bin/env bash
#
# reset_dev_db.sh - Reset the development database (native PostgreSQL)
#
# This script drops and recreates the database, runs migrations, and optionally seeds sample data.
# It works with native PostgreSQL installed via Homebrew (no Docker required).
#

set -euo pipefail

WITH_SAMPLE_DATA=0
POSITIONAL_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-sample-data)
      WITH_SAMPLE_DATA=1
      shift
      ;;
    *)
      POSITIONAL_ARGS+=("$1")
      shift
      ;;
  esac
done

if ((${#POSITIONAL_ARGS[@]})); then
  set -- "${POSITIONAL_ARGS[@]}"
else
  set --
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"
EXAMPLE_ENV_FILE="${PROJECT_ROOT}/.env.example"
UV_BIN="${UV_BIN:-uv}"
PYTHON_BIN="${PYTHON_BIN:-}"

run_project_python() {
  if [[ -n "${PYTHON_BIN}" ]]; then
    if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
      echo "[reset-dev-db] Runtime python not found: ${PYTHON_BIN}" >&2
      return 1
    fi
    PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" "${PYTHON_BIN}" "$@"
    return
  fi

  if ! command -v "${UV_BIN}" >/dev/null 2>&1; then
    echo "[reset-dev-db] uv not found: ${UV_BIN}" >&2
    return 1
  fi

  PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" \
    VIRTUAL_ENV= \
    "${UV_BIN}" --project "${PROJECT_ROOT}" run --locked --extra dev python "$@"
}

canonicalize_local_db_name() {
  local env_mode="$1"
  local db_name="$2"
  local resolved_name

  if ! resolved_name="$(run_project_python - "${env_mode}" "${db_name}" <<'PY'
from __future__ import annotations

import sys

from db.settings import canonicalize_local_db_name

resolved_name, warning = canonicalize_local_db_name(sys.argv[2] or None, env_mode=sys.argv[1])
if warning:
    print(warning, file=sys.stderr)
print("" if resolved_name is None else resolved_name)
PY
)"; then
    echo "[reset-dev-db] canonicalize_local_db_name: python invocation failed." >&2
    return 1
  fi

  printf '%s\n' "${resolved_name}"
}

ORIGINAL_ALLOW_DEV_DB_RESET="${ALLOW_DEV_DB_RESET-}"

if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${EXAMPLE_ENV_FILE}" ]]; then
    cp "${EXAMPLE_ENV_FILE}" "${ENV_FILE}"
    echo "[reset-dev-db] Bootstrapped ${ENV_FILE} from ${EXAMPLE_ENV_FILE}." >&2
  else
    echo "[reset-dev-db] Missing ${ENV_FILE}. Create it before retrying." >&2
    exit 1
  fi
fi

set -a
source "${ENV_FILE}"
set +a

if [[ -n "${ORIGINAL_ALLOW_DEV_DB_RESET}" ]]; then
  export ALLOW_DEV_DB_RESET="${ORIGINAL_ALLOW_DEV_DB_RESET}"
fi

ENV_MODE_VALUE="${ENV_MODE:-local}"
if [[ "${ENV_MODE_VALUE}" != "local" && "${ENV_MODE_VALUE}" != "development" ]]; then
  echo "[reset-dev-db] Refusing to run because ENV_MODE=${ENV_MODE_VALUE} (must be 'local' or 'development')." >&2
  exit 1
fi

if [[ "${ALLOW_DEV_DB_RESET:-0}" != "1" ]]; then
  echo "[reset-dev-db] Set ALLOW_DEV_DB_RESET=1 in your environment to confirm this destructive action." >&2
  exit 1
fi

# Resolve DB connection info directly from environment
DB_HOST="${PGHOST:-localhost}"
DB_PORT="${PGPORT:-5432}"
DB_USER="${PGUSER:-${APP_PGUSER:-}}"
DB_PASS="${PGPASSWORD:-${APP_PGPASSWORD:-}}"
DB_NAME="${DB_NAME:-}"
DB_NAME="$(canonicalize_local_db_name "${ENV_MODE_VALUE}" "${DB_NAME}")"

if [[ -z "${DB_USER}" || -z "${DB_PASS}" || -z "${DB_NAME}" ]]; then
  echo "[reset-dev-db] PGUSER/PGPASSWORD (or APP_PGUSER/APP_PGPASSWORD) and DB_NAME must be set in ${ENV_FILE}." >&2
  exit 1
fi

export DB_HOST DB_PORT DB_USER DB_PASS DB_NAME

# Admin user for creating databases (your macOS username for peer auth)
DEFAULT_ADMIN_USER="$(whoami)"
PREFERRED_ADMIN_USER="${ADMIN_PGUSER:-${DEFAULT_ADMIN_USER}}"
PREFERRED_ADMIN_PASS="${ADMIN_PGPASSWORD:-}"
ADMIN_USER="${PREFERRED_ADMIN_USER}"
ADMIN_PASS="${PREFERRED_ADMIN_PASS}"
ALLOW_ADMIN_FALLBACK="${ALLOW_ADMIN_FALLBACK:-1}"

cd "${PROJECT_ROOT}"

# Helper to run psql as admin
can_connect_as_admin() {
  local user="$1"
  local pass="$2"
  if [[ -n "${pass}" ]]; then
    PGPASSWORD="${pass}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${user}" -d postgres -tAc "SELECT 1" >/dev/null 2>&1
  else
    psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${user}" -d postgres -tAc "SELECT 1" >/dev/null 2>&1
  fi
}

run_admin_psql() {
  if [[ -n "${ADMIN_PASS}" ]]; then
    PGPASSWORD="${ADMIN_PASS}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${ADMIN_USER}" "$@"
  else
    # Use peer auth (no password needed for local macOS user)
    psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${ADMIN_USER}" "$@"
  fi
}

echo "[reset-dev-db] Checking PostgreSQL is running..." >&2
if ! pg_isready -h "${DB_HOST}" -p "${DB_PORT}" >/dev/null 2>&1; then
  echo "[reset-dev-db] PostgreSQL is not running. Start it with: brew services start postgresql@17" >&2
  exit 1
fi

if ! can_connect_as_admin "${ADMIN_USER}" "${ADMIN_PASS}"; then
  if [[ "${ALLOW_ADMIN_FALLBACK}" != "1" ]]; then
    echo "[reset-dev-db] Cannot connect to PostgreSQL as admin role \"${ADMIN_USER}\"." >&2
    echo "[reset-dev-db] ALLOW_ADMIN_FALLBACK=${ALLOW_ADMIN_FALLBACK}; refusing fallback. Fix ADMIN_PGUSER/ADMIN_PGPASSWORD." >&2
    exit 1
  fi

  if can_connect_as_admin "${ADMIN_USER}" ""; then
    echo "[reset-dev-db] Admin password rejected for role \"${ADMIN_USER}\"; retrying without password." >&2
    ADMIN_PASS=""
  elif [[ "${ADMIN_USER}" != "${DEFAULT_ADMIN_USER}" ]] && can_connect_as_admin "${DEFAULT_ADMIN_USER}" ""; then
    echo "[reset-dev-db] Admin role \"${ADMIN_USER}\" is unavailable; falling back to \"${DEFAULT_ADMIN_USER}\"." >&2
    ADMIN_USER="${DEFAULT_ADMIN_USER}"
    ADMIN_PASS=""
  else
    echo "[reset-dev-db] Cannot connect to PostgreSQL as admin role \"${ADMIN_USER}\"." >&2
    echo "[reset-dev-db] Set ADMIN_PGUSER to a valid local superuser (often \"${DEFAULT_ADMIN_USER}\" for Homebrew PostgreSQL)." >&2
    exit 1
  fi
fi

echo "[reset-dev-db] Terminating existing connections to \"${DB_NAME}\"..." >&2
run_admin_psql -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true

echo "[reset-dev-db] Dropping database \"${DB_NAME}\"..." >&2
run_admin_psql -d postgres -c "DROP DATABASE IF EXISTS \"${DB_NAME}\";" >/dev/null

echo "[reset-dev-db] Ensuring role \"${DB_USER}\" exists..." >&2
run_admin_psql -d postgres -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}') THEN CREATE ROLE \"${DB_USER}\" LOGIN PASSWORD '${DB_PASS}'; ELSE ALTER ROLE \"${DB_USER}\" WITH LOGIN PASSWORD '${DB_PASS}'; END IF; END \$\$;" >/dev/null

echo "[reset-dev-db] Creating database \"${DB_NAME}\"..." >&2
run_admin_psql -d postgres -c "CREATE DATABASE \"${DB_NAME}\" WITH OWNER \"${DB_USER}\";" >/dev/null

echo "[reset-dev-db] Ensuring pgvector extension and schema privileges..." >&2
run_admin_psql -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
run_admin_psql -d "${DB_NAME}" -c "ALTER SCHEMA public OWNER TO \"${DB_USER}\";" >/dev/null
run_admin_psql -d "${DB_NAME}" -c "GRANT ALL ON SCHEMA public TO \"${DB_USER}\";" >/dev/null

echo "[reset-dev-db] Cleaning up any existing custom functions..." >&2
run_admin_psql -d "${DB_NAME}" -c "DROP FUNCTION IF EXISTS notify_cluster_centroid_dirty(uuid) CASCADE;" >/dev/null 2>&1
run_admin_psql -d "${DB_NAME}" -c "DROP FUNCTION IF EXISTS mark_dirty_on_identity_members() CASCADE;" >/dev/null 2>&1
run_admin_psql -d "${DB_NAME}" -c "DROP FUNCTION IF EXISTS mark_dirty_on_media_identities() CASCADE;" >/dev/null 2>&1

echo "[reset-dev-db] Applying migrations as ${DB_USER}..." >&2
POSTGRES_SYNC_DSN="postgresql+psycopg://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}" \
PGHOST="${DB_HOST}" \
PGPORT="${DB_PORT}" \
PGUSER="${DB_USER}" \
PGPASSWORD="${DB_PASS}" \
run_project_python -m alembic -c db/alembic.ini upgrade head

echo "[reset-dev-db] Setting up test user for RLS testing..." >&2
TEST_USER="${TEST_PGUSER:-recognition_test_user}"
TEST_PASS="${TEST_PGPASSWORD:-recognition_test_password}"
run_admin_psql -d "${DB_NAME}" -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${TEST_USER}') THEN CREATE ROLE \"${TEST_USER}\" LOGIN PASSWORD '${TEST_PASS}'; END IF; END \$\$;" >/dev/null
run_admin_psql -d "${DB_NAME}" -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO \"${TEST_USER}\";" >/dev/null
run_admin_psql -d "${DB_NAME}" -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO \"${TEST_USER}\";" >/dev/null
run_admin_psql -d "${DB_NAME}" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO \"${TEST_USER}\";" >/dev/null
run_admin_psql -d "${DB_NAME}" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO \"${TEST_USER}\";" >/dev/null

if [[ "${WITH_SAMPLE_DATA}" == "1" ]]; then
  echo "[reset-dev-db] Seeding sample data for manual testing (--with-sample-data)..." >&2
  PYTHONPATH="${PROJECT_ROOT}" \
    DB_HOST="${DB_HOST}" \
    DB_PORT="${DB_PORT}" \
    DB_USER="${DB_USER}" \
    DB_PASS="${DB_PASS}" \
    DB_NAME="${DB_NAME}" \
    run_project_python <<'PY'
import math
import os
import random
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from db.models import IdentityCluster, IdentityMember, MediaIdentity, Tenant

def make_embedding(seed: int) -> list[float]:
    rng = random.Random(seed)
    values = [rng.random() for _ in range(1024)]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]

def main() -> None:
    db_host = os.environ["DB_HOST"]
    db_port = os.environ["DB_PORT"]
    db_user = os.environ["DB_USER"]
    db_pass = os.environ["DB_PASS"]
    db_name = os.environ["DB_NAME"]

    url = URL.create(
        "postgresql+psycopg",
        username=db_user,
        password=db_pass,
        host=db_host or None,
        port=int(db_port) if db_port else None,
        database=db_name,
    )

    engine = create_engine(url, future=True)

    tenant_id = uuid.uuid4()

    with Session(engine) as session:
        tenant = Tenant(id=tenant_id, site_url="https://sample.local")
        session.add(tenant)
        session.flush()

        session.execute(text(f"SET app.current_tenant = '{tenant_id}'"))

        media_objects: list[MediaIdentity] = []
        for idx in range(1, 6):
            embedding = make_embedding(idx)
            identity = MediaIdentity(
                tenant_id=tenant_id,
                media_id=idx,
                media_url=f"https://sample.local/media/{idx}.jpg",
                bbox_x=0,
                bbox_y=0,
                bbox_width=120,
                bbox_height=120,
                confidence=0.9,
                embedding=embedding,
                created_by_user_id=1,
            )
            session.add(identity)
            media_objects.append(identity)
        session.flush()

        cluster_a = IdentityCluster(
            tenant_id=tenant_id,
            label="sample-cluster-a",
            representative_identity_id=media_objects[0].id,
            identity_count=3,
            similarity_threshold=0.6,
            clustering_algorithm="seed",
        )
        cluster_b = IdentityCluster(
            tenant_id=tenant_id,
            label="sample-cluster-b",
            representative_identity_id=media_objects[3].id,
            identity_count=2,
            similarity_threshold=0.6,
            clustering_algorithm="seed",
        )
        session.add_all([cluster_a, cluster_b])
        session.flush()

        for identity in media_objects[:3]:
            session.add(
                IdentityMember(
                    tenant_id=tenant_id,
                    cluster_id=cluster_a.id,
                    identity_id=identity.id,
                    similarity=0.95,
                    created_by_user_id=identity.created_by_user_id,
                )
            )

        for identity in media_objects[3:5]:
            session.add(
                IdentityMember(
                    tenant_id=tenant_id,
                    cluster_id=cluster_b.id,
                    identity_id=identity.id,
                    similarity=0.9,
                    created_by_user_id=identity.created_by_user_id,
                )
            )

        session.commit()

        session.execute(text("RESET app.current_tenant"))

        with engine.begin() as conn:
            conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            conn.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
            conn.execute(text("RESET app.bypass_rls"))

    print("[reset-dev-db] Sample data created with tenant https://sample.local")

if __name__ == "__main__":
    main()
PY
fi

# Log the reset to the application log file
echo "[reset-dev-db] Logging reset to application log..." >&2
run_project_python -c "from api.logging_config import log_db_reset; log_db_reset('Database reset via reset_dev_db.sh')" 2>/dev/null || true

echo "[reset-dev-db] Done – database dropped, recreated, and migrated for development environment." >&2

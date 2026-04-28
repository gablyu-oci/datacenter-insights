#!/bin/bash
# ------------------------------------------------------------------
# start.sh — launch backend + frontend for local development
# Usage:  ./start.sh              (defaults: MOCK_DATA=1)
#         MOCK_DATA=0 ./start.sh  (skip mock data, real DB only)
# ------------------------------------------------------------------
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── Defaults ──────────────────────────────────────────────────────
export MOCK_DATA="${MOCK_DATA:-1}"

# ── Pre-flight: PostgreSQL ────────────────────────────────────────
echo "==> Checking PostgreSQL..."
if command -v pg_isready &>/dev/null; then
    if pg_isready -q; then
        echo "    PostgreSQL is ready."
    else
        echo "    WARNING: PostgreSQL is not ready. Backend may fail to connect."
    fi
else
    echo "    WARNING: pg_isready not found. Skipping DB check."
fi

# ── Pre-flight: Alembic migrations ───────────────────────────────
echo "==> Running Alembic migrations..."
cd "$ROOT/backend"
if [ -d ".venv" ]; then
    .venv/bin/alembic upgrade head 2>&1 | sed 's/^/    /'
else
    python3 -m alembic upgrade head 2>&1 | sed 's/^/    /'
fi

# ── Backend ──────────────────────────────────────────────────────
echo "==> Starting backend (MOCK_DATA=$MOCK_DATA)..."
cd "$ROOT/backend"
if [ -d ".venv" ]; then
    .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
else
    python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
fi
BACKEND_PID=$!
echo "    Backend started (PID $BACKEND_PID) -> http://localhost:8000"

# ── Frontend ─────────────────────────────────────────────────────
echo "==> Starting frontend..."
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"
cd "$ROOT/frontend"
npm run dev -- --host 0.0.0.0 --port 5173 &
FRONTEND_PID=$!
echo "    Frontend started (PID $FRONTEND_PID) -> http://localhost:5173"

# ── Cleanup on exit ──────────────────────────────────────────────
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT

echo ""
echo "==> All services running. Press Ctrl+C to stop."
echo "    Backend:  http://localhost:8000/api/health"
echo "    Frontend: http://localhost:5173"
echo ""
wait

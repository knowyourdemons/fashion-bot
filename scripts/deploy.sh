#!/bin/bash
# Fashion Bot Deploy — build image, recreate containers
# Usage:
#   ./scripts/deploy.sh          — full: test → build → restart
#   ./scripts/deploy.sh --quick  — skip tests
#   ./scripts/deploy.sh --hotfix — docker cp changed files (no rebuild)

set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker/docker-compose.yml"

echo "=== Fashion Bot Deploy ==="
echo "$(date '+%Y-%m-%d %H:%M:%S')"

MODE="${1:-full}"

# ── Hotfix mode: docker cp only (fast, for emergencies) ──
if [[ "$MODE" == "--hotfix" ]]; then
    shift || true
    if [ $# -gt 0 ]; then
        FILES="$@"
    else
        FILES=$(git diff --name-only HEAD~1 --diff-filter=ACMR -- '*.py' '*.html')
    fi
    for f in $FILES; do
        [ -f "$f" ] && docker cp "$f" docker-app-1:/app/"$f" 2>/dev/null && \
                        docker cp "$f" docker-worker-1:/app/"$f" 2>/dev/null && \
                        echo "  synced: $f"
    done
    docker restart docker-app-1 docker-worker-1 > /dev/null
    sleep 4
    curl -sf http://localhost:8000/health > /dev/null && echo "✅ Hotfix deployed" || echo "⚠️ Health check failed"
    exit 0
fi

# ── Full/Quick mode: build → recreate ──

# Tests (skip with --quick)
if [[ "$MODE" != "--quick" ]]; then
    echo "--- Running tests ---"
    $COMPOSE exec -T app python3 -m pytest /app/tests/ -x -q --tb=line 2>&1 | tail -5 || {
        echo "❌ Tests failed. Aborting deploy."
        exit 1
    }
    echo ""
fi

# Build both app and worker (same Dockerfile, separate images)
echo "--- Building ---"
$COMPOSE build app worker

# Recreate containers from new image (worker uses same image)
echo "--- Restarting worker ---"
$COMPOSE up -d --no-deps --force-recreate worker
sleep 3

echo "--- Restarting app ---"
$COMPOSE up -d --no-deps --force-recreate app
sleep 5

# Health check
echo "--- Health check ---"
for i in 1 2 3 4 5; do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ App healthy"
        break
    fi
    [ "$i" -eq 5 ] && echo "❌ Health check failed!" && exit 1
    sleep 3
done

# Worker check
if docker ps --format '{{.Names}} {{.Status}}' | grep -q "worker.*Up"; then
    echo "✅ Worker running"
else
    echo "⚠️  Worker status unknown"
fi

echo ""
echo "=== Deploy complete $(date '+%H:%M:%S') ==="

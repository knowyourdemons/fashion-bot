#!/bin/bash
# Deploy: sync files → restart → clear stale caches
# Usage: ./scripts/deploy.sh [file1 file2 ...]
# Without args: syncs ALL Python files

set -e
cd "$(dirname "$0")/.."

echo "=== Deploy ==="

# 1. Sync files to containers
if [ $# -gt 0 ]; then
    FILES="$@"
else
    FILES=$(git diff --name-only HEAD~1 --diff-filter=ACMR -- '*.py')
fi

for f in $FILES; do
    if [ -f "$f" ]; then
        docker cp "$f" docker-app-1:/app/"$f" 2>/dev/null && \
        docker cp "$f" docker-worker-1:/app/"$f" 2>/dev/null && \
        echo "  synced: $f"
    fi
done

# 2. Restart containers (modules reload)
echo "Restarting..."
docker restart docker-app-1 docker-worker-1 > /dev/null

# 3. Wait for containers to be ready
sleep 3

# 4. Clear stale caches (old gap_analysis versions)
docker exec docker-app-1 python3 -c "
import asyncio, redis.asyncio as aioredis
async def cleanup():
    r = aioredis.from_url('redis://redis:6379')
    # Clear old gap_analysis caches (non-versioned)
    old = [k async for k in r.scan_iter('gap_analysis:*') if b':v' not in k]
    if old:
        await r.delete(*old)
        print(f'  cleared {len(old)} stale cache keys')
    await r.aclose()
asyncio.run(cleanup())
" 2>/dev/null

echo "=== Done ==="

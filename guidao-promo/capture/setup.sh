#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

WORK=".work"
REPO="$WORK/guidao"

mkdir -p "$WORK" out/frames out/preview

if [ ! -d "$REPO/.git" ]; then
  git clone --depth 1 https://github.com/xcsweb/guidao "$REPO"
fi

cd "$REPO"
if [ ! -d node_modules ]; then
  npm install --no-audit --no-fund
fi

# capture-only patch: allow canvas.toDataURL() after a manual render
if ! grep -q "preserveDrawingBuffer" src/viewer/Viewer.ts; then
  python3 - <<'PY'
from pathlib import Path
p = Path('src/viewer/Viewer.ts')
s = p.read_text(encoding='utf-8')
s = s.replace('      logarithmicDepthBuffer: true,\n', '      logarithmicDepthBuffer: true,\n      preserveDrawingBuffer: true,\n', 1)
p.write_text(s, encoding='utf-8')
PY
fi

cd ../..
if ! curl -s -o /dev/null http://localhost:5173/; then
  (cd "$REPO" && nohup npm run dev -- --port 5173 > ../../.work/vite.log 2>&1 &)
  sleep 6
fi
curl -s -o /dev/null -w "guidao dev server: %{http_code}\n" http://localhost:5173/

#!/bin/sh
# Runs the API (internal, 127.0.0.1:8765) and the web server (public, $PORT) in one container.
# If either stops, the container stops, so the platform restarts it instead of serving a half-dead site.
set -e
python -m shorts_studio serve --data "$SHORTS_DATA" --port 8765 &
api=$!
# Start the public port only after the API answers. Cloud Run treats an open port as "ready" and then stops boosting
# the CPU, so an API that is still starting would be starved and every first request would fail with a 500.
i=0
until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=2)" 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -gt 120 ] || ! kill -0 "$api" 2>/dev/null; then echo "API did not start" >&2; exit 1; fi
  sleep 1
done
cd /app/frontend
# the standalone server reads PORT and HOSTNAME; HOSTNAME defaults to the container's own name, so set it
HOSTNAME=0.0.0.0 PORT="${PORT:-3000}" node server.js &
web=$!
trap 'kill "$api" "$web" 2>/dev/null' TERM INT
while kill -0 "$api" 2>/dev/null && kill -0 "$web" 2>/dev/null; do sleep 2; done
kill "$api" "$web" 2>/dev/null || true
exit 1

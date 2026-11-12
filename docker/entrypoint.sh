#!/bin/sh
# Runs the API (internal, 127.0.0.1:8765) and the web server (public, $PORT) in one container.
# If either stops, the container stops, so the platform restarts it instead of serving a half-dead site.
set -e
python -m shorts_studio serve --data "$SHORTS_DATA" --port 8765 &
api=$!
cd /app/frontend
node_modules/.bin/next start -p "${PORT:-3000}" -H 0.0.0.0 &
web=$!
trap 'kill "$api" "$web" 2>/dev/null' TERM INT
while kill -0 "$api" 2>/dev/null && kill -0 "$web" 2>/dev/null; do sleep 2; done
kill "$api" "$web" 2>/dev/null || true
exit 1

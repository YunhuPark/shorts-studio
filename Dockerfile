# Public demo image: the dashboard (Next.js) and the API (FastAPI) in one container, in demo mode.
# Demo mode never calls a paid service and needs no key; it serves the pre-built bundle in demo/.
#   docker build -t shorts-studio-demo .
#   docker run --rm -p 3000:3000 shorts-studio-demo
# Behind a reverse proxy that appends the client address to X-Forwarded-For, also pass -e SHORTS_TRUST_PROXY=1
# so that each visitor gets their own rate-limit budget (without it every visitor shares the proxy's).

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# the API runs in the same container; the build bakes this address into the /api rewrite
ENV API_ORIGIN=http://127.0.0.1:8765 NEXT_TELEMETRY_DISABLED=1
RUN npm run build && npm prune --omit=dev

FROM python:3.12-slim
WORKDIR /app
COPY docker/requirements-demo.txt ./
RUN pip install --no-cache-dir -r requirements-demo.txt
# the demo never renders, so ffmpeg (imageio-ffmpeg) and OpenCV are not installed
COPY --from=web /usr/local/bin/node /usr/local/bin/node
COPY --from=web /web /app/frontend
COPY src ./src
COPY demo ./demo
COPY docker/entrypoint.sh ./entrypoint.sh
# a Windows checkout may have turned the script's line endings into CRLF, which breaks "#!/bin/sh"
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh \
    && useradd --create-home --uid 10001 app && mkdir -p /data && chown app /data
USER app
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PORT=3000 \
    SHORTS_DEMO=1 SHORTS_DEMO_DIR=/app/demo SHORTS_DATA=/data
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ['PORT'], timeout=4)"
ENTRYPOINT ["./entrypoint.sh"]

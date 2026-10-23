# Job Scanner for a home server: the app plus Claude Code, which runs on your Claude subscription through
# CLAUDE_CODE_OAUTH_TOKEN (make one with `claude setup-token` on any computer where you're signed in).
FROM node:22-bookworm-slim

ARG CLAUDE_CODE_VERSION=latest
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 ca-certificates tini \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force \
 && mkdir -p /data && chown node:node /data

WORKDIR /app
COPY --chown=node:node job_scanner ./job_scanner
COPY --chown=node:node extension ./extension

USER node
ENV JOB_SCANNER_DATA=/data \
    JOB_SCANNER_HOST=0.0.0.0 \
    JOB_SCANNER_PORT=8766 \
    JOB_SCANNER_CLI_NEEDS_TOKEN=1 \
    PYTHONUNBUFFERED=1 \
    DISABLE_AUTOUPDATER=1
VOLUME /data
EXPOSE 8766
HEALTHCHECK --interval=1m --timeout=5s --start-period=20s \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8766/favicon.png', timeout=4)"
ENTRYPOINT ["tini", "--"]
CMD ["python3", "-m", "job_scanner", "serve"]

#!/bin/sh
# Keep a home-server Job Scanner up to date: pull the latest code and rebuild the container, only when something
# changed. Run it from cron, e.g. every 30 minutes:
#   */30 * * * * /path/to/Job_Scanner/scripts/update.sh >> /var/log/job-scanner-update.log 2>&1
# Your data lives in the Docker volume, so a rebuild never touches it. Local edits are kept (pull --ff-only
# refuses rather than overwrite them) and the script says so.
set -eu
cd "$(dirname "$0")/.."
branch="${JOB_SCANNER_BRANCH:-main}"
git fetch --quiet origin "$branch"
here=$(git rev-parse HEAD)
there=$(git rev-parse "origin/$branch")
if [ "$here" = "$there" ]; then
  exit 0
fi
echo "$(date -Iseconds) updating $here -> $there"
if ! git merge --ff-only --quiet "origin/$branch"; then
  echo "$(date -Iseconds) can't fast-forward: this copy has local changes or commits. Not updating." >&2
  exit 1
fi
docker compose up -d --build
docker image prune -f >/dev/null 2>&1 || true
echo "$(date -Iseconds) running $(git rev-parse --short HEAD)"

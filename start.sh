#!/bin/sh
# Starts Job Scanner and opens it in your browser.
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
exec python3 -m job_scanner serve --open

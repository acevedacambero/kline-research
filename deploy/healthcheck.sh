#!/usr/bin/env bash
set -euo pipefail

for attempt in {1..12}; do
  if curl --fail --silent --show-error --max-time 10 \
    http://127.0.0.1:8800/healthz; then
    exit 0
  fi
  if [[ "${attempt}" -lt 12 ]]; then
    sleep 1
  fi
done

echo "K-line health check failed after 12 attempts." >&2
exit 1

#!/usr/bin/env bash
set -euo pipefail

build_unit="${KLINE_FINAL_BUILD_UNIT:-kline-final-data-build.service}"
poll_seconds="${KLINE_FINAL_CHAIN_POLL_SECONDS:-30}"

while systemctl --user is-active --quiet "${build_unit}"; do
  sleep "${poll_seconds}"
done

if ! journalctl --user -u "${build_unit}" -o cat --no-pager \
  | grep -q '"event": "acceptance"'; then
  echo "Final data build did not emit an acceptance report; formal research will not run." >&2
  exit 1
fi

exec /bin/bash "${KLINE_APP_ROOT:-${HOME}/apps/kline}/current/deploy/run-formal-research.sh"

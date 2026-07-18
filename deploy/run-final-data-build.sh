#!/usr/bin/env bash
set -euo pipefail

root="${KLINE_APP_ROOT:-${HOME}/apps/kline}"

restart_web() {
  systemctl --user start kline.service
}

trap restart_web EXIT INT TERM
systemctl --user stop kline.service
set -a
# shellcheck disable=SC1091
source "${root}/shared/.env"
set +a
cd "${root}/current"
args=(--poll-seconds "${KLINE_FINAL_BUILD_POLL_SECONDS:-10}")
if [[ "${KLINE_FINAL_BUILD_SKIP_BACKFILL:-0}" == "1" ]]; then
  args+=(--skip-backfill)
fi
"${root}/shared/runtime-venv/bin/python" scripts/run_final_data_build.py "${args[@]}"

#!/usr/bin/env bash
set -euo pipefail

root="${KLINE_APP_ROOT:-${HOME}/apps/kline}"
releases="${root}/releases"
current="$(readlink -f "${root}/current")"
previous="$(readlink -f "${root}/previous" 2>/dev/null || true)"

for release in "${releases}"/*; do
  [[ -d "${release}" ]] || continue
  resolved="$(readlink -f "${release}")"
  case "${resolved}" in
    "${current}"|"${previous}") continue ;;
    "${releases}/"*) rm -rf -- "${resolved}" ;;
    *) echo "Refusing path outside releases: ${resolved}" >&2; exit 3 ;;
  esac
done

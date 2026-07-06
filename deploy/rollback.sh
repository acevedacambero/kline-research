#!/usr/bin/env bash
set -euo pipefail

root="${HOME}/apps/kline"
current="${root}/current"
previous="${root}/previous"

if [[ ! -L "${previous}" ]]; then
  echo "No previous release is available; current was not changed." >&2
  exit 2
fi

target="$(readlink -f "${previous}")"
case "${target}" in
  "${root}/releases/"*) ;;
  *) echo "Refusing rollback target outside releases: ${target}" >&2; exit 3 ;;
esac

old=""
if [[ -L "${current}" ]]; then
  old="$(readlink -f "${current}")"
fi
ln -sfn "${target}" "${root}/current.next"
mv -Tf "${root}/current.next" "${current}"
if [[ -n "${old}" ]]; then
  ln -sfn "${old}" "${previous}"
fi
systemctl --user restart kline.service
"${root}/scripts/healthcheck.sh"

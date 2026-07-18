#!/usr/bin/env bash
set -euo pipefail

root="${HOME}/apps/kline"
current="${root}/current"
previous="${root}/previous"
runtime="${root}/shared/runtime-venv"
pth="${runtime}/lib/python3.12/site-packages/_editable_impl_kline_research.pth"

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
[[ -n "${old}" && -d "${old}/src" ]] || {
  echo "Current release is unavailable; rollback was not attempted." >&2
  exit 3
}
[[ -d "${target}/src" && -d "$(dirname "${pth}")" ]] || {
  echo "Rollback target or shared runtime is incomplete." >&2
  exit 3
}

ln -sfn "${target}" "${root}/current.next"
mv -Tf "${root}/current.next" "${current}"
printf '%s\n' "${target}/src" > "${pth}"
systemctl --user restart kline.service
if ! "${target}/deploy/healthcheck.sh"; then
  ln -sfn "${old}" "${root}/current.next"
  mv -Tf "${root}/current.next" "${current}"
  printf '%s\n' "${old}/src" > "${pth}"
  systemctl --user restart kline.service
  "${old}/deploy/healthcheck.sh" || true
  echo "Rollback target failed health checks; restored the original release." >&2
  exit 4
fi
ln -sfn "${old}" "${previous}"
echo "${target}"

#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 RELEASE_ID SOURCE_TAR WEB_DIST_TAR" >&2
  exit 2
fi

release_id="$1"
source_tar="$(readlink -f "$2")"
web_tar="$(readlink -f "$3")"
root="${KLINE_APP_ROOT:-${HOME}/apps/kline}"
releases="${root}/releases"
runtime="${root}/shared/runtime-venv"
release="${releases}/${release_id}"

[[ "${release_id}" =~ ^[0-9A-Za-z._-]+$ ]] || { echo "invalid release id" >&2; exit 2; }
[[ -f "${source_tar}" && -f "${web_tar}" ]] || { echo "release archives missing" >&2; exit 2; }
[[ -x "${runtime}/bin/python" ]] || { echo "shared runtime missing" >&2; exit 3; }
[[ ! -e "${release}" ]] || { echo "release already exists" >&2; exit 3; }

old="$(readlink -f "${root}/current")"
old_previous="$(readlink -f "${root}/previous" 2>/dev/null || true)"
mkdir -p "${release}/web/dist"
trap 'rm -rf -- "${release}"' ERR
tar -xf "${source_tar}" -C "${release}"
tar -xf "${web_tar}" -C "${release}/web/dist"
ln -s "${runtime}" "${release}/.venv"
printf '%s\n' "${release}/src" > "${runtime}/lib/python3.12/site-packages/_editable_impl_kline_research.pth"

ln -sfn "${old}" "${root}/previous"
ln -sfn "${release}" "${root}/current"
systemctl --user restart kline.service
if ! bash "${release}/deploy/healthcheck.sh"; then
  ln -sfn "${old}" "${root}/current"
  if [[ -n "${old_previous}" ]]; then
    ln -sfn "${old_previous}" "${root}/previous"
  fi
  printf '%s\n' "${old}/src" > "${runtime}/lib/python3.12/site-packages/_editable_impl_kline_research.pth"
  systemctl --user restart kline.service
  rm -rf -- "${release}"
  exit 4
fi
trap - ERR
"${release}/deploy/prune-releases.sh"
echo "${release}"

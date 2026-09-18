#!/usr/bin/env bash
# Download Xray-core for live proxy probes (Linux amd64).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${ROOT}/bin"
mkdir -p "${BIN_DIR}"
VERSION="${XRAY_VERSION:-v26.3.27}"
ASSET="Xray-linux-64.zip"
URL="https://github.com/XTLS/Xray-core/releases/download/${VERSION}/${ASSET}"
TMP="$(mktemp -d)"
cleanup() { rm -rf "${TMP}"; }
trap cleanup EXIT

echo "Downloading Xray ${VERSION}..."
curl -fsSL -o "${TMP}/${ASSET}" "${URL}"
unzip -o "${TMP}/${ASSET}" -d "${TMP}/xray" >/dev/null
install -m 0755 "${TMP}/xray/xray" "${BIN_DIR}/xray"
# Optional geo files if present
if [[ -f "${TMP}/xray/geoip.dat" ]]; then
  cp "${TMP}/xray/geoip.dat" "${BIN_DIR}/geoip.dat"
fi
if [[ -f "${TMP}/xray/geosite.dat" ]]; then
  cp "${TMP}/xray/geosite.dat" "${BIN_DIR}/geosite.dat"
fi
echo "Installed ${BIN_DIR}/xray"
"${BIN_DIR}/xray" version || true

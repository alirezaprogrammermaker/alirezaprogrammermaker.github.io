#!/usr/bin/env bash
# Download Xray-core and sing-box for live proxy probes (Linux amd64).
# sing-box is required for hysteria2/hy2 — TCP-only must never mark hy2 alive.
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

# sing-box: real Hysteria2 (hy2) SOCKS probes — no TCP fake-pass
SINGBOX_VERSION="${SINGBOX_VERSION:-1.13.16}"
SINGBOX_ASSET="sing-box-${SINGBOX_VERSION}-linux-amd64.tar.gz"
SINGBOX_URL="https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VERSION}/${SINGBOX_ASSET}"
echo "Downloading sing-box ${SINGBOX_VERSION}..."
curl -fsSL -o "${TMP}/${SINGBOX_ASSET}" "${SINGBOX_URL}"
tar -xzf "${TMP}/${SINGBOX_ASSET}" -C "${TMP}"
SINGBOX_BIN="$(find "${TMP}" -type f -name sing-box -print -quit)"
if [[ -z "${SINGBOX_BIN}" ]]; then
  echo "sing-box binary not found in archive" >&2
  exit 1
fi
install -m 0755 "${SINGBOX_BIN}" "${BIN_DIR}/sing-box"
echo "Installed ${BIN_DIR}/sing-box"
"${BIN_DIR}/sing-box" version || true

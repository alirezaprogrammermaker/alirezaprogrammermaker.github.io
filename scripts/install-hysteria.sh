#!/usr/bin/env bash
# Download hysteria2 client for real hy2 live probes (Linux amd64).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${ROOT}/bin"
mkdir -p "${BIN_DIR}"
VERSION="${HYSTERIA_VERSION:-v2.6.2}"
ASSET="hysteria-linux-amd64"
URL="https://github.com/apernet/hysteria/releases/download/app%2F${VERSION}/${ASSET}"
TMP="$(mktemp -d)"
cleanup() { rm -rf "${TMP}"; }
trap cleanup EXIT

echo "Downloading hysteria2 ${VERSION}..."
curl -fsSL -o "${TMP}/${ASSET}" "${URL}"
install -m 0755 "${TMP}/${ASSET}" "${BIN_DIR}/hysteria"
echo "Installed ${BIN_DIR}/hysteria"
"${BIN_DIR}/hysteria" version || true

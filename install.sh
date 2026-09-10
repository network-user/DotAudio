#!/usr/bin/env bash
# Convenience wrapper: run deploy/install.sh from the repo root.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "${ROOT}/deploy/install.sh" "${ROOT}/deploy/update.sh" "${ROOT}/deploy/download-and-install.sh" 2>/dev/null || true
LAUNCH="${LAUNCH:-1}" exec bash "${ROOT}/deploy/install.sh" "$@"

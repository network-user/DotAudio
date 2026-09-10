#!/usr/bin/env bash
# Sync DotAudio checkout to origin/main and reinstall the editable package.
# Safe for user data: only touches the git tree and .venv.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
ALLOW_DIRTY="${ALLOW_DIRTY:-0}"
RELAUNCH="${RELAUNCH:-0}"
WAIT_PID="${WAIT_PID:-0}"

if [[ "$WAIT_PID" =~ ^[0-9]+$ ]] && [[ "$WAIT_PID" -gt 0 ]]; then
  if kill -0 "$WAIT_PID" 2>/dev/null; then
    echo "Ждём завершения процесса ${WAIT_PID}…"
    for _ in $(seq 1 120); do
      kill -0 "$WAIT_PID" 2>/dev/null || break
      sleep 1
    done
    sleep 1
  fi
fi

if [[ -z "$REPO_ROOT" ]]; then
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
cd "$REPO_ROOT"

[[ -d .git ]] || { echo "Не git-репозиторий: $REPO_ROOT" >&2; exit 1; }

porcelain="$(git status --porcelain --untracked-files=no || true)"
if [[ -n "$porcelain" && "$ALLOW_DIRTY" != "1" ]]; then
  echo "Есть локальные правки. Передайте ALLOW_DIRTY=1, чтобы сбросить их (reset --hard)." >&2
  exit 1
fi

echo "fetch ${REMOTE} ${BRANCH}"
git fetch "$REMOTE" "$BRANCH" || git fetch "$REMOTE"

TIP="${REMOTE}/${BRANCH}"
echo "checkout/reset ${TIP}"
git checkout -f -B "$BRANCH" "$TIP"
git reset --hard "$TIP"

PYTHON="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || command -v python)"
fi
echo "pip install -e ."
"$PYTHON" -m pip install -e . --quiet || {
  echo "Предупреждение: pip install завершился с ошибкой. Код уже на ${TIP}." >&2
}

echo "Готово: $(git rev-parse --short HEAD)"

if [[ "$RELAUNCH" == "1" ]]; then
  nohup "$PYTHON" -m dotaudio >/dev/null 2>&1 &
fi

#!/usr/bin/env bash
# Clone DotAudio (if needed) and run install.sh.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/network-user/DotAudio.git}"
BRANCH="${BRANCH:-main}"

if [[ "$(uname -s)" == "Darwin" ]]; then
  TARGET="${INSTALL_DIR:-$HOME/Applications/DotAudio}"
else
  TARGET="${INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/DotAudio}"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "  DotAudio - загрузка с GitHub и установка"
echo ""

command -v git >/dev/null 2>&1 || {
  echo "  Нужен git."
  exit 1
}

if [[ -d "${TARGET}/.git" ]]; then
  echo "  Найдена установка: ${TARGET}"
elif [[ -d "${script_dir}/../src/dotaudio" ]]; then
  echo "  Запуск установщика из этой папки…"
  LAUNCH=1 bash "${script_dir}/install.sh"
  exit $?
else
  echo "  Клонируем в ${TARGET} …"
  if [[ -e "$TARGET" ]]; then
    echo "  Каталог уже есть и это не git-клон."
    exit 1
  fi
  mkdir -p "$(dirname "$TARGET")"
  git clone --progress --branch "$BRANCH" --single-branch "$REPO_URL" "$TARGET"
fi

LAUNCH=1 bash "${TARGET}/deploy/install.sh"
exit $?

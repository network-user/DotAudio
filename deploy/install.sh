#!/usr/bin/env bash
# DotAudio installer for Linux and macOS.
# Requires: git, Python 3.12 or 3.13.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/network-user/DotAudio.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-}"
SKIP_SHORTCUT="${SKIP_SHORTCUT:-0}"
LAUNCH="${LAUNCH:-0}"
STEP=0
STEP_TOTAL=6

say() { printf '%s\n' "$*"; }
ok() { printf '  OK  %s\n' "$*"; }
info() { printf '  ..  %s\n' "$*"; }
die() { printf '\n  Ошибка установки: %s\n\n' "$*" >&2; exit 1; }

step() {
  STEP=$((STEP + 1))
  local title="$1"
  say ""
  say "=== Шаг ${STEP}/${STEP_TOTAL}: ${title}"
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

resolve_python() {
  local cand ver
  for cand in python3.13 python3.12 python3; do
    if have_cmd "$cand"; then
      ver="$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
      if [[ "$ver" == "3.12" || "$ver" == "3.13" ]]; then
        "$cand" -c 'import sys; print(sys.executable)'
        return 0
      fi
    fi
  done
  return 1
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_from_script="$(cd "${script_dir}/.." && pwd)"

resolve_install_dir() {
  if [[ -n "$INSTALL_DIR" ]]; then
    printf '%s\n' "$INSTALL_DIR"
    return
  fi
  if [[ -d "${repo_from_script}/src/dotaudio" ]]; then
    printf '%s\n' "$repo_from_script"
    return
  fi
  if [[ -d "$(pwd)/src/dotaudio" ]]; then
    pwd
    return
  fi
  if [[ -d "$(pwd)/.git" ]]; then
    pwd
    return
  fi
  if [[ "$(uname -s)" == "Darwin" ]]; then
    printf '%s\n' "${HOME}/Applications/DotAudio"
  else
    printf '%s\n' "${XDG_DATA_HOME:-$HOME/.local/share}/DotAudio"
  fi
}

write_desktop_entry() {
  local root="$1"
  local python_bin="$2"
  local icon="$3"
  local apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  mkdir -p "$apps"
  cat >"${apps}/DotAudio.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DotAudio
Comment=Локальное распознавание речи Whisper
Exec=${python_bin} -m dotaudio
Path=${root}
Icon=${icon}
Terminal=false
Categories=AudioVideo;Audio;Utility;
StartupWMClass=DotAudio
EOF
  ok "Ярлык: ${apps}/DotAudio.desktop"
}

write_macos_command() {
  local root="$1"
  local python_bin="$2"
  local cmd="${HOME}/Desktop/DotAudio.command"
  cat >"$cmd" <<EOF
#!/usr/bin/env bash
cd "${root}"
exec "${python_bin}" -m dotaudio
EOF
  chmod +x "$cmd"
  ok "Ярлык: ${cmd}"
}

say ""
say "  DotAudio - установка"
say "  Репозиторий: ${REPO_URL}"
say ""

step "Проверка Git и Python"
have_cmd git || die "Нужен git. Ubuntu: sudo apt install git. macOS: xcode-select --install или brew install git."
PYTHON_BIN="$(resolve_python)" || die "Нужен Python 3.12 или 3.13. Ubuntu: sudo apt install python3.12 python3.12-venv. macOS: brew install python@3.12"
ok "Git найден"
ok "Python: ${PYTHON_BIN}"

if [[ "$(uname -s)" == "Linux" ]]; then
  if ! ldconfig -p 2>/dev/null | grep -q 'libportaudio\|libsndfile' && ! [[ -e /usr/lib/*/libportaudio.so* ]]; then
    info "Подсказка: для микрофона обычно нужны пакеты libportaudio2 (и при сборке - portaudio19-dev)."
  fi
fi

INSTALL_DIR="$(resolve_install_dir)"
info "Каталог установки: ${INSTALL_DIR}"

step "Загрузка кода с GitHub"
if [[ ! -d "${INSTALL_DIR}/.git" ]]; then
  mkdir -p "$(dirname "$INSTALL_DIR")"
  if [[ -d "$INSTALL_DIR" ]] && [[ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null || true)" ]]; then
    if [[ ! -d "${INSTALL_DIR}/src/dotaudio" ]]; then
      die "Каталог уже занят и это не DotAudio: ${INSTALL_DIR}"
    fi
    info "Код уже на диске (без .git) - ставим из этой папки"
  else
    info "Клонируем ${BRANCH}…"
    git clone --progress --branch "$BRANCH" --single-branch "$REPO_URL" "$INSTALL_DIR"
    ok "Репозиторий скачан"
  fi
else
  info "Обновляем существующий клон…"
  git -C "$INSTALL_DIR" fetch --progress origin "$BRANCH" \
    || git -C "$INSTALL_DIR" fetch --progress origin \
    || die "git fetch не удался"
  git -C "$INSTALL_DIR" checkout -f -B "$BRANCH" "origin/${BRANCH}"
  git -C "$INSTALL_DIR" reset --hard "origin/${BRANCH}"
  ok "Код на $(git -C "$INSTALL_DIR" rev-parse --short HEAD)"
fi

step "Создание виртуального окружения"
VENV_PY="${INSTALL_DIR}/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  info "python -m venv .venv"
  "$PYTHON_BIN" -m venv "${INSTALL_DIR}/.venv"
  ok ".venv создан"
else
  ok ".venv уже есть"
fi

step "Установка зависимостей (pip)"
info "Обновляем pip…"
"$VENV_PY" -m pip install --upgrade pip
info "Ставим DotAudio и библиотеки (PySide6, faster-whisper…). Это самый долгий шаг."
"$VENV_PY" -m pip install -e "${INSTALL_DIR}"
ok "Пакет установлен"

step "Ярлыки и лаунчер"
ICON_PNG="${INSTALL_DIR}/src/dotaudio/assets/app_icon.png"
ICON_SVG="${INSTALL_DIR}/src/dotaudio/assets/app_icon.svg"
ICON="$ICON_PNG"
[[ -f "$ICON" ]] || ICON="$ICON_SVG"
LAUNCHER="${INSTALL_DIR}/deploy/dotaudio.sh"
cat >"$LAUNCHER" <<EOF
#!/usr/bin/env bash
cd "\$(cd "\$(dirname "\$0")/.." && pwd)"
exec .venv/bin/python -m dotaudio "\$@"
EOF
chmod +x "$LAUNCHER" "${INSTALL_DIR}/deploy/install.sh" "${INSTALL_DIR}/deploy/update.sh" 2>/dev/null || true

if [[ "$SKIP_SHORTCUT" != "1" ]]; then
  case "$(uname -s)" in
    Linux) write_desktop_entry "$INSTALL_DIR" "$VENV_PY" "$ICON" ;;
    Darwin) write_macos_command "$INSTALL_DIR" "$VENV_PY" ;;
    *) info "Ярлык для этой ОС не создан - запуск: ${LAUNCHER}" ;;
  esac
else
  info "Ярлыки пропущены (SKIP_SHORTCUT=1)"
fi

step "Готово"
say ""
say "  Установка завершена."
if [[ "$(uname -s)" == "Darwin" ]]; then
  say "  Данные: ~/Library/Application Support/DotCore/DotAudio"
else
  say "  Данные: ~/.local/share/DotCore/DotAudio"
fi
say "  Запуск: ${LAUNCHER}"
say ""
say "  При первом запуске откроется мастер настройки:"
say "  он сам скачает модели и FFmpeg (где доступно) и покажет прогресс."
say ""
if [[ "$(uname -s)" == "Darwin" ]]; then
  say "  macOS: разрешите микрофон в Системных настройках → Конфиденциальность."
  say "  Системный звук Live требует виртуальное устройство (BlackHole и т.п.)."
elif [[ "$(uname -s)" == "Linux" ]]; then
  say "  Linux: глобальные горячие клавиши пока только внутри окна приложения."
  say "  Системный звук Live - через monitor-устройства PulseAudio/PipeWire, если они есть в списке."
fi
say ""

if [[ "$LAUNCH" == "1" ]]; then
  info "Запускаем DotAudio…"
  nohup "$VENV_PY" -m dotaudio >/dev/null 2>&1 &
fi

exit 0

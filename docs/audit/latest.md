> Последний прогон: clear-harbor · 2026-09-09. Снимок: [2026-09-09-clear-harbor.md](2026-09-09-clear-harbor.md) · история: [docs/audit/](.)

# Security Audit · Clear Harbor · 2026-09-09

| Поле | Значение |
|------|----------|
| Статус | PASSED |
| Прогон | clear-harbor |
| Уровень | full |
| Охват | leaks + code |
| Фокус | исходящий трафик: аудио/расшифровки локальны; скачивание моделей допускается |
| Модель | Composer |
| Дата | 2026-09-09 |

## Сводка

```
Pre-Deploy Audit - full, охват: утечки + код
──────────────────────────────────────────────
Трек A · Секреты/ключи:   0  (Crit 0 / High 0)
Трек A · PII/экспозиция:   0
Трек A · История git:      0
Трек B · Инъекции/exec:    0
Трек B · Authz/крипто:     0
Трек B · Зависимости:      0
Инфра/CI:                  0
──────────────────────────────────────────────
Severity: Crit 0 · High 0 · Med 0 · Low 0 · Info 3
Готовность: 10/10
Вердикт: PASSED
```

## Вердикт по приватности

По умолчанию аудио и расшифровки в сеть не уходят. Сеть: только GET загрузок и loopback (Ollama / опциональный ASR с API-ключом). Внешние хосты - только с `DOTAUDIO_ALLOW_REMOTE_ASR=1` / `DOTAUDIO_ALLOW_REMOTE_OLLAMA=1`.

## Находки

| Severity | Категория | Файл:строка | Описание | Рекомендация |
|----------|-----------|-------------|----------|--------------|
| Info | optional-remote | src/dotaudio/engine.py | Remote ASR только на loopback/private или с `DOTAUDIO_ALLOW_REMOTE_ASR=1` | Держать opt-in выключенным |
| Info | server-auth | src/dotaudio/server.py | `/v1/*` требует API-ключ; `/health` минимальный; OpenAPI отключён | Не публиковать compose без `DOTAUDIO_API_KEY` |
| Info | tooling | scripts/strip-coauthors.py | Скрипт вырезает Co-authored-by из истории | Запускать перед public push |

## Remediation в этом прогоне

- Убраны machine-path из README/RESEARCH; удалён `karaoke.ass`; расширен `.gitignore`
- `netguard` + запрет remote backend без opt-in; Ollama только localhost
- API-ключ на сервере; ужесточены лимиты; compose требует `DOTAUDIO_API_KEY`
- Safe ZIP extract; karaoke `-vf` без пользовательского пути
- `requirements.lock`, pin cuda/diarize, CI `pip-audit`, `HF_HUB_DISABLE_TELEMETRY`

## Артефакты

- Снимок: `docs/audit/2026-09-09-clear-harbor.md`
- Latest: `docs/audit/latest.md`
- Бейдж README: `passed`

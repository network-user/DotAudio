# Security Audit · Quiet Circuit · 2026-09-09

| Поле | Значение |
|------|----------|
| Статус | PASSED WITH WARNINGS |
| Прогон | quiet-circuit |
| Уровень | full |
| Охват | leaks + code |
| Фокус | исходящий трафик: аудио и расшифровки не должны уходить в сеть (скачивание моделей допускается) |
| Модель | Composer |
| Дата | 2026-09-09 |

## Сводка

```
Pre-Deploy Audit - full, охват: утечки + код
──────────────────────────────────────────────
Трек A · Секреты/ключи:   1  (Crit 0 / High 0)
Трек A · PII/экспозиция:   4
Трек A · История git:      0
Трек B · Инъекции/exec:    4
Трек B · Authz/крипто:     4
Трек B · Зависимости:      3
Инфра/CI:                  2
──────────────────────────────────────────────
Severity: Crit 0 · High 0 · Med 12 · Low 5 · Info 6
Готовность: 6/10
Вердикт: PASSED WITH WARNINGS
```

## Вердикт по приватности (фокус прогона)

**По умолчанию аудио и расшифровки в сеть не отправляются.**

| Путь | Поведение |
|------|-----------|
| ASR (faster-whisper / Vosk) | Локально. `backend=local` по умолчанию; UI `MainMvp.qml` не предлагает remote |
| Перевод EN→RU | Локальный CTranslate2; сеть только при скачивании OPUS-MT zip |
| Ассистент | `llama.cpp` subprocess или Ollama на `127.0.0.1:11434` |
| Загрузки | Hugging Face / GitHub / PyPI / OPUS - только GET моделей и инструментов |
| Remote ASR | Код есть (`engine._transcribe_remote`), но только при явном `backend=remote`; в активном UI нет переключателя |
| Опциональный `dotaudio-server` | Desktop сам не запускает; bind по умолчанию `127.0.0.1`; без auth |
| Телеметрия | Sentry/analytics/OpenAI cloud не найдены; HF telemetry API в зависимости есть, но user audio/text туда не идут |

Риски утечки контента остаются **опциональными**: смена `backend=remote` + чужой `server_url`, либо `DOTAUDIO_OLLAMA_URL` на внешний хост.

## Находки

| Severity | Категория | Файл:строка | Описание | Рекомендация |
|----------|-----------|-------------|----------|--------------|
| Medium | machine-path | README.md:23 | Абсолютный путь `C:\Users\Us…\PycharmProjects\DotAudio` в инструкции запуска | Заменить на относительный/placeholder путь |
| Medium | machine-path | docs/RESEARCH.md:35 | Абсолютный путь к соседнему DotSoundBackend | Убрать абсолютный корень или заменить placeholder |
| Medium | machine-path | docs/RESEARCH.md:49 | Абсолютный путь к DotSoundComputeWorker | То же |
| Medium | client-dump | karaoke.ass:13 | Закоммиченный ASR-дамп с текстом песни/речи | Убрать из индекса, добавить `*.ass` в `.gitignore` (только вручную) |
| Medium | user-content-egress | src/dotaudio/llm.py:33 | Текст чата/выжимок POST в Ollama; `DOTAUDIO_OLLAMA_URL` без проверки loopback | Валидировать base URL (только loopback/private) или документировать запрет публичных хостов |
| Medium | missing-auth | src/dotaudio/server.py:349 | `/v1/transcribe` и `/v1/audio/transcriptions` без API-ключа (опциональный сервер) | Bearer/X-API-Key из env; не публиковать без auth |
| Medium | network-exposure | deploy/Dockerfile:12 | CMD слушает `0.0.0.0` (compose сейчас публикует только `127.0.0.1`) | Не открывать publish без auth; документировать риск `docker run -p` |
| Medium | insecure-default | src/dotaudio/server.py:14 | До 100 MiB / 1 ч аудио на открытых эндпоинтах | Ужесточить дефолты; сначала auth |
| Medium | path-traversal | src/dotaudio/tools_ffmpeg.py:185 | `ZipFile.extractall` без проверки членов (скачивание FFmpeg) | Safe extract + pin digest релиза |
| Medium | path-traversal | src/dotaudio/translate.py:240 | То же для OPUS-MT zip | Safe extract + hash |
| Medium | command-injection | src/dotaudio/karaoke.py:137 | Путь ASS вшит в `-vf ass=filename='…'` | Не вшивать путь в filtergraph; controlled temp name |
| Medium | missing-lockfile | pyproject.toml:10 | Нет lockfile; cuda/diarize слабо закреплены; нет pip-audit/CI | uv/pip-tools lock + workflow pip-audit |
| Low | gitignore-coverage | .gitignore:17 | Есть `.env*`, нет `*.pem` / `*.key` / credentials | Добавить паттерны ключей и credential-файлов |
| Low | telemetry | huggingface_hub (dep) | Telemetry API не отключён; в user audio/text не ходит | `HF_HUB_DISABLE_TELEMETRY=1` в процессе приложения |
| Low | info-disclosure | src/dotaudio/server.py:261 | `/health` и `/docs` без auth на опциональном сервере | Минимальный health; отключить OpenAPI в проде |
| Low | path-traversal | src/dotaudio/nemo_diarize.py:501 | extractall после sha256 всё ещё доверяет layout архива | Path confinement при распаковке |
| Low | docker-base-tag | deploy/Dockerfile:1 | `python:3.12-slim` без digest | Пинить `@sha256:…` |
| Info | default-safe | src/dotaudio/controller.py:126 | `backend=local`, remote не авто | Сохранить; при политике «только локально» запретить remote в `setSetting` |
| Info | optional-remote | src/dotaudio/engine.py:1031 | Remote POST аудио - только при `backend=remote` (после adversarial: не High) | Host allowlist / env-gate `DOTAUDIO_ALLOW_REMOTE_ASR` |
| Info | history-clean | (git) | История без живых секретов/ключей | - |
| Info | no-cloud-asr | src/dotaudio | Нет OpenAI cloud / Sentry / analytics upload | Не добавлять без явного согласия |
| Info | docker-hardening | deploy/Dockerfile:9 | Non-root user, без секретов в ENV | Сохранить |
| Info | sql-ok | src/dotaudio/storage.py | Запросы параметризованы | - |

## Adversarial

| Кандидат | Было | Вердикт | Итог |
|----------|------|---------|------|
| Remote ASR POST без allowlist | High | downgrade | Info - нужен явный `backend=remote`; MainMvp UI не предлагает |
| Unauthenticated `/v1/*` | High | downgrade | Medium - сервер опционален, default bind `127.0.0.1`, desktop не стартует сам |

## Артефакты

- Снимок: `docs/audit/2026-09-09-quiet-circuit.md`
- Latest: `docs/audit/latest.md`
- Бейдж README: `passed_with_warnings`

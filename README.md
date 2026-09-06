# .аудио / DotAudio

<p>
  <img src="https://img.shields.io/badge/Python-3.12–3.13-3776AB?style=flat" alt="Python 3.12–3.13" />
  <img src="https://img.shields.io/badge/Platform-Windows-555?style=flat" alt="Windows first" />
  <img src="https://img.shields.io/badge/Category-ASR_scaffold-555?style=flat" alt="ASR scaffold" />
  <!-- loc:start --><img src="https://img.shields.io/badge/Python_LoC-2528-lightgrey?style=flat" alt="2528 Python lines of code" /><!-- loc:end -->
</p>

<img src="docs/cover.svg" width="720" alt="DotAudio: речь, субтитры и эфир" />

Основа приложения к статье на Хабре о Whisper. Есть Python-ядро распознавания, хранения расшифровок, серверный адаптер и черновая Qt-оболочка. Перед продолжением прочитать [передачу работы](docs/HANDOFF.md), [замысел продукта](docs/PRODUCT.md) и [принципы архитектуры](docs/ARCHITECTURE.md).

## Что внутри

- **Распознавание:** local/remote, выбор Whisper-модели, CPU/GPU, сегменты с таймкодами.
- **Источники:** заготовки микрофона, системного звука, медиафайлов и прямых HTTP(S)-эфиров.
- **История:** SQLite, поиск, исходный/исправленный текст, экспорт TXT/SRT/VTT/JSON.
- **Интерфейс:** черновая навигация и компактное окно. Плеер, редактор и окончательный дизайн пока не реализованы.
- **Контекст:** [аналоги и .звук](docs/RESEARCH.md), [проверки и оставшаяся работа](docs/HANDOFF.md).

## Запуск

Python 3.12 или 3.13. PowerShell из корня проекта:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev,server]'
.\.venv\Scripts\dotaudio.exe
```

Если используешь уже созданную `.venv`, повторно создавать её не нужно. Без editable-установки пакета:

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m dotaudio
```

Модели автоматически скачиваются при первом распознавании. Для потоков нужен FFmpeg в PATH; файлы faster-whisper декодирует через PyAV. CUDA требует подходящих библиотек согласно [документации faster-whisper](https://github.com/SYSTRAN/faster-whisper). Реальное распознавание на этом этапе не проверено.

История по умолчанию сохраняется в пользовательский каталог platformdirs. Для отдельной тестовой истории передать `--data-dir .local-check`. Микрофонные записи на диск сейчас не сохраняются.

### Необязательный сервер

```powershell
.\.venv\Scripts\dotaudio-server.exe --host 127.0.0.1 --port 8765 --models base
docker compose -f deploy/compose.yaml up --build
```

Это два альтернативных способа запуска. Docker-конфигурация подготовлена, но образ не собирался. Сервер предназначен для localhost или SSH-туннеля, без публичного доступа. По умолчанию принимает только модель `base`; разрешённые модели задаются `--models`.

## Команды

| Команда | Назначение |
|---|---|
| `dotaudio` | Черновое настольное приложение |
| `dotaudio --smoke-test --data-dir .local-check` | Загрузить QML и завершить работу без записи |
| `dotaudio --screenshot docs/preview.png --data-dir .local-check` | Сохранить вид окна и завершить работу |
| `dotaudio-server --help` | Параметры локального сервера |
| `python -m pytest -q` | Тесты ядра и сервера |
| `python -m ruff check src tests` | Проверка Python-кода |

## Стек

<p>
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge" alt="Python" />
  <img src="https://img.shields.io/badge/PySide6-41CD52?style=for-the-badge" alt="PySide6" />
  <img src="https://img.shields.io/badge/faster--whisper-555?style=for-the-badge" alt="faster-whisper" />
  <img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge" alt="SQLite" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge" alt="FastAPI" />
</p>

## Проверки

27 тестов прошли, Ruff без замечаний, QML загрузился в offscreen-режиме. Реальные аудиоустройства, Whisper inference, GPU, автoвставка, Docker и установщик не проверялись. Полный статус и ограничения: [HANDOFF.md](docs/HANDOFF.md).

LoC посчитан `code-counter src` + `code-counter tests`: 2055 + 473 строк Python. QML и документация не входят в бейдж.

## Архитектура

Интерфейс передаёт действия в Python controller; захват и распознавание вынесены из GUI thread. SQLite хранит сессии, а экспорт использует единый формат сегментов.

```text
src/dotaudio/
  app.py, controller.py, desktop.py
  qml/Main.qml
  capture.py -> pipeline.py -> engine.py
  storage.py, transcripts.py
  server.py
tests/
deploy/
docs/
```

- Engine и capture не зависят от Qt.
- Время сегмента измеряется в секундах от начала источника.
- Локальный и серверный ASR возвращают одинаковую структуру сегментов.
- Исходный текст сохраняется при ручной правке.
- Публичный сервер и поддержка всех ОС не заявлены.

## Лицензия

© 2026 DotCore. Все права защищены. Проприетарный код; использование, копирование, изменение и распространение требуют письменного разрешения автора. См. [LICENSE](LICENSE). Условия использования читателями статьи ещё нужно определить.

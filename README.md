# .аудио / DotAudio

<p>
  <img src="https://img.shields.io/badge/Python-3.12–3.13-3776AB?style=flat" alt="Python 3.12–3.13" />
  <img src="https://img.shields.io/badge/Platform-Windows_MVP-555?style=flat" alt="Windows MVP" />
  <img src="https://img.shields.io/badge/Category-Desktop_ASR-555?style=flat" alt="Desktop ASR" />
  <!-- loc:start --><img src="https://img.shields.io/badge/lines_of_code-2699-lightgrey?style=flat" alt="2699 lines of code" /><!-- loc:end -->
</p>

<img src="docs/cover.svg" width="720" alt="DotAudio: речь, субтитры и эфир" />

MVP приложения к статье на Хабре о Whisper. Оно запускает локальное или удалённое распознавание, сохраняет расшифровки, показывает субтитры, редактирует сегменты медиа и отслеживает ключевые слова в прямых эфирах. Полный контекст решений находится в [PRODUCT.md](docs/PRODUCT.md) и [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Что внутри

- **Диктовка:** Ctrl+Alt+Space запускает запись в активном поле. После остановки текст сохраняется в истории и буфере; вставка выполняется только при сохранённом фокусе целевого окна.
- **Субтитры:** микрофон или системный звук, крупный текст и компактный остров поверх окон.
- **Медиа:** файл аудио или видео, плеер, кликабельные таймкоды, правка сегментов и экспорт TXT/SRT/VTT/JSON.
- **Эфиры:** до четырёх прямых HTTP(S)-потоков, список ключевых фраз и журнал совпадений.
- **История:** локальная SQLite, поиск по названию и тексту, исходный текст остаётся доступным после правки.

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

Модели автоматически скачиваются при первом распознавании. Локальный запуск `tiny` на CPU проверен на тестовом аудиобуфере. Для эфиров нужен FFmpeg в PATH; медиафайлы faster-whisper декодирует через PyAV. CUDA требует подходящих библиотек согласно [документации faster-whisper](https://github.com/SYSTRAN/faster-whisper).

История по умолчанию сохраняется в пользовательский каталог platformdirs. Для отдельной тестовой истории передать `--data-dir .local-check`. Микрофонные записи на диск сейчас не сохраняются.

### Необязательный сервер

```powershell
.\.venv\Scripts\dotaudio-server.exe --host 127.0.0.1 --port 8765 --models base
docker compose -f deploy/compose.yaml up --build
```

Это два альтернативных способа запуска. Сервер предназначен для localhost или SSH-туннеля, без публичного доступа. По умолчанию принимает только модель `base`; разрешённые модели задаются `--models`. Docker-конфигурация подготовлена, но образ ещё не собирался.

## Команды

| Команда | Назначение |
|---|---|
| `dotaudio` | Настольный MVP |
| `dotaudio --smoke-test --data-dir .local-check` | Загрузить QML и завершить работу без записи |
| `dotaudio --screenshot .local-check\preview.png --data-dir .local-check` | Сохранить вид окна и завершить работу |
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

33 теста прошли, Ruff без замечаний, QML загрузился в offscreen-режиме, CLI сервера и реальный локальный inference `tiny` на CPU отработали. Микрофонные драйверы, системный звук, GPU, вставка в сторонние приложения, Docker и установщик зависят от конкретного ПК и требуют ручной проверки. Полный статус: [HANDOFF.md](docs/HANDOFF.md).

LoC посчитан `code-counter .`: 2677 строк Python и 22 строки YAML. QML и документация счётчик не учитывает.

## Архитектура

Интерфейс передаёт действия в Python controller; захват и распознавание вынесены из GUI thread. SQLite хранит сессии, а экспорт использует единый формат сегментов.

```text
src/dotaudio/
  app.py, controller.py, desktop.py
  qml/MainMvp.qml, qml/TranscriptEditor.qml
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

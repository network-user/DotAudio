# .аудио / DotAudio

<p>
  <img src="https://img.shields.io/badge/Python-3.12--3.13-3776AB?style=flat" alt="Python 3.12-3.13" />
  <img src="https://img.shields.io/badge/Platform-Windows_MVP-555?style=flat" alt="Windows MVP" />
  <img src="https://img.shields.io/badge/Category-Desktop_ASR-555?style=flat" alt="Desktop ASR" />
</p>

<img src="docs/cover.svg" width="720" alt="DotAudio: речь и субтитры" />

Desktop-приложение к статье о Whisper. Оно распознаёт русскую речь локально через
faster-whisper, выводит живые субтитры, помогает с диктовкой и превращает аудио
или видео в редактируемую расшифровку и караоке-субтитры.

## Запуск

Нужен **Python 3.12 или 3.13**. Откройте PowerShell в папке проекта и выполните:

```powershell
cd C:\Users\User\PycharmProjects\DotAudio

# Только при первом запуске
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,server]"

# Запуск приложения из исходников, без .exe
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m dotaudio
```

Если окружение уже создано и зависимости установлены, нужны только последние
dве строки. Альтернатива после `pip install -e`:

```powershell
.\.venv\Scripts\dotaudio.exe
```

При первом распознавании выбранная модель Whisper загрузится в локальный кеш.
Для быстрой проверки выберите `tiny` в разделе «Модели». Для MP4-экспорта с
караоке-субтитрами требуется установленный `ffmpeg` в `PATH`.

## Что уже работает

- Переносимый мини-остров: уровень сигнала, статус записи, раскрытие в
  рабочее окно и переназначаемые горячие клавиши.
- Live-субтитры - главный режим. Русский язык выбран по умолчанию; режим
  Whisper Translate создаёт английские субтитры.
- Диктовка с копированием текста в буфер обмена, безопасной вставкой в
  сохранённое целевое окно и сохранением исходной расшифровки в историю.
- Локальный словарь терминов, исправлений и voice snippets для финального
  текста диктовки без передачи правил на сервер.
- Выбор и проверка устройств ввода и вывода, визуальный уровень сигнала.
- Медиа-режим: аудио или видео, сегменты с таймкодами, ручное редактирование,
  undo/redo и экспорт TXT, SRT, VTT и JSON. SRT/VTT перегруппировываются по
  словным таймкодам, длине и пунктуации без выдумывания времени.
- Караоке-просмотр с подсветкой текущего слова, экспорт ASS и MP4 поверх видео
  или выбранной обложки.
- Мониторинг до четырёх прямых HTTP(S) источников, локальные ключевые фразы и
  автоматическое переподключение потока с backoff.
- Локальная SQLite-история с миграциями и восстановлением прерванных сессий,
  журнал работы, модели `tiny`, `base`, `small`,
  `medium` и `large-v3`, профили скорости и качества.

## Устройство

```text
src/dotaudio/
  app.py, controller.py, desktop.py   # запуск, связка QML и системное окно
  capture.py -> pipeline.py -> engine.py
                                      # захват, очередь и faster-whisper
  storage.py, transcripts.py          # SQLite, миграции и экспорт расшифровок
  karaoke.py                          # word timestamps, ASS и MP4
  qml/MainMvp.qml                     # остров и рабочее пространство
  qml/KaraokePreview.qml              # просмотр караоке
tests/                                # 40 тестов
docs/                                 # продукт, архитектура, исследование
```

Распознавание и запись выполняются вне GUI-потока. В live-режиме не запрашиваются
word timestamps, чтобы уменьшить задержку. В медиа-режиме они сохраняются для
караоке и точной правки таймкодов.

## Проверка разработки

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests

# Проверить загрузку QML без доступа к микрофону
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m dotaudio --smoke-test --data-dir .local-check
```

Последняя проверка: 68 passed, `ruff check src tests` без ошибок, QML smoke test
завершается успешно. Реальный микрофон, системный звук, GPU и FFmpeg зависят от
конкретного компьютера Windows и проверяются на нём вручную.

## Дополнительно

- [Описание продукта](docs/PRODUCT.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Исследование решений](docs/RESEARCH.md)
- [Передача проекта](docs/HANDOFF.md)

© 2026 DotCore. См. [LICENSE](LICENSE).

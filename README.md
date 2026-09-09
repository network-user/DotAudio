# .аудио / DotAudio

<p>
  <img src="https://img.shields.io/badge/Python-3.12--3.13-3776AB?style=flat" alt="Python 3.12-3.13" />
  <img src="https://img.shields.io/badge/Platform-Windows_MVP-555?style=flat" alt="Windows MVP" />
  <img src="https://img.shields.io/badge/Category-Desktop_ASR-555?style=flat" alt="Desktop ASR" />
  <!-- loc:start --><img src="https://img.shields.io/badge/lines_of_code-5657-lightgrey?style=flat" alt="5657 lines of code" /><!-- loc:end -->
</p>

<!-- audit:start -->
<p>
  <a href="docs/audit/latest.md"><img src="https://img.shields.io/badge/security_audit-passed-3fb950?style=flat" alt="security audit passed - full, leaks + code" /></a>
  <a href="docs/audit/2026-09-09-clear-harbor.md"><img src="https://img.shields.io/badge/date-2026--09--09-555?style=flat" alt="audit date" /></a>
</p>
<!-- audit:end -->

<img src="docs/cover.svg" width="720" alt="DotAudio: речь и субтитры" />

Desktop-приложение к статье о Whisper для Windows. Оно распознаёт русскую речь
локально через faster-whisper, показывает живые субтитры, помогает с диктовкой
и превращает аудио или видео в редактируемую расшифровку и караоке-субтитры.
Локальный ассистент отвечает по сохранённым записям: изложение, главные мысли,
вопросы по сказанному - всё на этом же компьютере.

## Запуск

Нужен **Python 3.12 или 3.13**. Откройте PowerShell в папке проекта и выполните:

```powershell
cd <path-to-DotAudio>

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

Раздел «Ассистент» просит отдельную нативную сборку - её нет в базовой
установке. Готовые колёса лежат в индексах по типу ускорения, поэтому команда
зависит от того, чем считать:

```powershell
# Процессор: работает на любой машине
.\.venv\Scripts\python.exe -m pip install llama-cpp-python `
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu

# Видеокарта NVIDIA: сборка плюс библиотеки CUDA 12
.\.venv\Scripts\python.exe -m pip install nvidia-cublas-cu12 nvidia-cuda-runtime-cu12
.\.venv\Scripts\python.exe -m pip install llama-cpp-python --upgrade --force-reinstall `
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
```

То же самое делает кнопка «Ускорение» в каталоге моделей ассистента. Сборка под
видеокарту не универсальна: если она не запускается на конкретном процессоре,
приложение говорит об этом словами и предлагает вернуться к сборке «Процессор».
Саму модель ассистента приложение скачивает само - каталог показывает размер и
то, что подходит этому устройству. Если на машине уже запущен Ollama с нужной
моделью, используется он, и второй копии в памяти не появляется.

## Что внутри

- Переносимый мини-остров: уровень сигнала, статус записи, принудительная
  остановка во время «Завершаем», раскрытие в рабочее окно и переназначаемые
  горячие клавиши.
- Live-субтитры - главный режим: отдельное always-on-top окно, предварительный
  текст по короткому окну текущей фразы и финализация в истории. Если модель
  отстаёт, неначатая фраза вытесняется новой, сессия не останавливается.
  Русский язык выбран по умолчанию; Whisper Translate даёт английские субтитры.
- Живой текст растёт словами: подтверждённый префикс остаётся на месте,
  уточняемый хвост приглушён и тоньше, перенос строки и сдвиг слов
  анимируются, предыдущая фраза уходит в строку истории. Одна и та же сцена
  работает в Live-окне и в окне зала.
- Диктовка с копированием текста в буфер обмена, безопасной вставкой в
  сохранённое целевое окно и сохранением исходной расшифровки в историю.
- Локальный словарь терминов, исправлений и voice snippets для финального
  текста диктовки без передачи правил на сервер.
- Выбор и проверка устройств ввода и вывода, визуальный уровень сигнала.
- Медиа-режим: аудио или видео, сегменты с таймкодами, ручное редактирование,
  undo/redo и сохранение в TXT, строку `00:16 - 00:20 [Диктор 2] текст`,
  реплики по ролям, протокол заседания, Markdown, SRT, VTT, CSV, JSON и LRC.
  Окно сохранения показывает готовый текст файла и меняет параметры на месте:
  точность времени от секунд до миллисекунд, вид имени голоса, разделители,
  склейку реплик одного говорящего, фильтр по голосу и по меткам проверки.
  SRT/VTT перегруппировываются по словным таймкодам, длине и пунктуации без
  выдумывания времени.
- Караоке-просмотр с подсветкой текущего слова, экспорт ASS и MP4 поверх видео
  или выбранной обложки.
- Расшифровка файла с определением говорящих: модель NVIDIA NeMo Sortformer
  (до четырёх голосов) размечает дорожку по времени, поэтому фраза со сменой
  голоса разрезается по границе, а не получает одну метку. Голоса можно
  переименовать, оставить в списке одного говорящего и перейти к фразе по
  полосе разговора. Движок необязателен: без него остаётся текст с
  таймкодами. Запасной вариант - SpeechBrain ECAPA, одна метка на фразу.
- Мониторинг до четырёх прямых HTTP(S) источников, локальные ключевые фразы,
  пауза 20 с на повтор одного слова и автоматическое переподключение потока
  с backoff.
- Локальная SQLite-история с миграциями и восстановлением прерванных сессий,
  журнал работы, модели `tiny`, `base`, `small`,
  `medium` и `large-v3`, профили скорости и качества.
- Ассистент по записям на локальной языковой модели: выбор записи слева, чат
  справа, готовые действия «изложение», «главные мысли», «задачи», «темы» и
  свободный разговор без записи. Часовой разговор не помещается в контекст
  небольшой модели, поэтому запись режется на части, для каждой части один раз
  считается выжимка, из выжимок собирается карта с таймкодами, и под вопрос
  раскрываются только нужные части. Переписка хранится рядом с записью.
- Подбор языковой модели по измеренному железу: число потоков, объём ОЗУ,
  видеокарта и её память. Каталог показывает, что поместится целиком в
  видеопамять, а что будет считаться на процессоре. Видеокарты перечисляются по
  вендору - NVIDIA, AMD, Intel, - а не по одному признаку «есть ли CUDA».

## Компоненты

```text
src/dotaudio/
  app.py, controller.py, desktop.py   # запуск, связка QML и системное окно
  capture.py -> pipeline.py -> engine.py
                                      # захват, очередь и faster-whisper
  storage.py, transcripts.py          # SQLite, миграции и экспорт расшифровок
  karaoke.py                          # word timestamps, ASS и MP4
  speaker_id.py, nemo_diarize.py      # голоса: разметка дорожки и разбор фраз
  hardware.py, cuda_runtime.py        # опрос устройства и сборки ускорения
  modelhub.py                         # скачивание файлов моделей с докачкой
  llm.py, assistant.py                # каталог языковых моделей и разбор записи
  assistant_controller.py             # мост ассистента: воркеры и сигналы
  qml/MainMvp.qml                     # оболочка: остров, сцена субтитров, окно
  qml/MiniIsland.qml, LiveTheater.qml, CaptionOverlay.qml
                                      # фазы острова, Live-сцена и экран зала
  qml/Theme.js, CaptionText.qml, CaptionStage.qml
                                      # токены и движение, живая строка и сцена фразы
  qml/Icon.qml, Waveform.qml, StatusDot.qml
  qml/PillButton.qml, IconButton.qml, ToggleSwitch.qml, Dropdown.qml
                                      # общие элементы управления
  qml/KaraokePreview.qml, TranscriptEditor.qml, TranscriptView.qml
  qml/TranscriptExportDialog.qml      # окно сохранения: формат, параметры, предпросмотр
  qml/AssistantPage.qml, AssistantModels.qml
                                      # чат по записи и каталог языковых моделей
tests/                                # pytest, без микрофона и без скачивания моделей
docs/                                 # продукт, архитектура, аналоги, исследование
```

Распознавание и запись выполняются вне GUI-потока. Черновой Live-текст хранится
только в памяти, а SQLite получает подтверждённые сегменты. В live-режиме не
запрашиваются word timestamps, чтобы уменьшить задержку. В медиа-режиме они
сохраняются для караоке и точной правки таймкодов.

## Команды

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests

# Проверить загрузку QML без доступа к микрофону
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m dotaudio --smoke-test --data-dir .local-check
```

Последняя проверка: 489 passed, 11 skipped, `ruff check src tests` без ошибок,
QML smoke-test завершается успешно. Четыре теста `test_engine.py` про поле
`confidence` падают от незавершённой чужой правки движка и ждут её автора.
В тестах остаются два предупреждения
совместимости FastAPI и Starlette с TestClient. Реальные микрофон, системный
звук, GPU и FFmpeg зависят от конкретного компьютера Windows и проверяются на
нём вручную. Скорость ответа ассистента тоже машинная величина: замеры для
конкретного железа лежат в [передаче проекта](docs/HANDOFF.md).

## Стек

<p>
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Qt_Quick-41CD52?style=for-the-badge" alt="Qt Quick" />
  <img src="https://img.shields.io/badge/faster--whisper-555555?style=for-the-badge" alt="faster-whisper" />
  <img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white" alt="pytest" />
  <img src="https://img.shields.io/badge/ruff-D7FF64?style=for-the-badge&logo=ruff&logoColor=black" alt="ruff" />
</p>

## Документы

- [Описание продукта](docs/PRODUCT.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Исследование решений](docs/RESEARCH.md)
- [Аналоги и принципы адаптации](docs/ANALOGS.md)
- [Передача проекта](docs/HANDOFF.md)

## Архитектура

```text
микрофон / WASAPI loopback
  -> capture.py, блоки 100 мс
  -> pipeline.py, endpointing + preview + final очередь
  -> engine.py, faster-whisper / CTranslate2
  -> controller.py, Qt signals
  -> CaptionOverlay.qml / LiveTheater.qml / SQLite history
```

```text
запись в SQLite
  -> assistant.py, части по границам фраз
  -> выжимка каждой части один раз -> карта с таймкодами
  -> выбор нужных частей (поиск по словам + сама модель)
  -> llm.py, llama.cpp или Ollama
  -> assistant_controller.py, Qt signals -> AssistantPage.qml
```

- QML не запускает inference и не обращается к SQLite.
- Свойства контроллеров не трогают диск и сеть: интерфейс читает их на каждой
  перерисовке, поэтому готовность модели считается в воркере.
- Модель готовится до старта захвата Live, тяжёлая работа не выполняется в GUI-потоке.
- Предварительные задачи заменяются свежими, финальные сегменты сохраняются один раз.
- Live догоняет звук: неначатая фраза вытесняется новой, сессия продолжается.
- Принудительная остановка на острове снимает «Завершаем», если decode не вернулся.

## Лицензия

© 2026 DotCore. Все права защищены.

Проприетарный код. Использование, копирование, изменение и распространение запрещены без письменного разрешения автора. Исходный код открыт только для ознакомления. См. [LICENSE](LICENSE).

# .аудио / DotAudio

<p>
  <img src="https://img.shields.io/badge/Python-3.12--3.13-3776AB?style=flat" alt="Python 3.12-3.13" />
  <img src="https://img.shields.io/badge/Platform-Windows_|_Linux_|_macOS-555?style=flat" alt="Windows Linux macOS" />
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

Desktop-приложение к статье о Whisper. Оно распознаёт русскую речь локально
через faster-whisper, показывает живые субтитры, помогает с диктовкой и
превращает аудио или видео в редактируемую расшифровку и караоке-субтитры.
Первая и наиболее полная платформа - Windows; Ubuntu и macOS поддерживаются
установщиком и ядром (микрофон, медиа, история, мастер загрузок).

## Запуск

Нужны **Git** и **Python 3.12 или 3.13**. На Linux обычно ещё `libportaudio2`
(и при сборке wheels - `portaudio19-dev`).

### Windows

```powershell
git clone https://github.com/network-user/DotAudio.git
cd DotAudio
.\Install.bat
```

`Install.bat` создаёт `.venv`, ставит пакет, ярлык на рабочем столе и запускает
приложение. Модели и портативный FFmpeg скачает мастер при первом запуске.

Обновление:

```powershell
.\deploy\update.ps1
```

или **Настройки → Обновления**.

### Ubuntu / Linux

```bash
git clone https://github.com/network-user/DotAudio.git
cd DotAudio
chmod +x install.sh deploy/*.sh
./install.sh
```

Установщик создаёт `.venv`, ставит пакет, `.desktop` в
`~/.local/share/applications` и лаунчер `deploy/dotaudio.sh`. Данные:
`~/.local/share/DotCore/DotAudio`. FFmpeg при отсутствии в PATH скачивается
автоматически (BtbN linux64/arm64).

Обновление:

```bash
./deploy/update.sh
```

или **Настройки → Обновления**.

Подсказка по системным пакетам (Ubuntu 24.04):

```bash
sudo apt install git python3.12 python3.12-venv libportaudio2
```

### macOS

```bash
git clone https://github.com/network-user/DotAudio.git
cd DotAudio
chmod +x install.sh deploy/*.sh
./install.sh
```

Нужен Homebrew Python 3.12/3.13. FFmpeg: мастер вызывает `brew install ffmpeg`,
если Homebrew есть; на Intel возможен и портативный архив. Данные:
`~/Library/Application Support/DotCore/DotAudio`. Разрешите микрофон в
Системных настройках. Системный звук Live требует виртуальный вход
(BlackHole и т.п.).

Обновление: `./deploy/update.sh` или **Настройки → Обновления**.

### Ручной запуск для разработки

Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,server]"
.\.venv\Scripts\dotaudio.exe
```

Linux / macOS:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,server]"
.venv/bin/dotaudio
```

При первом распознавании модель Whisper попадёт в локальный кеш. Для быстрой
проверки выберите `tiny` в «Модели».

Раздел «Ассистент» просит отдельную нативную сборку `llama-cpp-python`:

```bash
.venv/bin/python -m pip install llama-cpp-python \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

### Ограничения по платформам

| Возможность | Windows | Linux | macOS |
|---|---|---|---|
| Диктовка с микрофона | да | да | да (нужно разрешение) |
| Live «звук системы» | WASAPI loopback | Pulse/PipeWire monitor, если есть в списке | нужен BlackHole / аналог |
| Глобальные хоткеи / автовставка | да | только кнопки в окне | только кнопки в окне |
| Авто-FFmpeg | да | да (скачивание) | brew / Intel zip |
| Git-обновления из UI | да | да | да |

## Что внутри

- Переносимый мини-остров: уровень сигнала, статус записи, принудительная
  остановка во время «Завершаем», раскрытие в рабочее окно и переназначаемые
  горячие клавиши (глобально на Windows).
- Live-субтитры - главный режим: отдельное always-on-top окно, предварительный
  текст по короткому окну текущей фразы и финализация в истории. Если модель
  отстаёт, неначатая фраза вытесняется новой, сессия не останавливается.
  Русский язык выбран по умолчанию; Whisper Translate даёт английские субтитры.
- Живой текст растёт словами: подтверждённый префикс остаётся на месте,
  уточняемый хвост приглушён и тоньше, перенос строки и сдвиг слов
  анимируются, предыдущая фраза уходит в строку истории. Одна и та же сцена
  работает в Live-окне и в окне зала.
- Диктовка с копированием текста в буфер обмена, безопасной вставкой в
  сохранённое целевое окно (Windows) и сохранением исходной расшифровки в историю.
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
  modelhub.py, tools_ffmpeg.py        # модели и портативный FFmpeg
  updater.py, process_priority.py     # git-обновления и приоритет (Windows)
  llm.py, assistant.py                # каталог языковых моделей и разбор записи
  assistant_controller.py             # мост ассистента: воркеры и сигналы
  qml/MainMvp.qml                     # оболочка: остров, сцена субтитров, окно
  qml/MiniIsland.qml, LiveTheater.qml, CaptionOverlay.qml
  qml/Theme.js, CaptionText.qml, CaptionStage.qml
  qml/SettingsPage.qml                # среда, Live-источник, обновления
  qml/KaraokePreview.qml, TranscriptEditor.qml, TranscriptView.qml
  qml/TranscriptExportDialog.qml
  qml/AssistantPage.qml, AssistantModels.qml
deploy/
  install.ps1 / update.ps1            # Windows
  install.sh / update.sh              # Linux / macOS
tests/
docs/
```

Распознавание и запись выполняются вне GUI-потока. Черновой Live-текст хранится
только в памяти, а SQLite получает подтверждённые сегменты. В live-режиме не
запрашиваются word timestamps, чтобы уменьшить задержку. В медиа-режиме они
сохраняются для караоке и точной правки таймкодов.

## Команды

Windows:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m dotaudio --smoke-test --data-dir .local-check
```

Linux / macOS:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m dotaudio --smoke-test --data-dir .local-check
```

Последняя проверка на машине разработки (Windows): связанные с портом тесты
зелёные; полный прогон около 505 passed / 11 skipped при известных падениях
четырёх тестов `test_engine.py` из-за поля `confidence`. `ruff check src tests`
без ошибок. Реальные микрофон, системный звук, GPU и FFmpeg зависят от
конкретного компьютера и проверяются на нём вручную. Ubuntu и macOS в этой
сессии не прогонялись end-to-end - установщик и ветки кода добавлены, ручной
чеклист на целевых машинах ещё впереди.

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
микрофон / loopback (WASAPI | Pulse monitor | BlackHole)
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

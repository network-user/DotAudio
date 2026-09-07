# Аналоги и принципы адаптации

Дата обзора: 2026-09-07. Источники внешние; решения DotAudio остаются своими.
Код и контракты чужих приложений не копировать. Брать проверяемые идеи:
поток данных, состояния, ошибки, окна, модели.

Как читать статусы:

| Статус | Значение |
|---|---|
| **есть** | Уже в коде DotAudio |
| **взять** | Следующая адаптация, если сценарий это оправдывает |
| **не брать** | Противоречит PRODUCT.md / HANDOFF.md |

Связанные документы: [PRODUCT.md](PRODUCT.md), [ARCHITECTURE.md](ARCHITECTURE.md),
[RESEARCH.md](RESEARCH.md), [HANDOFF.md](HANDOFF.md).

## Зачем этот файл

Рынок 2025–2026 раскололся на четыре отдельные категории. DotAudio стыкует их
в одном Windows-приложении. Полного аналога нет: ближайшие продукты сильны
в одном слое и пустые в остальных.

| Слой DotAudio | Ближайшие примеры | Что у них обычно нет |
|---|---|---|
| Диктовка + вставка | Wispr Flow, Superwhisper, Handy | Live-зал, караоке, эфир |
| Live-субтитры | LiveTranslate, Windows Live Captions, jt-live-whisper | Безопасная диктовка, редактор |
| Медиа + караоке | Buzz, Vibe, faster-whisper-GUI, MacWhisper | Остров, WASAPI live |
| Эфир + ключевые слова | скрипты radio/scanner, jt-live-whisper | Desktop-продукт с историей |

Ниша DotAudio: локальный Whisper на Windows, русский по умолчанию, остров,
зал, диктовка без Enter, редактор с таймкодами, ASS/MP4, мониторинг HTTP.

---

## Каталог со ссылками

Звёзды GitHub - снимок сентября 2026, они плавают. Ориентир масштаба, не рейтинг.

### Диктовка

| Источник | Тип | Стек | Что брать |
|---|---|---|---|
| [Wispr Flow: первая диктовка](https://docs.wisprflow.ai/articles/6409258247-starting-your-first-dictation) | коммерция, облако | закрытый клиент | Hold / toggle, Esc, курсор до старта, лимит сессии, звук старта |
| [Wispr Flow: вставка не прошла](https://docs.wisprflow.ai/articles/7971211038-fix-text-not-pasting-after-dictation) | коммерция | clipboard + fallback | Распознавание и доставка - разные этапы; «вставить последний текст» |
| [Superwhisper: режимы](https://superwhisper.com/docs/modes/modes) | коммерция, local-first | Whisper / Parakeet | Явные режимы, словарь, история, system audio как отдельный источник |
| [cjpais/Handy](https://github.com/cjpais/Handy) | OSS ~22–31k, MIT | Tauri, whisper.cpp, Parakeet, GigaAM | Hold/toggle, Silero VAD, paste, winget; overlay не должен воровать фокус |
| [OpenWhispr/openwhispr](https://github.com/OpenWhispr/openwhispr) | OSS ~7.8k, MIT | Electron, Whisper.cpp, Parakeet | Словарь, локаль + BYOK |
| [Beingpax/VoiceInk](https://github.com/Beingpax/VoiceInk) | OSS ~6.3k, GPL, macOS | Swift, WhisperKit | Per-app правила, native overlay |
| [EpicenterHQ/epicenter](https://github.com/EpicenterHQ/epicenter) (Whispering) | OSS ~4.8k, AGPL | Tauri | Локальные движки; на Windows Parakeet из-за Vulkan/MSVC |
| [whispaste/whispaste](https://github.com/whispaste/whispaste) | OSS, MIT | Flutter | Overlay с waveform, snippets, Store |
| [malashkadev/aura](https://github.com/malashkadev/aura) | OSS, AGPL, Windows | whisper.cpp, Parakeet | Focus Guard, словарь, история |
| [gurjar1/OmniDictate](https://github.com/gurjar1/OmniDictate) | OSS ~153 | Python, faster-whisper | Ближайший стек к DotAudio для диктовки |
| [primaprashant/awesome-voice-typing](https://github.com/primaprashant/awesome-voice-typing) | каталог | - | Карта OSS-диктовок |

### Live-субтитры и overlay

| Источник | Тип | Стек | Что брать |
|---|---|---|---|
| [Windows Live Captions](https://support.microsoft.com/en-us/windows/use-live-captions-to-better-understand-audio) | система Win11 | Azure Speech on-device | Win+Ctrl+L, положение, микрофон+система. Русского в транскрипции нет: на Copilot+ русский только как исходный язык перевода в EN/zh |
| [Dehydrated-gumarabic195/LiveTranslate](https://github.com/Dehydrated-gumarabic195/LiveTranslate) | OSS, MIT, Windows | PyQt6, WASAPI 32 ms, Silero, несколько ASR | Mix mic+system, click-through overlay, менеджер моделей |
| [emidium-science/realtime-captions-system-audio](https://github.com/emidium-science/realtime-captions-system-audio) | OSS | RealtimeSTT, WASAPI | Preview + final, auto-hide, click-through, не в taskbar |
| [parkscloud/Hearsay](https://github.com/parkscloud/Hearsay) | OSS | faster-whisper, tray | Mic / system / both с метками Local/Remote |
| [evermoving/SystemCaptioner](https://github.com/evermoving/SystemCaptioner) | заброшен → Hearica | faster-whisper | Наивное резание Whisper ломает live |
| [jasoncheng7115/jt-live-whisper](https://github.com/jasoncheng7115/jt-live-whisper) | OSS | faster-whisper, WASAPI | Live + файлы + keyword alerts + overlay |
| [KoljaB/RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) | библиотека ~10k, MIT | faster-whisper + extras | VAD, partial/final, на CPU: streaming preview + качественный final |
| [ufal/whisper_streaming](https://github.com/ufal/whisper_streaming) | исследование | faster-whisper | Local agreement: стабильный префикс после n совпадений |
| [Aurora Subtitles](https://aurora.ilicilabs.com/) | коммерция | local ASR + Silero | Lifetime overlay, перевод, альтернатива Live Captions |
| [captionNode](https://captionnode.com/) | коммерция, зал | faster-whisper, NDI | Вывод на второй экран / NDI |

### Медиа, субтитры, караоке

| Источник | Тип | Стек | Что брать |
|---|---|---|---|
| [chidiwilliams/buzz](https://github.com/chidiwilliams/buzz) | OSS ~21.4k, MIT | Python/PyQt6, Whisper / whisper.cpp / faster-whisper | Файловый GUI + live с микрофона, UI `ru`. Текст остаётся в своём окне |
| [thewh1teagle/vibe](https://github.com/thewh1teagle/vibe) | OSS ~7.4k, MIT | Rust, whisper.cpp, свой HTTP-server | Установщик Win/Mac/Linux, SRT/VTT/JSON |
| [CheshireCC/faster-whisper-GUI](https://github.com/CheshireCC/faster-whisper-GUI) | OSS ~3k | **PySide6 + faster-whisper + whisperX** | Ближайший стек. Word-level → LRC karaoke |
| [pluja/whishper](https://github.com/pluja/whishper) | OSS ~3k, AGPL | Web UI, FasterWhisper | Редактор субтитров в браузере |
| [MacWhisper](https://www.macwhisper.com/) | коммерция, Mac | WhisperKit / Parakeet | Плеер, SRT/VTT, diarization, watch folders |
| [m-bain/whisperX](https://github.com/m-bain/whisperX) | библиотека ~23.9k | wav2vec2 alignment | Точные word timestamps и diarization |
| [Const-me/Whisper](https://github.com/Const-me/Whisper) | OSS ~10.7k, MPL-2.0 | C++ Direct3D 11, WhisperDesktop.exe | Нативный Windows GUI: файл + live с микрофона, без вставки в чужое окно и без loopback-зала |
| [jianfch/stable-ts](https://github.com/jianfch/stable-ts) | библиотека, MIT, пауза | поверх Whisper / faster-whisper | `to_ass(..., karaoke=True)` - progressive filling; ближе к ASS DotAudio, чем WhisperX v3 |
| [MNeMoNiCuZ/whisper-karaoke](https://github.com/MNeMoNiCuZ/whisper-karaoke) | скрипт | faster-whisper | Подсветка слов в web-плеере |

### Эфир и ключевые слова

| Источник | Тип | Что брать |
|---|---|---|
| [mc51/audio-stream-transcription-monitoring-and-alerting](https://github.com/mc51/audio-stream-transcription-monitoring-and-alerting) | скрипт | Чанки потока → Whisper → fuzzy keywords → мессенджер |
| [Nite01007/RadioTranscriber](https://github.com/Nite01007/RadioTranscriber) | CLI | Broadcastify/SDR, faster-whisper, MQTT |
| [watch-duty/radio-transcription](https://github.com/watch-duty/radio-transcription) | инфраструктура | Правила, UI мониторинга, не desktop |
| [arandomguyhere/ScannerTranscribe](https://github.com/arandomguyhere/ScannerTranscribe) | браузер | Keyword highlight + звуковой alert |

Готового desktop-продукта «несколько HTTP/HLS + журнал + история» нет.
Этот слой у DotAudio оригинальнее диктовки.

### Движки, сервер, упаковка, русский

| Источник | Роль |
|---|---|
| [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Текущий движок: CTranslate2, int8, Silero VAD, word timestamps |
| [ggml-org/whisper.cpp](https://github.com/ggml-org/whisper.cpp) | То, на чём Handy/Vibe. Легче упаковать в exe |
| [speaches-ai/speaches](https://github.com/speaches-ai/speaches) | OpenAI-compatible STT-сервер на faster-whisper, SSE, unload модели |
| [ahmetoner/whisper-asr-webservice](https://github.com/ahmetoner/whisper-asr-webservice) | FastAPI STT: openai-whisper / faster-whisper / whisperX, word timestamps, Docker CPU/GPU |
| [Purfview/whisper-standalone-win](https://github.com/Purfview/whisper-standalone-win) | Готовые CUDA/cuDNN DLL для Windows рядом с бинарём |
| [salute-developers/GigaAM](https://github.com/salute-developers/GigaAM) | MIT, SOTA на чистом русском, CPU, уже в Handy |
| [Qt for Python](https://doc.qt.io/qtforpython-6.8/index.html) | Текущий UI-стек |

## Языки проектов

Снимок по публичным репозиториям и README, сентябрь 2026.
У закрытых продуктов исходников нет: там указано только то, что видно снаружи.
«Python» значит, что приложение или библиотека пишется на Python; ядро ASR
часто всё равно C++ (CTranslate2, ggml).

### Кто на Python

Ближайшие к стеку DotAudio (Python + faster-whisper, часто Qt):

| Проект | Python для | UI / оболочка | ASR |
|---|---|---|---|
| **DotAudio** | всё приложение | Qt Quick / QML (PySide6) | faster-whisper |
| [CheshireCC/faster-whisper-GUI](https://github.com/CheshireCC/faster-whisper-GUI) | приложение | PySide6 | faster-whisper, whisperX |
| [Dehydrated-gumarabic195/LiveTranslate](https://github.com/Dehydrated-gumarabic195/LiveTranslate) | приложение | PyQt6 | faster-whisper и др. |
| [jasoncheng7115/jt-live-whisper](https://github.com/jasoncheng7115/jt-live-whisper) | приложение | терминал + PyQt6 overlay + HTML | faster-whisper, whisper.cpp |
| [gurjar1/OmniDictate](https://github.com/gurjar1/OmniDictate) | приложение | свой GUI | faster-whisper |
| [chidiwilliams/buzz](https://github.com/chidiwilliams/buzz) | приложение | Qt (Python) | Whisper / whisper.cpp / faster-whisper |
| [emidium-science/realtime-captions-system-audio](https://github.com/emidium-science/realtime-captions-system-audio) | приложение | overlay + terminal | RealtimeSTT → Whisper |
| [parkscloud/Hearsay](https://github.com/parkscloud/Hearsay) | приложение | tray | faster-whisper |
| [evermoving/SystemCaptioner](https://github.com/evermoving/SystemCaptioner) | приложение | overlay | faster-whisper |
| [KoljaB/RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) | библиотека | нет | faster-whisper и extras |
| [ufal/whisper_streaming](https://github.com/ufal/whisper_streaming) | библиотека | нет | faster-whisper |
| [m-bain/whisperX](https://github.com/m-bain/whisperX) | библиотека | нет | faster-whisper + wav2vec2 |
| [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | библиотека | нет | CTranslate2 (C++) |
| [speaches-ai/speaches](https://github.com/speaches-ai/speaches) | HTTP-сервер | нет | faster-whisper |
| [ahmetoner/whisper-asr-webservice](https://github.com/ahmetoner/whisper-asr-webservice) | HTTP-сервер | нет | faster-whisper / whisperX |
| [jianfch/stable-ts](https://github.com/jianfch/stable-ts) | библиотека | нет | Whisper / faster-whisper, ASS karaoke |
| [salute-developers/GigaAM](https://github.com/salute-developers/GigaAM) | библиотека | нет | свои веса, Python API |
| [MNeMoNiCuZ/whisper-karaoke](https://github.com/MNeMoNiCuZ/whisper-karaoke) | скрипт | Flask web-player | faster-whisper |
| [mc51/...-alerting](https://github.com/mc51/audio-stream-transcription-monitoring-and-alerting) | скрипт | нет | openai-whisper |
| [Nite01007/RadioTranscriber](https://github.com/Nite01007/RadioTranscriber) | CLI | нет | faster-whisper |

Вывод: live-overlay и файловые GUI вокруг faster-whisper почти все на Python.
Массовые диктовки (Handy, Aura, Whispering) ушли в Rust/Tauri. DotAudio
остаётся в Python-кластере вместе с Buzz, LiveTranslate и faster-whisper-GUI.

### Полная таблица языков

| Проект | Основной язык | UI / клиент | Нативное ядро / ASR | Python? |
|---|---|---|---|---|
| **DotAudio** | Python | QML / PySide6 | faster-whisper → CTranslate2 C++ | да, целиком |
| [Handy](https://github.com/cjpais/Handy) | Rust | React, TypeScript (Tauri) | whisper.cpp, Parakeet, GigaAM | нет |
| [Aura](https://github.com/malashkadev/aura) | Rust | TypeScript (Tauri 2) | whisper.cpp, sherpa-onnx | нет |
| [Epicenter Whispering](https://github.com/EpicenterHQ/epicenter) | TypeScript | Svelte + Tauri | whisper.cpp / Parakeet | нет |
| [OpenWhispr](https://github.com/OpenWhispr/openwhispr) | JavaScript | Electron | Whisper.cpp, Parakeet | нет |
| [VoiceInk](https://github.com/Beingpax/VoiceInk) | Swift | native macOS | WhisperKit | нет |
| [WhisPaste](https://github.com/whispaste/whispaste) | Dart | Flutter | Whisper / Parakeet | нет |
| [Buzz](https://github.com/chidiwilliams/buzz) | Python | Qt | Whisper, whisper.cpp, faster-whisper | да |
| [Vibe](https://github.com/thewh1teagle/vibe) | Rust + TypeScript | свой desktop | whisper.cpp | нет |
| [faster-whisper-GUI](https://github.com/CheshireCC/faster-whisper-GUI) | Python | PySide6 | faster-whisper, whisperX | да |
| [LiveTranslate](https://github.com/Dehydrated-gumarabic195/LiveTranslate) | Python | PyQt6 | faster-whisper, SenseVoice, FunASR | да |
| [jt-live-whisper](https://github.com/jasoncheng7115/jt-live-whisper) | Python | PyQt6 + HTML | faster-whisper, whisper.cpp | да |
| [OmniDictate](https://github.com/gurjar1/OmniDictate) | Python | GUI | faster-whisper | да |
| [realtime-captions-system-audio](https://github.com/emidium-science/realtime-captions-system-audio) | Python | overlay | RealtimeSTT | да |
| [Hearsay](https://github.com/parkscloud/Hearsay) | Python | tray | faster-whisper | да |
| [SystemCaptioner](https://github.com/evermoving/SystemCaptioner) | Python | overlay | faster-whisper | да |
| [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) | Python | нет (lib) | faster-whisper и др. | да |
| [whisper_streaming](https://github.com/ufal/whisper_streaming) | Python | нет (lib) | faster-whisper | да |
| [whisperX](https://github.com/m-bain/whisperX) | Python | нет (lib) | CTranslate2 + PyTorch | да |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Python | нет (lib) | CTranslate2 C++ | да, обёртка |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | C / C++ | нет (lib) | ggml | нет |
| [Const-me/Whisper](https://github.com/Const-me/Whisper) | C++ | Win32 GUI, Direct3D 11 | свой порт Whisper на GPU | нет |
| [Speaches](https://github.com/speaches-ai/speaches) | Python | нет (HTTP) | faster-whisper | да |
| [whisper-asr-webservice](https://github.com/ahmetoner/whisper-asr-webservice) | Python | нет (HTTP) | faster-whisper, whisperX | да |
| [stable-ts](https://github.com/jianfch/stable-ts) | Python | нет (lib) | Whisper / faster-whisper | да |
| [GigaAM](https://github.com/salute-developers/GigaAM) | Python | нет (lib) | свои модели | да |
| [Whishper](https://github.com/pluja/whishper) | Go + Svelte | веб | Python (FasterWhisper / WhisperX) | частично, worker |
| [whisper-karaoke](https://github.com/MNeMoNiCuZ/whisper-karaoke) | Python | Flask | faster-whisper | да |
| [radio alerting](https://github.com/mc51/audio-stream-transcription-monitoring-and-alerting) | Python | нет | openai-whisper | да |
| [RadioTranscriber](https://github.com/Nite01007/RadioTranscriber) | Python | нет | faster-whisper | да |
| [watch-duty/radio-transcription](https://github.com/watch-duty/radio-transcription) | TypeScript + Python | React | Whisper / Gemini | частично |
| [ScannerTranscribe](https://github.com/arandomguyhere/ScannerTranscribe) | JavaScript | браузер | Transformers.js / Deepgram | нет |
| [Purfview standalone](https://github.com/Purfview/whisper-standalone-win) | раздача exe | CLI | faster-whisper (Python → бинарь) | исходник Python, продукт - exe |
| [MacWhisper](https://www.macwhisper.com/) | закрытый native | macOS app | WhisperKit / Parakeet | нет, исходник закрыт |
| [Superwhisper](https://superwhisper.com/) | закрытый native | Mac / Win / iOS | Whisper, Parakeet, llama.cpp | нет, исходник закрыт |
| [Wispr Flow](https://docs.wisprflow.ai/) | закрытый клиент + облако | Mac / Win / mobile | облачный ASR | нет, исходник закрыт |
| [Windows Live Captions](https://support.microsoft.com/en-us/windows/use-live-captions-to-better-understand-audio) | системный Win11 | системный overlay | Azure Speech on-device | нет |
| [Aurora Subtitles](https://aurora.ilicilabs.com/) | закрытый | Windows overlay | local ASR | исходник закрыт |
| [captionNode](https://captionnode.com/) | закрытый | зал / NDI | faster-whisper | исходник закрыт |
| [awesome-voice-typing](https://github.com/primaprashant/awesome-voice-typing) | Markdown | нет | нет | каталог, не приложение |

По слоям: диктовка «в любой курсор» сейчас пишется на Rust/Tauri или Swift.
Live-субтитры с WASAPI и файловые GUI с faster-whisper остаются на Python.
Для статьи о Whisper Python-кластер ближе: тот же движок, что у DotAudio.

### Счёт

В полной таблице 38 аналогов (без DotAudio и без каталога awesome-voice-typing).

| Категория | Число | Доля |
|---|---|---|
| Python целиком | **19** | 50% |
| Python частично (worker / исходник exe) | **3** | 8% |
| Не Python | **16** | 42% |

Из 19 Python-проектов: 8 desktop-приложений, 2 HTTP-сервера, 6 библиотек, 3 скрипта/CLI.

Desktop-приложения в каталоге: 8 на Python из 22 (Buzz, faster-whisper-GUI, LiveTranslate, jt-live-whisper, OmniDictate, realtime-captions, Hearsay, SystemCaptioner). Остальные диктовки - Rust/Tauri, Electron, Swift, Flutter или закрытый native.

Частично Python: Whishper (Go UI + Python worker), watch-duty, Purfview (Python → exe).

---

## Принципы для адаптации

Каждый принцип: источник → суть → куда в DotAudio → статус.

### 1. Диктовка и вставка

**1.1 Hold и toggle - два режима, не один.**
Wispr: удержание Fn / Ctrl+Win; hands-free тем же сочетанием + Space.
Handy: hold, toggle, hold-only, toggle-only.
Сейчас DotAudio: toggle по умолчанию; `dictate_hold` включает удержание.
`desktop.py`, `controller.py`. **есть.**

**1.2 Курсор и целевое окно фиксируются в момент старта.**
Wispr: «click into a text field», вставка в то поле, куда кликнули.
Aura: Focus Guard.
DotAudio уже запоминает HWND. Не вставлять, если фокус сменился.
`desktop.py`. **есть**. Если остров перехватил фокус, `paste()` возвращает его целевому окну;
если пользователь ушёл в другое приложение, текст остаётся в буфере.

**1.3 Распознавание и доставка текста - разные этапы.**
[Wispr: paste failed](https://docs.wisprflow.ai/articles/7971211038-fix-text-not-pasting-after-dictation).
Успех ASR не равен успеху вставки. Нужны: буфер, «вставить последний текст»,
история, сообщение «текст в буфере».
Диагностика: Блокнот работает, целевое приложение нет.
`desktop.py`, история SQLite. **есть:** clipboard, целевое окно, `pasteLastTranscript`,
Shift+Alt+Z, сообщение если вставка не прошла.

**1.4 Esc отменяет без вставки и без смены буфера.**
Wispr, Handy, Aura, PRODUCT.md.
`pipeline.py` cancel vs stop. **есть**. Проверить на устройстве.

**1.5 Не нажимать Enter.**
PRODUCT.md. Чаты иначе отправят черновик.
**есть** как правило. Не ломать при SendInput.

**1.6 Буфер: оставлять расшифровку, не восстанавливать старое.**
Wispr после удачного paste возвращает прежний clipboard.
Пользователь DotAudio явно хочет оставить текст в буфере.
PRODUCT.md. **не брать** restore clipboard.

**1.7 Именованные ошибки микрофона со ссылкой в настройки.**
Wispr: permission, no device, selected mic gone, another app holds the mic,
disconnected mid-session.
Не «ошибка аудио», а конкретная причина и кнопка «открыть звук Windows».
`capture.py` `describe_capture_error`. **есть.**

**1.8 Не диктовать в password / numeric-only поля.**
Wispr Android прячет bubble в banking и password.
На Windows сложнее детектить класс поля; минимум: не вставлять в чужое окно
и не вставлять, если цель потеряна. **есть** проверка окна. Полный skip
sensitive-полей **не брать**, пока нет надёжного Win32-детектора.

**1.9 Словарь терминов живёт локально и не уходит на сервер.**
Handy, OpenWhispr, Superwhisper, README DotAudio.
`engine.py` `initial_prompt`. **есть**. Не слать словарь на remote без явной настройки.

**1.10 LLM-правка сказанного - отдельный выключатель, выключен по умолчанию.**
Wispr Smart Formatting, Superwhisper AI modes, Handy post-process.
RESEARCH.md. **не брать** в дефолт: меняет текст, добавляет задержку, нужен ключ.

### 2. Live-пайплайн

**2.1 Захват никогда не ждёт модель.**
ARCHITECTURE.md, `pipeline.py`.
LiveTranslate: 32 ms WASAPI → VAD → ASR.
RealtimeSTT: recorder отдельно от inference.
**есть.** Не нарушать при смене VAD.

**2.2 Preview latest-wins, final имеет приоритет, preview не в SQLite.**
`LiveSession` в `pipeline.py`.
RealtimeSTT / realtime-captions: partial затем committed utterance.
**есть.**

**2.3 Два качества: быстрый preview и качественный final.**
RealtimeSTT на CPU: Nemotron streaming для живого текста, Parakeet для финала.
DotAudio: greedy decode на preview, профиль пользователя на final.
**есть** как идея. **взять** позже отдельный маленький streaming-движок
только если замер RTF на целевой машине это оправдает. Не тащить второй
тяжёлый Whisper в память без измерения.

**2.4 Стабильный префикс, живой хвост.**
[whisper_streaming](https://github.com/ufal/whisper_streaming): LocalAgreement-n.
Подтверждать текст, на котором сошлись n соседних гипотез.
`pipeline.py` уже сравнивает начало preview (`stable_text`).
**есть** черновик. **взять** явное n=2 и не переписывать подтверждённые слова
в CaptionOverlay.

**2.5 Энергетический порог - черновик. Для зала нужен VAD.**
LiveTranslate: Silero, 32 ms, адаптивная тишина.
faster-whisper: `vad_filter` + `min_silence_duration_ms`.
DotAudio: RMS endpointing в `SpeechBuffer`, Silero внутри Whisper на live.
ARCHITECTURE.md уже пишет это.
**взять** Silero/VAC на входе capture для Live, оставив энергию как fallback.
Не включать второй VAD на медиа с музыкой (уже выключен).

**2.6 `condition_on_previous_text=False` на live-чанках.**
faster-whisper README, ARCHITECTURE.md.
Иначе Whisper повторяет предыдущую фразу.
**есть.**

**2.7 Перегрузка видима, старый final можно бросить.**
`catch_up` в `LiveSession`. Контроллер показывает backlog.
SystemCaptioner: скрытый лаг от плохого chunking.
**есть.** Не превращать очередь в бесконечный буфер.

**2.8 Модель готовится до открытия микрофона.**
`Engine.prepare`, LiveTranslate wizard, Speaches dynamic load.
**есть** асинхронный prepare. **взять** прогресс загрузки в острове
(размер, отмена, «офлайн готов»).

**2.9 Whisper не streaming-модель. Наивная нарезка ломает текст.**
SystemCaptioner → Hearica, статья whisper_streaming.
Не обещать «0,8 с до субтитра» без замера cold/warm/RTF на устройстве.
HANDOFF.md. **есть** как правило документации.

### 3. Захват звука

**3.1 Live по умолчанию слушает систему, диктовка - микрофон.**
HANDOFF loopback-итерация. Superwhisper: system audio отдельно.
Hearsay: mic / system / both.
**есть** `live_source`: microphone / system / mixed.

**3.2 Авто (mixed) складывает потоки; если один умер, остаётся второй.**
LiveTranslate mic mix-in. `capture.py`. **есть.**

**3.3 Waveform = фактический RMS, не декор.**
PRODUCT.md, MiniIsland. Superwhisper на system audio волны не двигает -
антипример. **есть.** Не копировать фейковый эквалайзер.

**3.4 Выбор устройства явный, с проверкой уровня.**
Wispr «selected microphone unavailable».
README DotAudio. **есть** перечисление. **взять** live-проверку «тишина при
открытом устройстве» как статус, не как фейковый уровень.

### 4. Остров, зал, дизайн

**4.1 Остров меняет размер по фазе, якорь не прыгает.**
PRODUCT.md, MiniIsland: готов / слушает / субтитр / распознаю / ошибка.
Apple Dynamic Island: morph по содержимому, предсказуемое место.
Тема: `morphMs = 220`, `contentMs = 160`.
**есть.** Не копировать логотипы и системные ассеты Apple.

**4.2 Два окна: компактный остров и зал.**
LiveTranslate / Aurora / Windows Captions: одно overlay.
DotAudio: остров для управления, CaptionOverlay для зала.
**есть.** Зал не должен жить, когда Live выключен (уже).

**4.3 Click-through на зале, возврат фокуса горячей клавишей.**
LiveTranslate, realtime-captions, CaptionOverlay flags:
`WindowDoesNotAcceptFocus` + `applyClickThrough`.
Handy: overlay ворует фокус и ломает paste.
**есть.** **взять** перетаскивание зала и память позиции по монитору.

**4.4 Не анимировать каждый preview.**
CaptionOverlay: fade только на финальном сегменте.
Частичный текст - обычная смена строки.
**есть.**

**4.5 Состояние не только цветом.**
PRODUCT.md, Windows Captions (положение, размер, фон).
Высокий контраст - отдельная настройка, не единственный акцент.
**есть** contrast + size. **взять** положение: сверху / снизу / плавающее,
как у Live Captions.

**4.6 Тишина: либо статус «Слушаю», либо auto-hide.**
realtime-captions прячет overlay в тишине.
Для зала auto-hide полезен; для острова статус нужен всегда.
**взять** опцию «скрывать зал в паузе», остров не прятать во время сессии.

**4.7 Второй монитор - отдельное окно зала, не дубль острова.**
PRODUCT.md, captionNode NDI.
**взять** после проверки DPI: перенос CaptionOverlay на выбранный экран.

**4.8 Типографика зала крупная, 1–2 строки, выравнивание по центру.**
Windows Captions, Aurora, CaptionText `maxLines: 2`.
Русские подписи длиннее английских - проверять 125/150/200%.
**есть** как ориентация. Проверка на устройстве не сделана.

**4.9 Монохром DotCore, не цветной «AI glow».**
Theme.js. LiveTranslate 14 цветных тем - не наш путь.
**есть.** Акцент белой прозрачностью и формой, не неоном.

### 5. Модели и русский

**5.1 Одна закешированная модель, inference сериализован.**
`engine.py`. Speaches unload после простоя - идея для сервера.
**есть** кеш одной модели. **взять** на сервере idle-unload.

**5.2 Профили - гипотезы, не бенчмарк.**
tiny/base CPU, small auto, large-v3 GPU. Не обещать «самая быстрая и точная».
faster-whisper README: сравнивать только с тем же beam и тем же WER.
**есть** как правило. Цифры чужих таблиц в README не переносить.

**5.3 Чистый русский на CPU: GigaAM как опция, не замена Whisper.**
[GigaAM](https://github.com/salute-developers/GigaAM), Handy PR с GigaAM,
статьи на Хабре 2026: на чистом RU GigaAM часто точнее и быстрее turbo;
на RU+EN выигрывает Whisper.
**взять** отдельный профиль «Русский CPU» после измерения на целевой машине.
Не заявлять чужие 3.3% WER как результат DotAudio.

**5.4 Language=ru по умолчанию, без лишнего language-id на старте live.**
`RecognitionConfig.language = "ru"`. **есть.**
`task=translate` = только English. Не обещать произвольный перевод.
LiveTranslate LLM-перевод **не брать** в ядро; это другой продукт.

**5.5 Менеджер моделей: размер, путь, прогресс, отмена, офлайн-готовность.**
LiveTranslate wizard (HF / ModelScope), Superwhisper sidebar, Handy manual drop.
Сейчас загрузка при первом распознавании.
**взять.** Не скачивать все модели сразу.

### 6. Медиа, редактор, караоке

**6.1 Word timestamps для медиа, не для live-preview.**
ARCHITECTURE.md, engine. **есть.**

**6.2 VAD на медиа с музыкой выключен.**
Иначе теряется вокал. **есть.**

**6.3 Плеер и сегменты синхронизированы.**
MacWhisper inline player, .звук LyricsEditor, TranscriptEditor.
**есть.** **взять** undo границ сегмента с проверкой `end >= start`.

**6.4 Караоке: ASS `\k` + опциональный burn-in MP4.**
faster-whisper-GUI даёт LRC; DotAudio уже ASS/MP4.
**есть.** Не выдумывать таймкоды при перегруппировке SRT.

**6.5 Более точное выравнивание - WhisperX или stable-ts, не второй live-проход.**
WhisperX v3 больше не отдаёт ASS (остался SRT `--highlight_words`).
[stable-ts](https://github.com/jianfch/stable-ts) пишет ASS karaoke, но репозиторий на паузе.
**взять** позже только для медиа. Не в Live.

**6.6 Исходный текст сегмента не затирается правкой.**
PRODUCT, storage `original_text`. **есть.**

### 7. Эфир

**7.1 Совпадение показывает правило, источник и время захвата.**
PRODUCT.md. Скрипты radio - только keyword + сообщение.
**есть** черновик мониторинга. Не развивать, пока live - приоритет (HANDOFF).

**7.2 Кулдаун на одно и то же слово.**
jt-live-whisper. Иначе лог забивается повтором.
**взять** когда вернётесь к эфиру.

**7.3 Время новости - часы захвата, не конец inference.**
ARCHITECTURE.md. **есть** как правило. Проверить в коде событий.

**7.4 Переподключение потока с backoff, явная перегрузка.**
README. **есть** заготовка. Не обещать YouTube/Telegram без адаптера.

### 8. Сервер

**8.1 Контракт сегментов тот же, что у локального Engine.**
ARCHITECTURE.md. **есть.**

**8.2 По умолчанию localhost, busy, cancel, лимиты.**
`server.py`. Speaches: OpenAI `/v1/audio/transcriptions` + SSE.
**взять** совместимый путь, не ломая текущий `/v1/transcribe`.
Публичный API **не брать**.

**8.3 Один запрос за раз, пока нет планировщика.**
HANDOFF. **есть.** 503 для занятого сервера - норма, не баг.

### 9. Упаковка и Windows-ввод

**9.1 SendInput вместо устаревшего `keybd_event`.**
HANDOFF, Aura/whisper-local. `desktop.py`. **есть.**

**9.2 CUDA/cuDNN класть рядом с приложением.**
[Purfview libs](https://github.com/Purfview/whisper-standalone-win/releases/tag/libs),
faster-whisper README.
**взять** на этапе установщика. Не требовать системный CUDA у читателя статьи
без инструкции.

**9.3 FFmpeg для MP4 - отдельная зависимость, не «внутри Python всегда».**
README. **есть** как требование PATH. **взять** app-local ffmpeg в установщике.

**9.4 Установщик и winget - после ручного чеклиста на устройстве.**
Handy уже в winget. HANDOFF: сначала устройство, потом упаковка.

---

## Очередь: что брать сначала

Не начинать с нового движка. Сначала довести то, что аналоги считают гигиеной UX.

1. **Диктовка как у Wispr/Handy, без облака.** **есть.**
2. **Зал как у Live Captions / LiveTranslate.** **есть** (положение, экран,
   auto-hide, закрепление/перетаскивание). Замеры DPI на устройстве остаются.
3. **Live устойчивее Whisper-нарезки.** **есть** hysteresis + grow-only prefix.
   Отдельный Silero на входе и RTF-замеры - после ручного чеклиста.
4. **Менеджер моделей.** **есть** кеш на диске, подготовка, отмена. GigaAM
   только после замера на русском.
5. **Сервер как Speaches по форме, не по объёму.** **есть**
   `POST /v1/audio/transcriptions` рядом с `/v1/transcribe`. localhost.
6. **Эфир.** Кулдаун keywords **есть**. WhisperX alignment - позже.

## Что не брать, даже если «так делают все»

- Облако как единственный путь (Wispr).
- Авторедактура LLM по умолчанию.
- Восстановление старого буфера после вставки.
- Авто-Enter.
- Цветные «AI» темы и фейковый эквалайзер.
- Demucs / large-v3 в live-очереди (это профиль .звук).
- Произвольный перевод «в любой язык» поверх Whisper Translate.
- Заявки NVIDIA Broadcast как субтитры: там шумодав, не ASR.
  Отдельного потребительского «NVIDIA Live Captions» с overlay нет.
- [Descript](https://www.descript.com/pricing) и [Otter](https://otter.ai/pricing): облачные редакторы встреч,
  не вставка в чужое окно. У Otter русского ASR нет; у Descript русский
  в translate/dubbing, не в базовом STT.
- Windows Live Captions как «русский зал»: транскрипции `ru` в штатном списке нет.
- Цифры WER/RTF из чужих статей как свои.

Независимое перекрёстное ревью 2026-09-07 подтвердило: готового аналога
«все режимы DotAudio в одном Windows-приложении» нет. Дополнительно
зафиксированы [Const-me/Whisper](https://github.com/Const-me/Whisper)
(C++ Direct3D, ~10.7k) и [whisper-asr-webservice](https://github.com/ahmetoner/whisper-asr-webservice)
как ближайший FastAPI-собрат optional HTTP. Обзор помечен Partial:
Aqua Voice, Spokenly, TypeWhisper (C#) в том проходе не разбирались
до того же уровня.

## Исследование .звук

Публичные слои соседних репозиториев разобраны в [RESEARCH.md](RESEARCH.md).
Оттуда для DotAudio полезны: очередь compute, сегмент с word timestamps,
синхронизация текста и плеера. Закрытые политики и внутренние алгоритмы
не извлекать и не копировать.
)

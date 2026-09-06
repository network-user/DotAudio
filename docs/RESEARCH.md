# Исследование для DotAudio

Дата: 2026-09-06. Внешние источники использованы для выбора направления; продуктовые решения DotAudio не являются копией контрактов других приложений.

## Аналоги

| Источник | Что полезно для DotAudio |
|---|---|
| [Wispr Flow: первая диктовка](https://docs.wisprflow.ai/articles/6409258247-starting-your-first-dictation) | Горячая клавиша, запись, остановка, вставка, отмена |
| [Wispr Flow: проблемы вставки](https://docs.wisprflow.ai/articles/7971211038-fix-text-not-pasting-after-dictation) | Распознавание и доставка текста в поле - отдельные этапы; нужен способ забрать текст при неудаче |
| [Superwhisper: режимы](https://superwhisper.com/docs/modes/modes) | Явные режимы обработки под разные задачи |
| [Superwhisper: начало работы](https://superwhisper.com/docs/get-started/introduction) | Сценарии диктовки и перевода |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Python API, CPU int8, GPU, VAD и сегменты |
| [Qt for Python](https://doc.qt.io/qtforpython-6.8/index.html) | Нативные компоненты Qt и декларативный интерфейс |

Вывод: общая идея - короткий путь от голоса до текста. Для DotAudio к нему добавляются редактор медиа и наблюдение за эфиром. Автоматическую «умную редактуру» через LLM не добавлять по умолчанию: она меняет сказанное, повышает задержку и требует отдельной настройки.

## Что изучено в .звук

Два подагента Terra независимо изучили публичные слои соседних репозиториев, только чтение. Содержимое секретных файлов и пути с private/token/credential/password/secret не читались. Код соседних проектов в DotAudio не копировался.

### DotSoundBackend

Корень: `C:\Users\User\PycharmProjects\DotSoundBackend`.

- `agents.md`, `docs/ai-boundary-policy.md`: граница транспортного слоя и закрытого ядра.
- `app/models/compute_job.py`, `app/services/compute_queue_service.py`: асинхронная очередь, claim/lease, retry и восстановление зависших работ.
- `docs/compute-worker-protocol.md`: worker получает задачу, сообщает progress и возвращает result/fail.
- `app/schemas/lyrics.py`: текст, построчные/словные таймкоды и confidence.
- `app/api/v1/lyrics.py`, `app/services/lyrics_worker.py`: публикация состояния/частичного текста.
- `frontend/src/store/lyricsTaskStore.ts`: SSE и fallback polling.
- `frontend/src/components/TrackCardSheet/LyricsEditor.tsx`: редактирование и работа с позициями плеера.

Стек публичного слоя: Python/FastAPI, PostgreSQL, Redis, MinIO/S3, Taskiq. Это пример организации фоновой обработки, а не готовый live-движок для микрофона.

### DotSoundComputeWorker

Корень: `C:\Users\User\PycharmProjects\DotSoundComputeWorker`.

- `worker/asr/whisper_runner.py`: faster-whisper/stable-ts, кеш модели, выбор CPU/GPU, CPU fallback при проблеме CUDA, словные таймкоды.
- `worker/pipeline.py`: загрузка медиа, необязательное выделение вокала, ASR и последующие стадии.
- `worker/main.py`, `worker/pull_control.py`: pull-loop, heartbeat, ограничение параллелизма и отмена.
- `worker/backend_client.py`: протокол взаимодействия с backend.
- `worker/config.py`, `pyproject.toml`, `docker/Dockerfile.cpu`: конфигурация и зависимости.

Профили этого проекта рассчитаны в том числе на музыку и тяжёлую офлайн-обработку. Demucs, large-v3 и усложнённое выравнивание не следует автоматически переносить в быстрый режим диктовки.

## Рекомендация для будущей статьи

Главный воспроизводимый пример - DotAudio. У него самостоятельная задача и отдельная кодовая база. .звук полезен как короткий production-кейс: как организовать очередь вычислений и синхронизированный текст в большом приложении.

Не нужно объяснять все внутренности .звук, чтобы читатель понял Whisper. Публичные транспортные компоненты можно обсуждать после проверки условий публикации, а закрытые политики и внутренние алгоритмы не извлекать. Статья в этой сессии не написана.

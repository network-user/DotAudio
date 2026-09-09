"""Разбор расшифровки: части, карта записи, поиск нужного и ответы."""

from __future__ import annotations

import threading

from dotaudio import assistant as core
from dotaudio.assistant import (
    NOT_FOUND_MARKER,
    Chunk,
    Digest,
    DigestCache,
    TranscriptAssistant,
    build_chunks,
    keywords_of,
    outline_text,
    parse_part_numbers,
    score_chunks,
    stamp,
)


def _segments(count: int, step: float = 5.0, text: str = "фраза") -> list[dict]:
    return [
        {"id": index, "start": index * step, "end": index * step + step, "text": f"{text} {index}"}
        for index in range(count)
    ]


class _Recorder:
    """Модель-заглушка: отвечает по сценарию и запоминает запросы."""

    def __init__(self, replies=None, default="ответ") -> None:
        self.replies = list(replies or [])
        self.default = default
        self.prompts: list[str] = []
        self.streamed: list[str] = []

    def __call__(self, messages, options, on_token=None):
        self.prompts.append(messages[-1]["content"])
        reply = self.replies.pop(0) if self.replies else self.default
        if on_token is not None:
            on_token(reply)
            self.streamed.append(reply)
        return reply


def test_stamp_shows_hours_only_when_needed() -> None:
    assert stamp(0) == "00:00"
    assert stamp(65.4) == "01:05"
    assert stamp(3725) == "1:02:05"


def test_chunks_break_on_phrase_boundaries_and_keep_timecodes() -> None:
    chunks = build_chunks(_segments(10, step=40.0), target_seconds=100.0)

    assert len(chunks) > 1
    # Часть всегда кончается на готовой фразе: иначе таймкод в ответе указывал
    # бы на середину слова.
    for chunk in chunks:
        assert chunk.lines
        assert chunk.start <= chunk.end
    joined = " ".join(chunk.text for chunk in chunks)
    for segment in _segments(10, step=40.0):
        assert segment["text"] in joined
    assert chunks[0].stamped.startswith("[00:00] ")
    assert chunks[0].segment_ids[0] == 0


def test_chunks_also_split_on_length_for_dense_speech() -> None:
    """Речь без пауз идёт одним потоком: часть режется и по объёму текста."""

    dense = [{"id": 0, "start": 0.0, "end": 3.0, "text": "слово " * 400}]
    chunks = build_chunks(dense, target_seconds=600.0, max_chars=1000)

    assert len(chunks) == 1  # одна фраза не рвётся посередине
    long_talk = [
        {"id": index, "start": index * 2.0, "end": index * 2.0 + 2.0, "text": "слово " * 60}
        for index in range(10)
    ]
    assert len(build_chunks(long_talk, target_seconds=600.0, max_chars=1000)) > 1


def test_empty_and_broken_segments_are_skipped() -> None:
    messy = [
        {"id": 1, "start": 0.0, "end": 1.0, "text": "  "},
        {"id": 2, "start": "плохо", "end": 1.0, "text": "текст"},
        {"id": 3, "start": 1.0, "end": 2.0, "text": "хороший"},
    ]
    chunks = build_chunks(messy)

    assert len(chunks) == 1
    assert chunks[0].text == "хороший"


def test_keywords_ignore_service_words() -> None:
    words = keywords_of("Мы договорились про смету и про сроки, а что делать потом - непонятно")

    assert "договорились" in words
    assert "что" not in words
    assert "про" not in words


def test_search_finds_the_part_that_mentions_the_subject() -> None:
    segments = [
        {"id": 0, "start": 0.0, "end": 10.0, "text": "Здравствуйте, начнём с приветствия"},
        {"id": 1, "start": 200.0, "end": 210.0, "text": "Смета по проекту выросла до трёх миллионов"},
        {"id": 2, "start": 400.0, "end": 410.0, "text": "Погода сегодня хорошая, все устали"},
    ]
    chunks = build_chunks(segments, target_seconds=1.0)
    ranked = score_chunks("что решили по смете?", chunks)

    assert ranked
    assert ranked[0][0] == 1


def test_search_matches_different_word_forms() -> None:
    segments = [
        {"id": 0, "start": 0.0, "end": 5.0, "text": "Обсудили договорённости по оплате"},
        {"id": 1, "start": 60.0, "end": 65.0, "text": "Ничего важного"},
    ]
    chunks = build_chunks(segments, target_seconds=1.0)
    ranked = score_chunks("какая договорённость про оплату", chunks)

    assert ranked[0][0] == 0


def test_selective_words_point_at_the_part_common_words_do_not() -> None:
    """Отбор идёт по редкому слову записи, а не по числу совпадений."""

    segments = [
        {"id": 0, "start": 0.0, "end": 90.0, "text": "проект обсуждение работа " * 20},
        {"id": 1, "start": 100.0, "end": 190.0, "text": "проект обсуждение смета " * 20},
        {"id": 2, "start": 200.0, "end": 290.0, "text": "проект обсуждение работа " * 20},
        {"id": 3, "start": 300.0, "end": 390.0, "text": "проект обсуждение работа " * 20},
    ]
    chunks = build_chunks(segments, target_seconds=1.0, max_chars=100000)

    # «Смета» встречается в одной части - по ней и открываем.
    assert core.selective_hits("что решили по смете?", chunks) == [1]
    # «Проект» и «обсуждение» есть везде: они ничего не выделяют.
    assert core.selective_hits("что там по проекту и обсуждению?", chunks) == []
    assert core.selective_hits("", chunks) == []


def test_part_numbers_survive_a_talkative_answer() -> None:
    assert parse_part_numbers("Нужны части 2, 5 и ещё 3", limit=6) == [1, 4, 2]
    # Номера за пределами карты игнорируются, а не ломают выбор.
    assert parse_part_numbers("часть 99", limit=3) == []
    assert parse_part_numbers("", limit=3) == []


def test_outline_lists_parts_with_time_and_words() -> None:
    digests = [
        Digest(index=0, start=0.0, end=60.0, summary="О смете", keywords=("смета", "деньги")),
    ]
    text = outline_text(digests)

    assert "Часть 1" in text
    assert "00:00-01:00" in text
    assert "смета" in text


def test_digests_are_computed_once_and_reused() -> None:
    chunks = build_chunks(_segments(6, step=60.0), target_seconds=120.0)
    model = _Recorder(default="о чём-то говорят")
    cache = DigestCache()
    helper = TranscriptAssistant(respond=model, context_tokens=2048, digests=cache)

    first = helper.ensure_digests("rec", chunks)
    calls_after_first = len(model.prompts)
    second = helper.ensure_digests("rec", chunks)

    assert len(first) == len(chunks)
    assert [item.summary for item in second] == [item.summary for item in first]
    # Второй вопрос по той же записи не платит за карту заново.
    assert len(model.prompts) == calls_after_first


def test_edited_transcript_invalidates_only_the_changed_part() -> None:
    segments = _segments(6, step=60.0)
    chunks = build_chunks(segments, target_seconds=120.0)
    model = _Recorder(default="описание")
    helper = TranscriptAssistant(respond=model, context_tokens=2048, digests=DigestCache())
    helper.ensure_digests("rec", chunks)
    before = len(model.prompts)

    segments[0]["text"] = "совершенно другой текст"
    changed = build_chunks(segments, target_seconds=120.0)
    helper.ensure_digests("rec", changed)

    assert len(model.prompts) == before + 1


def test_empty_model_reply_does_not_hide_a_part_from_the_map() -> None:
    chunks = build_chunks(_segments(3, step=60.0), target_seconds=120.0)
    helper = TranscriptAssistant(respond=_Recorder(default="   "), context_tokens=2048)

    digests = helper.ensure_digests("rec", chunks)

    assert all(item.summary for item in digests)


def test_short_record_is_read_whole_without_building_a_map() -> None:
    chunks = build_chunks(_segments(3), target_seconds=120.0)
    model = _Recorder(default="Коротко: обсудили фразы")
    helper = TranscriptAssistant(respond=model, context_tokens=8192)

    answer = helper.answer("о чём речь?", "rec", chunks)

    assert answer.mode == "full"
    assert answer.text == "Коротко: обсудили фразы"
    # Полный текст ушёл в один запрос, промежуточных шагов не было.
    assert len(model.prompts) == 1
    assert "фраза 0" in model.prompts[0]


def _long_record() -> list[Chunk]:
    segments = [
        {"id": 0, "start": 0.0, "end": 100.0, "text": "приветствие " * 60},
        {"id": 1, "start": 200.0, "end": 300.0, "text": "смета выросла до трёх миллионов " * 40},
        {"id": 2, "start": 400.0, "end": 500.0, "text": "посторонний разговор " * 60},
        {"id": 3, "start": 600.0, "end": 700.0, "text": "прощание и планы " * 60},
    ]
    return build_chunks(segments, target_seconds=1.0, max_chars=100000)


def test_question_with_distinct_words_skips_building_the_map() -> None:
    """Слово из вопроса звучало в записи - карта не нужна.

    Разбор часовой записи по частям стоит десятки запросов к модели. Платить
    за него ради «что решили по смете» незачем: нужную часть находит поиск.
    """

    chunks = _long_record()
    stages: list[str] = []
    model = _Recorder(replies=["Смета выросла [03:20]"])
    helper = TranscriptAssistant(
        respond=model,
        context_tokens=1024,
        digests=DigestCache(),
        on_stage=lambda name, payload: stages.append(name),
    )

    answer = helper.answer("что со сметой?", "rec", chunks)

    assert answer.mode == "search"
    assert answer.text == "Смета выросла [03:20]"
    assert "index_start" not in stages
    assert "select_start" not in stages
    # Один запрос к модели - сам ответ. Никаких выжимок по дороге.
    assert len(model.prompts) == 1
    assert 1 in answer.opened
    assert len(answer.opened) < len(chunks)
    assert "смета выросла" in model.prompts[-1]


def test_vague_question_goes_through_the_map_of_parts() -> None:
    """Вопрос без общих слов с записью: часть выбирает модель по карте."""

    chunks = _long_record()
    stages: list[str] = []
    model = _Recorder(replies=["выжимка", "выжимка", "выжимка", "выжимка", "2", "Про деньги [03:20]"])
    helper = TranscriptAssistant(
        respond=model,
        context_tokens=1024,
        digests=DigestCache(),
        on_stage=lambda name, payload: stages.append(name),
    )

    answer = helper.answer("какой был главный итог обсуждения?", "rec", chunks)

    assert answer.mode == "outline"
    assert answer.text == "Про деньги [03:20]"
    assert "index_start" in stages and "select_start" in stages
    assert 1 in answer.opened
    assert len(answer.opened) < len(chunks)


def test_missing_answer_triggers_a_second_pass_over_other_parts() -> None:
    segments = [
        {"id": index, "start": index * 100.0, "end": index * 100.0 + 90.0, "text": f"тема {index} " * 60}
        for index in range(4)
    ]
    chunks = build_chunks(segments, target_seconds=1.0, max_chars=100000)
    model = _Recorder(
        replies=[
            "выжимка", "выжимка", "выжимка", "выжимка",  # карта записи
            "1",                                        # выбор части
            NOT_FOUND_MARKER,                           # первый заход пустой
            "Нашлось во второй попытке",                # второй заход
        ]
    )
    helper = TranscriptAssistant(respond=model, context_tokens=1024, digests=DigestCache())

    answer = helper.answer("где это сказано?", "rec", chunks)

    assert answer.rounds == 2
    assert answer.not_found is False
    assert answer.text == "Нашлось во второй попытке"


def test_marker_left_after_all_passes_is_reported_not_shown() -> None:
    segments = [
        {"id": index, "start": index * 100.0, "end": index * 100.0 + 90.0, "text": f"тема {index} " * 60}
        for index in range(3)
    ]
    chunks = build_chunks(segments, target_seconds=1.0, max_chars=100000)
    helper = TranscriptAssistant(
        respond=_Recorder(default=NOT_FOUND_MARKER),
        context_tokens=1024,
        digests=DigestCache(),
    )

    answer = helper.answer("чего в записи нет?", "rec", chunks)

    assert answer.not_found is True
    assert NOT_FOUND_MARKER not in answer.text


def test_marker_is_recognised_in_any_case_the_model_writes_it() -> None:
    """Модель переписывает служебное слово по-своему: «Нет_в_записи», «нет в записи»."""

    chunks = build_chunks(_segments(3), target_seconds=120.0)
    for written in ("НЕТ_В_ЗАПИСИ", "Нет_в_записи", "нет в записи"):
        helper = TranscriptAssistant(respond=_Recorder(default=written), context_tokens=8192)
        answer = helper.answer("чего тут нет?", "rec", chunks)
        assert answer.not_found is True, written
        # Пустого пузыря быть не должно: на вопрос отвечают фразой.
        assert answer.text == core.NOT_FOUND_REPLY, written


def test_refusal_in_plain_words_counts_as_not_found() -> None:
    """Отказ своими словами тоже считается отказом.

    Иначе второй заход по остальным частям не начинался бы, и ответ терялся бы
    там, где он на самом деле есть.
    """

    chunks = build_chunks(_segments(3), target_seconds=120.0)
    helper = TranscriptAssistant(
        respond=_Recorder(default="Про это не говорится."), context_tokens=8192
    )

    answer = helper.answer("чего тут нет?", "rec", chunks)

    assert answer.not_found is True
    assert answer.text == "Про это не говорится."

    # Длинный разбор с такой фразой внутри - это не отказ по всему вопросу.
    long_reply = "Обсуждали смету и сроки. " * 12 + "Про премию не упоминается."
    helper = TranscriptAssistant(respond=_Recorder(default=long_reply), context_tokens=8192)
    assert helper.answer("что обсуждали?", "rec", chunks).not_found is False


def test_summary_of_a_long_record_goes_through_the_map() -> None:
    segments = [
        {"id": index, "start": index * 100.0, "end": index * 100.0 + 90.0, "text": f"часть {index} " * 80}
        for index in range(6)
    ]
    chunks = build_chunks(segments, target_seconds=1.0, max_chars=100000)
    model = _Recorder(default="описание части")
    helper = TranscriptAssistant(respond=model, context_tokens=1024, digests=DigestCache())

    answer = helper.summarize("rec", chunks, "summary")

    assert answer.mode == "outline"
    assert len(answer.opened) == len(chunks)
    assert "Составь связное краткое изложение" in model.prompts[-1]


def test_very_long_map_is_folded_before_the_final_answer() -> None:
    segments = [
        {"id": index, "start": index * 100.0, "end": index * 100.0 + 90.0, "text": f"тема {index} " * 60}
        for index in range(24)
    ]
    chunks = build_chunks(segments, target_seconds=1.0, max_chars=100000)
    stages: list[str] = []
    helper = TranscriptAssistant(
        respond=_Recorder(default="д" * 300),
        context_tokens=512,
        digests=DigestCache(),
        on_stage=lambda name, payload: stages.append(name),
    )

    helper.summarize("rec", chunks, "summary")

    # Перечень выжимок сам не влез, поэтому он сжимался группами.
    assert "fold" in stages


def test_actions_ask_for_what_their_name_promises() -> None:
    chunks = build_chunks(_segments(2), target_seconds=120.0)
    for kind, marker in (
        ("keypoints", "главные мысли"),
        ("tasks", "договорённости"),
        ("topics", "темы записи"),
    ):
        model = _Recorder(default="готово")
        helper = TranscriptAssistant(respond=model, context_tokens=8192)
        helper.summarize("rec", chunks, kind)
        assert marker.casefold() in model.prompts[-1].casefold()


def test_free_chat_does_not_mention_a_record() -> None:
    model = _Recorder(default="Просто отвечаю")
    helper = TranscriptAssistant(respond=model, context_tokens=8192)

    answer = helper.chat("Привет", [{"role": "user", "content": "раньше"}])

    assert answer.mode == "chat"
    assert answer.text == "Просто отвечаю"
    assert "Выдержки" not in model.prompts[-1]


def test_free_chat_includes_attached_text_file() -> None:
    seen = []

    def respond(messages, options, on_token=None):
        seen.append(messages)
        return "В файле смета"

    helper = TranscriptAssistant(respond=respond, context_tokens=8192)
    answer = helper.chat(
        "О чём файл?",
        material="Смета выросла до 3 млн.",
        material_name="notes.txt",
    )

    assert answer.mode == "chat"
    assert answer.text == "В файле смета"
    assert "notes.txt" in seen[0][-2]["content"]
    assert "Смета выросла" in seen[0][-2]["content"]
    assert seen[0][-1]["content"] == "О чём файл?"


def test_history_keeps_attachment_text_for_the_model() -> None:
    rows = core._history_messages(
        [
            {
                "role": "user",
                "content": "Суммируй",
                "meta": {
                    "attachment": {"name": "a.txt", "text": "Текст файла", "chars": 11}
                },
            }
        ]
    )

    assert "Текст файла" in rows[0]["content"]
    assert "Суммируй" in rows[0]["content"]


def test_generic_microphone_title_becomes_a_transcript_snippet() -> None:
    item = core.list_item_from_row(
        {
            "id": "1",
            "title": "Микрофон",
            "mode": "dictation",
            "created_at": "2026-09-09T10:15:00+00:00",
            "text": "Смета выросла до трёх миллионов и сроки сдвинули",
            "segment_count": 4,
            "chat_count": 0,
        }
    )

    assert item["needsTitle"] is True
    assert "Смета" in item["displayTitle"]
    assert "Диктовка" in item["subtitle"]
    assert "Микрофон" not in item["displayTitle"]


def test_suggested_title_is_cleaned_from_model_noise() -> None:
    assert core.clean_suggested_title('«Смета и сроки».\nЕщё текст') == "Смета и сроки"
    assert core.title_from_transcript(
        [{"text": "[Человек 1] Привет всем на совещании по смете"}]
    ).startswith("Привет")


def test_cancel_stops_building_the_map() -> None:
    chunks = build_chunks(_segments(8, step=60.0), target_seconds=120.0)
    cancel = threading.Event()
    cancel.set()
    helper = TranscriptAssistant(
        respond=_Recorder(default="описание"),
        context_tokens=1024,
        digests=DigestCache(),
        cancel=cancel,
    )

    assert helper.ensure_digests("rec", chunks) == []


def test_history_is_trimmed_so_the_record_keeps_the_context() -> None:
    long_talk = [{"role": "user", "content": "к" * 5000}] * 6
    trimmed = core._recent_history(long_talk)

    assert len(trimmed) < 5000
    assert core._history_messages([{"role": "tool", "content": "нет"}]) == []


def test_record_card_reports_duration_and_parts() -> None:
    card = core.record_from_session(
        {"id": "abc", "title": "Совещание", "created_at": "2026-01-01", "segments": _segments(4, step=30.0)}
    )

    assert card["id"] == "abc"
    assert card["durationLabel"] == "02:00"
    assert card["chunks"] >= 1

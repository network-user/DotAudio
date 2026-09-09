"""Работа локальной модели с расшифровкой: карта записи, поиск, ответы.

Модуль Qt-free и не знает, какой рантайм отвечает: он получает функцию
``respond(messages, options, on_token) -> str`` и работает через неё. Поэтому
его можно проверять без скачанной модели.

Как решается главная трудность - часовой разговор не влезает в контекст
маленькой модели:

1. Расшифровка режется на части по границам фраз, примерно по две с половиной
   минуты. Часть - это то, что модель может прочитать целиком.
2. Для каждой части один раз считается выжимка: две-три фразы и ключевые
   слова. Выжимки складываются в базу, поэтому второй вопрос по той же записи
   уже не платит за них.
3. Из выжимок собирается карта записи с таймкодами. Она короткая: даже у
   двухчасового разговора это меньше полутора тысяч токенов.
4. На вопрос сначала отвечает не модель, а поиск - лексический по словам и,
   если есть сохранённые векторы, лёгкий семантический по хеш-эмбеддингам
   (feature hashing стемов, не нейросеть). Затем модель читает карту и сама
   говорит, какие части нужно открыть.
5. Выбранные части раскрываются полным текстом (вместе с соседними, если
   помещаются) и только они идут в контекст ответа.
6. Если модель отвечает, что в открытых частях ответа нет, идёт второй заход
   по следующим кандидатам. Больше двух заходов не делается: пользователь
   ждёт ответ, а не полный перечёт записи.

Короткая запись обходит всё это: если расшифровка целиком влезает в бюджет,
она отдаётся моделью как есть.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from dotaudio.llm import GenerationOptions
from dotaudio.speaker_labels import default_speaker_label

# Сколько символов русского текста приходится на токен. Оценка снизу: лучше
# недобрать контекст, чем упереться в окно на середине ответа.
CHARS_PER_TOKEN = 2.4

# Часть записи. Две с половиной минуты - это связный кусок разговора, который
# ещё дёшево пересказать, и достаточно мелкий, чтобы точно указать таймкод.
CHUNK_TARGET_SECONDS = 150.0
CHUNK_MAX_CHARS = 3200

# Доля окна контекста под сам материал. Остальное - инструкции, переписка и
# место под ответ.
CONTEXT_SHARE = 0.5

# Сколько частей открывать на один вопрос. Больше - дольше ответ и выше шанс,
# что модель потеряет вопрос среди текста.
MAX_OPENED_CHUNKS = 6
MAX_ROUNDS = 2

# Слово считается редким, если встречается не более чем в такой доле частей.
# На записи из трёх частей это одна часть, на записи из тридцати - десять.
SELECTIVE_SHARE = 0.34

# Модель обязана сказать это, если в открытых частях ответа нет: тогда идёт
# второй заход, а не выдумка.
NOT_FOUND_MARKER = "НЕТ_В_ЗАПИСИ"
# Регистр и подчёркивания модель переписывает по-своему: проверено на этой
# машине, Qwen3 ответила «Нет_в_записи». Сравнение по образцу, а не по строке.
_NOT_FOUND_MARKER_RE = re.compile(r"НЕТ[_\s-]?В[_\s-]?ЗАПИСИ", re.IGNORECASE)
NOT_FOUND_REPLY = "Не нашёл этого в записи."

# Короткий отказ, сказанный словами вместо служебного слова. Проверяется только
# на коротком ответе: в длинном разборе такая фраза может относиться к одной
# частности, а не ко всему вопросу.
NOT_FOUND_PARAPHRASE_LIMIT = 180
_NOT_FOUND_PARAPHRASE = re.compile(
    r"(нет в записи|не упоминается|не говорится|не сказано|нет информации"
    r"|не обсуждал|нет данных|отсутствует в выдержк)",
    re.IGNORECASE,
)

_WORD = re.compile(r"[0-9a-zA-Zа-яёА-ЯЁ]+")

# Таймкоды в квадратных скобках для кликабельных ссылок в ответе.
TIMESTAMP_RE = re.compile(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]")

# Вес семантического скора при смешении с лексическим поиском.
SEMANTIC_BLEND_WEIGHT = 0.35

# Служебные слова не помогают найти нужную часть, зато уводят поиск: «что»
# и «как» есть в каждом вопросе.
_STOPWORDS = frozenset(
    """
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы
    по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг
    ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом
    себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам
    чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому
    этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были
    куда зачем всех никогда можно при наконец два об другой хоть после над больше
    тот через эти нас про всего них какая много разве три эту моя впрочем хорошо
    свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно
    всю между это скажи расскажи пожалуйста запись записи
    """.split()
)

# Окончания, которые снимаются для сравнения слов. Это не морфология, а
# дешёвое приведение форм: «договорились» и «договоримся» должны совпасть.
_ENDINGS = (
    "ениями", "ениям", "ениях", "ования", "ованию", "ениях", "ается", "аются",
    "ились", "илась", "ились", "ований", "ениями",
    "ами", "ями", "ого", "его", "ему", "ыми", "ими", "ать", "ять", "ить", "еть",
    "ешь", "ишь", "ете", "ите", "ует", "уют", "ился", "илось", "ались",
    "ой", "ый", "ая", "яя", "ое", "ее", "ые", "ие", "ов", "ев", "ам", "ям",
    "ах", "ях", "ий", "ии", "ию", "ья", "ье", "ем", "ом", "ет", "ут", "ют",
    "ла", "ло", "ли", "ть", "ся", "ны", "на", "но", "ин", "ен",
    "а", "я", "о", "е", "ы", "и", "у", "ю", "ь",
)


def stamp(seconds: float) -> str:
    """Таймкод для показа и для ссылок в ответе."""

    total = max(0, int(round(float(seconds or 0))))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _parse_timecode(code: str) -> float | None:
    parts = str(code or "").split(":")
    try:
        if len(parts) == 2:
            minutes, seconds = int(parts[0]), int(parts[1])
            return float(minutes * 60 + seconds)
        if len(parts) == 3:
            hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
            return float(hours * 3600 + minutes * 60 + seconds)
    except ValueError:
        return None
    return None


def parse_timestamp(text: str) -> float | None:
    """Секунды из строки с таймкодом ``[MM:SS]`` или ``[H:MM:SS]``."""

    match = TIMESTAMP_RE.search(str(text or ""))
    if match is None:
        return None
    return _parse_timecode(match.group(1))


def iter_timestamps(text: str) -> list[tuple[int, int, float]]:
    """Все таймкоды в тексте: начало, конец и секунды."""

    out: list[tuple[int, int, float]] = []
    for match in TIMESTAMP_RE.finditer(text or ""):
        seconds = _parse_timecode(match.group(1))
        if seconds is not None:
            out.append((match.start(), match.end(), seconds))
    return out


def _looks_like_timestamp_label(label: str) -> bool:
    return _parse_timecode(label) is not None


def _segment_speaker(segment: dict) -> str:
    """Подпись говорящего из полей сегмента или префикса в тексте."""

    for key in ("speaker", "speaker_label"):
        value = str(segment.get(key) or "").strip()
        if value:
            return value
    role = segment.get("role")
    if role is not None:
        try:
            return default_speaker_label(int(role))
        except (TypeError, ValueError):
            pass
    text = str(segment.get("text") or "").strip()
    if text.startswith("[") and "]" in text:
        label, _rest = text[1:].split("]", 1)
        label = label.strip()
        if label and not _looks_like_timestamp_label(label):
            return label
    return ""


def _strip_speaker_prefix(text: str, speaker: str) -> str:
    body = str(text or "").strip()
    if not body.startswith("[") or "]" not in body:
        return body
    label, rest = body[1:].split("]", 1)
    label = label.strip()
    if not label or _looks_like_timestamp_label(label):
        return body
    if speaker and label != speaker:
        return body
    return rest.strip()


LineTuple = tuple[float, str] | tuple[float, str, str]


def normalize_line(line: LineTuple) -> tuple[float, str, str]:
    """Привести строку части к виду ``(время, текст, говорящий)``."""

    if len(line) == 2:
        return (float(line[0]), str(line[1]), "")
    return (float(line[0]), str(line[1]), str(line[2] if len(line) > 2 else ""))


def _stem(word: str) -> str:
    low = word.casefold().replace("ё", "е")
    for ending in _ENDINGS:
        if len(low) - len(ending) >= 4 and low.endswith(ending):
            return low[: -len(ending)]
    return low


def keywords_of(text: str, limit: int = 8) -> list[str]:
    """Самые частые значимые слова текста - для карты записи и поиска."""

    counts: dict[str, tuple[int, str]] = {}
    for match in _WORD.finditer(text or ""):
        word = match.group(0)
        low = word.casefold().replace("ё", "е")
        if len(low) < 4 or low in _STOPWORDS:
            continue
        stem = _stem(word)
        found = counts.get(stem)
        counts[stem] = (found[0] + 1 if found else 1, found[1] if found else low)
    ordered = sorted(counts.items(), key=lambda item: (-item[1][0], item[1][1]))
    return [value[1] for _, value in ordered[:limit]]


def _stems(text: str) -> list[str]:
    out: list[str] = []
    for match in _WORD.finditer(text or ""):
        word = match.group(0)
        low = word.casefold().replace("ё", "е")
        if len(low) < 3 or low in _STOPWORDS:
            continue
        out.append(_stem(word))
    return out


def budget_chars(context_tokens: int, share: float = CONTEXT_SHARE) -> int:
    """Сколько символов материала помещается в это окно контекста."""

    return max(600, int(context_tokens * share * CHARS_PER_TOKEN))


@dataclass(frozen=True)
class Chunk:
    """Часть записи: связный кусок фраз с таймкодами."""

    index: int
    start: float
    end: float
    lines: tuple[tuple[float, str, str], ...]
    segment_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(normalize_line(line) for line in self.lines)
        object.__setattr__(self, "lines", normalized)

    @property
    def text(self) -> str:
        return " ".join(line for _at, line, _speaker in self.lines)

    @property
    def has_speakers(self) -> bool:
        return any(speaker for _at, _line, speaker in self.lines)

    @property
    def stamped(self) -> str:
        """Текст части с таймкодом у каждой фразы: по нему модель ставит ссылки."""

        rows: list[str] = []
        for at, line, speaker in self.lines:
            prefix = f"[{stamp(at)}]"
            if speaker:
                rows.append(f"{prefix} {speaker}: {line}")
            else:
                rows.append(f"{prefix} {line}")
        return "\n".join(rows)

    @property
    def content_hash(self) -> str:
        payload_rows = [
            f"{at:.2f}|{speaker}|{line}" for at, line, speaker in self.lines
        ]
        payload = f"{self.start:.2f}|{self.end:.2f}|" + "\n".join(payload_rows)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]

    @property
    def span(self) -> str:
        return f"{stamp(self.start)}-{stamp(self.end)}"


@dataclass(frozen=True)
class Digest:
    """Выжимка одной части: то, из чего собирается карта записи."""

    index: int
    start: float
    end: float
    summary: str
    keywords: tuple[str, ...] = ()
    content_hash: str = ""

    @property
    def span(self) -> str:
        return f"{stamp(self.start)}-{stamp(self.end)}"

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "summary": self.summary,
            "keywords": list(self.keywords),
            "contentHash": self.content_hash,
            "span": self.span,
        }


def build_chunks(
    segments: Sequence[dict],
    target_seconds: float = CHUNK_TARGET_SECONDS,
    max_chars: int = CHUNK_MAX_CHARS,
) -> list[Chunk]:
    """Разрезать расшифровку на части по границам фраз.

    Фраза никогда не рвётся: часть заканчивается на готовом сегменте, поэтому
    таймкод в ответе всегда указывает на то, что действительно было сказано.
    """

    chunks: list[Chunk] = []
    lines: list[tuple[float, str, str]] = []
    ids: list[int] = []
    start = 0.0
    end = 0.0
    chars = 0
    for segment in segments:
        speaker = _segment_speaker(segment)
        text = _strip_speaker_prefix(str(segment.get("text") or "").strip(), speaker)
        if not text:
            continue
        try:
            at = float(segment.get("start") or 0.0)
            until = float(segment.get("end") or at)
        except (TypeError, ValueError):
            continue
        if not lines:
            start = at
        lines.append((at, text, speaker))
        chars += len(text) + 1
        end = max(end, until)
        identifier = segment.get("id")
        if isinstance(identifier, int):
            ids.append(identifier)
        if (end - start) >= target_seconds or chars >= max_chars:
            chunks.append(
                Chunk(
                    index=len(chunks),
                    start=start,
                    end=end,
                    lines=tuple(lines),
                    segment_ids=tuple(ids),
                )
            )
            lines, ids, chars = [], [], 0
    if lines:
        chunks.append(
            Chunk(
                index=len(chunks),
                start=start,
                end=end,
                lines=tuple(lines),
                segment_ids=tuple(ids),
            )
        )
    return chunks


def transcript_text(chunks: Sequence[Chunk]) -> str:
    return "\n".join(chunk.stamped for chunk in chunks)


def _hash_feature(stem: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(stem.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "little")
    return value % dim, 1.0 if value & 1 else -1.0


def embed_text(text: str, dim: int = 256) -> list[float]:
    """Лёгкий хеш-эмбеддинг стемов слов. Не нейросеть, только feature hashing."""

    vec = [0.0] * dim
    for stem in _stems(text):
        index, sign = _hash_feature(stem, dim)
        vec[index] += sign
    norm = math.sqrt(sum(value * value for value in vec))
    if norm <= 0.0:
        return vec
    return [value / norm for value in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))


def build_chunk_embeddings(
    chunks: Sequence[Chunk],
    dim: int = 256,
) -> dict[int, list[float]]:
    """Векторы частей для семантического поиска. Сохранение - задача контроллера."""

    return {chunk.index: embed_text(chunk.text, dim=dim) for chunk in chunks}


def ensure_embeddings(
    session_id: str,
    chunks: Sequence[Chunk],
    store_callback: Callable[[str, Sequence[Chunk]], dict[int, list[float]] | None]
    | None = None,
    dim: int = 256,
) -> dict[int, list[float]]:
    """Embeddings частей: из store_callback или считаются на месте."""

    if store_callback is not None and session_id:
        cached = store_callback(session_id, chunks)
        if cached is not None:
            return cached
    return build_chunk_embeddings(chunks, dim=dim)


def score_chunks_semantic(
    question: str,
    chunks: Sequence[Chunk],
    digests: Sequence[Digest] = (),
    embeddings: dict[int, list[float]] | None = None,
    dim: int = 256,
) -> list[tuple[int, float]]:
    """Семантический скор частей по косинусу хеш-эмбеддингов."""

    vectors = embeddings or build_chunk_embeddings(chunks, dim=dim)
    if not vectors:
        return []
    query = embed_text(question, dim=dim)
    digest_by_index = {item.index: item for item in digests}
    scored: list[tuple[int, float]] = []
    for chunk in chunks:
        vector = vectors.get(chunk.index)
        if vector is None:
            continue
        score = cosine(query, vector)
        digest = digest_by_index.get(chunk.index)
        if digest is not None:
            digest_vec = embed_text(
                " ".join((digest.summary, *digest.keywords)),
                dim=dim,
            )
            score += cosine(query, digest_vec) * 0.5
        if score > 0:
            scored.append((chunk.index, round(score, 4)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def _blend_chunk_scores(
    lexical: list[tuple[int, float, int]],
    semantic: list[tuple[int, float]],
    semantic_weight: float = SEMANTIC_BLEND_WEIGHT,
) -> list[tuple[int, float, int]]:
    if not semantic:
        return lexical
    lex_by_index = {index: (score, matched) for index, score, matched in lexical}
    sem_by_index = dict(semantic)
    max_lex = max((score for score, _matched in lex_by_index.values()), default=1.0) or 1.0
    max_sem = max(sem_by_index.values(), default=1.0) or 1.0
    blended: list[tuple[int, float, int]] = []
    for index in dict.fromkeys(
        [item[0] for item in lexical] + [item[0] for item in semantic]
    ):
        lex_score, matched = lex_by_index.get(index, (0.0, 0))
        sem_score = sem_by_index.get(index, 0.0)
        norm_lex = lex_score / max_lex
        norm_sem = sem_score / max_sem
        combined = (1.0 - semantic_weight) * norm_lex + semantic_weight * norm_sem
        if combined > 0:
            blended.append((index, round(combined * max(max_lex, max_sem), 3), matched))
    blended.sort(key=lambda item: (-item[1], item[0]))
    return blended


def score_chunks(
    question: str,
    chunks: Sequence[Chunk],
    digests: Sequence[Digest] = (),
    embeddings: dict[int, list[float]] | None = None,
    semantic_weight: float = SEMANTIC_BLEND_WEIGHT,
) -> list[tuple[int, float, int]]:
    """Кандидаты по словам вопроса: номер части, вес и сколько слов совпало.

    Дешёвый отбор перед моделью: он не понимает смысла, но надёжно находит
    названия, имена и числа - именно то, о чём чаще всего спрашивают. Число
    совпавших слов важно отдельно от веса: по нему решают, можно ли ответить
    сразу, не собирая карту всей записи. Выжимки участвуют с меньшим весом,
    потому что они короче и слова в них уже отобраны.
    """

    wanted = set(_stems(question))
    if not wanted:
        return []
    digest_by_index = {item.index: item for item in digests}
    scored: list[tuple[int, float, int]] = []
    for chunk in chunks:
        body = _stems(chunk.text)
        if not body:
            continue
        hits = sum(1 for stem in body if stem in wanted)
        matched = wanted.intersection(body)
        score = len(matched) * 2.0 + hits / max(1, len(body) / 40)
        digest = digest_by_index.get(chunk.index)
        if digest is not None:
            summary_stems = set(_stems(digest.summary)) | {_stem(word) for word in digest.keywords}
            score += len(wanted.intersection(summary_stems)) * 1.0
        if score > 0:
            scored.append((chunk.index, round(score, 3), len(matched)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    if embeddings:
        semantic = score_chunks_semantic(
            question,
            chunks,
            digests,
            embeddings=embeddings,
        )
        return _blend_chunk_scores(scored, semantic, semantic_weight=semantic_weight)
    return scored


def selective_hits(question: str, chunks: Sequence[Chunk]) -> list[int]:
    """Части, где встретилось редкое для этой записи слово из вопроса.

    Признак «слово вопроса звучало здесь и почти нигде больше» надёжнее, чем
    «совпало несколько слов»: в русском вопросе половина слов - формы общих
    слов, которые есть в каждой части. Редкое слово - это название, имя, число
    или тема, то есть именно то, о чём спрашивают.

    Пустой список значит «по словам ничего не выделяется»: тогда нужна карта
    записи, а не поиск.
    """

    wanted = set(_stems(question))
    if not wanted or not chunks:
        return []
    bodies = [set(_stems(chunk.text)) for chunk in chunks]
    limit = max(1, int(len(chunks) * SELECTIVE_SHARE))
    selective = {
        stem for stem in wanted if 0 < sum(1 for body in bodies if stem in body) <= limit
    }
    if not selective:
        return []
    scored: list[tuple[int, int]] = []
    for chunk, body in zip(chunks, bodies):
        hits = len(selective.intersection(body))
        if hits:
            scored.append((chunk.index, hits))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return [index for index, _hits in scored]


def outline_text(digests: Sequence[Digest]) -> str:
    """Карта записи для модели: номер части, таймкоды, о чём она."""

    rows: list[str] = []
    for digest in digests:
        keys = ", ".join(digest.keywords[:6])
        tail = f" Слова: {keys}." if keys else ""
        rows.append(f"Часть {digest.index + 1} ({digest.span}): {digest.summary}{tail}")
    return "\n".join(rows)


def parse_part_numbers(reply: str, limit: int) -> list[int]:
    """Номера частей из ответа модели, переведённые в индексы.

    Модель просят вернуть цифры, но она может добавить слова или обёртку
    JSON. Берутся все числа в допустимом диапазоне, порядок сохраняется.
    """

    out: list[int] = []
    for token in re.findall(r"\d+", reply or ""):
        try:
            number = int(token)
        except ValueError:
            continue
        index = number - 1
        if 0 <= index < limit and index not in out:
            out.append(index)
    return out


SYSTEM_CHAT = (
    "Ты помощник в программе для расшифровки речи. Отвечай по-русски, коротко и по делу, "
    "без вступлений и без списков там, где хватает двух фраз. Не выдумывай факты."
)

SYSTEM_MATERIAL = (
    "Ты помощник в программе для расшифровки речи. Ниже приложен текстовый файл. "
    "Отвечай по-русски, коротко и только по этому тексту. Не выдумывай факты, "
    "которых в файле нет."
)

SYSTEM_TITLE = (
    "Ты придумываешь короткие заголовки к расшифровкам речи. Ответь по-русски "
    "только заголовком из трёх-семи слов: без кавычек, без точки в конце, "
    "без пояснений и без слова «заголовок»."
)

SYSTEM_RECORD = (
    "Ты помощник по расшифровкам записей. Отвечай по-русски своими словами и только "
    "по тем выдержкам, которые тебе дали. Не цитируй выдержки построчно и не "
    "повторяй один и тот же факт дважды: нужен ответ, а не пересказ записи. "
    "Таймкод из квадратных скобок добавляй в конце утверждения, к которому он "
    "относится, например «смета выросла до 3,2 млн [01:12]». Если в выдержках "
    "указаны говорящие, связывай обещания, задачи и решения с ними - особенно "
    "когда спрашивают, кто что обещал или кому что поручили. Расшифровка речи "
    "бывает неточной: если слово выглядит искажённым, скажи об этом, а не "
    "додумывай. Если в выдержках ответа нет, ответь ровно словом "
    f"{NOT_FOUND_MARKER} и ничем больше."
)

ACTION_PROMPTS = {
    "summary": (
        "Составь связное краткое изложение записи: о чём разговор, что важно, чем закончилось. "
        "От трёх до восьми предложений, без списка."
    ),
    "keypoints": (
        "Выпиши главные мысли записи списком, каждая с таймкодом начала. "
        "Не больше восьми пунктов, каждый - одно предложение."
    ),
    "tasks": (
        "Выпиши договорённости, задачи и решения из записи: кто что должен сделать. "
        "Если в тексте указаны говорящие, называй их в каждом пункте. "
        "Каждый пункт с таймкодом. Если задач нет, скажи об этом одной фразой."
    ),
    "topics": (
        "Перечисли темы записи по порядку, каждую с таймкодом начала и одной фразой описания."
    ),
}


class DigestCache:
    """Память выжимок на время процесса. База подставляется контроллером."""

    def __init__(self) -> None:
        self._data: dict[str, dict[int, Digest]] = {}

    def load(self, session_id: str) -> dict[int, Digest]:
        return dict(self._data.get(session_id, {}))

    def save(self, session_id: str, digest: Digest) -> None:
        self._data.setdefault(session_id, {})[digest.index] = digest

    def clear(self, session_id: str) -> None:
        self._data.pop(session_id, None)


@dataclass
class Answer:
    """Ответ вместе со следом того, как он получен."""

    text: str
    mode: str = "full"
    opened: tuple[int, ...] = ()
    rounds: int = 1
    not_found: bool = False


@dataclass
class TranscriptAssistant:
    """Разбор расшифровки локальной моделью.

    ``respond`` получает список сообщений и возвращает готовый текст. Токены
    промежуточного ответа уходят в ``on_token``, если он передан; служебные
    шаги (выжимки, выбор частей) в интерфейс не текут.
    """

    respond: Callable[[list[dict], GenerationOptions, Callable[[str], None] | None], str]
    context_tokens: int = 8192
    digests: DigestCache | None = None
    on_stage: Callable[[str, dict], None] | None = None
    cancel: threading.Event | None = field(default=None)

    def __post_init__(self) -> None:
        if self.digests is None:
            self.digests = DigestCache()

    # -- служебное ---------------------------------------------------------

    def _stage(self, name: str, **payload) -> None:
        if self.on_stage is not None:
            self.on_stage(name, payload)

    def _stopped(self) -> bool:
        return self.cancel is not None and self.cancel.is_set()

    def _ask(self, system: str, user: str, options: GenerationOptions, on_token=None) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return self.respond(messages, options, on_token)

    @property
    def material_chars(self) -> int:
        return budget_chars(self.context_tokens)

    # -- карта записи ------------------------------------------------------

    def digest_chunk(self, chunk: Chunk) -> Digest:
        """Выжимка одной части. Ключевые слова берутся из текста, не у модели:
        их надёжнее посчитать, чем просить."""

        options = GenerationOptions(temperature=0.2, max_tokens=200)
        speaker_hint = (
            " В выдержке указаны говорящие - упоминай их, если это важно для смысла."
            if chunk.has_speakers
            else ""
        )
        prompt = (
            "Ниже кусок расшифровки записи. Опиши двумя-тремя предложениями, о чём здесь "
            f"говорят и что решили.{speaker_hint} Без вступления, без списка, только "
            f"описание.\n\n{chunk.stamped}"
        )
        summary = self._ask(SYSTEM_CHAT, prompt, options).strip()
        if not summary:
            # Модель промолчала: карта не должна остаться пустой, иначе часть
            # станет невидимой для поиска.
            summary = chunk.text[:200].strip()
        return Digest(
            index=chunk.index,
            start=chunk.start,
            end=chunk.end,
            summary=summary,
            keywords=tuple(keywords_of(chunk.text)),
            content_hash=chunk.content_hash,
        )

    def ensure_digests(self, session_id: str, chunks: Sequence[Chunk]) -> list[Digest]:
        """Выжимки для всех частей: из базы, а недостающие - считаются один раз.

        Правка расшифровки меняет ``content_hash`` части, и такая выжимка
        пересчитывается: иначе карта отвечала бы за текст, которого уже нет.
        """

        cached = self.digests.load(session_id) if session_id else {}
        result: list[Digest] = []
        missing = [
            chunk
            for chunk in chunks
            if (
                chunk.index not in cached
                or cached[chunk.index].content_hash != chunk.content_hash
            )
        ]
        if missing:
            self._stage("index_start", total=len(missing), chunks=len(chunks))
        done = 0
        for chunk in chunks:
            known = cached.get(chunk.index)
            if known is not None and known.content_hash == chunk.content_hash:
                result.append(known)
                continue
            if self._stopped():
                break
            digest = self.digest_chunk(chunk)
            if session_id:
                self.digests.save(session_id, digest)
            result.append(digest)
            done += 1
            self._stage("index_progress", done=done, total=len(missing))
        if missing:
            self._stage("index_done", done=done, total=len(missing))
        return result

    # -- изложение записи --------------------------------------------------

    def summarize(
        self,
        session_id: str,
        chunks: Sequence[Chunk],
        kind: str = "summary",
        on_token=None,
    ) -> Answer:
        """Готовое действие по всей записи: изложение, тезисы, задачи, темы."""

        task = ACTION_PROMPTS.get(kind, ACTION_PROMPTS["summary"])
        options = GenerationOptions(temperature=0.3, max_tokens=1100)
        whole = transcript_text(chunks)
        if len(whole) <= self.material_chars:
            self._stage("answer_start", mode="full", opened=len(chunks))
            text = self._ask(
                SYSTEM_RECORD,
                f"{task}\n\nРасшифровка записи:\n{whole}",
                options,
                on_token,
            )
            return Answer(text=text.strip(), mode="full", opened=tuple(range(len(chunks))))

        digests = self.ensure_digests(session_id, chunks)
        if self._stopped():
            return Answer(text="", mode="cancelled")
        material = self._fold_digests(digests, options)
        self._stage("answer_start", mode="outline", opened=len(digests))
        text = self._ask(
            SYSTEM_RECORD,
            f"{task}\n\nЗапись разобрана по частям, вот их содержание:\n{material}",
            options,
            on_token,
        )
        return Answer(
            text=text.strip(),
            mode="outline",
            opened=tuple(digest.index for digest in digests),
        )

    def _fold_digests(self, digests: Sequence[Digest], options: GenerationOptions) -> str:
        """Свернуть карту записи до размера, который влезает в контекст.

        У очень длинной записи даже перечень выжимок не помещается. Тогда
        выжимки собираются группами, каждая группа пересказывается одной, и
        так до тех пор, пока перечень не влезет. Уровни не бесконечны:
        каждый шаг сокращает список кратно, и на практике их не больше двух.
        """

        level = list(digests)
        budget = self.material_chars
        guard = 0
        while len("\n".join(f"Часть {d.index + 1} ({d.span}): {d.summary}" for d in level)) > budget:
            guard += 1
            if guard > 3 or len(level) <= 2:
                break
            groups: list[list[Digest]] = []
            current: list[Digest] = []
            size = 0
            for digest in level:
                piece = len(digest.summary) + 40
                if current and size + piece > budget:
                    groups.append(current)
                    current, size = [], 0
                current.append(digest)
                size += piece
            if current:
                groups.append(current)
            folded: list[Digest] = []
            self._stage("fold", groups=len(groups), level=guard)
            for group in groups:
                if self._stopped():
                    break
                body = "\n".join(f"({item.span}) {item.summary}" for item in group)
                prompt = (
                    "Ниже описания идущих подряд отрывков одной записи. Сожми их в одно "
                    "описание на три-четыре предложения, сохранив, о чём шла речь.\n\n" + body
                )
                summary = self._ask(SYSTEM_CHAT, prompt, options).strip()
                folded.append(
                    Digest(
                        index=group[0].index,
                        start=group[0].start,
                        end=group[-1].end,
                        summary=summary or group[0].summary,
                        keywords=group[0].keywords,
                    )
                )
            if not folded:
                break
            level = folded
        return outline_text(level)

    # -- вопрос по записи --------------------------------------------------

    def answer(
        self,
        question: str,
        session_id: str,
        chunks: Sequence[Chunk],
        history: Sequence[dict] = (),
        on_token=None,
        embeddings: dict[int, list[float]] | None = None,
    ) -> Answer:
        """Ответ на вопрос по записи с раскрытием нужных частей."""

        # Потолок вдвое ниже, чем у изложения: ответ на вопрос - несколько
        # предложений, а зацикленный пересказ на процессоре стоит минуты.
        options = GenerationOptions(temperature=0.3, max_tokens=600)
        whole = transcript_text(chunks)
        if len(whole) <= self.material_chars:
            self._stage("answer_start", mode="full", opened=len(chunks))
            text = self._ask(
                SYSTEM_RECORD,
                self._question_prompt(question, whole, history),
                options,
                on_token,
            )
            clean, missing = self._clean(text)
            return Answer(
                text=clean,
                mode="full",
                opened=tuple(range(len(chunks))),
                not_found=missing,
            )

        by_index = {chunk.index: chunk for chunk in chunks}
        # Первый заход - поиск по словам, без модели и без карты. Вопрос про
        # смету или про имя почти всегда содержит слово, которое звучало в
        # записи, и открыть три части по нему стоит миллисекунды. Карта частей
        # на записи в час стоит десятки запросов к модели, и платить за неё
        # ради «что решили по смете» незачем.
        strong = selective_hits(question, chunks)[:MAX_OPENED_CHUNKS]
        # Очередь заходов. Первый - найденное по словам; если ответа там нет,
        # следующие идут по карте: сначала выбранное моделью, потом остальная
        # запись. Тиры разделены, иначе один заход открыл бы всю запись сразу
        # и смысл карты пропал бы.
        pending: list[list[int]] = [strong] if strong else []
        mode = "search" if strong else "outline"
        mapped = False
        digests: list[Digest] = []

        used: list[int] = []
        answer_text = ""
        missing = False
        rounds = 0
        while rounds < MAX_ROUNDS and not self._stopped():
            rounds += 1
            if not pending and not mapped:
                # Слов не хватило или по ним ответа не нашлось: теперь нужна
                # карта записи, и часть выбирает сама модель.
                digests = self.ensure_digests(session_id, chunks)
                if self._stopped():
                    return Answer(text="", mode="cancelled")
                picked = self._pick_parts(question, digests)
                lexical = [
                    index
                    for index, _score, _matched in score_chunks(
                        question,
                        chunks,
                        digests,
                        embeddings=embeddings,
                    )
                ]
                chosen = [
                    index
                    for index in dict.fromkeys(picked + lexical)
                    if index in by_index and index not in used
                ]
                rest = [
                    chunk.index
                    for chunk in chunks
                    if chunk.index not in chosen and chunk.index not in used
                ]
                pending = [tier for tier in (chosen, rest) if tier]
                mode = "outline"
                mapped = True
            batch: list[int] = []
            while pending and not batch:
                batch = [index for index in pending.pop(0) if index not in used][:MAX_OPENED_CHUNKS]
            if not batch:
                break
            opened = self._expand(batch, by_index, used)
            used.extend(index for index in opened if index not in used)
            material = "\n\n".join(
                f"Часть {by_index[index].index + 1} ({by_index[index].span}):\n"
                f"{by_index[index].stamped}"
                for index in opened
            )
            self._stage("answer_start", mode=mode, opened=len(opened), round=rounds)
            # Поток в интерфейс идёт только на последнем заходе: иначе
            # пользователь увидит служебное слово «нет в записи» как ответ.
            last = rounds >= MAX_ROUNDS or len(used) >= len(chunks)
            text = self._ask(
                SYSTEM_RECORD,
                self._question_prompt(question, material, history),
                options,
                on_token if last else None,
            )
            answer_text, missing = self._clean(text)
            if not missing:
                break
            if last:
                break
        return Answer(
            text=answer_text,
            mode=mode,
            opened=tuple(used),
            rounds=rounds,
            not_found=missing,
        )

    def _pick_parts(self, question: str, digests: Sequence[Digest]) -> list[int]:
        """Спросить модель, какие части записи открыть под этот вопрос."""

        if not digests:
            return []
        self._stage("select_start", parts=len(digests))
        prompt = (
            "Ниже карта записи: номер части, её время и о чём она.\n\n"
            f"{outline_text(digests)}\n\n"
            f"Вопрос: {question}\n\n"
            f"Назови номера частей, которые нужно прочитать целиком, чтобы ответить. "
            f"Не больше {MAX_OPENED_CHUNKS}, только цифры через запятую, в порядке важности."
        )
        reply = self._ask(SYSTEM_CHAT, prompt, GenerationOptions(temperature=0.1, max_tokens=80))
        return parse_part_numbers(reply, len(digests))

    def _expand(
        self,
        batch: Sequence[int],
        by_index: dict[int, Chunk],
        used: Sequence[int],
    ) -> list[int]:
        """Добавить соседние части, если остаётся место.

        Мысль часто начинается в предыдущей части и кончается в следующей:
        сосед снимает обрыв на границе, из-за которого ответ теряет причину
        или итог сказанного.
        """

        chosen = list(dict.fromkeys(batch))
        room = self.material_chars - sum(len(by_index[index].stamped) for index in chosen)
        for index in list(chosen):
            for neighbour in (index - 1, index + 1):
                if neighbour not in by_index or neighbour in chosen or neighbour in used:
                    continue
                size = len(by_index[neighbour].stamped)
                if size > room:
                    continue
                chosen.append(neighbour)
                room -= size
        return sorted(chosen)

    def _question_prompt(self, question: str, material: str, history: Sequence[dict]) -> str:
        parts: list[str] = []
        talk = _recent_history(history)
        if talk:
            parts.append("Предыдущий разговор:\n" + talk)
        parts.append("Выдержки из записи:\n" + material)
        parts.append(
            f"Вопрос: {question}\n"
            "Ответь кратко, одним-тремя предложениями, своими словами."
        )
        return "\n\n".join(parts)

    def _clean(self, text: str) -> tuple[str, bool]:
        body = (text or "").strip()
        if _NOT_FOUND_MARKER_RE.search(body):
            leftover = _NOT_FOUND_MARKER_RE.sub("", body).strip(" .\n\t-")
            # Если весь ответ был служебным словом, показать нужно фразу, а не
            # пустой пузырь: пользователь спросил и заслуживает ответа.
            return (leftover or NOT_FOUND_REPLY, True)
        # Модель часто отвечает «нет в записи» своими словами вместо служебного
        # слова. Проверено на этой машине: на вопрос о том, чего в записи нет,
        # Qwen3 отвечает «Нет в записи.». Без такого разбора второй заход по
        # остальным частям не начинался бы, и ответ терялся бы там, где он есть.
        if len(body) <= NOT_FOUND_PARAPHRASE_LIMIT and _NOT_FOUND_PARAPHRASE.search(body):
            return (body, True)
        return (body, False)

    # -- свободный чат -----------------------------------------------------

    def chat(
        self,
        question: str,
        history: Sequence[dict] = (),
        on_token=None,
        material: str = "",
        material_name: str = "",
    ) -> Answer:
        """Разговор без записи: обычный чат-бот на той же модели.

        ``material`` - текст прикреплённого файла. Он и вопрос идут одним
        user-ходом: у Gemma два user подряд ломают chat-шаблон.
        """

        body = (material or "").strip()
        name = (material_name or "файл").strip() or "файл"
        if body:
            messages: list[dict] = [{"role": "system", "content": SYSTEM_MATERIAL}]
            messages.extend(_history_messages(history))
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Прикреплённый файл «{name}»:\n\n{body}\n\n"
                        f"Вопрос: {question}"
                    ),
                }
            )
        else:
            messages = [{"role": "system", "content": SYSTEM_CHAT}]
            messages.extend(_history_messages(history))
            messages.append({"role": "user", "content": question})
        options = GenerationOptions(temperature=0.5, max_tokens=900)
        text = self.respond(messages, options, on_token)
        return Answer(text=text.strip(), mode="chat")


def _history_messages(history: Sequence[dict], limit: int = 8) -> list[dict]:
    """Последние реплики в виде сообщений для модели.

    Текст вложения хранится в ``meta.attachment`` и подмешивается здесь, чтобы
    в пузыре на экране оставался только вопрос пользователя.
    """

    out: list[dict] = []
    for item in list(history)[-limit:]:
        role = str(item.get("role") or "")
        content = _message_content_for_model(item)
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


def _message_content_for_model(item: dict) -> str:
    content = str(item.get("content") or "").strip()
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    attachment = meta.get("attachment") if isinstance(meta, dict) else None
    if not isinstance(attachment, dict):
        return content
    body = str(attachment.get("text") or "").strip()
    if not body:
        return content
    name = str(attachment.get("name") or "файл").strip() or "файл"
    prefix = f"Прикреплённый файл «{name}»:\n\n{body}"
    return f"{prefix}\n\n{content}" if content else prefix


def _recent_history(history: Sequence[dict], limit: int = 4, chars: int = 700) -> str:
    """Короткая выжимка переписки для вопроса по записи.

    Полная переписка вытеснила бы выдержки из записи, а без неё «а когда это
    было?» теряет смысл. Поэтому берутся последние реплики и обрезаются.
    """

    rows: list[str] = []
    for item in list(history)[-limit:]:
        role = "Вы" if item.get("role") == "user" else "Помощник"
        content = _message_content_for_model(item).strip()
        if content:
            rows.append(f"{role}: {content[:chars]}")
    return "\n".join(rows)


def record_from_session(session: dict) -> dict:
    """Сжатая карточка записи для интерфейса ассистента."""

    segments: Iterable[dict] = session.get("segments") or ()
    chunks = build_chunks(list(segments))
    duration = max((chunk.end for chunk in chunks), default=0.0)
    card = {
        "id": session.get("id", ""),
        "title": session.get("title", ""),
        "mode": session.get("mode", ""),
        "createdAt": session.get("created_at", ""),
        "duration": duration,
        "durationLabel": stamp(duration),
        "chunks": len(chunks),
        "segments": len(chunks and [line for chunk in chunks for line in chunk.lines] or []),
    }
    card.update(
        list_item_from_row(
            {
                **session,
                "text": " ".join(
                    str(segment.get("text") or "") for segment in segments
                ),
                "segment_count": card["segments"],
                "chat_count": int(session.get("chat_count") or 0),
            }
        )
    )
    return card


MODE_LABELS_RU = {
    "dictation": "Диктовка",
    "live": "Live",
    "media": "Медиа",
    "monitor": "Эфир",
    "transcript": "Транскрибация",
    "chat": "Чат",
}

# Типовые имена источников и режимов: в списке они не различимы.
GENERIC_TITLES = frozenset(
    {
        "Микрофон",
        "Звук компьютера",
        "Микрофон и звук компьютера",
        "Диктовка",
        "Живые субтитры",
        "Мониторинг эфира",
        "Эфир",
    }
)


def is_generic_title(title: str) -> bool:
    cleaned = " ".join(str(title or "").split())
    return not cleaned or cleaned in GENERIC_TITLES


def title_from_transcript(segments: Sequence[dict] | str, max_words: int = 7) -> str:
    """Короткий заголовок из начала расшифровки без модели."""

    if isinstance(segments, str):
        raw = segments
    else:
        parts: list[str] = []
        for segment in segments or ():
            text = str(segment.get("text") or "").strip()
            if text.startswith("[") and "]" in text:
                text = text.split("]", 1)[1].strip()
            if text:
                parts.append(text)
            if sum(len(part) for part in parts) > 240:
                break
        raw = " ".join(parts)
    words = [word for word in raw.replace("\n", " ").split() if word]
    if not words:
        return ""
    phrase = " ".join(words[:max_words]).strip(" .,;:!?-")
    if len(words) > max_words:
        phrase = phrase.rstrip(".,;:") + "…"
    return phrase


def format_session_when(created_at: str) -> str:
    """Короткая дата для списка: день и время без секунд."""

    raw = str(created_at or "").strip()
    if not raw:
        return ""
    try:
        # Хранится UTC ISO; для подписи достаточно среза без зоны.
        stamp_raw = raw.replace("Z", "+00:00")
        moment = datetime.fromisoformat(stamp_raw)
        if moment.tzinfo is not None:
            moment = moment.astimezone().replace(tzinfo=None)
        return f"{moment.day:02d}.{moment.month:02d} {moment.hour:02d}:{moment.minute:02d}"
    except ValueError:
        return raw[:16].replace("T", " ")


def list_item_from_row(row: dict) -> dict:
    """Карточка записи/чата для левой колонки ассистента."""

    title = str(row.get("title") or "").strip()
    mode = str(row.get("mode") or "")
    mode_label = MODE_LABELS_RU.get(mode, mode or "Запись")
    when = format_session_when(str(row.get("created_at") or ""))
    preview = " ".join(str(row.get("text") or "").split())
    if preview.startswith("[") and "]" in preview:
        preview = preview.split("]", 1)[1].strip()
    snippet = title_from_transcript(preview, max_words=8)
    generic = is_generic_title(title)
    pinned = bool(int(row.get("pinned") or 0))
    if generic and snippet:
        display = snippet
    elif title:
        display = title
    else:
        display = f"{mode_label}" + (f" · {when}" if when else "")
    if pinned and not display.startswith("★"):
        display = f"★ {display}"
    subtitle_parts = [mode_label]
    if when:
        subtitle_parts.append(when)
    segments = int(row.get("segment_count") or 0)
    if segments:
        subtitle_parts.append(f"{segments} фраз")
    chat_count = int(row.get("chat_count") or 0)
    if mode == "chat" and chat_count:
        subtitle_parts.append(f"{chat_count} сообщ.")
    return {
        "id": row.get("id", ""),
        "title": title,
        "displayTitle": display,
        "subtitle": " · ".join(subtitle_parts),
        "mode": mode,
        "createdAt": row.get("created_at", ""),
        "segments": segments,
        "preview": (snippet or preview)[:160],
        "needsTitle": generic and mode != "chat",
        "chatCount": chat_count,
        "pinned": pinned,
    }


def clean_suggested_title(text: str) -> str:
    """Убрать кавычки и хвост, который модель иногда дописывает."""

    cleaned = " ".join(str(text or "").strip().split())
    cleaned = cleaned.strip(" «»\"'`")
    for separator in ("\n", ".", ";", " - ", " — "):
        if separator in cleaned:
            cleaned = cleaned.split(separator, 1)[0].strip()
    return cleaned[:80].strip(" .,;:«»\"'`")


def suggest_title_messages(excerpt: str) -> list[dict]:
    body = " ".join(str(excerpt or "").split())
    if len(body) > 1800:
        body = body[:1800].rsplit(" ", 1)[0] + "…"
    return [
        {"role": "system", "content": SYSTEM_TITLE},
        {
            "role": "user",
            "content": (
                "По этой расшифровке придумай заголовок записи.\n\n"
                f"{body or 'Пустая запись.'}"
            ),
        },
    ]

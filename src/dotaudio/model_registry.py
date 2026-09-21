"""Bounded registry and validation for local translation models.

The registry is deliberately data-only.  A record can describe a local
CTranslate2 model and its tokenizers, but it cannot contain Python modules,
commands, callbacks, or any other executable entry point.  Loading a registry
only parses JSON and checks files on disk; it never imports model code.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotaudio.modelhub import UnsafeModelPath, safe_join

REGISTRY_VERSION = 1
DEFAULT_REGISTRY_FILENAME = "models.json"
MAX_REGISTRY_MODELS = 128
MAX_MODEL_ID_LENGTH = 64
MAX_LABEL_LENGTH = 160
MAX_DESCRIPTION_LENGTH = 4_000

MODEL_BACKEND_CTRANSLATE2 = "ctranslate2"
MODEL_KIND_TRANSLATION = "translation"

_MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$")
_RELATIVE_NAME_RE = re.compile(r"^[^\x00]+$")
_DESCRIPTOR_FIELDS = frozenset(
    {
        "id",
        "model_id",
        "label",
        "path",
        "kind",
        "backend",
        "source_language",
        "target_language",
        "source",
        "target",
        "source_tokenizer",
        "target_tokenizer",
        "description",
        "license",
        "homepage",
        "revision",
        "size_bytes",
        "metadata",
    }
)


class ModelValidationError(ValueError):
    """A model or registry record cannot be used safely."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_model",
        path: Path | None = None,
        problems: Iterable[str] = (),
    ) -> None:
        self.code = code
        self.path = Path(path) if path is not None else None
        self.problems = tuple(str(problem) for problem in problems if str(problem).strip())
        detail = "; ".join(self.problems)
        rendered = f"{message}: {detail}" if detail else message
        super().__init__(rendered)


@dataclass(frozen=True, slots=True)
class ModelValidationReport:
    """Machine-readable result of a local CTranslate2 validation pass."""

    path: Path
    valid: bool
    files: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    size_bytes: int = 0
    backend: str = MODEL_BACKEND_CTRANSLATE2

    @property
    def ok(self) -> bool:
        return self.valid

    def __bool__(self) -> bool:
        return self.valid

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "valid": self.valid,
            "ready": self.valid,
            "files": list(self.files),
            "errors": list(self.errors),
            "size_bytes": self.size_bytes,
            "backend": self.backend,
        }

    def raise_for_error(self) -> None:
        if not self.valid:
            raise ModelValidationError(
                "Локальная модель не прошла проверку CTranslate2",
                code="invalid_ctranslate2_model",
                path=self.path,
                problems=self.errors,
            )


def normalize_language_code(value: object) -> str:
    """Return a bounded language tag suitable for a translation pair."""

    code = str(value or "").strip().lower().replace("_", "-")
    if not _LANGUAGE_RE.fullmatch(code):
        raise ModelValidationError(
            f"Некорректный код языка: {value!r}",
            code="invalid_language",
            problems=("Ожидался код из 2–3 букв, например en, ru или zh-Hans",),
        )
    return code


def normalize_model_id(value: object) -> str:
    """Validate the identifier used in a registry, path, and UI payload."""

    model_id = str(value or "").strip().lower()
    if len(model_id) > MAX_MODEL_ID_LENGTH or not _MODEL_ID_RE.fullmatch(model_id):
        raise ModelValidationError(
            f"Некорректный идентификатор модели: {value!r}",
            code="invalid_model_id",
            problems=(
                "Используйте до 64 символов: латинские буквы, цифры, точка, дефис или подчёркивание",
            ),
        )
    return model_id


def _relative_file_name(value: object, field_name: str) -> str:
    name = str(value or "").strip()
    if not name or not _RELATIVE_NAME_RE.fullmatch(name):
        raise ModelValidationError(
            f"Некорректное имя {field_name}",
            code="invalid_model_path",
            problems=("Имя файла должно быть непустым относительным путём без NUL",),
        )
    try:
        # This rejects absolute paths, ``..`` traversal, drive prefixes, and
        # symlinked parents when the model directory is checked later.
        safe_join(Path("."), name, label=field_name)
    except UnsafeModelPath as exc:
        raise ModelValidationError(
            f"Небезопасное имя {field_name}",
            code="unsafe_model_path",
            problems=(str(exc),),
        ) from exc
    return name.replace("\\", "/")


def _json_metadata(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ModelValidationError(
            "Поле metadata должно быть JSON-объектом",
            code="invalid_metadata",
        )
    metadata = dict(value)
    try:
        encoded = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ModelValidationError(
            "Поле metadata содержит не-JSON значение",
            code="invalid_metadata",
        ) from exc
    if len(encoded) > MAX_DESCRIPTION_LENGTH:
        raise ModelValidationError(
            "Поле metadata слишком большое",
            code="metadata_too_large",
            problems=(f"Лимит: {MAX_DESCRIPTION_LENGTH} символов",),
        )
    return metadata


def _regular_file(model_dir: Path, relative: str, errors: list[str]) -> tuple[Path | None, int]:
    try:
        candidate = safe_join(model_dir, relative, label="файл модели")
    except UnsafeModelPath as exc:
        errors.append(str(exc))
        return None, 0
    if candidate.is_symlink():
        errors.append(f"{relative}: символические ссылки запрещены")
        return None, 0
    if not candidate.is_file():
        errors.append(f"{relative}: файл не найден")
        return None, 0
    try:
        return candidate, candidate.stat().st_size
    except OSError as exc:
        errors.append(f"{relative}: не удалось прочитать размер файла ({exc})")
        return None, 0


def validate_ctranslate2_model(
    path: Path,
    *,
    source_tokenizer: str = "source.spm",
    target_tokenizer: str = "target.spm",
    require_tokenizers: bool = False,
) -> ModelValidationReport:
    """Inspect a local CTranslate2 directory without importing or executing it.

    A generic CTranslate2 directory must contain a non-empty ``model.bin`` and
    a JSON ``config.json``.  Translation models additionally need the two
    SentencePiece files used by :class:`dotaudio.translate.Translator`.
    """

    raw_path = Path(path).expanduser()
    try:
        model_dir = raw_path.resolve(strict=False)
    except OSError as exc:
        return ModelValidationReport(raw_path, False, errors=(f"не удалось открыть путь: {exc}",))

    errors: list[str] = []
    files: list[str] = []
    size_bytes = 0
    if raw_path.is_symlink():
        errors.append("каталог модели не должен быть символической ссылкой")
    if not model_dir.is_dir():
        errors.append("каталог модели не найден")

    model_file, model_size = _regular_file(model_dir, "model.bin", errors)
    if model_file is not None:
        files.append("model.bin")
        if model_size <= 0:
            errors.append("model.bin: файл пустой")
        size_bytes += model_size

    config_file, config_size = _regular_file(model_dir, "config.json", errors)
    if config_file is not None:
        files.append("config.json")
        size_bytes += config_size
        try:
            with config_file.open("r", encoding="utf-8") as handle:
                config = json.load(handle)
            if not isinstance(config, dict):
                errors.append("config.json: корнем должен быть JSON-объект")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"config.json: некорректный JSON ({exc})")

    if require_tokenizers:
        for name, label in (
            (source_tokenizer, "source_tokenizer"),
            (target_tokenizer, "target_tokenizer"),
        ):
            try:
                relative = _relative_file_name(name, label)
            except ModelValidationError as exc:
                errors.extend(exc.problems or (str(exc),))
                continue
            tokenizer_file, tokenizer_size = _regular_file(model_dir, relative, errors)
            if tokenizer_file is not None:
                files.append(relative)
                size_bytes += tokenizer_size

    return ModelValidationReport(
        path=model_dir,
        valid=not errors,
        files=tuple(files),
        errors=tuple(errors),
        size_bytes=size_bytes,
    )


def require_ctranslate2_model(
    path: Path,
    *,
    source_tokenizer: str = "source.spm",
    target_tokenizer: str = "target.spm",
    require_tokenizers: bool = False,
) -> ModelValidationReport:
    report = validate_ctranslate2_model(
        path,
        source_tokenizer=source_tokenizer,
        target_tokenizer=target_tokenizer,
        require_tokenizers=require_tokenizers,
    )
    report.raise_for_error()
    return report


# Short aliases make the validation entry point easy to discover without
# creating a second implementation.
validate_ct2_model = validate_ctranslate2_model
require_ct2_model = require_ctranslate2_model


@dataclass(frozen=True, slots=True)
class TranslationPair:
    source: str
    target: str
    model_id: str
    label: str
    builtin: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", normalize_language_code(self.source))
        object.__setattr__(self, "target", normalize_language_code(self.target))
        object.__setattr__(self, "model_id", normalize_model_id(self.model_id))
        label = str(self.label or "").strip() or self.model_id
        if len(label) > MAX_LABEL_LENGTH:
            raise ModelValidationError(
                "Название пары перевода слишком длинное",
                code="label_too_long",
            )
        object.__setattr__(self, "label", label)

    @property
    def code(self) -> str:
        return f"{self.source}-{self.target}"


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    """A data-only description of one local translation model."""

    id: str
    label: str
    path: Path
    source_language: str
    target_language: str
    backend: str = MODEL_BACKEND_CTRANSLATE2
    kind: str = MODEL_KIND_TRANSLATION
    source_tokenizer: str = "source.spm"
    target_tokenizer: str = "target.spm"
    description: str = ""
    license: str = ""
    homepage: str = ""
    revision: str = ""
    size_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        model_id = normalize_model_id(self.id)
        source = normalize_language_code(self.source_language)
        target = normalize_language_code(self.target_language)
        if source == target:
            raise ModelValidationError(
                "Исходный и целевой языки должны различаться",
                code="invalid_language_pair",
            )
        if self.backend != MODEL_BACKEND_CTRANSLATE2:
            raise ModelValidationError(
                f"Backend {self.backend!r} не поддерживается",
                code="unsupported_backend",
                problems=("Поддерживается только ctranslate2 без запуска внешнего кода",),
            )
        if self.kind != MODEL_KIND_TRANSLATION:
            raise ModelValidationError(
                f"Тип модели {self.kind!r} не поддерживается",
                code="unsupported_model_kind",
                problems=("В этом bounded-треке поддерживаются только translation-модели",),
            )
        try:
            model_path = Path(self.path).expanduser().resolve(strict=False)
        except OSError as exc:
            raise ModelValidationError(
                "Не удалось нормализовать путь модели",
                code="invalid_model_path",
            ) from exc
        label = str(self.label or "").strip() or model_id
        description = str(self.description or "").strip()
        if len(label) > MAX_LABEL_LENGTH:
            raise ModelValidationError("Название модели слишком длинное", code="label_too_long")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise ModelValidationError(
                "Описание модели слишком длинное",
                code="description_too_long",
            )
        if self.size_bytes is not None:
            try:
                size_bytes = int(self.size_bytes)
            except (TypeError, ValueError) as exc:
                raise ModelValidationError("size_bytes должен быть целым числом", code="invalid_size") from exc
            if size_bytes < 0:
                raise ModelValidationError("size_bytes не может быть отрицательным", code="invalid_size")
        else:
            size_bytes = None
        source_tokenizer = _relative_file_name(self.source_tokenizer, "source_tokenizer")
        target_tokenizer = _relative_file_name(self.target_tokenizer, "target_tokenizer")
        metadata = _json_metadata(self.metadata)

        object.__setattr__(self, "id", model_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "path", model_path)
        object.__setattr__(self, "source_language", source)
        object.__setattr__(self, "target_language", target)
        object.__setattr__(self, "source_tokenizer", source_tokenizer)
        object.__setattr__(self, "target_tokenizer", target_tokenizer)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "license", str(self.license or "").strip())
        object.__setattr__(self, "homepage", str(self.homepage or "").strip())
        object.__setattr__(self, "revision", str(self.revision or "").strip())
        object.__setattr__(self, "size_bytes", size_bytes)
        object.__setattr__(self, "metadata", metadata)

    @property
    def pair(self) -> TranslationPair:
        return TranslationPair(
            self.source_language,
            self.target_language,
            self.id,
            self.label,
        )

    def tokenizer_path(self, which: str) -> Path:
        name = self.source_tokenizer if which == "source" else self.target_tokenizer
        return safe_join(self.path, name, label=f"{which}_tokenizer")

    def validate(self) -> ModelValidationReport:
        return validate_ctranslate2_model(
            self.path,
            source_tokenizer=self.source_tokenizer,
            target_tokenizer=self.target_tokenizer,
            require_tokenizers=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "path": str(self.path),
            "kind": self.kind,
            "backend": self.backend,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "source_tokenizer": self.source_tokenizer,
            "target_tokenizer": self.target_tokenizer,
            "description": self.description,
            "license": self.license,
            "homepage": self.homepage,
            "revision": self.revision,
            "size_bytes": self.size_bytes,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ModelDescriptor":
        if not isinstance(raw, Mapping):
            raise ModelValidationError("Запись модели должна быть JSON-объектом", code="invalid_record")
        unknown = sorted(set(raw) - _DESCRIPTOR_FIELDS)
        if unknown:
            raise ModelValidationError(
                "В записи модели есть неподдерживаемые поля",
                code="unsupported_record_field",
                problems=(", ".join(unknown),),
            )
        model_id = raw.get("id", raw.get("model_id", ""))
        source = raw.get("source_language", raw.get("source", ""))
        target = raw.get("target_language", raw.get("target", ""))
        return cls(
            id=model_id,
            label=str(raw.get("label") or model_id),
            path=Path(str(raw.get("path") or "")),
            kind=str(raw.get("kind") or MODEL_KIND_TRANSLATION),
            backend=str(raw.get("backend") or MODEL_BACKEND_CTRANSLATE2),
            source_language=source,
            target_language=target,
            source_tokenizer=str(raw.get("source_tokenizer") or "source.spm"),
            target_tokenizer=str(raw.get("target_tokenizer") or "target.spm"),
            description=str(raw.get("description") or ""),
            license=str(raw.get("license") or ""),
            homepage=str(raw.get("homepage") or ""),
            revision=str(raw.get("revision") or ""),
            size_bytes=raw.get("size_bytes"),
            metadata=raw.get("metadata") or {},
        )


class ModelRegistry:
    """Persistent bounded registry for user-selected local models."""

    def __init__(
        self,
        root: Path,
        *,
        filename: str = DEFAULT_REGISTRY_FILENAME,
        max_models: int = MAX_REGISTRY_MODELS,
        load: bool = True,
    ) -> None:
        if not 1 <= int(max_models) <= MAX_REGISTRY_MODELS:
            raise ValueError(f"max_models должен быть от 1 до {MAX_REGISTRY_MODELS}")
        self.root = Path(root).expanduser().resolve(strict=False)
        self.max_models = int(max_models)
        try:
            self.path = safe_join(self.root, filename, label="реестр моделей")
        except UnsafeModelPath as exc:
            raise ModelValidationError("Небезопасный путь реестра", code="unsafe_registry_path") from exc
        self._models: dict[str, ModelDescriptor] = {}
        if load and self.path.is_file():
            self._load()

    def _load(self) -> None:
        if self.path.is_symlink():
            raise ModelValidationError(
                "Файл реестра не должен быть символической ссылкой",
                code="unsafe_registry_path",
                path=self.path,
            )
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ModelValidationError(
                "Не удалось прочитать реестр моделей",
                code="invalid_registry",
                path=self.path,
                problems=(str(exc),),
            ) from exc
        if isinstance(payload, list):
            version = REGISTRY_VERSION
            records = payload
        elif isinstance(payload, dict):
            version = payload.get("version", REGISTRY_VERSION)
            records = payload.get("models", [])
        else:
            raise ModelValidationError("Реестр должен быть JSON-объектом", code="invalid_registry")
        if version != REGISTRY_VERSION:
            raise ModelValidationError(
                f"Версия реестра {version!r} не поддерживается",
                code="unsupported_registry_version",
            )
        if not isinstance(records, list):
            raise ModelValidationError("Поле models должно быть массивом", code="invalid_registry")
        if len(records) > self.max_models:
            raise ModelValidationError(
                "В реестре слишком много моделей",
                code="registry_limit",
                problems=(f"Лимит: {self.max_models}",),
            )
        loaded: dict[str, ModelDescriptor] = {}
        problems: list[str] = []
        for index, record in enumerate(records):
            try:
                descriptor = ModelDescriptor.from_dict(record)
                if descriptor.id in loaded:
                    raise ModelValidationError(
                        f"Дублирующийся идентификатор модели: {descriptor.id}",
                        code="duplicate_model_id",
                    )
                loaded[descriptor.id] = descriptor
            except ModelValidationError as exc:
                problems.append(f"models[{index}]: {exc}")
        if problems:
            raise ModelValidationError(
                "Реестр содержит некорректные записи",
                code="invalid_registry",
                path=self.path,
                problems=problems,
            )
        self._models = loaded

    def save(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ModelValidationError(
                "Файл реестра не должен быть символической ссылкой",
                code="unsafe_registry_path",
                path=self.path,
            )
        temporary = self.path.with_name(f"{self.path.name}.part")
        if temporary.is_symlink():
            raise ModelValidationError(
                "Временный файл реестра не должен быть символической ссылкой",
                code="unsafe_registry_path",
                path=temporary,
            )
        payload = {
            "version": REGISTRY_VERSION,
            "models": [descriptor.to_dict() for descriptor in self._models.values()],
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return self.path

    def add(self, descriptor: ModelDescriptor, *, validate: bool = True, persist: bool = True) -> ModelDescriptor:
        if not isinstance(descriptor, ModelDescriptor):
            raise TypeError("descriptor должен быть ModelDescriptor")
        if descriptor.id not in self._models and len(self._models) >= self.max_models:
            raise ModelValidationError(
                "Достигнут лимит пользовательских моделей",
                code="registry_limit",
                problems=(f"Лимит: {self.max_models}",),
            )
        if validate:
            descriptor.validate().raise_for_error()
        self._models[descriptor.id] = descriptor
        if persist:
            self.save()
        return descriptor

    register = add

    def register_local(
        self,
        path: Path,
        *,
        model_id: str,
        source_language: str,
        target_language: str,
        label: str = "",
        source_tokenizer: str = "source.spm",
        target_tokenizer: str = "target.spm",
        description: str = "",
        license: str = "",
        homepage: str = "",
        revision: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> ModelDescriptor:
        descriptor = ModelDescriptor(
            id=model_id,
            label=label,
            path=Path(path),
            source_language=source_language,
            target_language=target_language,
            source_tokenizer=source_tokenizer,
            target_tokenizer=target_tokenizer,
            description=description,
            license=license,
            homepage=homepage,
            revision=revision,
            metadata=dict(metadata or {}),
        )
        descriptor.validate().raise_for_error()
        self.add(descriptor, validate=False, persist=True)
        return descriptor

    def get(self, model_id: object) -> ModelDescriptor | None:
        try:
            key = normalize_model_id(model_id)
        except ModelValidationError:
            return None
        return self._models.get(key)

    def require(self, model_id: object) -> ModelDescriptor:
        descriptor = self.get(model_id)
        if descriptor is None:
            raise ModelValidationError(
                f"Модель {model_id!r} не зарегистрирована",
                code="model_not_found",
            )
        return descriptor

    def validate(self, model_id: object) -> ModelValidationReport:
        return self.require(model_id).validate()

    def list(self) -> tuple[ModelDescriptor, ...]:
        return tuple(self._models.values())

    models = list

    def pairs(self) -> tuple[TranslationPair, ...]:
        return tuple(descriptor.pair for descriptor in self._models.values())

    translation_pairs = pairs

    def resolve_pair(
        self,
        source: object,
        target: object,
        *,
        model_id: object | None = None,
    ) -> ModelDescriptor | None:
        src = normalize_language_code(source)
        dst = normalize_language_code(target)
        if model_id is not None and str(model_id).strip():
            descriptor = self.require(model_id)
            if (descriptor.source_language, descriptor.target_language) != (src, dst):
                raise ModelValidationError(
                    f"Модель {descriptor.id} не переводит {src} → {dst}",
                    code="model_pair_mismatch",
                    problems=(
                        f"Модель заявлена для {descriptor.source_language} → {descriptor.target_language}",
                    ),
                )
            return descriptor
        for descriptor in self._models.values():
            if (descriptor.source_language, descriptor.target_language) == (src, dst):
                return descriptor
        return None

    def remove(self, model_id: object, *, persist: bool = True) -> bool:
        try:
            key = normalize_model_id(model_id)
        except ModelValidationError:
            return False
        removed = self._models.pop(key, None) is not None
        if removed and persist:
            self.save()
        return removed


__all__ = [
    "DEFAULT_REGISTRY_FILENAME",
    "MAX_REGISTRY_MODELS",
    "MODEL_BACKEND_CTRANSLATE2",
    "MODEL_KIND_TRANSLATION",
    "ModelDescriptor",
    "ModelRegistry",
    "ModelValidationError",
    "ModelValidationReport",
    "TranslationPair",
    "normalize_language_code",
    "normalize_model_id",
    "require_ct2_model",
    "require_ctranslate2_model",
    "validate_ct2_model",
    "validate_ctranslate2_model",
]

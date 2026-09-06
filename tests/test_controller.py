from dotaudio.controller import STATUS_LABELS


def test_engine_statuses_have_russian_labels() -> None:
    assert STATUS_LABELS["loading_model"].startswith("Загружаем")
    assert STATUS_LABELS["transcribing_cpu"].startswith("Распознаём")

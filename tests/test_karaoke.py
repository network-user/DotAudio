from pathlib import Path

import pytest

from dotaudio.karaoke import export_ass, render_video


def test_ass_export_uses_word_timings_and_phrase_without_words() -> None:
    result = export_ass([
        {"start": 0, "end": 1, "text": "Привет мир", "words": [
            {"text": "Привет", "start": 0, "end": 0.4},
            {"text": "мир", "start": 0.4, "end": 1},
        ]},
        {"start": 1, "end": 2, "text": "ещё строка"},
    ])
    assert "{\\k40}Привет {\\k60}мир" in result
    phrase_line = next(line for line in result.splitlines() if "ещё строка" in line)
    assert phrase_line.startswith("Dialogue: 0,0:00:01.00,0:00:02.00,")
    assert "{\\k" not in phrase_line


def test_ass_uniform_karaoke_opt_in_splits_phrase() -> None:
    result = export_ass(
        [{"start": 0, "end": 1, "text": "раз два"}],
        uniform_karaoke=True,
    )
    assert "{\\k50}раз {\\k50}два" in result


def test_audio_video_export_requires_cover(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="обложку"):
        render_video(str(tmp_path / "song.mp3"), str(tmp_path / "karaoke.ass"), str(tmp_path / "out.mp4"))

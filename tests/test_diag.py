"""Тесты diag.py: журнал, check_*, summarize_doctor, format_doctor_report."""
from __future__ import annotations

from dotaudio.diag import (
    FileLog,
    busy_job_reason,
    check_whisper_disk,
    empty_transcript_reason,
    explain_transcribe_error,
    format_doctor_report,
    format_duration_ru,
    probe_media_duration,
    running_transcribe_check,
    summarize_doctor,
    transcribe_wait_note,
    whisper_runtime_check,
)


def test_explain_transcribe_error_float16_mentions_int8_or_cpu():
    error = ValueError(
        "requested float16 compute type, but the target device "
        "or backend do not support efficient float16 computation"
    )
    result = explain_transcribe_error(error)
    assert "float16" in result
    lower = result.casefold()
    assert "int8" in lower or "процессор" in lower


def test_whisper_runtime_check_float16_offers_cpu():
    result = whisper_runtime_check(
        {
            "ok": False,
            "code": "error",
            "detail": (
                "Эта видеокарта не считает Whisper в float16. Программа должна "
                "сама перейти на int8; если ошибка осталась, выберите процессор."
            ),
        },
        "small",
    )
    assert result["ok"] is False
    assert result["fix"] == "cpu"


def test_file_log_writes_line(tmp_path):
    log = FileLog(tmp_path / "diag.log")
    log.write("info", "тестовое сообщение")
    content = (tmp_path / "diag.log").read_text(encoding="utf-8")
    assert "тестовое сообщение" in content
    assert "info" in content


def test_check_whisper_disk_not_ready_ok_false():
    result = check_whisper_disk(
        "small",
        catalog={"small": {"download_mb": 483}},
        disk={"ready": False, "bytes": 0},
    )
    assert result["ok"] is False
    assert result["fix"] == "prepare_model"


def test_check_whisper_disk_ready_large_ok():
    result = check_whisper_disk(
        "small",
        catalog={"small": {"download_mb": 483}},
        disk={"ready": True, "bytes": 600 * 1048576},
    )
    assert result["ok"] is True


def test_summarize_doctor_prepare_model_can_fix():
    checks = [
        {
            "id": "whisper_files",
            "ok": False,
            "label": "Whisper",
            "detail": "нет модели",
            "fix": "prepare_model",
        },
    ]
    result = summarize_doctor(checks)
    assert result["canFix"] is True
    assert "prepare_model" in result["fixes"]


def test_format_doctor_report_contains_fail():
    checks = [
        {"id": "pyav", "ok": False, "label": "PyAV", "detail": "не импортируется", "fix": ""},
    ]
    report = format_doctor_report(checks)
    assert "[fail]" in report


def test_format_doctor_report_contains_timestamp():
    checks: list[dict] = []
    report = format_doctor_report(checks)
    # timestamp format: YYYY-MM-DD HH:MM:SS
    import re
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", report)


def test_format_doctor_report_with_extra():
    checks = [{"id": "pyav", "ok": True, "label": "PyAV", "detail": "ok", "fix": ""}]
    report = format_doctor_report(checks, extra={"model": "small", "device": "cpu"})
    assert "model: small" in report
    assert "device: cpu" in report


def test_format_doctor_report_extra_none_backward_compat():
    checks = [{"id": "pyav", "ok": True, "label": "PyAV", "detail": "ok", "fix": ""}]
    report = format_doctor_report(checks)
    assert "[ok]" in report


def test_busy_job_reason_mentions_live():
    result = busy_job_reason({"x": {"mode": "live", "name": "Live"}})
    assert "Live" in result


def test_empty_transcript_reason_not_downloaded():
    result = empty_transcript_reason("small", False)
    lower = result.casefold()
    assert "не скачана" in lower or "скачайте" in lower or "скачать" in lower


def test_format_duration_ru_minutes():
    assert format_duration_ru(125) == "2 мин"
    assert format_duration_ru(18) == "18 с"


def test_transcribe_wait_note_explains_mp3_read():
    note = transcribe_wait_note(12, 0, duration_s=900)
    assert "файл" in note.casefold()
    assert "12" in note
    later = transcribe_wait_note(40, 3, duration_s=900)
    assert "3" in later


def test_probe_media_duration_wav(tmp_path):
    import wave

    wav = tmp_path / "tone.wav"
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 32000)
    assert abs(probe_media_duration(wav) - 2.0) < 0.05


def test_running_transcribe_check_is_not_a_failure():
    result = running_transcribe_check("talk.mp3")
    assert result["ok"] is True
    assert "talk.mp3" in result["detail"]

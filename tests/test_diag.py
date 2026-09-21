"""Тесты diag.py: журнал, check_*, summarize_doctor, format_doctor_report."""
from __future__ import annotations

import json

from dotaudio.diag import (
    DIAGNOSTIC_REPORT_MAX_BYTES,
    FileLog,
    busy_job_reason,
    check_whisper_disk,
    empty_transcript_reason,
    explain_transcribe_error,
    export_diagnostic_report,
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


def test_export_diagnostic_report_success_has_stable_sections_and_json():
    result = {
        "ok": True,
        "message": "Проверки прошли",
        "phase": "ok",
        "checks": [
            {"id": "python", "ok": True, "label": "Python", "detail": "CPython 3.12"},
            {"id": "whisper", "ok": True, "label": "Whisper", "detail": "модель готова"},
        ],
        "extra": {"model": "small", "device": "cpu"},
    }

    text = export_diagnostic_report(result)
    assert text == export_diagnostic_report(result)
    assert "format_version: 1" in text
    assert "[summary]" in text
    assert "[environment]" in text
    assert "[checks]" in text
    assert "[actions]" in text

    payload = json.loads(export_diagnostic_report(result, format="json"))
    assert payload["format_version"] == 1
    assert list(payload["sections"]) == ["summary", "environment", "checks", "actions"]
    assert payload["sections"]["summary"]["status"] == "ok"
    assert payload["sections"]["environment"]["device"] == "cpu"
    assert payload["sections"]["checks"][0]["id"] == "python"


def test_export_diagnostic_report_errors_include_recommended_actions():
    result = {
        "ok": False,
        "message": "Whisper не отвечает",
        "phase": "fail",
        "canFix": True,
        "fixLabel": "Починить: процессор",
        "fixes": ["cpu", "prepare_model"],
        "checks": [
            {
                "id": "whisper_runtime",
                "ok": False,
                "label": "Whisper отвечает",
                "detail": "CUDA не приняла модель",
                "fix": "cpu",
                "advice": ["Переключить устройство на процессор"],
            }
        ],
    }

    payload = json.loads(export_diagnostic_report(result, format="json"))
    summary = payload["sections"]["summary"]
    actions = payload["sections"]["actions"]
    assert summary["status"] == "failed"
    assert summary["can_fix"] is True
    assert summary["fix_label"] == "Починить: процессор"
    assert actions[:2] == ["cpu", "prepare_model"]
    assert "Переключить устройство на процессор" in actions
    assert "CUDA не приняла модель" in payload["sections"]["checks"][0]["detail"]


def test_export_diagnostic_report_redacts_sensitive_and_bounds_huge_values():
    result = {
        "ok": False,
        "message": "token=super-secret-token; файл C:\\Users\\frog2\\secret folder\\input.wav",
        "checks": [
            {
                "id": "media",
                "ok": False,
                "label": "Файл",
                "detail": "Authorization: Bearer very-secret-value",
            }
        ],
        "extra": {
            "secret_token": "do-not-export",
            "log_path": r"C:\Users\frog2\secret folder\diagnostic.log",
            "huge_field": "X" * 100_000,
        },
        "report": "сырой отчёт не должен попадать в новый bounded API",
    }

    text = export_diagnostic_report(result)
    payload_text = export_diagnostic_report(result, format="json")
    for report in (text, payload_text):
        assert len(report.encode("utf-8")) <= DIAGNOSTIC_REPORT_MAX_BYTES
        assert "super-secret-token" not in report
        assert "do-not-export" not in report
        assert r"C:\Users\frog2" not in report
        assert "secret folder" not in report
        assert "сырой отчёт не должен" not in report
        assert "[truncated]" in report
    payload = json.loads(payload_text)
    assert payload["sections"]["environment"]["log_path"] == "[path redacted]"

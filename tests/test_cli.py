from typer.testing import CliRunner

from subtitle_forge.cli import app


runner = CliRunner()


def test_cli_inspect_example():
    result = runner.invoke(app, ["inspect", "examples/movie.en.srt"])

    assert result.exit_code == 0
    assert "Cues: 3" in result.stdout


def test_cli_validate_example():
    result = runner.invoke(app, ["validate", "examples/movie.en.srt"])

    assert result.exit_code == 0
    assert "OK: parsed 3 cues" in result.stdout


def test_cli_providers():
    result = runner.invoke(app, ["providers"])

    assert result.exit_code == 0
    assert "ArgosTranslate" in result.stdout
    assert "codex" in result.stdout
    assert "mock" in result.stdout


def test_cli_translate_with_hybrid_mock(monkeypatch, tmp_path):
    output = tmp_path / "movie.fa.srt"

    monkeypatch.setattr("subtitle_forge.cli.translate_cues_with_argos", _fake_argos_bad_first_pass)

    result = runner.invoke(
        app,
        [
            "translate",
            "examples/movie.en.srt",
            "--from",
            "en",
            "--to",
            "fa",
            "--cleanup-provider",
            "mock",
            "--out",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    assert "سلام." in output.read_text(encoding="utf-8")
    assert "1/6 Reading subtitles" in result.stdout
    assert "6/6 Final normalization, validation, and write" in result.stdout
    assert "No suspicious cues flagged; skipping AI cleanup." not in result.stdout


def test_cli_translate_uses_output_extension_over_config_default(monkeypatch, tmp_path):
    output = tmp_path / "movie.fa.vtt"

    monkeypatch.setattr("subtitle_forge.cli.translate_cues_with_argos", _fake_argos_bad_first_pass)

    result = runner.invoke(
        app,
        [
            "translate",
            "examples/movie.en.vtt",
            "--from",
            "en",
            "--to",
            "fa",
            "--cleanup-provider",
            "mock",
            "--out",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert output.read_text(encoding="utf-8").startswith("WEBVTT")


def test_cli_translate_skips_cleanup_progress_when_no_cues_flagged(monkeypatch, tmp_path):
    output = tmp_path / "movie.fa.srt"

    monkeypatch.setattr("subtitle_forge.cli.translate_cues_with_argos", _fake_argos_clean_first_pass)

    result = runner.invoke(
        app,
        [
            "translate",
            "examples/movie.en.srt",
            "--from",
            "en",
            "--to",
            "fa",
            "--cleanup-provider",
            "mock",
            "--out",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "No suspicious cues flagged; skipping AI cleanup." in result.stdout
    assert "Cleanup batches" not in result.stdout


def test_cli_translate_does_not_build_cleanup_provider_when_no_cues_flagged(monkeypatch, tmp_path):
    output = tmp_path / "movie.fa.srt"

    monkeypatch.setattr("subtitle_forge.cli.translate_cues_with_argos", _fake_argos_clean_first_pass)
    monkeypatch.setattr("subtitle_forge.cli._build_cleanup_provider", _raise_if_cleanup_provider_is_built)

    result = runner.invoke(
        app,
        [
            "translate",
            "examples/movie.en.srt",
            "--from",
            "en",
            "--to",
            "fa",
            "--out",
            str(output),
        ],
    )

    assert result.exit_code == 0


def test_cli_translate_failed_validation_exits_cleanly(monkeypatch, tmp_path):
    output = tmp_path / "movie.fa.srt"

    monkeypatch.setattr("subtitle_forge.cli.translate_cues_with_argos", _fake_argos_unfixable_first_pass)
    monkeypatch.setattr("subtitle_forge.cli.cleanup_flagged_cues", _fake_cleanup_leaves_cues_unchanged)

    result = runner.invoke(
        app,
        [
            "translate",
            "examples/movie.en.srt",
            "--from",
            "en",
            "--to",
            "fa",
            "--cleanup-provider",
            "mock",
            "--out",
            str(output),
        ],
    )

    assert result.exit_code == 1
    assert "Final validation failed" in result.stdout
    assert "Traceback" not in result.stdout
    assert output.exists()


def test_cli_translate_cuda_without_runtime_fails_early(monkeypatch, tmp_path):
    output = tmp_path / "movie.fa.srt"

    monkeypatch.setattr("subtitle_forge.cli._cuda_status", lambda: "1 CUDA device(s), but cublas64_12.dll is not loadable")
    monkeypatch.setattr("subtitle_forge.cli.translate_cues_with_argos", _raise_if_argos_translation_runs)

    result = runner.invoke(
        app,
        [
            "translate",
            "examples/movie.en.srt",
            "--from",
            "en",
            "--to",
            "fa",
            "--out",
            str(output),
            "--argos-device",
            "cuda",
        ],
    )

    assert result.exit_code == 1
    assert "CUDA 12.x runtime libraries" in result.stdout
    assert "--argos-device cpu" in result.stdout
    assert "Traceback" not in result.stdout


def _fake_argos_bad_first_pass(cues, source_language, target_language, translator=None, device_type=None, on_cue=None):
    translated = []
    for index, cue in enumerate(cues, start=1):
        if on_cue:
            on_cue(index, cue)
        translated.append(cue.with_text("Hello."))
    return translated


def _fake_argos_clean_first_pass(cues, source_language, target_language, translator=None, device_type=None, on_cue=None):
    translations = {
        "Hello.": "سلام.",
        "Welcome to Subtitle Forge.": "به City Hunter خوش آمدید.",
        "<i>Keep moving.</i>": "<i>ادامه بدهید.</i>",
    }
    translated = []
    for index, cue in enumerate(cues, start=1):
        if on_cue:
            on_cue(index, cue)
        translated.append(cue.with_text(translations[cue.text]))
    return translated


def _fake_argos_unfixable_first_pass(cues, source_language, target_language, translator=None, device_type=None, on_cue=None):
    translated = []
    for index, cue in enumerate(cues, start=1):
        if on_cue:
            on_cue(index, cue)
        translated.append(cue.with_text("..."))
    return translated


def _fake_cleanup_leaves_cues_unchanged(
    source_cues,
    current_cues,
    flagged_ids,
    issues,
    provider,
    source_language,
    target_language,
    translation_config,
    allowed_latin_names,
    batch_size,
    on_batch=None,
):
    if on_batch:
        on_batch(1, flagged_ids)
    return current_cues


def _raise_if_cleanup_provider_is_built(*args, **kwargs):
    raise AssertionError("cleanup provider should not be built when no cues are flagged")


def _raise_if_argos_translation_runs(*args, **kwargs):
    raise AssertionError("Argos translation should not start when CUDA preflight fails")

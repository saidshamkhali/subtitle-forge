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


def _fake_argos_bad_first_pass(cues, source_language, target_language, translator=None, on_cue=None):
    translated = []
    for index, cue in enumerate(cues, start=1):
        if on_cue:
            on_cue(index, cue)
        translated.append(cue.with_text("Hello."))
    return translated

from pathlib import Path

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
    assert "codex" in result.stdout
    assert "mock" in result.stdout


def test_cli_translate_with_mock(tmp_path):
    output = tmp_path / "movie.fa.srt"

    result = runner.invoke(
        app,
        [
            "translate",
            "examples/movie.en.srt",
            "--from",
            "en",
            "--to",
            "fa",
            "--provider",
            "mock",
            "--out",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    assert "سلام." in output.read_text(encoding="utf-8")


def test_cli_translate_uses_output_extension_over_config_default(tmp_path):
    output = tmp_path / "movie.fa.vtt"

    result = runner.invoke(
        app,
        [
            "translate",
            "examples/movie.en.vtt",
            "--from",
            "en",
            "--to",
            "fa",
            "--provider",
            "mock",
            "--out",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert output.read_text(encoding="utf-8").startswith("WEBVTT")

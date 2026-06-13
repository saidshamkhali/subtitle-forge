from types import SimpleNamespace

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


def test_cli_translate_help_does_not_include_output_format_option():
    result = runner.invoke(app, ["translate", "--help"])

    assert result.exit_code == 0
    assert "--output-format" not in result.stdout


def test_cli_providers():
    result = runner.invoke(app, ["providers"])

    assert result.exit_code == 0
    assert "ArgosTranslate" in result.stdout
    assert "codex" in result.stdout
    assert "mock" in result.stdout


def test_cli_doctor_skips_codex_check_for_mock_cleanup(monkeypatch, tmp_path):
    config = tmp_path / "subtitle-forge.toml"
    config.write_text(
        """
[defaults]
cleanup_provider = "mock"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("subtitle_forge.cli._cuda_status", lambda: "test cuda status")
    monkeypatch.setattr("subtitle_forge.cli._load_argos_translate", _fake_argos_translate)
    monkeypatch.setattr("subtitle_forge.cli.resolve_executable", _raise_if_codex_resolution_runs)

    result = runner.invoke(app, ["doctor", "--config", str(config)])

    assert result.exit_code == 0
    assert "Cleanup provider: mock" in result.stdout
    assert "Codex CLI: skipped because cleanup provider is 'mock'" in result.stdout


def test_cli_translate_with_mock_cleanup(monkeypatch, tmp_path):
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
    assert "Top issue types:" in result.stdout
    assert "No suspicious cues flagged; skipping AI cleanup." not in result.stdout


def test_cli_translate_writes_vtt_when_output_extension_is_vtt(monkeypatch, tmp_path):
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


def test_cli_translate_inherits_input_format_when_output_has_no_subtitle_extension(monkeypatch, tmp_path):
    output = tmp_path / "movie.fa"

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
    assert output.read_text(encoding="utf-8").lstrip().startswith("1\n")


def test_cli_translate_allows_srt_input_with_vtt_output(monkeypatch, tmp_path):
    output = tmp_path / "movie.fa.vtt"

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


def test_cli_translate_no_keep_intermediate_overrides_config(monkeypatch, tmp_path):
    config = tmp_path / "subtitle-forge.toml"
    output = tmp_path / "movie.fa.srt"
    config.write_text(
        """
[defaults]
keep_intermediate = true
cleanup_provider = "mock"
""",
        encoding="utf-8",
    )

    monkeypatch.setattr("subtitle_forge.cli.translate_cues_with_argos", _fake_argos_clean_first_pass)

    result = runner.invoke(
        app,
        [
            "translate",
            "examples/movie.en.srt",
            "--config",
            str(config),
            "--from",
            "en",
            "--to",
            "fa",
            "--out",
            str(output),
            "--no-keep-intermediate",
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    assert not output.with_name("movie.fa.argos.srt").exists()
    assert not output.with_name("movie.fa.normalized.srt").exists()


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


def test_cli_translate_installs_argos_package_when_requested(monkeypatch, tmp_path):
    output = tmp_path / "movie.fa.srt"
    calls = []

    def fake_install_argos_package(source_language, target_language, on_status=None):
        calls.append((source_language, target_language))
        if on_status:
            on_status("fake Argos package setup")
        return True

    monkeypatch.setattr("subtitle_forge.cli.install_argos_language_package", fake_install_argos_package)
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
            "--install-argos-package",
        ],
    )

    assert result.exit_code == 0
    assert calls == [("en", "fa")]
    assert "Argos package setup" in result.stdout
    assert "fake Argos package setup" in result.stdout


def test_cli_translate_installs_argos_package_without_translating(monkeypatch):
    calls = []

    def fake_install_argos_package(source_language, target_language, on_status=None):
        calls.append((source_language, target_language))
        return False

    monkeypatch.setattr("subtitle_forge.cli.install_argos_language_package", fake_install_argos_package)
    monkeypatch.setattr("subtitle_forge.cli.translate_cues_with_argos", _raise_if_argos_translation_runs)

    result = runner.invoke(
        app,
        [
            "translate",
            "--from",
            "en",
            "--to",
            "fa",
            "--install-argos-package",
        ],
    )

    assert result.exit_code == 0
    assert calls == [("en", "fa")]
    assert "Argos translation path already installed: en -> fa" in result.stdout


def test_cli_translate_does_not_install_argos_package_by_default(monkeypatch, tmp_path):
    output = tmp_path / "movie.fa.srt"

    monkeypatch.setattr("subtitle_forge.cli.install_argos_language_package", _raise_if_argos_package_install_runs)
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


def test_cli_translate_cuda_without_runtime_fails_early(monkeypatch, tmp_path):
    output = tmp_path / "movie.fa.srt"

    monkeypatch.setattr(
        "subtitle_forge.cli._cuda_status",
        lambda: "1 CUDA device(s), but cublas64_12.dll is not loadable",
    )
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


def _fake_argos_clean_first_pass(
    cues, source_language, target_language, translator=None, device_type=None, on_cue=None
):
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


def _fake_argos_unfixable_first_pass(
    cues, source_language, target_language, translator=None, device_type=None, on_cue=None
):
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
    cleanup_cache=None,
):
    if on_batch:
        on_batch(1, flagged_ids)
    return current_cues


def _raise_if_cleanup_provider_is_built(*args, **kwargs):
    raise AssertionError("cleanup provider should not be built when no cues are flagged")


def _raise_if_argos_translation_runs(*args, **kwargs):
    raise AssertionError("Argos translation should not start when CUDA preflight fails")


def _raise_if_argos_package_install_runs(*args, **kwargs):
    raise AssertionError("Argos package install should be opt-in")


def _fake_argos_translate():
    return SimpleNamespace(get_installed_languages=lambda: [])


def _raise_if_codex_resolution_runs(*args, **kwargs):
    raise AssertionError("Codex executable should not be resolved for mock cleanup")

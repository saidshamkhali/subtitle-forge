from __future__ import annotations

import ctypes
import json
import math
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

import typer

from subtitle_forge.argos import (
    VALID_ARGOS_DEVICES,
    configure_cuda_dll_directories,
    translate_cues_with_argos,
)
from subtitle_forge.argos import (
    install_argos_package as install_argos_language_package,
)
from subtitle_forge.cleanup import cleanup_flagged_cues
from subtitle_forge.config import (
    AppConfig,
    TranslationConfig,
    load_codex_default_model,
    load_codex_default_reasoning_effort,
    load_config,
)
from subtitle_forge.errors import SubtitleForgeError
from subtitle_forge.executables import resolve_executable
from subtitle_forge.logging_config import configure_logging
from subtitle_forge.normalization import normalize_cues_for_target
from subtitle_forge.providers import CodexExecProvider, MockProvider, TranslationProvider
from subtitle_forge.quality import ValidationReport, validate_translation, validation_passed
from subtitle_forge.subtitles import detect_format, read_subtitles, write_subtitles

if TYPE_CHECKING:
    from pathlib import Path

    from subtitle_forge.models import SubtitleCue

app = typer.Typer(
    help="Translate subtitles with ArgosTranslate, deterministic validation, and targeted Codex cleanup.",
    no_args_is_help=True,
)


def _version_callback(show_version: bool = False) -> None:
    if show_version:
        from subtitle_forge import __version__

        typer.echo(f"subtitle-forge {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False, "--version", help="Show version and exit.", callback=_version_callback
    ),
) -> None:
    pass


@app.command()
def inspect(
    input_path: Annotated[Path, typer.Argument(exists=True, readable=True, help="Subtitle file to inspect.")],
    input_format: Annotated[str | None, typer.Option("--format", help="Input format: srt or vtt.")] = None,
):
    """Print basic subtitle metadata."""
    try:
        cues = read_subtitles(input_path, input_format)
        fmt = detect_format(input_path, input_format)
    except SubtitleForgeError as exc:
        _fail(exc)
    typer.echo(f"File: {input_path}")
    typer.echo(f"Format: {fmt}")
    typer.echo(f"Cues: {len(cues)}")
    if cues:
        typer.echo(f"First cue: {cues[0].start} -> {cues[0].end}")
        typer.echo(f"Last cue: {cues[-1].start} -> {cues[-1].end}")


@app.command()
def validate(
    input_path: Annotated[Path, typer.Argument(exists=True, readable=True, help="Subtitle file to validate.")],
    input_format: Annotated[str | None, typer.Option("--format", help="Input format: srt or vtt.")] = None,
):
    """Validate that a subtitle file can be parsed."""
    try:
        cues = read_subtitles(input_path, input_format)
    except SubtitleForgeError as exc:
        _fail(exc)
    typer.echo(f"OK: parsed {len(cues)} cues from {input_path}")


@app.command()
def providers(
    config_path: Annotated[Path | None, typer.Option("--config", "-c", help="Path to subtitle-forge.toml.")] = None,
):
    """List cleanup providers used after Argos validation."""
    config = _load_config_or_fail(config_path)
    typer.echo("Translation pipeline: ArgosTranslate first pass + deterministic normalization + flagged-cue cleanup")
    typer.echo(f"Cleanup provider: {config.cleanup_provider}")
    typer.echo("Available cleanup providers:")
    typer.echo("- codex: uses local Codex CLI for flagged-cue repair")
    typer.echo("- mock: deterministic local cleanup provider for tests and dry runs")


@app.command()
def doctor(
    config_path: Annotated[Path | None, typer.Option("--config", "-c", help="Path to subtitle-forge.toml.")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show debug logging output.")] = False,
):
    """Check local setup for ArgosTranslate and the Codex cleanup provider."""
    config = _load_config_or_fail(config_path)
    configure_logging(verbose)
    try:
        argos_translate = _load_argos_translate()
    except ImportError as err:
        typer.secho("Missing: ArgosTranslate Python package was not found.", fg=typer.colors.RED)
        raise typer.Exit(1) from err

    installed_languages = argos_translate.get_installed_languages()
    installed_codes = sorted(language.code for language in installed_languages)
    typer.echo(f"ArgosTranslate: installed languages: {', '.join(installed_codes) or 'none'}")
    typer.echo(f"Argos device default: {config.argos_device}")
    typer.echo(f"CUDA status: {_cuda_status()}")
    typer.echo("Pipeline: ArgosTranslate -> normalize -> validate -> cleanup -> normalize -> validate")
    typer.echo(f"Cleanup provider: {config.cleanup_provider}")

    if config.cleanup_provider != "codex":
        typer.echo(f"Codex CLI: skipped because cleanup provider is '{config.cleanup_provider}'")
        return

    command = config.codex.command
    executable = resolve_executable(command)
    if not executable:
        typer.secho(f"Missing: Codex CLI command '{command}' was not found.", fg=typer.colors.RED)
        typer.echo("Install Codex CLI, then run 'codex login' with your ChatGPT account.")
        raise typer.Exit(1)

    completed = subprocess.run(
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    version = completed.stdout.strip() or completed.stderr.strip() or "version unavailable"
    codex_default_model = load_codex_default_model()
    codex_default_reasoning_effort = load_codex_default_reasoning_effort()
    selected_model = config.codex.model or codex_default_model
    typer.echo(f"Codex CLI: {version}")
    if config.codex.model:
        typer.echo(f"Model: {config.codex.model} from subtitle-forge.toml")
    elif codex_default_model:
        typer.echo(f"Model: {codex_default_model} from ~/.codex/config.toml")
    else:
        typer.echo("Model: local Codex default")
    if selected_model == "gpt-5.5" and "0.106.0" in version:
        typer.secho(
            "Warning: gpt-5.5 may require a newer Codex CLI/app than the one currently installed.",
            fg=typer.colors.YELLOW,
        )
    if config.codex.reasoning_effort:
        typer.echo(f"Reasoning effort: {config.codex.reasoning_effort} from subtitle-forge.toml")
    elif codex_default_reasoning_effort:
        typer.echo(f"Reasoning effort: {codex_default_reasoning_effort} from ~/.codex/config.toml")
    else:
        typer.echo("Reasoning effort: local Codex default")
    typer.echo("Override reasoning with: --reasoning-effort low|medium|high")
    typer.echo("Login: run 'codex login' if this Codex CLI is not already connected to your ChatGPT account.")


@app.command()
def translate(
    input_path: Annotated[Path | None, typer.Argument(help="Subtitle file to translate.")] = None,
    output_path: Annotated[Path | None, typer.Option("--out", "-o", help="Output subtitle path.")] = None,
    config_path: Annotated[Path | None, typer.Option("--config", "-c", help="Path to subtitle-forge.toml.")] = None,
    source_language: Annotated[str | None, typer.Option("--from", help="Source language code/name.")] = None,
    target_language: Annotated[str | None, typer.Option("--to", help="Target language code/name.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Optional Codex model override.")] = None,
    reasoning_effort: Annotated[
        str | None, typer.Option("--reasoning-effort", help="Optional Codex reasoning effort.")
    ] = None,
    cleanup_provider_name: Annotated[
        str | None,
        typer.Option("--cleanup-provider", help="Cleanup provider for flagged cues: codex or mock."),
    ] = None,
    argos_device: Annotated[
        str | None, typer.Option("--argos-device", help="Argos first-pass device: cpu, cuda, or auto.")
    ] = None,
    cleanup_batch_size: Annotated[
        int | None,
        typer.Option("--cleanup-batch-size", min=1, help="Flagged cues per cleanup call."),
    ] = None,
    report_path: Annotated[Path | None, typer.Option("--report", help="Validation report path.")] = None,
    keep_intermediate: Annotated[
        bool | None,
        typer.Option(
            "--keep-intermediate/--no-keep-intermediate",
            help="Keep Argos and normalized intermediate files.",
        ),
    ] = None,
    install_argos_package: Annotated[
        bool,
        typer.Option(
            "--install-argos-package",
            help="Download and install the requested Argos language package. Without input, install and exit.",
        ),
    ] = False,
    prompt: Annotated[str | None, typer.Option("--prompt", help="Additional prompt instructions.")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show debug logging output.")] = False,
):
    """Run the full Argos -> normalize -> validate -> cleanup pipeline."""
    config = _load_config_or_fail(config_path)
    configure_logging(verbose)
    settings = _resolve_translate_settings(
        config=config,
        input_path=input_path,
        output_path=output_path,
        source_language=source_language,
        target_language=target_language,
        model=model,
        reasoning_effort=reasoning_effort,
        cleanup_provider_name=cleanup_provider_name,
        argos_device=argos_device,
        cleanup_batch_size=cleanup_batch_size,
        report_path=report_path,
        keep_intermediate=keep_intermediate,
        prompt=prompt,
    )
    started_at = time.perf_counter()
    timings: list[tuple[str, float]] = []

    try:
        if install_argos_package and settings.input_path is None:
            _install_argos_package_for_cli(settings.source, settings.target)
            return
        settings = _require_translate_settings(settings)
        _validate_translate_inputs(settings)

        _print_translate_header(
            settings.input_path,
            settings.output_path,
            settings.source,
            settings.target,
            settings.cleanup_provider,
            settings.argos_device,
        )

        cues, read_seconds = _stage_read_subtitles(settings.input_path)
        timings.append(("Read", read_seconds))

        if install_argos_package:
            _install_argos_package_for_cli(settings.source, settings.target)

        argos_cues, argos_seconds = _stage_argos_translation(cues, settings)
        timings.append(("Argos", argos_seconds))

        normalized_cues, intermediate_paths, normalize_seconds = _stage_normalize(
            argos_cues, settings
        )
        timings.append(("Normalize", normalize_seconds))

        initial_report, validate_seconds = _stage_initial_validation(cues, normalized_cues, settings)
        timings.append(("Validate", validate_seconds))

        cleaned_cues, cleanup_seconds = _stage_cleanup(cues, normalized_cues, initial_report, settings)
        timings.append(("Cleanup", cleanup_seconds))

        final_cues, final_report, finalize_seconds = _stage_finalize(cues, cleaned_cues, settings)
        timings.append(("Finalize", finalize_seconds))

        _write_report(
            report_path=settings.report_path,
            input_path=settings.input_path,
            output_path=settings.output_path,
            source_language=settings.source,
            target_language=settings.target,
            initial_report=initial_report,
            final_report=final_report,
            intermediate_paths=intermediate_paths,
        )
        elapsed_seconds = time.perf_counter() - started_at
        _print_summary(
            settings.output_path,
            settings.report_path,
            len(cues),
            initial_report,
            final_report,
            elapsed_seconds,
            timings,
        )
        if not validation_passed(final_report):
            _warning(
                f"Final validation failed with {len(final_report.suspicious_cue_ids)} suspicious cues remaining. "
                f"Review the report: {settings.report_path}"
            )
            raise typer.Exit(1)
    except SubtitleForgeError as exc:
        _fail(exc)

    _success(f"Translated {len(final_cues)} cues to {settings.output_path}")


def _build_cleanup_provider(
    name: str,
    config: AppConfig,
    target_language: str,
    model: str | None,
    reasoning_effort: str | None,
) -> TranslationProvider:
    normalized = name.lower()
    if normalized == "codex":
        selected_reasoning_effort = (
            reasoning_effort if reasoning_effort is not None else (config.codex.reasoning_effort or "low")
        )
        return CodexExecProvider(config.codex, model=model, reasoning_effort=selected_reasoning_effort)
    if normalized == "mock":
        return MockProvider(target_language=target_language)
    raise SubtitleForgeError(f"Unknown cleanup provider '{name}'. Expected one of: codex, mock.")


def _resolve_output_format(input_path: Path, output_path: Path) -> str:
    output_suffix = output_path.suffix.lstrip(".").lower()
    if output_suffix in {"srt", "vtt"}:
        return output_suffix
    return detect_format(input_path)


def _load_argos_translate():
    import argostranslate.translate

    return argostranslate.translate


def _load_config_or_fail(config_path: Path | None) -> AppConfig:
    try:
        return load_config(config_path)
    except SubtitleForgeError as exc:
        _fail(exc)


def _install_argos_package_for_cli(source_language: str, target_language: str) -> None:
    _stage("Argos package setup", f"Ensuring {source_language} -> {target_language} is installed")
    installed_argos_package = install_argos_language_package(source_language, target_language, on_status=_detail)
    if installed_argos_package:
        _success(f"Installed Argos package {source_language} -> {target_language}.")
    else:
        _detail(f"Argos translation path already installed: {source_language} -> {target_language}")


def _merge_translation_config(config: TranslationConfig, prompt: str | None) -> TranslationConfig:
    if prompt is None:
        return config
    existing = config.prompt
    merged_prompt = f"{existing}\n{prompt}" if existing else prompt
    return TranslationConfig(
        style=config.style,
        preserve_names=config.preserve_names,
        preserve_formatting=config.preserve_formatting,
        prompt=merged_prompt,
    )


@dataclass(frozen=True)
class _TranslateSettings:
    input_path: Path | None
    output_path: Path | None
    report_path: Path | None
    output_format: str | None
    source: str
    target: str
    cleanup_provider: str
    argos_device: str
    cleanup_batch_size: int
    keep_intermediate: bool
    translation_config: TranslationConfig
    model: str | None
    reasoning_effort: str | None
    config: AppConfig


def _resolve_translate_settings(
    config: AppConfig,
    input_path: Path | None,
    output_path: Path | None,
    source_language: str | None,
    target_language: str | None,
    model: str | None,
    reasoning_effort: str | None,
    cleanup_provider_name: str | None,
    argos_device: str | None,
    cleanup_batch_size: int | None,
    report_path: Path | None,
    keep_intermediate: bool | None,
    prompt: str | None,
) -> _TranslateSettings:
    source = source_language or config.source_language
    target = target_language or config.target_language
    selected_cleanup_provider = cleanup_provider_name or config.cleanup_provider
    selected_argos_device = argos_device or config.argos_device
    selected_cleanup_batch_size = cleanup_batch_size or config.cleanup_batch_size
    selected_keep_intermediate = config.keep_intermediate if keep_intermediate is None else keep_intermediate
    translation_config = _merge_translation_config(config.translation, prompt)
    resolved_output_format = (
        _resolve_output_format(input_path, output_path)
        if input_path is not None and output_path is not None
        else None
    )
    resolved_report = (
        report_path
        or (output_path.with_suffix(output_path.suffix + ".report.json") if output_path is not None else None)
    )
    return _TranslateSettings(
        input_path=input_path,
        output_path=output_path,
        report_path=resolved_report,
        output_format=resolved_output_format,
        source=source,
        target=target,
        cleanup_provider=selected_cleanup_provider,
        argos_device=selected_argos_device,
        cleanup_batch_size=selected_cleanup_batch_size,
        keep_intermediate=selected_keep_intermediate,
        translation_config=translation_config,
        model=model,
        reasoning_effort=reasoning_effort,
        config=config,
    )


def _require_translate_settings(settings: _TranslateSettings) -> _TranslateSettings:
    if settings.input_path is None:
        raise SubtitleForgeError(
            "Input subtitle path is required. To install an Argos package without translating, run: "
            f"subtitle-forge translate --from {settings.source} --to {settings.target} --install-argos-package"
        )
    if settings.output_path is None:
        raise SubtitleForgeError("Output path is required for translation. Pass it with '--out OUTPUT_PATH'.")
    if settings.report_path is None or settings.output_format is None:
        raise SubtitleForgeError("Validation report path could not be resolved.")
    return settings


def _validate_translate_inputs(settings: _TranslateSettings) -> None:
    if not settings.input_path.exists() or not settings.input_path.is_file():
        raise SubtitleForgeError(f"Input subtitle file was not found: {settings.input_path}")
    if settings.argos_device not in VALID_ARGOS_DEVICES:
        expected = ", ".join(sorted(VALID_ARGOS_DEVICES))
        raise SubtitleForgeError(f"Unsupported Argos device '{settings.argos_device}'. Expected one of: {expected}.")
    if settings.argos_device == "cuda":
        cuda_status = _cuda_status()
        if "CUDA runtime looks loadable" not in cuda_status:
            raise SubtitleForgeError(
                "Argos GPU mode requires the CUDA 12.x runtime libraries. "
                f"Current CUDA status: {cuda_status}. "
                "Install CUDA Toolkit 12.x and make sure its 'bin' directory is on PATH, "
                "or rerun with '--argos-device cpu'."
            )


def _stage_read_subtitles(input_path: Path) -> tuple[list[SubtitleCue], float]:
    started = time.perf_counter()
    _stage("1/6 Reading subtitles", f"Source: {input_path}")
    cues = read_subtitles(input_path)
    _detail(f"{len(cues)} cues loaded")
    return cues, time.perf_counter() - started


def _stage_argos_translation(
    cues: list[SubtitleCue],
    settings: _TranslateSettings,
) -> tuple[list[SubtitleCue], float]:
    started = time.perf_counter()
    _stage("2/6 Argos full-file translation", "Local first pass; timings stay locked")
    with typer.progressbar(length=len(cues), label="Translating cues") as progress:
        argos_cues = translate_cues_with_argos(
            cues,
            settings.source,
            settings.target,
            device_type=settings.argos_device,
            on_cue=lambda _index, _cue: progress.update(1),
        )
    return argos_cues, time.perf_counter() - started


def _stage_normalize(
    argos_cues: list[SubtitleCue],
    settings: _TranslateSettings,
) -> tuple[list[SubtitleCue], dict[str, str], float]:
    started = time.perf_counter()
    _stage("3/6 Normalizing Persian subtitle display", "Adding RTL/LTR controls and safe Persian spacing")
    normalized_cues = normalize_cues_for_target(argos_cues, settings.target, settings.config.allowed_latin_names)
    intermediate_paths = _write_intermediate_files(
        settings.output_path,
        settings.output_format,
        argos_cues,
        normalized_cues,
        settings.keep_intermediate,
    )
    if intermediate_paths:
        _detail(f"Intermediate files kept: {len(intermediate_paths)}")
    return normalized_cues, intermediate_paths, time.perf_counter() - started


def _stage_initial_validation(
    cues: list[SubtitleCue],
    normalized_cues: list[SubtitleCue],
    settings: _TranslateSettings,
) -> tuple[ValidationReport, float]:
    started = time.perf_counter()
    _stage(
        "4/6 Validating and flagging suspicious cues",
        "Checking structure, mojibake, tags, RTL marks, and Latin text",
    )
    report = validate_translation(cues, normalized_cues, settings.config.allowed_latin_names)
    _detail(f"Flagged suspicious cues: {len(report.suspicious_cue_ids)}")
    issue_summary = _issue_summary(report)
    if issue_summary:
        _detail(f"Top issue types: {issue_summary}")
    return report, time.perf_counter() - started


def _stage_cleanup(
    cues: list[SubtitleCue],
    normalized_cues: list[SubtitleCue],
    initial_report: ValidationReport,
    settings: _TranslateSettings,
) -> tuple[list[SubtitleCue], float]:
    started = time.perf_counter()
    flagged_ids = initial_report.suspicious_cue_ids
    batch_count = math.ceil(len(flagged_ids) / settings.cleanup_batch_size) if flagged_ids else 0
    _stage("5/6 AI cleanup", f"{len(flagged_ids)} flagged cues in {batch_count} batches")

    if not batch_count:
        _success("No suspicious cues flagged; skipping AI cleanup.")
        return normalized_cues, time.perf_counter() - started

    provider = _build_cleanup_provider(
        settings.cleanup_provider,
        settings.config,
        settings.target,
        settings.model,
        settings.reasoning_effort,
    )
    cache_path = _cleanup_cache_path(settings)
    cleanup_cache = _load_cleanup_cache(cache_path)
    if cleanup_cache:
        _detail(f"Cleanup cache entries: {len(cleanup_cache)}")

    def on_cleanup_batch(index: int, batch_ids: list[str]) -> None:
        preview = ", ".join(batch_ids[:8])
        suffix = "..." if len(batch_ids) > 8 else ""
        _detail(f"Cleanup batch {index}/{batch_count}: cues {preview}{suffix}")

    with typer.progressbar(length=batch_count, label="Repairing flagged cues") as progress:
        cleaned_cues = cleanup_flagged_cues(
            source_cues=cues,
            current_cues=normalized_cues,
            flagged_ids=flagged_ids,
            issues=initial_report.issues,
            provider=provider,
            source_language=settings.source,
            target_language=settings.target,
            translation_config=settings.translation_config,
            allowed_latin_names=settings.config.allowed_latin_names,
            batch_size=settings.cleanup_batch_size,
            on_batch=lambda index, ids: (on_cleanup_batch(index, ids), progress.update(1)),
            cleanup_cache=cleanup_cache,
        )
    _write_cleanup_cache(cache_path, cleanup_cache)
    return cleaned_cues, time.perf_counter() - started


def _stage_finalize(
    cues: list[SubtitleCue],
    cleaned_cues: list[SubtitleCue],
    settings: _TranslateSettings,
) -> tuple[list[SubtitleCue], ValidationReport, float]:
    started = time.perf_counter()
    _stage("6/6 Final normalization, validation, and write", f"Output: {settings.output_path}")
    final_cues = normalize_cues_for_target(cleaned_cues, settings.target, settings.config.allowed_latin_names)
    final_report = validate_translation(cues, final_cues, settings.config.allowed_latin_names)
    write_subtitles(final_cues, settings.output_path, settings.output_format)
    return final_cues, final_report, time.perf_counter() - started


def _issue_summary(report: ValidationReport) -> str:
    counts = Counter(issue.code for issue in report.issues if issue.code)
    return ", ".join(f"{code}={count}" for code, count in counts.most_common(5))


def _cleanup_cache_path(settings: _TranslateSettings) -> Path:
    return settings.output_path.with_suffix(settings.output_path.suffix + ".cleanup-cache.json")


def _load_cleanup_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(key, str) and isinstance(value, str)}


def _write_cleanup_cache(path: Path, cleanup_cache: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cleanup_cache, ensure_ascii=False, indent=2), encoding="utf-8", newline="")


def _write_intermediate_files(
    output_path: Path,
    output_format: str,
    argos_cues: list[SubtitleCue],
    normalized_cues: list[SubtitleCue],
    keep_intermediate: bool,
) -> dict[str, str]:
    if not keep_intermediate:
        return {}
    argos_path = output_path.with_name(f"{output_path.stem}.argos{output_path.suffix}")
    normalized_path = output_path.with_name(f"{output_path.stem}.normalized{output_path.suffix}")
    write_subtitles(argos_cues, argos_path, output_format)
    write_subtitles(normalized_cues, normalized_path, output_format)
    return {"argos": str(argos_path), "normalized": str(normalized_path)}


def _write_report(
    report_path: Path,
    input_path: Path,
    output_path: Path,
    source_language: str,
    target_language: str,
    initial_report: ValidationReport,
    final_report: ValidationReport,
    intermediate_paths: dict[str, str],
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "input": str(input_path),
        "output": str(output_path),
        "source_language": source_language,
        "target_language": target_language,
        "initial": initial_report.to_dict(),
        "final": final_report.to_dict(),
        "intermediate_paths": intermediate_paths,
        "validation_passed": validation_passed(final_report),
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="")


def _print_translate_header(
    input_path: Path,
    output_path: Path,
    source_language: str,
    target_language: str,
    cleanup_provider: str,
    argos_device: str,
) -> None:
    typer.echo()
    typer.secho("Subtitle Forge", fg=typer.colors.MAGENTA, bold=True)
    typer.echo("Argos first pass -> Persian polish -> targeted AI cleanup")
    typer.echo("-" * 68)
    _metric("Input", str(input_path))
    _metric("Output", str(output_path))
    _metric("Languages", f"{source_language} -> {target_language}")
    _metric("Argos", argos_device)
    _metric("Cleanup", cleanup_provider)


def _stage(title: str, detail: str | None = None) -> None:
    typer.echo()
    typer.secho(f"== {title} ==", fg=typer.colors.CYAN, bold=True)
    if detail:
        _detail(detail)


def _detail(message: str) -> None:
    typer.secho(f"   {message}", fg=typer.colors.BRIGHT_BLACK)


def _success(message: str) -> None:
    typer.secho(f"OK  {message}", fg=typer.colors.GREEN)


def _warning(message: str) -> None:
    typer.secho(f"WARN  {message}", fg=typer.colors.YELLOW)


def _metric(label: str, value: str) -> None:
    typer.echo(f"  {label:<10} {value}")


def _print_summary(
    output_path: Path,
    report_path: Path,
    cue_count: int,
    initial_report: ValidationReport,
    final_report: ValidationReport,
    elapsed_seconds: float,
    timings: list[tuple[str, float]],
) -> None:
    passed = validation_passed(final_report)
    typer.echo()
    typer.secho("Result", fg=typer.colors.GREEN if passed else typer.colors.YELLOW, bold=True)
    typer.echo("-" * 68)
    _metric("Output", str(output_path))
    _metric("Report", str(report_path))
    _metric("Cues", str(cue_count))
    _metric(
        "Flagged",
        f"{len(initial_report.suspicious_cue_ids)} before cleanup, {len(final_report.suspicious_cue_ids)} after",
    )
    _metric("Latin", f"{final_report.disallowed_latin_dialogue_line_count} disallowed dialogue lines")
    _metric("Elapsed", f"{elapsed_seconds:.1f}s")
    _metric("Status", "passed" if passed else "failed")
    if timings:
        timing_text = ", ".join(f"{label} {seconds:.1f}s" for label, seconds in timings)
        _metric("Timing", timing_text)


def _fail(exc: Exception) -> None:
    typer.secho(f"Error: {exc}", fg=typer.colors.RED)
    raise typer.Exit(1)


def _cuda_status() -> str:
    try:
        import ctranslate2
    except ImportError:
        return "CTranslate2 is not installed"

    try:
        device_count = ctranslate2.get_cuda_device_count()
    except Exception as exc:
        return f"CUDA check failed: {exc}"

    if device_count < 1:
        return "no CUDA device visible to CTranslate2"

    added_dirs = configure_cuda_dll_directories()
    try:
        ctypes.CDLL("cublas64_12.dll")
    except OSError:
        return f"{device_count} CUDA device(s), but cublas64_12.dll is not loadable"

    detail = f" via {added_dirs[0]}" if added_dirs else ""
    return f"{device_count} CUDA device(s), CUDA runtime looks loadable{detail}"


if __name__ == "__main__":
    app()

from __future__ import annotations

import math
from pathlib import Path
import subprocess
from typing import Annotated

import typer

from subtitle_forge.argos import translate_cues_with_argos
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
from subtitle_forge.normalization import normalize_cues_for_target
from subtitle_forge.providers import CodexExecProvider, MockProvider, TranslationProvider
from subtitle_forge.quality import validate_translation, validation_passed
from subtitle_forge.subtitles import detect_format, read_subtitles, write_subtitles


app = typer.Typer(help="Translate existing subtitle files while preserving timings.", no_args_is_help=True)


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
    """List available translation providers."""
    config = load_config(config_path)
    typer.echo("Translation pipeline: ArgosTranslate first pass + deterministic normalization + flagged-cue cleanup")
    typer.echo(f"Cleanup provider: {config.cleanup_provider}")
    typer.echo("Available cleanup providers:")
    typer.echo("- codex: uses local Codex CLI for flagged-cue repair")
    typer.echo("- mock: deterministic local cleanup provider for tests and dry runs")


@app.command()
def doctor(
    config_path: Annotated[Path | None, typer.Option("--config", "-c", help="Path to subtitle-forge.toml.")] = None,
):
    """Check local setup for ArgosTranslate and the Codex cleanup provider."""
    config = load_config(config_path)
    try:
        import argostranslate.translate
    except ImportError:
        typer.secho("Missing: ArgosTranslate Python package was not found.", fg=typer.colors.RED)
        raise typer.Exit(1)

    installed_languages = argostranslate.translate.get_installed_languages()
    installed_codes = sorted(language.code for language in installed_languages)
    typer.echo(f"ArgosTranslate: installed languages: {', '.join(installed_codes) or 'none'}")

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
    typer.echo("Pipeline: ArgosTranslate -> normalize -> validate -> Codex cleanup -> normalize -> validate")
    typer.echo("Cleanup provider: codex")
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
    input_path: Annotated[Path, typer.Argument(exists=True, readable=True, help="Subtitle file to translate.")],
    output_path: Annotated[Path, typer.Option("--out", "-o", help="Output subtitle path.")],
    config_path: Annotated[Path | None, typer.Option("--config", "-c", help="Path to subtitle-forge.toml.")] = None,
    source_language: Annotated[str | None, typer.Option("--from", help="Source language code/name.")] = None,
    target_language: Annotated[str | None, typer.Option("--to", help="Target language code/name.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Optional Codex model override.")] = None,
    reasoning_effort: Annotated[str | None, typer.Option("--reasoning-effort", help="Optional Codex reasoning effort.")] = None,
    cleanup_provider_name: Annotated[str | None, typer.Option("--cleanup-provider", help="Cleanup provider: codex or mock.")] = None,
    cleanup_batch_size: Annotated[int | None, typer.Option("--cleanup-batch-size", min=1, help="Flagged cues per cleanup call.")] = None,
    report_path: Annotated[Path | None, typer.Option("--report", help="Validation report path.")] = None,
    keep_intermediate: Annotated[bool, typer.Option("--keep-intermediate", help="Keep Argos and normalized intermediate files.")] = False,
    output_format: Annotated[str | None, typer.Option("--output-format", help="Output format: srt or vtt.")] = None,
    prompt: Annotated[str | None, typer.Option("--prompt", help="Additional prompt instructions.")] = None,
):
    """Translate with Argos first, repair flagged cues with AI, and preserve original timings."""
    config = load_config(config_path)
    source = source_language or config.source_language
    target = target_language or config.target_language
    selected_cleanup_provider = cleanup_provider_name or config.cleanup_provider
    selected_cleanup_batch_size = cleanup_batch_size or config.cleanup_batch_size
    selected_output_format = output_format or output_path.suffix.lstrip(".") or config.output_format
    selected_report_path = report_path or output_path.with_suffix(output_path.suffix + ".report.json")
    selected_keep_intermediate = keep_intermediate or config.keep_intermediate
    translation_config = _merge_translation_config(config.translation, prompt)

    try:
        cleanup_provider = _build_cleanup_provider(selected_cleanup_provider, config, target, model, reasoning_effort)

        typer.echo("1/6 Reading subtitles")
        cues = read_subtitles(input_path)

        typer.echo("2/6 Argos full-file translation")
        with typer.progressbar(length=len(cues), label="Argos cues") as progress:
            argos_cues = translate_cues_with_argos(
                cues,
                source,
                target,
                on_cue=lambda _index, _cue: progress.update(1),
            )

        typer.echo("3/6 Normalizing Persian subtitle display")
        normalized_cues = normalize_cues_for_target(argos_cues, target, config.allowed_latin_names)
        intermediate_paths = _write_intermediate_files(
            output_path,
            selected_output_format,
            argos_cues,
            normalized_cues,
            selected_keep_intermediate,
        )

        typer.echo("4/6 Validating and flagging suspicious cues")
        initial_report = validate_translation(cues, normalized_cues, config.allowed_latin_names)
        flagged_ids = initial_report.suspicious_cue_ids
        typer.echo(f"Flagged suspicious cues: {len(flagged_ids)}")

        batch_count = math.ceil(len(flagged_ids) / selected_cleanup_batch_size) if flagged_ids else 0
        typer.echo(f"5/6 AI cleanup: {len(flagged_ids)} flagged cues in {batch_count} batches")

        def on_cleanup_batch(index: int, batch_ids: list[str]) -> None:
            preview = ", ".join(batch_ids[:8])
            suffix = "..." if len(batch_ids) > 8 else ""
            typer.echo(f"Cleanup batch {index}/{batch_count}: cues {preview}{suffix}")

        with typer.progressbar(length=batch_count, label="Cleanup batches") as progress:
            cleaned_cues = cleanup_flagged_cues(
                source_cues=cues,
                current_cues=normalized_cues,
                flagged_ids=flagged_ids,
                issues=initial_report.issues,
                provider=cleanup_provider,
                source_language=source,
                target_language=target,
                translation_config=translation_config,
                allowed_latin_names=config.allowed_latin_names,
                batch_size=selected_cleanup_batch_size,
                on_batch=lambda index, ids: (on_cleanup_batch(index, ids), progress.update(1)),
            )

        typer.echo("6/6 Final normalization, validation, and write")
        final_cues = normalize_cues_for_target(cleaned_cues, target, config.allowed_latin_names)
        final_report = validate_translation(cues, final_cues, config.allowed_latin_names)
        write_subtitles(final_cues, output_path, selected_output_format)
        _write_report(
            report_path=selected_report_path,
            input_path=input_path,
            output_path=output_path,
            source_language=source,
            target_language=target,
            initial_report=initial_report,
            final_report=final_report,
            intermediate_paths=intermediate_paths,
        )
        _print_summary(output_path, selected_report_path, len(cues), initial_report, final_report)
        if not validation_passed(final_report):
            raise SubtitleForgeError(
                f"Final validation failed with {len(final_report.suspicious_cue_ids)} suspicious cues remaining."
            )
    except SubtitleForgeError as exc:
        _fail(exc)

    typer.echo(f"OK: translated {len(final_cues)} cues to {output_path}")


def _build_cleanup_provider(
    name: str,
    config: AppConfig,
    target_language: str,
    model: str | None,
    reasoning_effort: str | None,
) -> TranslationProvider:
    normalized = name.lower()
    if normalized == "codex":
        selected_reasoning_effort = reasoning_effort if reasoning_effort is not None else (config.codex.reasoning_effort or "low")
        return CodexExecProvider(config.codex, model=model, reasoning_effort=selected_reasoning_effort)
    if normalized == "mock":
        return MockProvider(target_language=target_language)
    raise SubtitleForgeError(f"Unknown cleanup provider '{name}'. Expected one of: codex, mock.")


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


def _write_intermediate_files(
    output_path: Path,
    output_format: str,
    argos_cues,
    normalized_cues,
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
    initial_report,
    final_report,
    intermediate_paths: dict[str, str],
) -> None:
    import json

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


def _print_summary(output_path: Path, report_path: Path, cue_count: int, initial_report, final_report) -> None:
    typer.echo("Summary")
    typer.echo(f"Final output: {output_path}")
    typer.echo(f"Report: {report_path}")
    typer.echo(f"Cue count: {cue_count}")
    typer.echo(f"Flagged before cleanup: {len(initial_report.suspicious_cue_ids)}")
    typer.echo(f"Flagged after cleanup: {len(final_report.suspicious_cue_ids)}")
    typer.echo(f"Disallowed Latin lines: {final_report.disallowed_latin_dialogue_line_count}")
    typer.echo(f"Validation: {'passed' if validation_passed(final_report) else 'failed'}")


def _fail(exc: Exception) -> None:
    typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


if __name__ == "__main__":
    app()

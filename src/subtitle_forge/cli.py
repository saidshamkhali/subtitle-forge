from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Annotated

import typer

from subtitle_forge.config import (
    AppConfig,
    TranslationConfig,
    load_codex_default_model,
    load_codex_default_reasoning_effort,
    load_config,
)
from subtitle_forge.bidi import VALID_RTL_MODES, stabilize_cues_for_rtl_display
from subtitle_forge.errors import SubtitleForgeError
from subtitle_forge.executables import resolve_executable
from subtitle_forge.providers import CodexExecProvider, MockProvider, OpenAICompatibleProvider, TranslationProvider
from subtitle_forge.subtitles import detect_format, read_subtitles, write_subtitles
from subtitle_forge.translation import translate_cues


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
    typer.echo(f"Default provider: {config.provider}")
    typer.echo("Available providers:")
    typer.echo("- codex: active MVP provider using local Codex CLI")
    typer.echo("- mock: deterministic local provider for tests and dry runs")
    typer.echo("- openai-compatible: planned future provider, not active in MVP")


@app.command()
def doctor(
    config_path: Annotated[Path | None, typer.Option("--config", "-c", help="Path to subtitle-forge.toml.")] = None,
):
    """Check local setup for the Codex CLI provider."""
    config = load_config(config_path)
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
    typer.echo("Provider: codex")
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
    provider_name: Annotated[str | None, typer.Option("--provider", help="Provider: codex or mock.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Optional Codex model override.")] = None,
    reasoning_effort: Annotated[str | None, typer.Option("--reasoning-effort", help="Optional Codex reasoning effort.")] = None,
    output_format: Annotated[str | None, typer.Option("--output-format", help="Output format: srt or vtt.")] = None,
    batch_size: Annotated[int | None, typer.Option("--batch-size", min=1, help="Number of cues per provider call.")] = None,
    rtl_mode: Annotated[str | None, typer.Option("--rtl-mode", help="RTL display handling: auto, off, or marks.")] = None,
    prompt: Annotated[str | None, typer.Option("--prompt", help="Additional prompt instructions.")] = None,
):
    """Translate subtitles using a provider and preserve original timings."""
    config = load_config(config_path)
    source = source_language or config.source_language
    target = target_language or config.target_language
    selected_provider = provider_name or config.provider
    selected_batch_size = batch_size or config.batch_size
    selected_output_format = output_format or output_path.suffix.lstrip(".") or config.output_format
    selected_rtl_mode = rtl_mode or config.rtl_mode
    translation_config = _merge_translation_config(config.translation, prompt)

    try:
        if selected_rtl_mode.lower() not in VALID_RTL_MODES:
            expected = ", ".join(sorted(VALID_RTL_MODES))
            raise SubtitleForgeError(f"Unsupported RTL mode '{selected_rtl_mode}'. Expected one of: {expected}.")
        cues = read_subtitles(input_path)
        provider = _build_provider(selected_provider, config, target, model, reasoning_effort)
        translated = translate_cues(
            cues=cues,
            provider=provider,
            source_language=source,
            target_language=target,
            translation_config=translation_config,
            batch_size=selected_batch_size,
        )
        translated = stabilize_cues_for_rtl_display(translated, target, selected_rtl_mode)
        write_subtitles(translated, output_path, selected_output_format)
    except SubtitleForgeError as exc:
        _fail(exc)

    typer.echo(f"OK: translated {len(translated)} cues to {output_path}")


def _build_provider(
    name: str,
    config: AppConfig,
    target_language: str,
    model: str | None,
    reasoning_effort: str | None,
) -> TranslationProvider:
    normalized = name.lower()
    if normalized == "codex":
        return CodexExecProvider(config.codex, model=model, reasoning_effort=reasoning_effort)
    if normalized == "mock":
        return MockProvider(target_language=target_language)
    if normalized in {"openai", "openai-compatible", "openai_compatible"}:
        return OpenAICompatibleProvider()
    raise SubtitleForgeError(f"Unknown provider '{name}'. Expected one of: codex, mock.")


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


def _fail(exc: Exception) -> None:
    typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


if __name__ == "__main__":
    app()

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from subtitle_forge.argos import TextTranslator, translate_cues_with_argos
from subtitle_forge.cleanup import cleanup_flagged_cues
from subtitle_forge.config import TranslationConfig
from subtitle_forge.errors import TranslationValidationError
from subtitle_forge.models import SubtitleCue
from subtitle_forge.normalization import normalize_cues_for_target
from subtitle_forge.providers import TranslationProvider
from subtitle_forge.quality import ValidationReport, validate_translation, validation_passed
from subtitle_forge.subtitles import read_subtitles, write_subtitles


@dataclass(frozen=True)
class HybridTranslationResult:
    source_cues: list[SubtitleCue]
    argos_cues: list[SubtitleCue]
    normalized_cues: list[SubtitleCue]
    final_cues: list[SubtitleCue]
    initial_report: ValidationReport
    final_report: ValidationReport
    intermediate_paths: dict[str, str]


def run_hybrid_translation(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    source_language: str,
    target_language: str,
    output_format: str,
    cleanup_provider: TranslationProvider,
    translation_config: TranslationConfig,
    allowed_latin_names: list[str],
    cleanup_batch_size: int,
    keep_intermediate: bool,
    argos_translator: TextTranslator | None = None,
    on_stage: Callable[[str], None] | None = None,
    on_argos_cue: Callable[[int, SubtitleCue], None] | None = None,
    on_cleanup_batch: Callable[[int, list[str]], None] | None = None,
) -> HybridTranslationResult:
    _stage(on_stage, "1/6 Reading subtitles")
    source_cues = read_subtitles(input_path)

    _stage(on_stage, "2/6 Argos full-file translation")
    argos_cues = translate_cues_with_argos(
        source_cues,
        source_language,
        target_language,
        translator=argos_translator,
        on_cue=on_argos_cue,
    )

    _stage(on_stage, "3/6 Normalizing Persian subtitle display")
    normalized_cues = normalize_cues_for_target(argos_cues, target_language, allowed_latin_names)

    intermediate_paths: dict[str, str] = {}
    if keep_intermediate:
        argos_path = _intermediate_path(output_path, ".argos")
        normalized_path = _intermediate_path(output_path, ".normalized")
        write_subtitles(argos_cues, argos_path, output_format)
        write_subtitles(normalized_cues, normalized_path, output_format)
        intermediate_paths = {"argos": str(argos_path), "normalized": str(normalized_path)}

    _stage(on_stage, "4/6 Validating and flagging suspicious cues")
    initial_report = validate_translation(source_cues, normalized_cues, allowed_latin_names)
    flagged_ids = initial_report.suspicious_cue_ids

    _stage(on_stage, f"5/6 AI cleanup: {len(flagged_ids)} flagged cues")
    cleaned_cues = cleanup_flagged_cues(
        source_cues=source_cues,
        current_cues=normalized_cues,
        flagged_ids=flagged_ids,
        issues=initial_report.issues,
        provider=cleanup_provider,
        source_language=source_language,
        target_language=target_language,
        translation_config=translation_config,
        allowed_latin_names=allowed_latin_names,
        batch_size=cleanup_batch_size,
        on_batch=on_cleanup_batch,
    )

    _stage(on_stage, "6/6 Final normalization, validation, and write")
    final_cues = normalize_cues_for_target(cleaned_cues, target_language, allowed_latin_names)
    final_report = validate_translation(source_cues, final_cues, allowed_latin_names)
    write_subtitles(final_cues, output_path, output_format)
    _write_report(
        report_path=report_path,
        input_path=input_path,
        output_path=output_path,
        source_language=source_language,
        target_language=target_language,
        initial_report=initial_report,
        final_report=final_report,
        intermediate_paths=intermediate_paths,
    )

    if not validation_passed(final_report):
        raise TranslationValidationError(
            "Final validation failed. "
            f"Suspicious cues remaining: {len(final_report.suspicious_cue_ids)}. "
            f"Report written to {report_path}."
        )

    return HybridTranslationResult(
        source_cues=source_cues,
        argos_cues=argos_cues,
        normalized_cues=normalized_cues,
        final_cues=final_cues,
        initial_report=initial_report,
        final_report=final_report,
        intermediate_paths=intermediate_paths,
    )


def _stage(callback: Callable[[str], None] | None, message: str) -> None:
    if callback:
        callback(message)


def _intermediate_path(output_path: Path, suffix: str) -> Path:
    return output_path.with_name(f"{output_path.stem}{suffix}{output_path.suffix}")


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

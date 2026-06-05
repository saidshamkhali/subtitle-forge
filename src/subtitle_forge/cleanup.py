from __future__ import annotations

import json
from typing import Callable

from subtitle_forge.config import TranslationConfig
from subtitle_forge.errors import TranslationValidationError
from subtitle_forge.models import SubtitleCue
from subtitle_forge.normalization import strip_bidi_and_invisible
from subtitle_forge.providers import TranslationProvider
from subtitle_forge.quality import CueIssue


def cleanup_flagged_cues(
    source_cues: list[SubtitleCue],
    current_cues: list[SubtitleCue],
    flagged_ids: list[str],
    issues: list[CueIssue],
    provider: TranslationProvider,
    source_language: str,
    target_language: str,
    translation_config: TranslationConfig,
    allowed_latin_names: list[str],
    batch_size: int,
    on_batch: Callable[[int, list[str]], None] | None = None,
) -> list[SubtitleCue]:
    if batch_size < 1:
        raise TranslationValidationError("Cleanup batch size must be at least 1.")
    if not flagged_ids:
        return current_cues

    source_by_id = {cue.id: cue for cue in source_cues}
    current_by_id = {cue.id: cue for cue in current_cues}
    corrected = dict(current_by_id)
    for index, batch_ids in enumerate(_batches(flagged_ids, batch_size), start=1):
        prompt = build_cleanup_prompt(
            batch_ids=batch_ids,
            source_by_id=source_by_id,
            current_by_id=corrected,
            issues=issues,
            source_language=source_language,
            target_language=target_language,
            translation_config=translation_config,
            allowed_latin_names=allowed_latin_names,
        )
        if on_batch:
            on_batch(index, batch_ids)
        response = provider.translate_batch(prompt)
        fixes = parse_cleanup_response(response, batch_ids)
        for cue_id, text in fixes.items():
            corrected[cue_id] = corrected[cue_id].with_text(text)

    return [corrected[cue.id] for cue in current_cues]


def build_cleanup_prompt(
    batch_ids: list[str],
    source_by_id: dict[str, SubtitleCue],
    current_by_id: dict[str, SubtitleCue],
    issues: list[CueIssue],
    source_language: str,
    target_language: str,
    translation_config: TranslationConfig,
    allowed_latin_names: list[str],
) -> str:
    issue_map: dict[str, list[str]] = {}
    for issue in issues:
        if issue.cue_id in batch_ids:
            issue_map.setdefault(issue.cue_id, []).append(issue.code)

    payload = []
    for cue_id in batch_ids:
        if cue_id not in source_by_id:
            raise TranslationValidationError(f"Cannot cleanup cue {cue_id!r}: source cue id is missing.")
        if cue_id not in current_by_id:
            raise TranslationValidationError(f"Cannot cleanup cue {cue_id!r}: current cue id is missing.")
        source = source_by_id[cue_id]
        current = current_by_id[cue_id]
        payload.append(
            {
                "id": cue_id,
                "src": source.text,
                "mt": strip_bidi_and_invisible(current.text),
                "issues": issue_map.get(cue_id, []),
            }
        )

    custom_prompt = f"\nExtra: {translation_config.prompt}" if translation_config.prompt else ""
    return f"""Repair only these suspicious subtitle cues.
Return JSON object only: {{"cue_id":"corrected text"}}.
Rules: {source_language}->{target_language}; use src for meaning; use mt if usable; preserve <i>/<b>/<u>; no cue numbers/timestamps; no bidi controls; no Latin except: {", ".join(allowed_latin_names)}; style: {translation_config.style}.{custom_prompt}
Cues:
{json.dumps(payload, ensure_ascii=False)}
"""


def parse_cleanup_response(response: str, expected_ids: list[str]) -> dict[str, str]:
    try:
        data = json.loads(response)
    except json.JSONDecodeError as exc:
        raise TranslationValidationError(f"Cleanup provider response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TranslationValidationError("Cleanup provider response must be a JSON object.")

    expected = set(expected_ids)
    fixes: dict[str, str] = {}
    for cue_id, text in data.items():
        if cue_id not in expected:
            raise TranslationValidationError(f"Cleanup provider returned unknown cue id {cue_id!r}.")
        if not isinstance(text, str):
            raise TranslationValidationError(f"Cleanup correction for cue {cue_id!r} must be a string.")
        fixes[cue_id] = text

    missing = [cue_id for cue_id in expected_ids if cue_id not in fixes]
    if missing:
        raise TranslationValidationError(f"Cleanup provider response is missing cue ids: {', '.join(missing)}.")
    return fixes


def _batches(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]

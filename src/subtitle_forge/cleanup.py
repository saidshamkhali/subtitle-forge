from __future__ import annotations

import hashlib
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
    cleanup_cache: dict[str, str] | None = None,
) -> list[SubtitleCue]:
    if batch_size < 1:
        raise TranslationValidationError("Cleanup batch size must be at least 1.")
    if not flagged_ids:
        return current_cues

    source_by_id = {cue.id: cue for cue in source_cues}
    current_by_id = {cue.id: cue for cue in current_cues}
    stripped_current_text = {cue.id: strip_bidi_and_invisible(cue.text) for cue in current_cues}
    issue_codes_by_id = _issue_codes_by_id(issues, set(flagged_ids))
    corrected = dict(current_by_id)

    uncached_ids: list[str] = []
    cache_keys: dict[str, str] = {}
    for cue_id in flagged_ids:
        if cue_id not in source_by_id:
            raise TranslationValidationError(f"Cannot cleanup cue {cue_id!r}: source cue id is missing.")
        if cue_id not in current_by_id:
            raise TranslationValidationError(f"Cannot cleanup cue {cue_id!r}: current cue id is missing.")
        cache_key = build_cleanup_cache_key(
            source_text=source_by_id[cue_id].text,
            mt_text=stripped_current_text[cue_id],
            issue_codes=issue_codes_by_id.get(cue_id, []),
            source_language=source_language,
            target_language=target_language,
            translation_config=translation_config,
            allowed_latin_names=allowed_latin_names,
        )
        cache_keys[cue_id] = cache_key
        if cleanup_cache is not None and cache_key in cleanup_cache:
            corrected[cue_id] = corrected[cue_id].with_text(cleanup_cache[cache_key])
        else:
            uncached_ids.append(cue_id)

    for index, batch_ids in enumerate(_batches(uncached_ids, batch_size), start=1):
        prompt = build_cleanup_prompt(
            batch_ids=batch_ids,
            source_by_id=source_by_id,
            current_by_id=corrected,
            issues=issues,
            source_language=source_language,
            target_language=target_language,
            translation_config=translation_config,
            allowed_latin_names=allowed_latin_names,
            stripped_current_text=stripped_current_text,
        )
        if on_batch:
            on_batch(index, batch_ids)
        response = provider.translate_batch(prompt)
        fixes = parse_cleanup_response(response, batch_ids)
        for cue_id, text in fixes.items():
            corrected[cue_id] = corrected[cue_id].with_text(text)
            if cleanup_cache is not None:
                cleanup_cache[cache_keys[cue_id]] = text

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
    stripped_current_text: dict[str, str] | None = None,
) -> str:
    issue_map = _issue_codes_by_id(issues, set(batch_ids))

    payload = []
    for cue_id in batch_ids:
        if cue_id not in source_by_id:
            raise TranslationValidationError(f"Cannot cleanup cue {cue_id!r}: source cue id is missing.")
        if cue_id not in current_by_id:
            raise TranslationValidationError(f"Cannot cleanup cue {cue_id!r}: current cue id is missing.")
        source = source_by_id[cue_id]
        mt_text = (
            stripped_current_text[cue_id]
            if stripped_current_text is not None
            else strip_bidi_and_invisible(current_by_id[cue_id].text)
        )
        payload.append(
            {
                "id": cue_id,
                "src": source.text,
                "mt": mt_text,
                "issues": issue_map.get(cue_id, []),
            }
        )

    allowed_names = ", ".join(allowed_latin_names) or "none"
    custom_prompt = f"\nExtra: {translation_config.prompt}" if translation_config.prompt else ""
    return f"""Repair only these suspicious subtitle cues.
Return JSON object only: {{"cue_id":"corrected text"}}.
Rules: {source_language}->{target_language}; use src for meaning; use mt if usable; preserve <i>/<b>/<u>; no cue numbers/timestamps; no bidi controls; no Latin except: {allowed_names}; style: {translation_config.style}.{custom_prompt}
Cues:
{json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}
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


def build_cleanup_cache_key(
    source_text: str,
    mt_text: str,
    issue_codes: list[str],
    source_language: str,
    target_language: str,
    translation_config: TranslationConfig,
    allowed_latin_names: list[str],
) -> str:
    payload = {
        "source_text": source_text,
        "mt_text": mt_text,
        "issue_codes": issue_codes,
        "source_language": source_language,
        "target_language": target_language,
        "style": translation_config.style,
        "prompt": translation_config.prompt,
        "allowed_latin_names": allowed_latin_names,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _issue_codes_by_id(issues: list[CueIssue], cue_ids: set[str]) -> dict[str, list[str]]:
    issue_map: dict[str, list[str]] = {}
    for issue in issues:
        if issue.cue_id in cue_ids:
            codes = issue_map.setdefault(issue.cue_id, [])
            if issue.code not in codes:
                codes.append(issue.code)
    return issue_map


def _batches(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]

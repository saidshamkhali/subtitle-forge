from __future__ import annotations

import json

from subtitle_forge.config import TranslationConfig
from subtitle_forge.errors import TranslationValidationError
from subtitle_forge.models import SubtitleCue
from subtitle_forge.prompting import build_translation_prompt
from subtitle_forge.providers import TranslationProvider


def translate_cues(
    cues: list[SubtitleCue],
    provider: TranslationProvider,
    source_language: str,
    target_language: str,
    translation_config: TranslationConfig,
    batch_size: int = 50,
) -> list[SubtitleCue]:
    if batch_size < 1:
        raise TranslationValidationError("Batch size must be at least 1.")

    translated: list[SubtitleCue] = []
    for batch in _batches(cues, batch_size):
        prompt = build_translation_prompt(batch, source_language, target_language, translation_config)
        response = provider.translate_batch(prompt)
        translations = parse_provider_response(response, batch)
        translated.extend([cue.with_text(translations[cue.id]) for cue in batch])
    return translated


def parse_provider_response(response: str, batch: list[SubtitleCue]) -> dict[str, str]:
    try:
        data = json.loads(response)
    except json.JSONDecodeError as exc:
        raise TranslationValidationError(f"Provider response was not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise TranslationValidationError("Provider response must be a JSON array.")

    expected_ids = [cue.id for cue in batch]
    expected_set = set(expected_ids)
    if len(data) != len(batch):
        raise TranslationValidationError(f"Expected {len(batch)} translations, received {len(data)}.")

    translations: dict[str, str] = {}
    for item in data:
        if not isinstance(item, dict):
            raise TranslationValidationError("Every translation item must be a JSON object.")
        extra_fields = set(item) - {"id", "text"}
        if extra_fields:
            fields = ", ".join(sorted(extra_fields))
            raise TranslationValidationError(f"Translation item contains unsupported fields: {fields}.")
        cue_id = item.get("id")
        text = item.get("text")
        if not isinstance(cue_id, str):
            raise TranslationValidationError("Every translation item must include string field 'id'.")
        if not isinstance(text, str):
            raise TranslationValidationError(f"Translation for cue {cue_id!r} must include string field 'text'.")
        if cue_id not in expected_set:
            raise TranslationValidationError(f"Provider returned unknown cue id {cue_id!r}.")
        if cue_id in translations:
            raise TranslationValidationError(f"Provider returned duplicate cue id {cue_id!r}.")
        translations[cue_id] = text

    missing = [cue_id for cue_id in expected_ids if cue_id not in translations]
    if missing:
        raise TranslationValidationError(f"Provider response is missing cue ids: {', '.join(missing)}.")

    return translations


def _batches(cues: list[SubtitleCue], size: int) -> list[list[SubtitleCue]]:
    return [cues[index : index + size] for index in range(0, len(cues), size)]

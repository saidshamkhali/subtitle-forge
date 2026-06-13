from __future__ import annotations

import json

from subtitle_forge.config import TranslationConfig
from subtitle_forge.languages import language_label
from subtitle_forge.logging_config import get_logger
from subtitle_forge.models import SubtitleCue

logger = get_logger("prompting")


def build_translation_prompt(
    cues: list[SubtitleCue],
    source_language: str,
    target_language: str,
    translation: TranslationConfig,
) -> str:
    logger.debug("Building translation prompt for %d cues, %s -> %s", len(cues), source_language, target_language)
    custom = f"\nAdditional project prompt:\n{translation.prompt}\n" if translation.prompt else ""
    payload = [{"id": cue.id, "text": cue.text} for cue in cues]
    source = language_label(source_language)
    target = language_label(target_language)
    names_rule = (
        f"Do not translate proper names unless {target} has a widely known equivalent."
        if translation.preserve_names
        else "Translate proper names only when that is natural for the target audience."
    )
    formatting_rule = (
        "Preserve simple formatting tags such as <i>, <b>, and <u>."
        if translation.preserve_formatting
        else "Keep formatting readable for the target subtitle format."
    )
    rtl_rules = _rtl_prompt_rules(target_language)

    return f"""You are translating subtitles from {source} to {target}.

Return only valid JSON. Do not include markdown, comments, explanations, or extra text.
The JSON must be an array of objects. Each object must have exactly:
- "id": the original cue id as a string
- "text": the translated subtitle text

Rules:
- Translate naturally for subtitles.
- Keep line breaks where they help readability.
- {formatting_rule}
- {names_rule}
- Do not add explanations or notes.
- Do not change, invent, remove, merge, or split cue ids.
- For Persian/Farsi and other right-to-left languages, return normal UTF-8 text without visual reshaping.
- {rtl_rules}
- Style: {translation.style}.{custom}

Subtitles to translate:
{json.dumps(payload, ensure_ascii=False)}
"""


def _rtl_prompt_rules(target_language: str) -> str:
    if target_language.lower() not in {"fa", "fas", "per", "persian", "farsi", "persian/farsi"}:
        return "If the target language is right-to-left, keep mixed-language text in natural reading order."

    return (
        "For Persian/Farsi, preserve brand names and product names such as Subtitle Forge unless a user-provided "
        "equivalent exists, but place them where they naturally belong in Persian word order. Avoid awkward "
        "mixed Persian/English ordering; when an English brand appears inside a Persian sentence, keep the full "
        "brand phrase together and write the surrounding Persian so the sentence reads naturally. For phrases like "
        "'Welcome to [English Brand]', prefer wording that keeps the English brand at the end of the logical "
        "sentence when natural, such as the Persian equivalent of 'Welcome to Subtitle Forge' written as "
        "'خوش آمدید به Subtitle Forge'."
    )

from __future__ import annotations

import re
from typing import Callable, Protocol

from subtitle_forge.errors import ProviderError
from subtitle_forge.models import SubtitleCue


TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")


class TextTranslator(Protocol):
    def translate(self, text: str) -> str:
        ...


def translate_cues_with_argos(
    cues: list[SubtitleCue],
    source_language: str,
    target_language: str,
    translator: TextTranslator | None = None,
    on_cue: Callable[[int, SubtitleCue], None] | None = None,
) -> list[SubtitleCue]:
    engine = translator or get_argos_translation(source_language, target_language)
    translated: list[SubtitleCue] = []
    for index, cue in enumerate(cues, start=1):
        if on_cue:
            on_cue(index, cue)
        translated.append(cue.with_text(_translate_text_preserving_tags(cue.text, engine)))
    return translated


def get_argos_translation(source_language: str, target_language: str) -> TextTranslator:
    try:
        import argostranslate.translate
    except ImportError as exc:
        raise ProviderError(
            "ArgosTranslate is required for Subtitle Forge. Install project dependencies, then retry."
        ) from exc

    installed = argostranslate.translate.get_installed_languages()
    source = next((language for language in installed if language.code == source_language), None)
    target = next((language for language in installed if language.code == target_language), None)
    if source is None:
        codes = ", ".join(sorted(language.code for language in installed)) or "none"
        raise ProviderError(f"Argos source language is not installed: {source_language}. Installed: {codes}.")
    if target is None:
        codes = ", ".join(sorted(language.code for language in installed)) or "none"
        raise ProviderError(f"Argos target language is not installed: {target_language}. Installed: {codes}.")

    translation = source.get_translation(target)
    if translation is None:
        raise ProviderError(f"Argos translation path is not installed: {source_language} -> {target_language}.")
    return translation


def _translate_text_preserving_tags(text: str, translator: TextTranslator) -> str:
    lines = text.splitlines()
    if not lines:
        return translator.translate(text).strip()
    return "\n".join(_translate_line_preserving_tags(line, translator) for line in lines)


def _translate_line_preserving_tags(line: str, translator: TextTranslator) -> str:
    parts = TAG_RE.split(line)
    tags = TAG_RE.findall(line)
    translated_parts = [_translate_plain_part(part, translator) for part in parts]
    translated = translated_parts[0]
    for tag, part in zip(tags, translated_parts[1:]):
        translated += tag + part
    return translated.replace("\r", " ").replace("\n", " ").strip()


def _translate_plain_part(text: str, translator: TextTranslator) -> str:
    if not text.strip():
        return text
    leading = text[: len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()) :]
    return f"{leading}{translator.translate(text.strip()).strip()}{trailing}"

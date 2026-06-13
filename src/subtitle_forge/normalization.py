from __future__ import annotations

import re

from subtitle_forge.bidi import LTR_EMBEDDING, POP_DIRECTIONAL_FORMATTING, RTL_EMBEDDING, is_rtl_language
from subtitle_forge.logging_config import get_logger
from subtitle_forge.models import SubtitleCue

logger = get_logger("normalization")


BIDI_OR_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
PERSIAN_RE = re.compile(r"[\u0600-\u06ff]")
TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
ZWNJ = "\u200c"

_ALLOWED_LATIN_NAME_PATTERNS: dict[str, re.Pattern] = {}


def _get_latin_name_pattern(name: str) -> re.Pattern:
    if name not in _ALLOWED_LATIN_NAME_PATTERNS:
        _ALLOWED_LATIN_NAME_PATTERNS[name] = re.compile(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])")
    return _ALLOWED_LATIN_NAME_PATTERNS[name]

DEFAULT_ALLOWED_LATIN_NAMES = [
    "City Hunter",
    "Kaori",
    "Kiyoko",
    "Imamura",
    "MacDonald",
    "Olsen Park",
    "Hong Kong",
    "Mah Jong",
    "Thunder Strikers",
    "Dragon Claw",
    "White Crane",
]


def normalize_cues_for_target(
    cues: list[SubtitleCue],
    target_language: str,
    allowed_latin_names: list[str],
) -> list[SubtitleCue]:
    rtl = is_rtl_language(target_language)
    logger.debug("Normalizing %d cues, target=%s, rtl=%s", len(cues), target_language, rtl)
    if not rtl:
        return [_strip_structural_marks(cue) for cue in cues]
    return [_strip_structural_marks(cue).with_text(normalize_persian_text(cue.text, allowed_latin_names)) for cue in cues]


def normalize_persian_text(text: str, allowed_latin_names: list[str]) -> str:
    lines = text.splitlines()
    if not lines:
        return _wrap_rtl_line(_normalize_persian_spacing(text), allowed_latin_names)
    return "\n".join(_wrap_rtl_line(_normalize_persian_spacing(line), allowed_latin_names) for line in lines)


def strip_bidi_and_invisible(text: str) -> str:
    return BIDI_OR_INVISIBLE_RE.sub("", text)


def strip_tags(text: str) -> str:
    return TAG_RE.sub("", text)


def strip_allowed_latin_names(text: str, allowed_latin_names: list[str]) -> str:
    stripped = text
    for name in sorted(allowed_latin_names, key=len, reverse=True):
        stripped = _get_latin_name_pattern(name).sub("", stripped)
    return stripped


def _strip_structural_marks(cue: SubtitleCue) -> SubtitleCue:
    return SubtitleCue(
        id=strip_bidi_and_invisible(cue.id),
        start=cue.start,
        end=cue.end,
        text=cue.text,
    )


def _wrap_rtl_line(line: str, allowed_latin_names: list[str]) -> str:
    stripped = strip_outer_rtl(line)
    wrapped_names = _wrap_allowed_latin_names(stripped, allowed_latin_names)
    return f"{RTL_EMBEDDING}{wrapped_names}{POP_DIRECTIONAL_FORMATTING}"


def strip_outer_rtl(line: str) -> str:
    stripped = line
    if stripped.startswith(RTL_EMBEDDING) and stripped.endswith(POP_DIRECTIONAL_FORMATTING):
        stripped = stripped[1:-1]
    return stripped


def _wrap_allowed_latin_names(text: str, allowed_latin_names: list[str]) -> str:
    stripped = strip_bidi_and_invisible(text)
    for name in sorted(allowed_latin_names, key=len, reverse=True):
        stripped = _get_latin_name_pattern(name).sub(f"{LTR_EMBEDDING}{name}{POP_DIRECTIONAL_FORMATTING}", stripped)
    return stripped


def _normalize_persian_spacing(text: str) -> str:
    normalized = text
    replacements = {
        "می ": f"می{ZWNJ}",
        "نمی ": f"نمی{ZWNJ}",
        "بی نقص": f"بی{ZWNJ}نقص",
        "کم پشت": f"کم{ZWNJ}پشت",
        "چشم های": f"چشم{ZWNJ}های",
        "گوش های": f"گوش{ZWNJ}های",
        "رسیده اند": f"رسیده{ZWNJ}اند",
    }
    for before, after in replacements.items():
        normalized = normalized.replace(before, after)
    return normalized

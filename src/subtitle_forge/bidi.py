from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from subtitle_forge.models import SubtitleCue

RTL_EMBEDDING = "\u202b"
LTR_EMBEDDING = "\u202a"
POP_DIRECTIONAL_FORMATTING = "\u202c"

RTL_LANGUAGES = {"fa", "fas", "per", "persian", "farsi", "persian/farsi", "ar", "arabic", "he", "hebrew", "ur", "urdu"}
VALID_RTL_MODES = {"auto", "off", "marks"}

_TAG_OR_ASCII_RUN = re.compile(r"(<[^>]+>)|([A-Za-z0-9][A-Za-z0-9 ._&'\u2019:-]*[A-Za-z0-9])")


def stabilize_cues_for_rtl_display(cues: list[SubtitleCue], target_language: str, mode: str) -> list[SubtitleCue]:
    normalized_mode = mode.lower()
    if normalized_mode not in VALID_RTL_MODES:
        expected = ", ".join(sorted(VALID_RTL_MODES))
        raise ValueError(f"Unsupported RTL mode '{mode}'. Expected one of: {expected}.")
    if normalized_mode == "off":
        return cues
    if normalized_mode == "auto" and not is_rtl_language(target_language):
        return cues
    return [cue.with_text(stabilize_text_for_rtl_display(cue.text)) for cue in cues]


def is_rtl_language(language: str) -> bool:
    return language.lower() in RTL_LANGUAGES


def stabilize_text_for_rtl_display(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    return "\n".join(_wrap_rtl_line(line) for line in lines)


def _wrap_rtl_line(line: str) -> str:
    if line.startswith(RTL_EMBEDDING) and line.endswith(POP_DIRECTIONAL_FORMATTING):
        return line
    return f"{RTL_EMBEDDING}{_isolate_ltr_runs(line)}{POP_DIRECTIONAL_FORMATTING}"


def _isolate_ltr_runs(line: str) -> str:
    def replace(match: re.Match[str]) -> str:
        tag, ascii_run = match.groups()
        if tag is not None:
            return tag
        if ascii_run is None:
            return match.group(0)
        stripped = ascii_run.strip()
        if not stripped or len(stripped) == 1:
            return ascii_run
        prefix = ascii_run[: len(ascii_run) - len(ascii_run.lstrip())]
        suffix = ascii_run[len(ascii_run.rstrip()) :]
        return f"{prefix}{LTR_EMBEDDING}{stripped}{POP_DIRECTIONAL_FORMATTING}{suffix}"

    return _TAG_OR_ASCII_RUN.sub(replace, line)

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import srt
import webvtt

from subtitle_forge.errors import SubtitleParseError
from subtitle_forge.logging_config import get_logger
from subtitle_forge.models import SubtitleCue

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger("subtitles")


SUPPORTED_FORMATS = {"srt", "vtt"}


def detect_format(path: Path, explicit_format: str | None = None) -> str:
    value = (explicit_format or path.suffix.lstrip(".")).lower()
    if value not in SUPPORTED_FORMATS:
        raise SubtitleParseError(f"Unsupported subtitle format '{value}'. Expected one of: srt, vtt.")
    return value


def read_subtitles(path: Path, input_format: str | None = None) -> list[SubtitleCue]:
    fmt = detect_format(path, input_format)
    logger.debug("Reading %s subtitles from %s", fmt, path)
    try:
        if fmt == "srt":
            cues = _read_srt(path)
        elif fmt == "vtt":
            cues = _read_vtt(path)
        else:
            raise SubtitleParseError(f"Unsupported subtitle format '{fmt}'.")
    except SubtitleParseError:
        raise
    except Exception as exc:
        raise SubtitleParseError(f"Could not parse {path}: {exc}") from exc

    _reject_duplicate_cue_ids(cues)
    logger.debug("Loaded %d cues from %s", len(cues), path)
    return cues


def write_subtitles(cues: list[SubtitleCue], path: Path, output_format: str | None = None) -> None:
    fmt = detect_format(path, output_format)
    logger.debug("Writing %d cues as %s to %s", len(cues), fmt, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "srt":
        path.write_text(_format_srt(cues), encoding="utf-8")
        return
    if fmt == "vtt":
        path.write_text(_format_vtt(cues), encoding="utf-8")
        return
    raise SubtitleParseError(f"Unsupported subtitle format '{fmt}'.")


def _read_srt(path: Path) -> list[SubtitleCue]:
    content = path.read_text(encoding="utf-8-sig")
    parsed = list(srt.parse(content))
    return [
        SubtitleCue(id=str(item.index), start=item.start, end=item.end, text=item.content)
        for item in parsed
    ]


def _read_vtt(path: Path) -> list[SubtitleCue]:
    captions = webvtt.read(str(path))
    cues: list[SubtitleCue] = []
    for index, caption in enumerate(captions, start=1):
        cues.append(
            SubtitleCue(
                id=caption.identifier or str(index),
                start=_parse_vtt_timestamp(caption.start),
                end=_parse_vtt_timestamp(caption.end),
                text=caption.text,
            )
        )
    return cues


def _reject_duplicate_cue_ids(cues: list[SubtitleCue]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for cue in cues:
        if cue.id in seen and cue.id not in duplicates:
            duplicates.append(cue.id)
        seen.add(cue.id)

    if duplicates:
        duplicate_text = ", ".join(repr(cue_id) for cue_id in duplicates)
        logger.warning("Duplicate subtitle cue ids found: %s", duplicate_text)
        raise SubtitleParseError(f"Duplicate subtitle cue id(s) found: {duplicate_text}. Cue ids must be unique.")


def _format_srt(cues: list[SubtitleCue]) -> str:
    subtitles = [
        srt.Subtitle(index=_srt_index(cue.id, fallback), start=cue.start, end=cue.end, content=cue.text)
        for fallback, cue in enumerate(cues, start=1)
    ]
    return srt.compose(subtitles, reindex=False)


def _format_vtt(cues: list[SubtitleCue]) -> str:
    lines = ["WEBVTT", ""]
    for cue in cues:
        if cue.id:
            lines.append(cue.id)
        lines.append(f"{_format_vtt_timestamp(cue.start)} --> {_format_vtt_timestamp(cue.end)}")
        lines.extend(cue.text.splitlines() or [""])
        lines.append("")
    return "\n".join(lines)


def _srt_index(cue_id: str, fallback: int) -> int:
    try:
        return int(cue_id)
    except ValueError:
        return fallback


def _parse_vtt_timestamp(value: str) -> timedelta:
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes_text, seconds_text = parts
    elif len(parts) == 3:
        hours = int(parts[0])
        minutes_text, seconds_text = parts[1:]
    else:
        raise ValueError(f"Invalid VTT timestamp: {value}")

    seconds, milliseconds = seconds_text.split(".")
    return timedelta(
        hours=hours,
        minutes=int(minutes_text),
        seconds=int(seconds),
        milliseconds=int(milliseconds.ljust(3, "0")[:3]),
    )


def _format_vtt_timestamp(value: timedelta) -> str:
    total_ms = int(value.total_seconds() * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"

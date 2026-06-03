from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import srt
import webvtt

from subtitle_forge.errors import SubtitleParseError
from subtitle_forge.models import SubtitleCue


SUPPORTED_FORMATS = {"srt", "vtt"}


def detect_format(path: Path, explicit_format: str | None = None) -> str:
    value = (explicit_format or path.suffix.lstrip(".")).lower()
    if value not in SUPPORTED_FORMATS:
        raise SubtitleParseError(f"Unsupported subtitle format '{value}'. Expected one of: srt, vtt.")
    return value


def read_subtitles(path: Path, input_format: str | None = None) -> list[SubtitleCue]:
    fmt = detect_format(path, input_format)
    try:
        if fmt == "srt":
            return _read_srt(path)
        if fmt == "vtt":
            return _read_vtt(path)
    except Exception as exc:
        raise SubtitleParseError(f"Could not parse {path}: {exc}") from exc
    raise SubtitleParseError(f"Unsupported subtitle format '{fmt}'.")


def write_subtitles(cues: list[SubtitleCue], path: Path, output_format: str | None = None) -> None:
    fmt = detect_format(path, output_format)
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

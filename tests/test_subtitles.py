from datetime import timedelta

import pytest

from subtitle_forge.errors import SubtitleParseError
from subtitle_forge.models import SubtitleCue
from subtitle_forge.subtitles import read_subtitles, write_subtitles


def test_parse_srt(tmp_path):
    path = tmp_path / "sample.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:02,500\nHello.\n",
        encoding="utf-8",
    )

    cues = read_subtitles(path)

    assert cues == [
        SubtitleCue(
            id="1", start=timedelta(seconds=1), end=timedelta(seconds=2, milliseconds=500), text="Hello."
        )
    ]


def test_parse_vtt(tmp_path):
    path = tmp_path / "sample.vtt"
    path.write_text(
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.500\nHello.\n",
        encoding="utf-8",
    )

    cues = read_subtitles(path)

    assert cues == [
        SubtitleCue(
            id="1", start=timedelta(seconds=1), end=timedelta(seconds=2, milliseconds=500), text="Hello."
        )
    ]


def test_export_srt_preserves_timings(tmp_path):
    path = tmp_path / "out.srt"
    cues = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=3), text="سلام.")]

    write_subtitles(cues, path)
    parsed = read_subtitles(path)

    assert parsed == cues


def test_export_vtt_preserves_timings(tmp_path):
    path = tmp_path / "out.vtt"
    cues = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=3), text="سلام.")]

    write_subtitles(cues, path)
    parsed = read_subtitles(path)

    assert parsed == cues


def test_parse_srt_rejects_duplicate_cue_ids(tmp_path):
    path = tmp_path / "duplicate.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nHello.\n\n"
        "1\n00:00:03,000 --> 00:00:04,000\nAgain.\n",
        encoding="utf-8",
    )

    with pytest.raises(SubtitleParseError, match="Duplicate subtitle cue id"):
        read_subtitles(path)


def test_parse_vtt_rejects_duplicate_cue_ids(tmp_path):
    path = tmp_path / "duplicate.vtt"
    path.write_text(
        "WEBVTT\n\n"
        "same\n00:00:01.000 --> 00:00:02.000\nHello.\n\n"
        "same\n00:00:03.000 --> 00:00:04.000\nAgain.\n",
        encoding="utf-8",
    )

    with pytest.raises(SubtitleParseError, match="Duplicate subtitle cue id"):
        read_subtitles(path)

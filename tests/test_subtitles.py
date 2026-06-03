from datetime import timedelta

from subtitle_forge.models import SubtitleCue
from subtitle_forge.subtitles import read_subtitles, write_subtitles


def test_parse_srt(tmp_path):
    path = tmp_path / "sample.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:02,500\nHello.\n",
        encoding="utf-8",
    )

    cues = read_subtitles(path)

    assert cues == [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2, milliseconds=500), text="Hello.")]


def test_parse_vtt(tmp_path):
    path = tmp_path / "sample.vtt"
    path.write_text(
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.500\nHello.\n",
        encoding="utf-8",
    )

    cues = read_subtitles(path)

    assert cues == [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2, milliseconds=500), text="Hello.")]


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

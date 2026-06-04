from datetime import timedelta

from subtitle_forge.bidi import POP_DIRECTIONAL_FORMATTING, RTL_EMBEDDING
from subtitle_forge.models import SubtitleCue
from subtitle_forge.quality import validate_translation


def test_validator_flags_disallowed_latin_and_missing_persian():
    source = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")]
    output = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text=f"{RTL_EMBEDDING}Hello.{POP_DIRECTIONAL_FORMATTING}")]

    report = validate_translation(source, output, [])

    assert "1" in report.suspicious_cue_ids
    assert report.disallowed_latin_dialogue_line_count == 1


def test_validator_allows_configured_latin_name_inside_persian():
    source = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="City Hunter.")]
    output = [
        SubtitleCue(
            id="1",
            start=timedelta(seconds=1),
            end=timedelta(seconds=2),
            text=f"{RTL_EMBEDDING}به City Hunter خوش آمدید.{POP_DIRECTIONAL_FORMATTING}",
        )
    ]

    report = validate_translation(source, output, ["City Hunter"])

    assert report.disallowed_latin_dialogue_line_count == 0


def test_validator_flags_mojibake_and_tag_mismatch():
    source = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="<i>Hello.</i>")]
    output = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text=f"{RTL_EMBEDDING}Ã bad{POP_DIRECTIONAL_FORMATTING}")]

    report = validate_translation(source, output, [])

    assert report.mojibake_count == 1
    assert report.tag_mismatch_count == 1

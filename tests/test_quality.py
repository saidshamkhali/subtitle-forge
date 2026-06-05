from datetime import timedelta

from subtitle_forge.bidi import POP_DIRECTIONAL_FORMATTING, RTL_EMBEDDING
from subtitle_forge.models import SubtitleCue
from subtitle_forge.quality import validate_translation, validation_passed


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


def test_validator_allows_configured_latin_name_only_line():
    source = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Kaori.")]
    output = [
        SubtitleCue(
            id="1",
            start=timedelta(seconds=1),
            end=timedelta(seconds=2),
            text=f"{RTL_EMBEDDING}Kaori...{POP_DIRECTIONAL_FORMATTING}",
        )
    ]

    report = validate_translation(source, output, ["Kaori"])

    assert report.suspicious_cue_ids == []


def test_validator_still_flags_untranslated_latin_only_line():
    source = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")]
    output = [
        SubtitleCue(
            id="1",
            start=timedelta(seconds=1),
            end=timedelta(seconds=2),
            text=f"{RTL_EMBEDDING}Hello...{POP_DIRECTIONAL_FORMATTING}",
        )
    ]

    report = validate_translation(source, output, ["Kaori"])

    assert "1" in report.suspicious_cue_ids


def test_validator_flags_mojibake_and_tag_mismatch():
    source = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="<i>Hello.</i>")]
    output = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text=f"{RTL_EMBEDDING}Ã bad{POP_DIRECTIONAL_FORMATTING}")]

    report = validate_translation(source, output, [])

    assert report.mojibake_count == 1
    assert report.tag_mismatch_count == 1


def test_validator_flags_empty_translation_for_nonempty_source():
    source = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")]
    output = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="")]

    report = validate_translation(source, output, [])

    assert "1" in report.suspicious_cue_ids
    assert any(issue.code == "empty_translation" for issue in report.issues)
    assert not validation_passed(report)


def test_validator_allows_empty_translation_for_empty_source():
    source = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="")]
    output = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="")]

    report = validate_translation(source, output, [])

    assert report.suspicious_cue_ids == []

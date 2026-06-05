from datetime import timedelta

import pytest

from subtitle_forge.cleanup import build_cleanup_prompt, parse_cleanup_response
from subtitle_forge.config import TranslationConfig
from subtitle_forge.errors import TranslationValidationError
from subtitle_forge.models import SubtitleCue
from subtitle_forge.prompting import build_translation_prompt
from subtitle_forge.translation import parse_provider_response


def test_cleanup_response_accepts_expected_cue_ids():
    fixes = parse_cleanup_response('{"1": "سلام."}', ["1"])

    assert fixes == {"1": "سلام."}


def test_cleanup_response_rejects_unknown_cue_id():
    with pytest.raises(TranslationValidationError, match="unknown cue id"):
        parse_cleanup_response('{"2": "سلام."}', ["1"])


def test_cleanup_response_rejects_invalid_json():
    with pytest.raises(TranslationValidationError, match="not valid JSON"):
        parse_cleanup_response("not json", ["1"])


def test_cleanup_prompt_uses_compact_payload():
    cue = SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")
    prompt = build_cleanup_prompt(
        batch_ids=["1"],
        source_by_id={"1": cue},
        current_by_id={"1": cue.with_text("Hello.")},
        issues=[],
        source_language="en",
        target_language="fa",
        translation_config=TranslationConfig(),
        allowed_latin_names=["City Hunter"],
    )

    assert "Cues:" in prompt
    assert '"src":' in prompt
    assert '"mt":' in prompt
    assert "source_text" not in prompt
    assert '"timestamp":' not in prompt


def test_cleanup_prompt_rejects_missing_source_cue_id():
    cue = SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")

    with pytest.raises(TranslationValidationError, match="source cue id is missing"):
        build_cleanup_prompt(
            batch_ids=["2"],
            source_by_id={"1": cue},
            current_by_id={"2": cue.with_text("Hello.")},
            issues=[],
            source_language="en",
            target_language="fa",
            translation_config=TranslationConfig(),
            allowed_latin_names=[],
        )


def test_cleanup_prompt_rejects_missing_current_cue_id():
    cue = SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")

    with pytest.raises(TranslationValidationError, match="current cue id is missing"):
        build_cleanup_prompt(
            batch_ids=["1"],
            source_by_id={"1": cue},
            current_by_id={"2": cue.with_text("Hello.")},
            issues=[],
            source_language="en",
            target_language="fa",
            translation_config=TranslationConfig(),
            allowed_latin_names=[],
        )


def test_provider_batch_response_parser_still_rejects_missing_cue():
    batch = [
        SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello."),
        SubtitleCue(id="2", start=timedelta(seconds=3), end=timedelta(seconds=4), text="Good morning."),
    ]

    with pytest.raises(TranslationValidationError, match="Expected 2 translations"):
        parse_provider_response('[{"id": "1", "text": "سلام."}]', batch)


def test_persian_prompt_guides_brand_names_and_mixed_direction_ordering():
    cues = [
        SubtitleCue(
            id="1",
            start=timedelta(seconds=1),
            end=timedelta(seconds=2),
            text="Welcome to Subtitle Forge.",
        )
    ]

    prompt = build_translation_prompt(cues, "en", "fa", TranslationConfig())

    assert "preserve brand names" in prompt
    assert "naturally belong in Persian word order" in prompt
    assert "mixed Persian/English ordering" in prompt
    assert "Welcome to [English Brand]" in prompt

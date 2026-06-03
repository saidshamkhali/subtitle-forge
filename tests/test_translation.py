from datetime import timedelta

import pytest

from subtitle_forge.config import TranslationConfig
from subtitle_forge.errors import TranslationValidationError
from subtitle_forge.models import SubtitleCue
from subtitle_forge.prompting import build_translation_prompt
from subtitle_forge.providers import MockProvider
from subtitle_forge.translation import parse_provider_response, translate_cues


def test_translate_with_mock_provider():
    cues = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")]

    translated = translate_cues(cues, MockProvider("fa"), "en", "fa", TranslationConfig(), batch_size=50)

    assert translated[0].text == "سلام."
    assert translated[0].start == cues[0].start
    assert translated[0].end == cues[0].end


def test_missing_cue_fails():
    batch = [
        SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello."),
        SubtitleCue(id="2", start=timedelta(seconds=3), end=timedelta(seconds=4), text="Good morning."),
    ]

    with pytest.raises(TranslationValidationError, match="Expected 2 translations"):
        parse_provider_response('[{"id": "1", "text": "سلام."}]', batch)


def test_invalid_json_fails():
    batch = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")]

    with pytest.raises(TranslationValidationError, match="not valid JSON"):
        parse_provider_response("not json", batch)


def test_preserves_simple_tags_with_mock_provider():
    cues = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="<i>Keep moving.</i>")]

    translated = translate_cues(cues, MockProvider("fa"), "en", "fa", TranslationConfig(), batch_size=50)

    assert translated[0].text == "<i>ادامه بده.</i>"


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

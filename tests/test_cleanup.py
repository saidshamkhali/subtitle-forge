from datetime import timedelta

import pytest

from subtitle_forge.cleanup import build_cleanup_cache_key, build_cleanup_prompt, cleanup_flagged_cues, parse_cleanup_response
from subtitle_forge.config import TranslationConfig
from subtitle_forge.errors import TranslationValidationError
from subtitle_forge.models import SubtitleCue
from subtitle_forge.prompting import build_translation_prompt
from subtitle_forge.quality import CueIssue
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


def test_cleanup_prompt_deduplicates_issue_codes():
    cue = SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")
    prompt = build_cleanup_prompt(
        batch_ids=["1"],
        source_by_id={"1": cue},
        current_by_id={"1": cue.with_text("Hello.")},
        issues=[
            CueIssue("1", "missing_persian", "Dialogue line has no Persian text."),
            CueIssue("1", "missing_persian", "Dialogue line has no Persian text."),
            CueIssue("1", "disallowed_latin", "Dialogue line contains disallowed Latin text."),
            CueIssue("2", "missing_persian", "Dialogue line has no Persian text."),
        ],
        source_language="en",
        target_language="fa",
        translation_config=TranslationConfig(),
        allowed_latin_names=[],
    )

    assert prompt.count("missing_persian") == 1
    assert prompt.count("disallowed_latin") == 1
    assert '"issues":["missing_persian","disallowed_latin"]' in prompt


def test_cleanup_uses_cached_fix_without_calling_provider():
    source = SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Oopsie.")
    current = source.with_text("Oopsie")
    config = TranslationConfig()
    issues = [CueIssue("1", "disallowed_latin", "Dialogue line contains disallowed Latin text.")]
    cache_key = build_cleanup_cache_key(
        source_text=source.text,
        mt_text=current.text,
        issue_codes=["disallowed_latin"],
        source_language="en",
        target_language="fa",
        translation_config=config,
        allowed_latin_names=[],
    )

    cleaned = cleanup_flagged_cues(
        source_cues=[source],
        current_cues=[current],
        flagged_ids=["1"],
        issues=issues,
        provider=_ProviderThatShouldNotRun(),
        source_language="en",
        target_language="fa",
        translation_config=config,
        allowed_latin_names=[],
        batch_size=25,
        cleanup_cache={cache_key: "اوه."},
    )

    assert cleaned[0].text == "اوه."


def test_cleanup_stores_provider_fix_in_cache():
    source = SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Oopsie.")
    current = source.with_text("Oopsie")
    config = TranslationConfig()
    issues = [CueIssue("1", "disallowed_latin", "Dialogue line contains disallowed Latin text.")]
    cleanup_cache = {}

    cleaned = cleanup_flagged_cues(
        source_cues=[source],
        current_cues=[current],
        flagged_ids=["1"],
        issues=issues,
        provider=_StaticCleanupProvider('{"1":"اوه."}'),
        source_language="en",
        target_language="fa",
        translation_config=config,
        allowed_latin_names=[],
        batch_size=25,
        cleanup_cache=cleanup_cache,
    )

    assert cleaned[0].text == "اوه."
    assert list(cleanup_cache.values()) == ["اوه."]


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


class _ProviderThatShouldNotRun:
    def translate_batch(self, prompt: str) -> str:
        raise AssertionError("provider should not run when cleanup fix is cached")


class _StaticCleanupProvider:
    def __init__(self, response: str) -> None:
        self.response = response

    def translate_batch(self, prompt: str) -> str:
        return self.response

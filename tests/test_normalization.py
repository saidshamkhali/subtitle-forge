from datetime import timedelta

from subtitle_forge.bidi import LTR_EMBEDDING, POP_DIRECTIONAL_FORMATTING, RTL_EMBEDDING
from subtitle_forge.models import SubtitleCue
from subtitle_forge.normalization import normalize_cues_for_target


def test_persian_normalizer_wraps_lines_and_allowed_latin_names():
    cues = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="به City Hunter خوش آمدید.")]

    normalized = normalize_cues_for_target(cues, "fa", ["City Hunter"])

    assert normalized[0].text.startswith(RTL_EMBEDDING)
    assert normalized[0].text.endswith(POP_DIRECTIONAL_FORMATTING)
    assert f"{LTR_EMBEDDING}City Hunter{POP_DIRECTIONAL_FORMATTING}" in normalized[0].text


def test_persian_normalizer_strips_structural_marks_from_ids():
    cues = [SubtitleCue(id=f"{RTL_EMBEDDING}1{POP_DIRECTIONAL_FORMATTING}", start=timedelta(seconds=1), end=timedelta(seconds=2), text="سلام.")]

    normalized = normalize_cues_for_target(cues, "fa", [])

    assert normalized[0].id == "1"


def test_persian_normalizer_preserves_simple_tags():
    cues = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="<i>سلام.</i>")]

    normalized = normalize_cues_for_target(cues, "fa", [])

    assert "<i>" in normalized[0].text
    assert "</i>" in normalized[0].text

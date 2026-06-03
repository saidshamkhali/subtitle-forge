from datetime import timedelta

from subtitle_forge.bidi import (
    LTR_EMBEDDING,
    POP_DIRECTIONAL_FORMATTING,
    RTL_EMBEDDING,
    stabilize_cues_for_rtl_display,
    stabilize_text_for_rtl_display,
)
from subtitle_forge.models import SubtitleCue


def test_stabilizes_persian_line_for_rtl_players():
    text = stabilize_text_for_rtl_display("به Subtitle Forge خوش آمدید.")

    assert text.startswith(RTL_EMBEDDING)
    assert text.endswith(POP_DIRECTIONAL_FORMATTING)
    assert f"{LTR_EMBEDDING}Subtitle Forge{POP_DIRECTIONAL_FORMATTING}" in text


def test_auto_mode_only_applies_to_rtl_targets():
    cues = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="سلام.")]

    assert stabilize_cues_for_rtl_display(cues, "en", "auto") == cues
    assert stabilize_cues_for_rtl_display(cues, "fa", "auto")[0].text.startswith(RTL_EMBEDDING)


def test_off_mode_leaves_text_unchanged():
    cues = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="سلام.")]

    assert stabilize_cues_for_rtl_display(cues, "fa", "off") == cues

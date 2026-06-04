from datetime import timedelta

from subtitle_forge.argos import translate_cues_with_argos
from subtitle_forge.models import SubtitleCue


class FakeTranslator:
    def translate(self, text: str) -> str:
        return {"Hello.": "سلام.", "Keep moving.": "ادامه بده."}.get(text, text)


def test_argos_pass_preserves_srt_structure_and_tags():
    cues = [
        SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello."),
        SubtitleCue(id="2", start=timedelta(seconds=3), end=timedelta(seconds=4), text="<i>Keep moving.</i>"),
    ]

    translated = translate_cues_with_argos(cues, "en", "fa", translator=FakeTranslator())

    assert translated[0].id == "1"
    assert translated[0].start == cues[0].start
    assert translated[0].end == cues[0].end
    assert translated[0].text == "سلام."
    assert translated[1].text == "<i>ادامه بده.</i>"

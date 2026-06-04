from datetime import timedelta
import logging
import sys

from subtitle_forge.argos import translate_cues_with_argos
from subtitle_forge.models import SubtitleCue


CACHED_STDERR = sys.stderr


class FakeTranslator:
    def __init__(self):
        self.calls: list[str] = []

    def translate(self, text: str) -> str:
        self.calls.append(text)
        return {"Hello.": "سلام.", "Keep moving.": "ادامه بده."}.get(text, text)


class NoisyTranslator:
    def translate(self, text: str) -> str:
        logging.warning("Language en package default expects mwt, which has been added")
        print("2026-06-04 20:31:28 WARNING: Language en package default expects mwt, which has been added", file=CACHED_STDERR)
        return "سلام."


def test_argos_pass_preserves_srt_structure_and_tags():
    translator = FakeTranslator()
    cues = [
        SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello."),
        SubtitleCue(id="2", start=timedelta(seconds=3), end=timedelta(seconds=4), text="<i>Keep moving.</i>"),
    ]

    translated = translate_cues_with_argos(cues, "en", "fa", translator=translator)

    assert translated[0].id == "1"
    assert translated[0].start == cues[0].start
    assert translated[0].end == cues[0].end
    assert translated[0].text == "سلام."
    assert translated[1].text == "<i>ادامه بده.</i>"


def test_argos_pass_reuses_duplicate_translation_segments():
    translator = FakeTranslator()
    cues = [
        SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello."),
        SubtitleCue(id="2", start=timedelta(seconds=3), end=timedelta(seconds=4), text="Hello."),
    ]

    translate_cues_with_argos(cues, "en", "fa", translator=translator)

    assert translator.calls == ["Hello."]


def test_argos_pass_suppresses_known_stanza_package_warning(caplog, capfd):
    cues = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")]

    with caplog.at_level(logging.WARNING):
        translate_cues_with_argos(cues, "en", "fa", translator=NoisyTranslator())

    assert "expects mwt" not in caplog.text
    assert "expects mwt" not in capfd.readouterr().err

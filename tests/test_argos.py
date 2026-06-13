import logging
import os
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import argostranslate
import pytest

from subtitle_forge.argos import (
    _translate_segments_in_chunks,
    get_argos_translation,
    install_argos_package,
    translate_cues_with_argos,
)
from subtitle_forge.errors import ProviderError
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
        logging.warning("GPU requested, but is not available!")
        print(
            "2026-06-04 20:31:28 WARNING: Language en package default expects mwt, which has been added",
            file=CACHED_STDERR,
        )
        print("2026-06-05 00:41:41 WARNING: GPU requested, but is not available!", file=CACHED_STDERR)
        return "سلام."


class BadBatchTranslator:
    def __init__(self):
        self.calls: list[str] = []

    def translate(self, text: str) -> str:
        self.calls.append(text)
        if "\n" in text:
            return "یک خط"
        return text.upper()


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


def test_cuda_segment_batch_translates_segments_individually():
    translator = BadBatchTranslator()

    translated = _translate_segments_in_chunks(translator, ["one", "two"], 10)

    assert translated == {"one": "ONE", "two": "TWO"}
    assert translator.calls == ["one", "two"]


def test_argos_pass_suppresses_known_stanza_package_warning(caplog, capfd):
    cues = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")]

    with caplog.at_level(logging.WARNING):
        translate_cues_with_argos(cues, "en", "fa", translator=NoisyTranslator())

    assert "expects mwt" not in caplog.text
    assert "GPU requested" not in caplog.text
    stderr = capfd.readouterr().err
    assert "expects mwt" not in stderr
    assert "GPU requested" not in stderr


def test_install_argos_package_downloads_missing_translation(monkeypatch):
    installed_pairs = set()
    statuses = []

    class FakeLanguage:
        def __init__(self, code):
            self.code = code

        def get_translation(self, target):
            if (self.code, target.code) in installed_pairs:
                return FakeTranslator()
            return None

    class FakeAvailablePackage:
        from_code = "xx"
        to_code = "yy"
        type = "translate"

        def download(self):
            return Path("xx_yy.argosmodel")

    def get_installed_languages():
        return [FakeLanguage("xx"), FakeLanguage("yy")]

    def install_from_path(path):
        assert path == Path("xx_yy.argosmodel")
        installed_pairs.add(("xx", "yy"))

    fake_translate = SimpleNamespace(get_installed_languages=get_installed_languages)
    fake_package = SimpleNamespace(
        update_package_index=lambda: None,
        get_available_packages=lambda: [FakeAvailablePackage()],
        install_from_path=install_from_path,
    )
    monkeypatch.setitem(sys.modules, "argostranslate.translate", fake_translate)
    monkeypatch.setitem(sys.modules, "argostranslate.package", fake_package)

    installed = install_argos_package("xx", "yy", on_status=statuses.append)

    assert installed is True
    assert installed_pairs == {("xx", "yy")}
    assert statuses == [
        "Refreshing Argos package index",
        "Downloading Argos package xx -> yy",
        "Installing Argos package from xx_yy.argosmodel",
    ]


def test_get_argos_translation_suggests_install_command_for_missing_path(monkeypatch):
    class FakeLanguage:
        def __init__(self, code):
            self.code = code

        def get_translation(self, target):
            return None

    fake_translate = SimpleNamespace(get_installed_languages=lambda: [FakeLanguage("en"), FakeLanguage("fa")])
    monkeypatch.setitem(sys.modules, "argostranslate.translate", fake_translate)
    monkeypatch.setattr(argostranslate, "translate", fake_translate, raising=False)

    with pytest.raises(ProviderError) as exc_info:
        get_argos_translation("en", "fa")

    assert "Argos translation path is not installed: en -> fa" in str(exc_info.value)
    assert "subtitle-forge translate --from en --to fa --install-argos-package" in str(exc_info.value)


def test_argos_device_is_scoped_to_translation(monkeypatch):
    translator = FakeTranslator()
    cues = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")]

    monkeypatch.setenv("ARGOS_DEVICE_TYPE", "cpu")
    translate_cues_with_argos(cues, "en", "fa", translator=translator, device_type="cuda")

    assert os.environ["ARGOS_DEVICE_TYPE"] == "cpu"


def test_argos_device_updates_imported_argos_settings(monkeypatch):
    translator = FakeTranslator()
    cues = [SubtitleCue(id="1", start=timedelta(seconds=1), end=timedelta(seconds=2), text="Hello.")]
    fake_settings = SimpleNamespace(device="cpu")

    monkeypatch.setitem(sys.modules, "argostranslate.settings", fake_settings)
    translate_cues_with_argos(cues, "en", "fa", translator=translator, device_type="cuda")

    assert fake_settings.device == "cpu"
    assert translator.calls == ["Hello."]

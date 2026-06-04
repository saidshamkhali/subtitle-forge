from __future__ import annotations

from contextlib import contextmanager
import io
import logging
import os
import re
import sys
import threading
from typing import Callable, Protocol

from subtitle_forge.errors import ProviderError
from subtitle_forge.models import SubtitleCue


TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")


class TextTranslator(Protocol):
    def translate(self, text: str) -> str:
        ...


def translate_cues_with_argos(
    cues: list[SubtitleCue],
    source_language: str,
    target_language: str,
    translator: TextTranslator | None = None,
    on_cue: Callable[[int, SubtitleCue], None] | None = None,
) -> list[SubtitleCue]:
    translated: list[SubtitleCue] = []
    cache: dict[str, str] = {}
    with _suppress_known_argos_warnings():
        engine = translator or get_argos_translation(source_language, target_language)
        for index, cue in enumerate(cues, start=1):
            if on_cue:
                on_cue(index, cue)
            translated.append(cue.with_text(_translate_text_preserving_tags(cue.text, engine, cache)))
    return translated


def get_argos_translation(source_language: str, target_language: str) -> TextTranslator:
    try:
        import argostranslate.translate
    except ImportError as exc:
        raise ProviderError(
            "ArgosTranslate is required for Subtitle Forge. Install project dependencies, then retry."
        ) from exc

    installed = argostranslate.translate.get_installed_languages()
    source = next((language for language in installed if language.code == source_language), None)
    target = next((language for language in installed if language.code == target_language), None)
    if source is None:
        codes = ", ".join(sorted(language.code for language in installed)) or "none"
        raise ProviderError(f"Argos source language is not installed: {source_language}. Installed: {codes}.")
    if target is None:
        codes = ", ".join(sorted(language.code for language in installed)) or "none"
        raise ProviderError(f"Argos target language is not installed: {target_language}. Installed: {codes}.")

    translation = source.get_translation(target)
    if translation is None:
        raise ProviderError(f"Argos translation path is not installed: {source_language} -> {target_language}.")
    return translation


def _translate_text_preserving_tags(text: str, translator: TextTranslator, cache: dict[str, str]) -> str:
    lines = text.splitlines()
    if not lines:
        return _translate_with_cache(text, translator, cache)
    return "\n".join(_translate_line_preserving_tags(line, translator, cache) for line in lines)


def _translate_line_preserving_tags(line: str, translator: TextTranslator, cache: dict[str, str]) -> str:
    parts = TAG_RE.split(line)
    tags = TAG_RE.findall(line)
    translated_parts = [_translate_plain_part(part, translator, cache) for part in parts]
    translated = translated_parts[0]
    for tag, part in zip(tags, translated_parts[1:]):
        translated += tag + part
    return translated.replace("\r", " ").replace("\n", " ").strip()


def _translate_plain_part(text: str, translator: TextTranslator, cache: dict[str, str]) -> str:
    if not text.strip():
        return text
    leading = text[: len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()) :]
    return f"{leading}{_translate_with_cache(text.strip(), translator, cache)}{trailing}"


def _translate_with_cache(text: str, translator: TextTranslator, cache: dict[str, str]) -> str:
    if text not in cache:
        cache[text] = translator.translate(text).strip()
    return cache[text]


class _ArgosNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return "package default expects mwt, which has been added" not in message


@contextmanager
def _suppress_known_argos_warnings():
    root_logger = logging.getLogger()
    noise_filter = _ArgosNoiseFilter()
    original_stderr = sys.stderr
    filtered_stderr = _FilteredStderr(original_stderr)
    fd_filter = _StderrFdFilter()
    root_logger.addFilter(noise_filter)
    for handler in root_logger.handlers:
        handler.addFilter(noise_filter)
    try:
        sys.stderr = filtered_stderr
        fd_filter.start()
        yield
    finally:
        fd_filter.stop()
        sys.stderr = original_stderr
        root_logger.removeFilter(noise_filter)
        for handler in root_logger.handlers:
            handler.removeFilter(noise_filter)


class _FilteredStderr(io.TextIOBase):
    def __init__(self, wrapped):
        self._wrapped = wrapped
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._write_line(line + "\n")
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._write_line(self._buffer)
            self._buffer = ""
        self._wrapped.flush()

    def writable(self) -> bool:
        return True

    @property
    def encoding(self):
        return getattr(self._wrapped, "encoding", None)

    def _write_line(self, line: str) -> None:
        if "package default expects mwt, which has been added" not in line:
            self._wrapped.write(line)


class _StderrFdFilter:
    noise = b"package default expects mwt, which has been added"

    def __init__(self) -> None:
        self._saved_fd: int | None = None
        self._write_fd: int | None = None
        self._thread: threading.Thread | None = None
        self._started = False

    def start(self) -> None:
        try:
            sys.stderr.flush()
            read_fd, write_fd = os.pipe()
            self._saved_fd = os.dup(2)
            os.dup2(write_fd, 2)
            os.close(write_fd)
            self._write_fd = None
            self._thread = threading.Thread(target=self._forward_filtered, args=(read_fd, self._saved_fd), daemon=True)
            self._thread.start()
            self._started = True
        except OSError:
            self._cleanup()

    def stop(self) -> None:
        if not self._started or self._saved_fd is None:
            self._cleanup()
            return
        try:
            sys.stderr.flush()
            os.dup2(self._saved_fd, 2)
        finally:
            if self._thread:
                self._thread.join(timeout=1)
            self._cleanup()

    def _forward_filtered(self, read_fd: int, output_fd: int) -> None:
        buffer = b""
        with os.fdopen(read_fd, "rb", closefd=True) as reader:
            while True:
                chunk = reader.read(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self._write_allowed_line(output_fd, line + b"\n")
            if buffer:
                self._write_allowed_line(output_fd, buffer)

    def _write_allowed_line(self, output_fd: int, line: bytes) -> None:
        if self.noise not in line:
            os.write(output_fd, line)

    def _cleanup(self) -> None:
        if self._saved_fd is not None:
            try:
                os.close(self._saved_fd)
            except OSError:
                pass
        if self._write_fd is not None:
            try:
                os.close(self._write_fd)
            except OSError:
                pass
        self._saved_fd = None
        self._write_fd = None
        self._thread = None
        self._started = False

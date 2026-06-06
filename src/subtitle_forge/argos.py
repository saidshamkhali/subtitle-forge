from __future__ import annotations

from contextlib import contextmanager
import io
import logging
import os
from pathlib import Path
import re
import sys
import threading
from typing import Callable, Protocol

from subtitle_forge.errors import ProviderError
from subtitle_forge.models import SubtitleCue


TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
VALID_ARGOS_DEVICES = {"cpu", "cuda", "auto"}
CUDA_SEGMENT_CHUNK_SIZE = 1200
CUDA_INTERNAL_BATCH_SIZE = 128
CUDA_COMPUTE_TYPE = "float16"
_CUDA_DLL_DIRECTORY_HANDLES = []


class TextTranslator(Protocol):
    def translate(self, text: str) -> str:
        ...


def translate_cues_with_argos(
    cues: list[SubtitleCue],
    source_language: str,
    target_language: str,
    translator: TextTranslator | None = None,
    device_type: str | None = None,
    on_cue: Callable[[int, SubtitleCue], None] | None = None,
) -> list[SubtitleCue]:
    if device_type is not None and device_type not in VALID_ARGOS_DEVICES:
        expected = ", ".join(sorted(VALID_ARGOS_DEVICES))
        raise ProviderError(f"Unsupported Argos device '{device_type}'. Expected one of: {expected}.")

    translated: list[SubtitleCue] = []
    cache: dict[str, str] = {}
    with _argos_device(device_type), _suppress_known_argos_warnings():
        if device_type in {"cuda", "auto"}:
            configure_cuda_dll_directories()
        engine = translator or get_argos_translation(source_language, target_language)
        if translator is None and device_type == "cuda":
            return _translate_cues_batched_for_cuda(cues, engine, on_cue)
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
        raise ProviderError(
            f"Argos source language is not installed: {source_language}. Installed: {codes}. "
            f"Install the package with: {_argos_install_command(source_language, target_language)}"
        )
    if target is None:
        codes = ", ".join(sorted(language.code for language in installed)) or "none"
        raise ProviderError(
            f"Argos target language is not installed: {target_language}. Installed: {codes}. "
            f"Install the package with: {_argos_install_command(source_language, target_language)}"
        )

    translation = source.get_translation(target)
    if translation is None:
        raise ProviderError(
            f"Argos translation path is not installed: {source_language} -> {target_language}. "
            f"Install it with: {_argos_install_command(source_language, target_language)}"
        )
    return translation


def install_argos_package(
    source_language: str,
    target_language: str,
    on_status: Callable[[str], None] | None = None,
) -> bool:
    """Install the direct Argos package for the requested language pair.

    Returns True when a package was downloaded/installed and False when an
    installed translation path already exists.
    """
    try:
        import argostranslate.package as argos_package
        import argostranslate.translate as argos_translate
    except ImportError as exc:
        raise ProviderError(
            "ArgosTranslate is required for Subtitle Forge. Install project dependencies, then retry."
        ) from exc

    if _find_argos_translation(argos_translate, source_language, target_language) is not None:
        return False

    _emit_status(on_status, "Refreshing Argos package index")
    try:
        argos_package.update_package_index()
        available_packages = argos_package.get_available_packages()
    except Exception as exc:
        raise ProviderError(f"Could not refresh Argos package index: {exc}") from exc

    available_package = next(
        (
            package
            for package in available_packages
            if getattr(package, "from_code", None) == source_language
            and getattr(package, "to_code", None) == target_language
            and getattr(package, "type", "translate") == "translate"
        ),
        None,
    )
    if available_package is None:
        raise ProviderError(f"No Argos package is available for {source_language} -> {target_language}.")

    try:
        _emit_status(on_status, f"Downloading Argos package {source_language} -> {target_language}")
        download_path = available_package.download()
        _emit_status(on_status, f"Installing Argos package from {download_path}")
        argos_package.install_from_path(download_path)
    except Exception as exc:
        raise ProviderError(f"Failed to install Argos package {source_language} -> {target_language}: {exc}") from exc

    if _find_argos_translation(argos_translate, source_language, target_language) is None:
        raise ProviderError(
            f"Argos package install completed, but translation path is still unavailable: "
            f"{source_language} -> {target_language}."
        )
    return True


def _find_argos_translation(argos_translate, source_language: str, target_language: str) -> TextTranslator | None:
    installed = argos_translate.get_installed_languages()
    source = next((language for language in installed if language.code == source_language), None)
    target = next((language for language in installed if language.code == target_language), None)
    if source is None or target is None:
        return None
    return source.get_translation(target)


def _emit_status(on_status: Callable[[str], None] | None, message: str) -> None:
    if on_status:
        on_status(message)


def _argos_install_command(source_language: str, target_language: str) -> str:
    return f"subtitle-forge translate --from {source_language} --to {target_language} --install-argos-package"


def configure_cuda_dll_directories() -> list[Path]:
    """Register CUDA bin directories with the Windows DLL loader.

    CUDA installers do not always update PATH for the current terminal. Python 3.8+
    supports adding DLL search directories explicitly, which is more reliable than
    relying on PATH alone.
    """
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return []

    added: list[Path] = []
    for directory in _candidate_cuda_bin_dirs():
        if not (directory / "cublas64_12.dll").exists():
            continue
        if str(directory) in {str(path) for path in added}:
            continue
        try:
            handle = os.add_dll_directory(str(directory))
        except OSError:
            continue
        _CUDA_DLL_DIRECTORY_HANDLES.append(handle)
        _prepend_process_path(directory)
        _set_windows_dll_directory(directory)
        added.append(directory)
    return added


def _translate_text_preserving_tags(text: str, translator: TextTranslator, cache: dict[str, str]) -> str:
    lines = text.splitlines()
    if not lines:
        return _translate_with_cache(text, translator, cache)
    return "\n".join(_translate_line_preserving_tags(line, translator, cache) for line in lines)


def _process_line_preserving_tags(line: str, process_fn: Callable[[str], str]) -> str:
    parts = TAG_RE.split(line)
    tags = TAG_RE.findall(line)
    processed_parts = [process_fn(part) for part in parts]
    result = processed_parts[0]
    for tag, part in zip(tags, processed_parts[1:]):
        result += tag + part
    return result.replace("\r", " ").replace("\n", " ").strip()


def _translate_line_preserving_tags(line: str, translator: TextTranslator, cache: dict[str, str]) -> str:
    return _process_line_preserving_tags(line, lambda part: _translate_plain_part(part, translator, cache))


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


def _translate_cues_batched_for_cuda(
    cues: list[SubtitleCue],
    translator: TextTranslator,
    on_cue: Callable[[int, SubtitleCue], None] | None,
) -> list[SubtitleCue]:
    segments = _unique_plain_segments(cues)
    translations = _translate_segments_in_chunks(translator, segments, CUDA_SEGMENT_CHUNK_SIZE)
    translated: list[SubtitleCue] = []
    for index, cue in enumerate(cues, start=1):
        if on_cue:
            on_cue(index, cue)
        translated.append(cue.with_text(_reconstruct_text_from_segments(cue.text, translations)))
    return translated


def _unique_plain_segments(cues: list[SubtitleCue]) -> list[str]:
    segments: list[str] = []
    seen: set[str] = set()
    for cue in cues:
        for line in cue.text.splitlines() or [cue.text]:
            for part in TAG_RE.split(line):
                segment = part.strip()
                if segment and segment not in seen:
                    seen.add(segment)
                    segments.append(segment)
    return segments


def _translate_segments_in_chunks(
    translator: TextTranslator,
    segments: list[str],
    chunk_size: int,
) -> dict[str, str]:
    direct_cuda = _translate_segments_direct_cuda(translator, segments)
    if direct_cuda is not None:
        return direct_cuda

    translated: dict[str, str] = {}
    for index in range(0, len(segments), chunk_size):
        chunk = segments[index : index + chunk_size]
        for source in chunk:
            translated[source] = translator.translate(source).strip()
    return translated


def _translate_segments_direct_cuda(
    translator: TextTranslator,
    segments: list[str],
) -> dict[str, str] | None:
    if not segments:
        return {}

    underlying = getattr(translator, "underlying", None)
    pkg = getattr(underlying, "pkg", None)
    tokenizer = getattr(pkg, "tokenizer", None)
    if underlying is None or pkg is None or tokenizer is None:
        return None

    try:
        import argostranslate.settings as settings
        import ctranslate2
    except ImportError:
        return None

    if getattr(settings, "device", None) != "cuda":
        return None

    try:
        if getattr(underlying, "translator", None) is None:
            model_path = str(pkg.package_path / "model")
            underlying.translator = ctranslate2.Translator(
                model_path,
                device=settings.device,
                inter_threads=settings.inter_threads,
                intra_threads=settings.intra_threads,
                compute_type=settings.compute_type,
            )
        tokenized = [tokenizer.encode(segment) for segment in segments]
        target_prefix = None
        if getattr(pkg, "target_prefix", ""):
            target_prefix = [[pkg.target_prefix]] * len(tokenized)
        translated_batches = underlying.translator.translate_batch(
            tokenized,
            target_prefix=target_prefix,
            replace_unknowns=True,
            max_batch_size=settings.batch_size,
            batch_type="tokens",
            beam_size=max(1, settings.beam_size),
            num_hypotheses=1,
            length_penalty=0.2,
        )
    except Exception:
        return None

    translated: dict[str, str] = {}
    for source, result in zip(segments, translated_batches):
        value = tokenizer.decode(result.hypotheses[0])
        if getattr(pkg, "target_prefix", "") and value.startswith(pkg.target_prefix):
            value = value[len(pkg.target_prefix) :]
        translated[source] = value.strip()
    return translated


def _reconstruct_text_from_segments(text: str, translations: dict[str, str]) -> str:
    lines = text.splitlines()
    if not lines:
        return translations.get(text.strip(), text).strip()
    return "\n".join(_reconstruct_line_from_segments(line, translations) for line in lines)


def _reconstruct_line_from_segments(line: str, translations: dict[str, str]) -> str:
    return _process_line_preserving_tags(line, lambda part: _replace_plain_segment(part, translations))


def _replace_plain_segment(text: str, translations: dict[str, str]) -> str:
    if not text.strip():
        return text
    leading = text[: len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()) :]
    return f"{leading}{translations.get(text.strip(), text.strip())}{trailing}"


def _candidate_cuda_bin_dirs() -> list[Path]:
    candidates: list[Path] = []
    for key, value in os.environ.items():
        if key.startswith("CUDA_PATH") and value:
            candidates.append(Path(value) / "bin")

    default_root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA GPU Computing Toolkit" / "CUDA"
    if default_root.exists():
        candidates.extend(path / "bin" for path in sorted(default_root.glob("v*"), reverse=True))

    path_dirs = [Path(value) for value in os.environ.get("PATH", "").split(os.pathsep) if value]
    candidates.extend(path_dirs)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(candidate)
        if resolved not in seen:
            seen.add(resolved)
            unique.append(candidate)
    return unique


def _prepend_process_path(directory: Path) -> None:
    current_entries = os.environ.get("PATH", "").split(os.pathsep)
    directory_text = str(directory)
    if directory_text not in current_entries:
        os.environ["PATH"] = directory_text + os.pathsep + os.environ.get("PATH", "")


def _set_windows_dll_directory(directory: Path) -> None:
    try:
        ctypes = __import__("ctypes")
        ctypes.windll.kernel32.SetDllDirectoryW(str(directory))
    except Exception:
        pass


class _ArgosNoiseFilter(logging.Filter):
    noise_messages = (
        "package default expects mwt, which has been added",
        "GPU requested, but is not available!",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(noise in message for noise in self.noise_messages)


@contextmanager
def _argos_device(device_type: str | None):
    if device_type is None:
        yield
        return

    previous = os.environ.get("ARGOS_DEVICE_TYPE")
    try:
        import argostranslate.settings as settings_module
    except ImportError:
        settings_module = sys.modules.get("argostranslate.settings")
    previous_setting = getattr(settings_module, "device", None) if settings_module else None
    previous_batch_size = getattr(settings_module, "batch_size", None) if settings_module else None
    previous_compute_type = getattr(settings_module, "compute_type", None) if settings_module else None
    os.environ["ARGOS_DEVICE_TYPE"] = device_type
    if settings_module is not None:
        settings_module.device = device_type
        if device_type == "cuda":
            settings_module.batch_size = max(int(previous_batch_size or 0), CUDA_INTERNAL_BATCH_SIZE)
            if previous_compute_type in {None, "auto"}:
                settings_module.compute_type = CUDA_COMPUTE_TYPE
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("ARGOS_DEVICE_TYPE", None)
        else:
            os.environ["ARGOS_DEVICE_TYPE"] = previous
        if settings_module is not None:
            settings_module.device = previous_setting
            settings_module.batch_size = previous_batch_size
            settings_module.compute_type = previous_compute_type


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
        if not any(noise in line for noise in _ArgosNoiseFilter.noise_messages):
            self._wrapped.write(line)


class _StderrFdFilter:
    noise_messages = tuple(message.encode("utf-8") for message in _ArgosNoiseFilter.noise_messages)

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
        if not any(noise in line for noise in self.noise_messages):
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

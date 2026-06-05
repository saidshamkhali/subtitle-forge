from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib

from subtitle_forge.errors import SubtitleForgeError
from subtitle_forge.normalization import DEFAULT_ALLOWED_LATIN_NAMES


CONFIG_FILENAMES = ("subtitle-forge.toml", "pyproject.toml")
SUPPORTED_OUTPUT_FORMATS = {"srt", "vtt"}
VALID_ARGOS_DEVICES = {"auto", "cpu", "cuda"}
VALID_CLEANUP_PROVIDERS = {"codex", "mock"}


@dataclass(frozen=True)
class CodexProviderConfig:
    command: str = "codex"
    extra_args: list[str] = field(default_factory=lambda: ["exec", "--skip-git-repo-check"])
    model: str | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class TranslationConfig:
    style: str = "natural subtitle translation"
    preserve_names: bool = True
    preserve_formatting: bool = True
    prompt: str | None = None


@dataclass(frozen=True)
class AppConfig:
    source_language: str = "en"
    target_language: str = "fa"
    output_format: str | None = None
    argos_device: str = "cpu"
    cleanup_batch_size: int = 25
    cleanup_provider: str = "codex"
    keep_intermediate: bool = False
    codex: CodexProviderConfig = field(default_factory=CodexProviderConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    allowed_latin_names: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_LATIN_NAMES))


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or find_config_file()
    if not config_path:
        return AppConfig()

    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SubtitleForgeError(f"Could not parse config file {config_path}: {exc}") from exc

    if config_path.name == "pyproject.toml":
        data = data.get("tool", {}).get("subtitle-forge", {})

    defaults = _table(data, "defaults", config_path)
    providers = _table(data, "providers", config_path)
    translation = _table(data, "translation", config_path)
    quality = _table(data, "quality", config_path)
    codex_data = _table(providers, "codex", config_path)

    return AppConfig(
        source_language=_string(defaults, "source_language", "en", config_path),
        target_language=_string(defaults, "target_language", "fa", config_path),
        output_format=_optional_choice(defaults, "output_format", SUPPORTED_OUTPUT_FORMATS, config_path),
        argos_device=_choice(defaults, "argos_device", "cpu", VALID_ARGOS_DEVICES, config_path),
        cleanup_batch_size=_positive_int(defaults, "cleanup_batch_size", 25, config_path),
        cleanup_provider=_choice(defaults, "cleanup_provider", "codex", VALID_CLEANUP_PROVIDERS, config_path),
        keep_intermediate=_bool(defaults, "keep_intermediate", False, config_path),
        codex=CodexProviderConfig(
            command=_string(codex_data, "command", "codex", config_path),
            extra_args=_string_list(codex_data, "extra_args", ["exec", "--skip-git-repo-check"], config_path),
            model=_optional_string(codex_data, "model", config_path),
            reasoning_effort=_optional_string(codex_data, "reasoning_effort", config_path),
        ),
        translation=TranslationConfig(
            style=_string(translation, "style", "natural subtitle translation", config_path),
            preserve_names=_bool(translation, "preserve_names", True, config_path),
            preserve_formatting=_bool(translation, "preserve_formatting", True, config_path),
            prompt=_optional_string(translation, "prompt", config_path),
        ),
        allowed_latin_names=_string_list(quality, "allowed_latin_names", DEFAULT_ALLOWED_LATIN_NAMES, config_path),
    )


def _table(data: dict, key: str, config_path: Path) -> dict:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise SubtitleForgeError(f"Config value '{key}' in {config_path} must be a table.")
    return value


def _string(data: dict, key: str, default: str, config_path: Path) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise SubtitleForgeError(f"Config value '{key}' in {config_path} must be a non-empty string.")
    return value


def _optional_string(data: dict, key: str, config_path: Path) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SubtitleForgeError(f"Config value '{key}' in {config_path} must be a non-empty string.")
    return value


def _choice(data: dict, key: str, default: str, choices: set[str], config_path: Path) -> str:
    value = _string(data, key, default, config_path).lower()
    if value not in choices:
        expected = ", ".join(sorted(choices))
        raise SubtitleForgeError(f"Config value '{key}' in {config_path} must be one of: {expected}.")
    return value


def _optional_choice(data: dict, key: str, choices: set[str], config_path: Path) -> str | None:
    value = _optional_string(data, key, config_path)
    if value is None:
        return None
    normalized = value.lower()
    if normalized not in choices:
        expected = ", ".join(sorted(choices))
        raise SubtitleForgeError(f"Config value '{key}' in {config_path} must be one of: {expected}.")
    return normalized


def _positive_int(data: dict, key: str, default: int, config_path: Path) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SubtitleForgeError(f"Config value '{key}' in {config_path} must be an integer greater than 0.")
    return value


def _bool(data: dict, key: str, default: bool, config_path: Path) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise SubtitleForgeError(f"Config value '{key}' in {config_path} must be true or false.")
    return value


def _string_list(data: dict, key: str, default: list[str], config_path: Path) -> list[str]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SubtitleForgeError(f"Config value '{key}' in {config_path} must be a list of strings.")
    return list(value)


def find_config_file(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        for filename in CONFIG_FILENAMES:
            candidate = directory / filename
            if candidate.exists():
                if filename == "pyproject.toml":
                    try:
                        data = tomllib.loads(candidate.read_text(encoding="utf-8"))
                    except tomllib.TOMLDecodeError:
                        continue
                    if "subtitle-forge" not in data.get("tool", {}):
                        continue
                return candidate
    return None


def load_codex_default_model() -> str | None:
    data = _load_codex_config()
    model = data.get("model")
    return model if isinstance(model, str) and model else None


def load_codex_default_reasoning_effort() -> str | None:
    data = _load_codex_config()
    reasoning_effort = data.get("model_reasoning_effort")
    return reasoning_effort if isinstance(reasoning_effort, str) and reasoning_effort else None


def _load_codex_config() -> dict:
    config_path = Path.home() / ".codex" / "config.toml"
    if not config_path.exists():
        return {}

    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib

from subtitle_forge.normalization import DEFAULT_ALLOWED_LATIN_NAMES


CONFIG_FILENAMES = ("subtitle-forge.toml", "pyproject.toml")


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

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if config_path.name == "pyproject.toml":
        data = data.get("tool", {}).get("subtitle-forge", {})

    defaults = data.get("defaults", {})
    providers = data.get("providers", {})
    translation = data.get("translation", {})
    quality = data.get("quality", {})
    codex_data = providers.get("codex", {})

    return AppConfig(
        source_language=defaults.get("source_language", "en"),
        target_language=defaults.get("target_language", "fa"),
        output_format=defaults.get("output_format"),
        argos_device=defaults.get("argos_device", "cpu"),
        cleanup_batch_size=int(defaults.get("cleanup_batch_size", 25)),
        cleanup_provider=defaults.get("cleanup_provider", "codex"),
        keep_intermediate=bool(defaults.get("keep_intermediate", False)),
        codex=CodexProviderConfig(
            command=codex_data.get("command", "codex"),
            extra_args=list(codex_data.get("extra_args", ["exec", "--skip-git-repo-check"])),
            model=codex_data.get("model"),
            reasoning_effort=codex_data.get("reasoning_effort"),
        ),
        translation=TranslationConfig(
            style=translation.get("style", "natural subtitle translation"),
            preserve_names=bool(translation.get("preserve_names", True)),
            preserve_formatting=bool(translation.get("preserve_formatting", True)),
            prompt=translation.get("prompt"),
        ),
        allowed_latin_names=list(quality.get("allowed_latin_names", DEFAULT_ALLOWED_LATIN_NAMES)),
    )


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

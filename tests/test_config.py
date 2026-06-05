import pytest

from subtitle_forge.config import load_config
from subtitle_forge.errors import SubtitleForgeError


def test_load_config_accepts_valid_values(tmp_path):
    path = tmp_path / "subtitle-forge.toml"
    path.write_text(
        """
[defaults]
source_language = "en"
target_language = "fa"
output_format = "vtt"
argos_device = "cuda"
cleanup_provider = "mock"
cleanup_batch_size = 3
keep_intermediate = true

[providers.codex]
command = "codex"
extra_args = ["exec"]

[translation]
style = "concise"
preserve_names = false
preserve_formatting = true

[quality]
allowed_latin_names = ["City Hunter"]
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.output_format == "vtt"
    assert config.argos_device == "cuda"
    assert config.cleanup_provider == "mock"
    assert config.cleanup_batch_size == 3
    assert config.keep_intermediate is True
    assert config.codex.extra_args == ["exec"]
    assert config.translation.preserve_names is False
    assert config.allowed_latin_names == ["City Hunter"]


def test_load_config_rejects_invalid_cleanup_batch_size(tmp_path):
    path = tmp_path / "subtitle-forge.toml"
    path.write_text(
        """
[defaults]
cleanup_batch_size = 0
""",
        encoding="utf-8",
    )

    with pytest.raises(SubtitleForgeError, match="cleanup_batch_size"):
        load_config(path)


def test_load_config_rejects_invalid_output_format(tmp_path):
    path = tmp_path / "subtitle-forge.toml"
    path.write_text(
        """
[defaults]
output_format = "ass"
""",
        encoding="utf-8",
    )

    with pytest.raises(SubtitleForgeError, match="output_format"):
        load_config(path)


def test_load_config_rejects_invalid_extra_args_type(tmp_path):
    path = tmp_path / "subtitle-forge.toml"
    path.write_text(
        """
[providers.codex]
extra_args = "exec"
""",
        encoding="utf-8",
    )

    with pytest.raises(SubtitleForgeError, match="extra_args"):
        load_config(path)


def test_load_config_rejects_invalid_boolean_type(tmp_path):
    path = tmp_path / "subtitle-forge.toml"
    path.write_text(
        """
[defaults]
keep_intermediate = "false"
""",
        encoding="utf-8",
    )

    with pytest.raises(SubtitleForgeError, match="keep_intermediate"):
        load_config(path)

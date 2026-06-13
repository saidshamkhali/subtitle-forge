from unittest import mock

import httpx
import pytest

from subtitle_forge.config import CodexProviderConfig, OpenCodeProviderConfig
from subtitle_forge.errors import ProviderError
from subtitle_forge.providers import OpenCodeProvider, build_codex_command


def test_build_codex_command_omits_model_and_reasoning_by_default():
    command = build_codex_command(CodexProviderConfig(command="python", extra_args=["exec"]))

    assert "--model" not in command
    assert "--config" not in command
    assert command[-1] == "-"


def test_build_codex_command_adds_model_and_reasoning_overrides():
    command = build_codex_command(
        CodexProviderConfig(command="python", extra_args=["exec"]),
        model="gpt-5.5",
        reasoning_effort="low",
    )

    assert command[-1] == "-"
    assert command[command.index("--model") + 1] == "gpt-5.5"
    assert command[command.index("--config") + 1] == 'model_reasoning_effort="low"'


class TestOpenCodeProvider:
    def test_raises_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
        config = OpenCodeProviderConfig(api_key_env="OPENCODE_API_KEY")
        provider = OpenCodeProvider(config)

        with pytest.raises(ProviderError, match="API key not found"):
            provider.translate_batch("test prompt")

    def test_raises_on_http_error(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
        config = OpenCodeProviderConfig()

        def mock_post(*args, **kwargs):
            mock_resp = mock.MagicMock()
            mock_resp.status_code = 401
            mock_resp.text = "Unauthorized"
            return mock_resp

        with mock.patch.object(httpx.Client, "post", mock_post):
            provider = OpenCodeProvider(config)
            with pytest.raises(ProviderError, match="HTTP 401"):
                provider.translate_batch("test prompt")

    def test_raises_on_invalid_json_response(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
        config = OpenCodeProviderConfig()

        def mock_post(*args, **kwargs):
            mock_resp = mock.MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.side_effect = ValueError("bad json")
            return mock_resp

        with mock.patch.object(httpx.Client, "post", mock_post):
            provider = OpenCodeProvider(config)
            with pytest.raises(ProviderError, match="invalid JSON"):
                provider.translate_batch("test prompt")

    def test_raises_when_no_choices(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
        config = OpenCodeProviderConfig()

        def mock_post(*args, **kwargs):
            mock_resp = mock.MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"choices": []}
            return mock_resp

        with mock.patch.object(httpx.Client, "post", mock_post):
            provider = OpenCodeProvider(config)
            with pytest.raises(ProviderError, match="no choices"):
                provider.translate_batch("test prompt")

    def test_returns_content_on_success(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
        config = OpenCodeProviderConfig()

        def mock_post(*args, **kwargs):
            mock_resp = mock.MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "  translated text  "}}]
            }
            return mock_resp

        with mock.patch.object(httpx.Client, "post", mock_post):
            provider = OpenCodeProvider(config)
            result = provider.translate_batch("test prompt")
            assert result == "translated text"

    def test_respects_model_and_reasoning_overrides(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
        config = OpenCodeProviderConfig(model="default-model", reasoning_effort="low")

        captured_payload = {}

        def mock_post(*args, **kwargs):
            captured_payload["json"] = kwargs.get("json", {})
            mock_resp = mock.MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "ok"}}]
            }
            return mock_resp

        with mock.patch.object(httpx.Client, "post", mock_post):
            provider = OpenCodeProvider(
                config, model="override-model", reasoning_effort="high"
            )
            provider.translate_batch("prompt")

        assert captured_payload["json"]["model"] == "override-model"
        assert captured_payload["json"]["reasoning_effort"] == "high"

    def test_uses_config_defaults_when_no_overrides(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
        config = OpenCodeProviderConfig(model="config-model", reasoning_effort="high")

        captured_payload = {}

        def mock_post(*args, **kwargs):
            captured_payload["json"] = kwargs.get("json", {})
            mock_resp = mock.MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "ok"}}]
            }
            return mock_resp

        with mock.patch.object(httpx.Client, "post", mock_post):
            provider = OpenCodeProvider(config)
            provider.translate_batch("prompt")

        assert captured_payload["json"]["model"] == "config-model"
        assert captured_payload["json"]["reasoning_effort"] == "high"
        assert captured_payload["json"]["max_tokens"] == 16384
        assert "temperature" not in captured_payload["json"]

    def test_omits_reasoning_effort_when_none(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
        config = OpenCodeProviderConfig(model="m")  # reasoning_effort defaults to None

        captured_payload = {}

        def mock_post(*args, **kwargs):
            captured_payload["json"] = kwargs.get("json", {})
            mock_resp = mock.MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "ok"}}]
            }
            return mock_resp

        with mock.patch.object(httpx.Client, "post", mock_post):
            provider = OpenCodeProvider(config, reasoning_effort=None)
            provider.translate_batch("prompt")

        assert "reasoning_effort" not in captured_payload["json"]
        assert captured_payload["json"]["max_tokens"] == 16384
        assert "temperature" not in captured_payload["json"]

    def test_handles_missing_message_field(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
        config = OpenCodeProviderConfig()

        def mock_post(*args, **kwargs):
            mock_resp = mock.MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"choices": [{}]}
            return mock_resp

        with mock.patch.object(httpx.Client, "post", mock_post):
            provider = OpenCodeProvider(config)
            with pytest.raises(ProviderError, match="no message"):
                provider.translate_batch("test prompt")

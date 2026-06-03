from subtitle_forge.config import CodexProviderConfig
from subtitle_forge.providers import build_codex_command


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

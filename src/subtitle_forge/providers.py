from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import httpx

from subtitle_forge.errors import ProviderError
from subtitle_forge.executables import resolve_executable
from subtitle_forge.logging_config import get_logger

if TYPE_CHECKING:
    from subtitle_forge.config import CodexProviderConfig, OpenCodeProviderConfig

logger = get_logger("providers")


class TranslationProvider(Protocol):
    def translate_batch(self, prompt: str) -> str:
        ...


@dataclass(frozen=True)
class CodexExecProvider:
    config: CodexProviderConfig
    model: str | None = None
    reasoning_effort: str | None = None

    def translate_batch(self, prompt: str) -> str:
        logger.debug("Starting Codex batch, prompt length=%d", len(prompt))
        command = build_codex_command(self.config, self.model, self.reasoning_effort)
        logger.debug("Codex command: %s", " ".join(command))

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".txt", delete=False) as output_file:
            output_path = output_file.name

        try:
            completed = subprocess.run(
                [*command[:-1], "--output-last-message", output_path, command[-1]],
                input=prompt,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            logger.debug("Codex subprocess completed, returncode=%d", completed.returncode)

            if completed.returncode != 0:
                stderr = completed.stderr.strip()
                logger.warning("Codex failure: %s", stderr)
                raise ProviderError(_format_codex_failure(completed.returncode, stderr))

            with open(output_path, encoding="utf-8") as output:
                last_message = output.read().strip()
        finally:
            with contextlib.suppress(OSError):
                os.unlink(output_path)

        return last_message or completed.stdout.strip()


@dataclass(frozen=True)
class MockProvider:
    target_language: str = "fa"

    def translate_batch(self, prompt: str) -> str:
        if "Cues:" in prompt:
            cues = _extract_cleanup_payload(prompt)
            return json.dumps(
                {cue["id"]: _mock_translate(cue["src"], self.target_language) for cue in cues},
                ensure_ascii=False,
            )
        cues = _extract_prompt_payload(prompt)
        return json.dumps(
            [{"id": cue["id"], "text": _mock_translate(cue["text"], self.target_language)} for cue in cues],
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class OpenCodeProvider:
    config: OpenCodeProviderConfig
    model: str | None = None
    reasoning_effort: str | None = None

    def translate_batch(self, prompt: str) -> str:
        logger.debug("Starting OpenCode batch, prompt length=%d", len(prompt))

        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise ProviderError(
                f"OpenCode API key not found. Set the {self.config.api_key_env} environment variable."
            )

        selected_model = self.model or self.config.model
        selected_reasoning = self.reasoning_effort if self.reasoning_effort is not None else self.config.reasoning_effort

        payload: dict = {
            "model": selected_model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a subtitle translation assistant. Return only valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 16384,
        }
        if selected_reasoning:
            payload["reasoning_effort"] = selected_reasoning

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        logger.debug("OpenCode request: model=%s reasoning=%s", selected_model, selected_reasoning)

        try:
            client = httpx.Client(timeout=120.0)
            response = client.post(self.config.base_url, json=payload, headers=headers)
        except httpx.TimeoutException:
            raise ProviderError("OpenCode API request timed out after 120 seconds.") from None
        except httpx.RequestError as exc:
            raise ProviderError(f"OpenCode API request failed: {exc}") from exc

        if response.status_code != 200:
            detail = response.text[:500] if response.text else "no response body"
            raise ProviderError(f"OpenCode API returned HTTP {response.status_code}: {detail}")

        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError("OpenCode API returned invalid JSON response.") from exc

        if not isinstance(body, dict):
            raise ProviderError("OpenCode API response is not a JSON object.")

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError("OpenCode API response has no choices array.")

        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ProviderError("OpenCode API response choice has no message object.")

        content = message.get("content")
        if not isinstance(content, str):
            raise ProviderError("OpenCode API message has no string content.")

        if not content.strip():
            logger.warning("OpenCode returned empty content. Full response: %s", json.dumps(body, ensure_ascii=False)[:2000])
            finish_reason = choices[0].get("finish_reason", "unknown")
            raise ProviderError(
                f"OpenCode API returned empty content (finish_reason={finish_reason}). "
                "This may indicate the max_tokens limit was too low for this batch, "
                "or the model refused the request."
            )

        logger.debug("OpenCode batch complete, response length=%d", len(content))
        return content.strip()


def build_codex_command(
    config: CodexProviderConfig,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> list[str]:
    executable = resolve_executable(config.command)
    if not executable:
        raise ProviderError(
            f"Codex CLI command '{config.command}' was not found. Install Codex CLI and run 'codex login'."
        )

    command = [executable, *config.extra_args]
    selected_model = model or config.model
    selected_reasoning_effort = reasoning_effort or config.reasoning_effort

    if selected_model:
        command.extend(["--model", selected_model])
    if selected_reasoning_effort:
        command.extend(["--config", f"model_reasoning_effort={json.dumps(selected_reasoning_effort)}"])

    command.append("-")
    return command


def _extract_prompt_payload(prompt: str) -> list[dict[str, str]]:
    marker = "Subtitles to translate:\n"
    if marker not in prompt:
        raise ProviderError("MockProvider could not find subtitle payload in the prompt.")
    payload = prompt.split(marker, 1)[1].strip()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"MockProvider received invalid prompt JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ProviderError("MockProvider expected a list of cue objects.")
    return data


def _extract_cleanup_payload(prompt: str) -> list[dict[str, str]]:
    marker = "Cues:\n"
    if marker not in prompt:
        raise ProviderError("MockProvider could not find cleanup payload in the prompt.")
    payload = prompt.split(marker, 1)[1].strip()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"MockProvider received invalid cleanup prompt JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ProviderError("MockProvider expected a list of cleanup cue objects.")
    return data


def _format_codex_failure(returncode: int, stderr: str) -> str:
    model_match = re.search(r"^model:\s*(.+)$", stderr, flags=re.MULTILINE)
    model = model_match.group(1).strip() if model_match else None

    if "requires a newer version of Codex" in stderr:
        model_text = f" '{model}'" if model else ""
        return (
            f"Codex CLI rejected model{model_text} because this Codex version is too old for it. "
            "Upgrade Codex CLI/the Codex app, or pass a supported model with '--model', or change "
            "the model in ~/.codex/config.toml."
        )

    detail = stderr or "no error output"
    if len(detail) > 1200:
        detail = f"{detail[:1200]}..."
    return f"Codex CLI failed with exit code {returncode}: {detail}"


def _mock_translate(text: str, target_language: str) -> str:
    if target_language.lower() in {"fa", "fas", "per"}:
        dictionary = {
            "Hello.": "سلام.",
            "Hello": "سلام",
            "Welcome to Subtitle Forge.": "به سابتایتل فورج خوش آمدید.",
            "<i>Keep moving.</i>": "<i>ادامه بده.</i>",
            "Good morning.": "صبح بخیر.",
            "Where are we going?": "کجا می‌رویم؟",
            "Hola.": "سلام.",
            "Bienvenido a Subtitle Forge.": "به سابتایتل فورج خوش آمدید.",
        }
        return dictionary.get(text, text)
    return text


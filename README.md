# Subtitle Forge

Subtitle Forge translates existing `.srt` and `.vtt` subtitle files while preserving cue timings.

The MVP uses your local **Codex CLI** session as its first real provider. Sign in to Codex with your ChatGPT account first, then Subtitle Forge can call `codex exec` for non-interactive translation. Subtitle Forge does not extract tokens, automate browser sessions, or store credentials.

Audio/video transcription is not included in the MVP.

## Install

```bash
python -m pip install -e ".[dev]"
```

If `subtitle-forge` is not on PATH after installation, use:

```bash
python -m subtitle_forge --help
```

On Windows, editable installs commonly place scripts in:

```text
C:\Users\Said\AppData\Roaming\Python\Python313\Scripts
```

Add that directory to your user `Path` environment variable if you want to run `subtitle-forge` directly from any new terminal.

Check that Codex CLI is available:

```bash
codex --version
```

If you still need to sign in:

```bash
codex login
```

Check the local Subtitle Forge setup:

```bash
subtitle-forge doctor
subtitle-forge providers
```

Equivalent module form:

```bash
python -m subtitle_forge doctor
python -m subtitle_forge providers
```

## Quick Start

Inspect a file:

```bash
subtitle-forge inspect examples/movie.en.srt
```

Validate a file:

```bash
subtitle-forge validate examples/movie.en.srt
```

Translate English subtitles to Persian/Farsi with Codex CLI:

```bash
subtitle-forge translate examples/movie.en.srt --from en --to fa --provider codex --out examples/movie.fa.srt
```

Persian/Farsi output uses `--rtl-mode auto` by default. This adds invisible Unicode direction marks so players such as VLC have a better chance of rendering punctuation and embedded English names correctly.

Translate Spanish subtitles to Persian/Farsi:

```bash
subtitle-forge translate examples/movie.es.srt --from es --to fa --provider codex --out examples/movie.fa.srt
```

Use the local mock provider for tests or dry runs:

```bash
subtitle-forge translate examples/movie.en.srt --from en --to fa --provider mock --out tmp/movie.fa.srt
```

## Model Selection

By default, Subtitle Forge does not pass a model to Codex. Your local Codex CLI default is used.

You can pass a model explicitly:

```bash
subtitle-forge translate examples/movie.en.srt --from en --to fa --provider codex --rtl-mode marks --out examples/movie.fa.srt
```

## Reasoning Effort

By default, Subtitle Forge does not pass a reasoning effort to Codex. Your local Codex CLI default is used.

You can pass one explicitly:

```bash
subtitle-forge translate examples/movie.en.srt --from en --to fa --provider codex --model gpt-5.5 --reasoning-effort medium --out tmp/movie.fa.medium.srt
subtitle-forge translate examples/movie.en.srt --from en --to fa --provider codex --model gpt-5.5 --reasoning-effort low --out tmp/movie.fa.low.srt
```

For Codex CLI, Subtitle Forge sends this as:

```bash
--config model_reasoning_effort="low"
```

Common values are `low`, `medium`, and `high`, depending on what your installed Codex CLI and selected model allow. Exact model and reasoning availability depends on your Codex CLI account and version.

You can set project defaults in `subtitle-forge.toml`:

```toml
[providers.codex]
command = "codex"
extra_args = ["exec", "--skip-git-repo-check"]
model = "gpt-5.5"
reasoning_effort = "medium"
```

If `model` or `reasoning_effort` are omitted from `subtitle-forge.toml`, Codex uses its own defaults from `~/.codex/config.toml`.

If Codex fails with a message like `The 'gpt-5.5' model requires a newer version of Codex`, your local Codex config is asking for a model that your installed Codex CLI cannot use yet.

Fast options:

```bash
subtitle-forge translate examples/movie.en.srt --from en --to fa --provider codex --model gpt-5 --out examples/movie.fa.srt
```

Or update Codex CLI/the Codex app, then retry with your default model.

You can also change the default model in:

```text
~/.codex/config.toml
```

## Configuration

Create `subtitle-forge.toml` in the project or working directory:

```toml
[defaults]
provider = "codex"
source_language = "en"
target_language = "fa"
output_format = "srt"
batch_size = 50
rtl_mode = "auto"

[providers.codex]
command = "codex"
extra_args = ["exec", "--skip-git-repo-check"]
# model = "gpt-5.5"
# reasoning_effort = "medium"

[translation]
style = "natural subtitle translation"
preserve_names = true
preserve_formatting = true
```

CLI flags override config values.

## Persian / RTL Preview

Persian subtitles are stored in logical Unicode order. For example, `سلام.` is stored as the letters for `سلام` followed by a period. Some terminals and plain text editors display mixed right-to-left and left-to-right text in confusing visual order, especially when English names like `Subtitle Forge` appear inside Persian sentences.

Subtitle Forge supports three RTL modes:

```bash
--rtl-mode auto   # default: add bidi marks for known RTL target languages
--rtl-mode marks  # always add bidi marks
--rtl-mode off    # write raw provider text without bidi marks
```

For VLC, use `auto` or `marks`:

```bash
subtitle-forge translate examples/movie.en.srt --from en --to fa --provider codex --rtl-mode marks --out examples/movie.fa.srt
```

For debugging raw model output, use:

```bash
subtitle-forge translate examples/movie.en.srt --from en --to fa --provider codex --rtl-mode off --out examples/movie.fa.raw.srt
```

To test real playback, use a subtitle-aware video player instead of judging only from the raw `.srt` file:

```text
VLC -> Subtitle -> Add Subtitle File...
```

For a quick smoke test, open any video in VLC, add the generated `.srt`, and jump to the cue times. If the player still shows punctuation on the wrong visual side, that is a player/font/bidi rendering issue rather than changed subtitle timings or corrupted UTF-8.

The Persian prompt asks the model to preserve brand names, keep brand phrases together, and place them naturally in Persian word order to reduce awkward mixed-direction output.

## Current Scope

Included:

- `.srt` and `.vtt` input.
- `.srt` and `.vtt` output.
- Codex CLI provider.
- Mock provider for tests.
- Batch translation with JSON validation.

Not included yet:

- Audio/video subtitle generation.
- `.ass` subtitle support.
- Persistent caching.
- Other suscription-based providers.
- API key based providers.

# Subtitle Forge

Subtitle Forge translates existing `.srt` and `.vtt` subtitle files while preserving cue timings.

The translation flow is fixed:

1. ArgosTranslate creates a local first-pass translation.
2. Subtitle Forge normalizes Persian subtitle display marks.
3. A validator flags only suspicious cues.
4. Codex CLI repairs only those flagged cues.
5. Subtitle Forge normalizes again, validates again, and writes the final subtitle plus a JSON report.

Subtitle Forge does not download Argos language packages automatically. Install the required Argos language pair locally before translating.

## Install

```bash
python -m pip install -e ".[dev]"
```

Check the local setup:

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

Translate English subtitles to Persian/Farsi:

```bash
subtitle-forge translate examples/movie.en.srt --from en --to fa --out examples/movie.fa.srt
```

Keep intermediate Argos and normalized files:

```bash
subtitle-forge translate examples/movie.en.srt --from en --to fa --out examples/movie.fa.srt --keep-intermediate
```

Use a low-reasoning Codex cleanup pass explicitly:

```bash
subtitle-forge translate examples/movie.en.srt --from en --to fa --out examples/movie.fa.srt --reasoning-effort low
```

Write the validation report to a custom path:

```bash
subtitle-forge translate examples/movie.en.srt --from en --to fa --out examples/movie.fa.srt --report tmp/movie.report.json
```

## Progress Output

The CLI prints the main stages while it runs:

```text
1/6 Reading subtitles
2/6 Argos full-file translation
3/6 Normalizing Persian subtitle display
4/6 Validating and flagging suspicious cues
5/6 AI cleanup: N flagged cues in M batches
6/6 Final normalization, validation, and write
```

At the end it prints the final output path, report path, cue count, flagged cue counts before and after cleanup, disallowed Latin line count, and validation status.

## Configuration

Create `subtitle-forge.toml` in the project or working directory:

```toml
[defaults]
source_language = "en"
target_language = "fa"
output_format = "srt"
cleanup_provider = "codex"
cleanup_batch_size = 25
keep_intermediate = false

[providers.codex]
command = "codex"
extra_args = ["exec", "--skip-git-repo-check"]
# model = "gpt-5"
# reasoning_effort = "low"

[translation]
style = "natural subtitle translation"
preserve_names = true
preserve_formatting = true

[quality]
allowed_latin_names = [
  "City Hunter",
  "Kaori",
  "Kiyoko",
  "Imamura",
  "MacDonald",
  "Olsen Park",
  "Hong Kong",
  "Mah Jong",
  "Thunder Strikers",
  "Dragon Claw",
  "White Crane",
]
```

CLI flags override config values.

## Current Scope

Included:

- `.srt` and `.vtt` input.
- `.srt` and `.vtt` output.
- ArgosTranslate local first-pass translation.
- Codex CLI cleanup for flagged cues only.
- Persian/Farsi RTL display normalization and validation reports.

Not included:

- Audio/video subtitle generation.
- `.ass` subtitle support.
- Automatic Argos package downloads.
- OpenAI API cleanup provider.

# Subtitle Forge

Subtitle Forge translates existing `.srt` and `.vtt` subtitle files while preserving cue timings.

The default workflow is:

1. ArgosTranslate creates a local first-pass translation.
2. Subtitle Forge normalizes subtitle display details such as Persian RTL marks.
3. A validator flags suspicious cues.
4. Codex CLI repairs only the flagged cues.
5. Subtitle Forge validates again and writes the final subtitle plus a JSON report.

## Install

```bash
python -m pip install -e ".[dev]"
```

ArgosTranslate is installed with Subtitle Forge. Install the Argos language package for each translation pair before the first run:

```bash
subtitle-forge translate --from en --to fa --install-argos-package
```

Argos packages are installed for a translation pair, such as `en -> fa`. After installing the pair once, translate normally:

```bash
subtitle-forge translate input.en.srt --from en --to fa --out output.fa.srt
```

If the package is missing, Subtitle Forge prints the setup command to run. You can also combine setup and translation in one command by adding `--install-argos-package` to a normal `translate` command.

Check your setup:

```bash
subtitle-forge doctor
```

## Translate

Basic translation:

```bash
subtitle-forge translate input.en.srt --from en --to fa --out output.fa.srt
```

VTT files are supported too:

```bash
subtitle-forge translate input.en.vtt --from en --to fa --out output.fa.vtt
```

You can also convert between subtitle formats while translating:

```bash
subtitle-forge translate input.en.srt --from en --to fa --out output.fa.vtt
subtitle-forge translate input.en.vtt --from en --to fa --out output.fa.srt
```

The output format is inferred from `--out` when it ends in `.srt` or `.vtt`:

```bash
subtitle-forge translate input.en.srt --from en --to fa --out output.fa.vtt
```

If `--out` does not end in `.srt` or `.vtt`, Subtitle Forge inherits the input file format:

```bash
subtitle-forge translate input.en.srt --from en --to fa --out output.fa
```

Use CUDA for the Argos first pass:

```bash
subtitle-forge translate input.en.srt --from en --to fa --out output.fa.srt --argos-device cuda
```

Keep intermediate files:

```bash
subtitle-forge translate input.en.srt --from en --to fa --out output.fa.srt --keep-intermediate
```

Write the validation report to a custom path:

```bash
subtitle-forge translate input.en.srt --from en --to fa --out output.fa.srt --report output.report.json
```

## CLI Commands

Show help:

```bash
subtitle-forge --help
subtitle-forge translate --help
```

Commands:

```text
inspect    Print subtitle metadata.
validate   Check that a subtitle file can be parsed.
providers  List cleanup providers used after Argos validation.
doctor     Check Argos, CUDA, and Codex CLI or OpenCode setup.
translate  Run the full translation pipeline.
benchmark  Compare translation pipeline performance across multiple cleanup providers.
```

Translate options:

```text
input_path             Subtitle file to translate. Optional only when using --install-argos-package for setup.
--out, -o              Final output subtitle path. Required for translation.
--config, -c           Path to subtitle-forge.toml.
--from                 Source language code, such as en.
--to                   Target language code, such as fa.
--model                Optional model override for cleanup provider.
--reasoning-effort     Optional reasoning effort override (low|medium|high|max).
--cleanup-provider     Cleanup provider for flagged cues: codex, opencode, or mock.
--argos-device         Argos first-pass device: cpu, cuda, or auto.
--cleanup-batch-size   Flagged cues per cleanup call.
--report               Validation report path.
--keep-intermediate / --no-keep-intermediate
                       Write or skip Argos and normalized intermediate subtitles.
--install-argos-package
                       Download and install the requested Argos language package.
                       If no input file is provided, install the package and exit.
--prompt               Additional cleanup prompt instructions.
```

## Cleanup Providers

Subtitle Forge supports three cleanup providers that repair flagged cues after the Argos first pass:

| Provider  | Backend                         | Setup                              |
|-----------|---------------------------------|------------------------------------|
| `codex`   | Local Codex CLI                 | Install Codex CLI, run `codex login` |
| `opencode`| OpenCode Go HTTP API            | Set `OPENCODE_API_KEY` env var     |
| `mock`    | Deterministic local (testing)   | None                               |

### Codex (default)

```bash
subtitle-forge translate input.en.srt --to fa --out output.fa.srt --cleanup-provider codex
```

Override model or reasoning effort:

```bash
subtitle-forge translate input.en.srt --to fa --out output.fa.srt --cleanup-provider codex --model gpt-5.5 --reasoning-effort medium
```

### OpenCode Go

Uses your OpenCode Go subscription via the HTTP chat-completions API. Defaults to DeepSeek V4 Flash with max reasoning effort.

```bash
# Set your API key
export OPENCODE_API_KEY="your-key-here"

# Translate with opencode
subtitle-forge translate input.en.srt --to fa --out output.fa.srt --cleanup-provider opencode

# Use a different model
subtitle-forge translate input.en.srt --to fa --out output.fa.srt --cleanup-provider opencode --model deepseek-v4-pro

# Check setup
subtitle-forge doctor

# List available providers
subtitle-forge providers
```

## Benchmark

Compare cleanup providers side by side:

```bash
# Compare codex vs opencode (default)
subtitle-forge benchmark input.en.srt --to fa --out output.fa.srt

# Compare specific providers
subtitle-forge benchmark input.en.srt --to fa --out output.fa.srt --providers codex,opencode

# With custom model and reasoning
subtitle-forge benchmark input.en.srt --to fa --out output.fa.srt --providers codex,opencode --model deepseek-v4-flash --reasoning-effort max
```

The benchmark runs the full pipeline for each provider and prints a comparison table with per-stage timings, flagged cue counts, validation pass/fail, and a speedup ratio.

## CUDA

CUDA is optional. CPU mode is the default and works without GPU setup.

To use CUDA, install CUDA Toolkit 12.x and confirm:

```bash
subtitle-forge doctor
```

The CUDA status should say the runtime is loadable. If it is not, run with CPU:

```bash
subtitle-forge translate input.en.srt --from en --to fa --out output.fa.srt --argos-device cpu
```

CUDA mainly speeds up the Argos first-pass translation. Cleanup time depends on how many cues are flagged and Codex latency.

## CLI Output

The translate command shows the pipeline stages and final timing:

```text
1/6 Reading subtitles
2/6 Argos full-file translation
3/6 Normalizing Persian subtitle display
4/6 Validating and flagging suspicious cues
5/6 AI cleanup
6/6 Final normalization, validation, and write
```

The final summary includes output path, report path, cue count, flagged cue counts, validation status, and per-stage timing.

## Configuration

Create `subtitle-forge.toml` in the project or working directory:

```toml
[defaults]
source_language = "en"
target_language = "fa"
argos_device = "cpu"
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
  "Brand Name",
  "Character Name",
  "Place Name",
]
```

CLI flags override config values.

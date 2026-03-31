> [!WARNING]
> This repo is 90% written by GPT-5.3-codex, and is just an incomplete tool for personal use.

# Vocab Shell

Terminal vocabulary trainer for TOEFL preparation.

## Features

- `search <word>`: fetch dictionary data, show all meanings, and print example sentences under each meaning with a POS prefix (for example `[VERB]`), then optionally save the word into one of your custom dictionaries.
- `dict create <name>`: create a custom dictionary.
- `dict list`: show dictionaries and due-review counts.
- `review <dictionary> <count>`: run a multiple-choice review session using due words and an Ebbinghaus-style schedule.
- `stats <dictionary>`: inspect word counts and next reviews.

## Requirements

- Python 3.11+
- A terminal font with Unicode symbol support is recommended for prompt glyphs (for example `❯`). If your font cannot render them, prompt symbols may look incorrect.

Optional environment variables:

- `COLLINS_DICT_CODE`: Collins dictionary path segment, defaults to `english`
- `VOCAB_SHELL_HOME`: where JSON data is stored, defaults to `./.vocab-shell`

## Run

```bash
python3 -m vocab_shell
```

Inside the REPL:

```text
search abandon
dict create toefl-core
review toefl-core 10
stats toefl-core
help
quit
```

## Review Schedule

The app uses these intervals by default:

- 1 day
- 2 days
- 4 days
- 7 days
- 15 days
- 30 days
- 45 days
- 60 days

This is a configurable Ebbinghaus-style schedule stored per word in local JSON.

## Data Layout

Data is stored in `VOCAB_SHELL_HOME`:

- `config.json`: global configuration
- `theme.json`: color theme config for output styling (supports `dark`/`light` profiles and RGB colors)
- `dictionaries/<name>.json`: one file per custom dictionary, including review state per word

Default `theme.json` structure:

- `active_profile`: `auto` | `dark` | `light`
- `profiles.dark.highlight` / `profiles.light.highlight`
- `profiles.dark.meaning` / `profiles.light.meaning`
- `profiles.dark.pos` / `profiles.light.pos`
- `profiles.dark.prompt_border` / `profiles.light.prompt_border`
- `profiles.dark.prompt_marker` / `profiles.light.prompt_marker`
- `profiles.dark.prompt_transient` / `profiles.light.prompt_transient`

Style fields support:

- `fg`: RGB color like `#66ffff`
- `bg`: RGB color like `#101010`
- `bold`: `true` / `false`
- `underline`: `true` / `false`
- `reverse`: `true` / `false`

Example:

```json
{
  "active_profile": "auto",
  "profiles": {
    "dark": {
      "highlight": {"fg": "#ff5fd7", "bold": true, "underline": true},
      "meaning": {"fg": "#66ffff", "bold": true},
      "pos": {"fg": "#101010", "bg": "#ffe082", "bold": true},
      "prompt_border": {"fg": "#94a3b8"},
      "prompt_marker": {"fg": "#38bdf8", "bold": true},
      "prompt_transient": {"fg": "#22c55e", "bold": true}
    },
    "light": {
      "highlight": {"fg": "#8a005c", "bold": true, "underline": true},
      "meaning": {"fg": "#005a9c", "bold": true},
      "pos": {"fg": "#000000", "bg": "#ffd54f", "bold": true},
      "prompt_border": {"fg": "#64748b"},
      "prompt_marker": {"fg": "#0284c7", "bold": true},
      "prompt_transient": {"fg": "#15803d", "bold": true}
    }
  }
}
```

## Notes

- The search command now follows the public Collins entry-page pattern, for example `/dictionary/english/account`, and parses definitions/examples from the returned HTML.
- If Collins blocks automated page requests (HTTP 403), the app now automatically falls back to `dictionaryapi.dev` so `search` can still return usable definitions.
- The review scheduler uses the commonly used interval sequence above. If you want to match a different exact table later, the schedule can be changed in code without changing saved word data structure.

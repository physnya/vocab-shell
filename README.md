# Vocab Shell

Terminal vocabulary trainer for TOEFL preparation.

## Features

- `search <word>`: query Collins Dictionary, then optionally save the word into one of your custom dictionaries.
- `dict create <name>`: create a custom dictionary.
- `dict list`: show dictionaries and due-review counts.
- `review <dictionary> <count>`: run a multiple-choice review session using due words and an Ebbinghaus-style schedule.
- `stats <dictionary>`: inspect word counts and next reviews.

## Requirements

- Python 3.11+
- A Collins Dictionary API key in `COLLINS_API_KEY`

Optional environment variables:

- `COLLINS_DICT_CODE`: Collins dictionary code, defaults to `english`
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

- 5 minutes
- 30 minutes
- 12 hours
- 1 day
- 2 days
- 4 days
- 7 days
- 15 days

This is a configurable Ebbinghaus-style schedule stored per word in local JSON.

## Data Layout

Data is stored in `VOCAB_SHELL_HOME`:

- `config.json`: global configuration
- `dictionaries/<name>.json`: one file per custom dictionary, including review state per word

## Notes

- Collins API details are based on the official documentation for `/api/v1/dictionaries/{dictCode}/search/first`, which returns `entryContent` and supports the `format` query parameter:
  - https://api.collinsdictionary.com/api/v1/documentation/html
  - https://www.collinsdictionary.com/us/collins-api
- The review scheduler uses the commonly used interval sequence above. If you want to match a different exact table later, the schedule can be changed in code without changing saved word data structure.

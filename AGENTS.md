# Repository Guidelines

## Project Structure & Module Organization
Core source code lives in `vocab_shell/`:
- `cli.py`: REPL entry and command handling (`search`, `dict`, `review`, `stats`).
- `collins.py`: dictionary fetching/parsing and fallback behavior.
- `storage.py`: JSON persistence under `VOCAB_SHELL_HOME`.
- `review.py` and `models.py`: spaced-review logic and data models.

Tests are in `tests/` (`test_cli.py`, `test_review.py`, `test_collins_parser.py`).  
Project metadata is in `pyproject.toml`, and runtime usage is documented in `README.md`.

## Build, Test, and Development Commands
- `python3 -m venv .venv && source .venv/bin/activate`: create and activate local environment.
- `python3 -m pip install -e .`: install package in editable mode.
- `python3 -m vocab_shell`: run the CLI locally.
- `python3 -m unittest discover -s tests`: run all unit tests.

If your default `python3` is not compatible, run tests with a specific interpreter (example: `/opt/homebrew/bin/python3 -m unittest discover -s tests`).

## Coding Style & Naming Conventions
- Target Python `>=3.11` (see `pyproject.toml`).
- Follow PEP 8: 4-space indentation, snake_case for functions/variables, PascalCase for classes.
- Keep functions focused and small; prefer explicit error messages via `StorageError`, `ReviewError`, `CollinsError`.
- Preserve existing CLI output style and command semantics when changing UX behavior.

## Testing Guidelines
- Use `unittest` (existing project standard).
- Add tests in `tests/test_*.py`; name methods as `test_<behavior>()`.
- For CLI/completion features, validate exact completion candidates and command-path behavior.
- Keep tests deterministic and isolated (use temporary `VOCAB_SHELL_HOME` like existing tests).

## Commit & Pull Request Guidelines
- Commit messages are short, imperative, and scoped when helpful (examples from history: `Improve CLI autocomplete...`, `docs: update README`).
- Prefer one logical change per commit.
- PRs should include:
  - What changed and why.
  - How it was tested (commands run).
  - Any user-facing CLI behavior changes, with brief examples.

## Configuration & Local Data Tips
- Important env vars: `VOCAB_SHELL_HOME`, `COLLINS_DICT_CODE`.
- Do not commit generated local data (dictionary JSON, shell history, virtualenv artifacts).

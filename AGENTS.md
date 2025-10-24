# Repository Guidelines

## Project Structure & Module Organization
- Core sources live in `autoPDFtagger/`: `main.py` exposes the CLI entry point, `autoPDFtagger.py` orchestrates analyses, `PDFDocument.py` models individual files, `PDFList.py` maintains collections, and `config.py` loads user settings.
- Example configuration (`autoPDFtagger_example_config.conf`) sits at the repo root; use it to seed `~/.autoPDFtagger.conf`.
- No automated tests ship yet. Place new ones under `tests/` (mirror package structure) and keep fixtures small so they can be reviewed easily.

## Build, Test, and Development Commands
- Create a local environment and install the package in editable mode: `python -m venv .venv && source .venv/bin/activate && pip install -e .`.
- Run the CLI help to confirm the install: `autoPDFtagger --help`. During iterative work you can target sample data with `autoPDFtagger ./pdf_archive -ftic -e ./out`.
- When you add tests, execute `pytest` from the repo root; prefer deterministic inputs and stub external API calls.

## Coding Style & Naming Conventions
- Follow PEP 8: four-space indentation, snake_case for functions, PascalCase for classes, and descriptive module-level constants.
- Reuse the existing logging approach (`logging.info/debug`) instead of print statements, and thread cost tracking through the same pattern.
- Keep prompts, API payloads, and configuration keys in English, and guard API calls with explicit error handling.

## Testing Guidelines
- Break complex behaviours into testable units by mocking OpenAI clients and file-system operations; avoid hitting real APIs in CI.
- Name tests `test_<feature>.py` and annotate fixtures with docstrings describing expected metadata outcomes.
- Document new test datasets in the PR so reviewers understand scope and sensitivity.

## Commit & Pull Request Guidelines
- Craft concise, imperative commit subjects similar to the existing history (`Bug fix: Import CSV-files`, `Change confidence defaults`).
- Squash unrelated work; each PR should focus on one change set, include a high-level summary, manual test notes, and any cost-sensitivity callouts.
- Reference linked issues when available, and include CLI examples or screenshots when behaviour changes the user experience.

## Configuration & API Keys
- Keep personal credentials out of the repo. Point contributors to `~/.autoPDFtagger.conf` for local secrets and remind them to rotate keys used in tests.
- If you add new configuration options, document defaults in the sample config and guard loads with helpful error messages.
